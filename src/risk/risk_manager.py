"""Crypto-specific risk management.

Key differences vs. stock risk logic:

1. **ATR-based position sizing**. Because crypto volatility varies wildly between
   coins and regimes, we size each position so the ATR-based stop distance represents
   a fixed % of capital (volatility targeting).

2. **Flash-crash kill switch**. If the 5-minute return exceeds a threshold (default
   -8%), ALL positions are closed and trading pauses for `cooldown_minutes`.

3. **Max Daily Drawdown (MDD)**. Since crypto trades 24/7 there is no market-close
   reset; we track drawdown from the daily-peak equity (UTC) and halt trading for
   the remainder of the day if exceeded.

4. **Per-position stop-loss and take-profit** are set at entry using ATR multiples
   rather than fixed percentages.

5. **Trailing stop-loss**. Once a position is profitable by >= 1 ATR, the stop-loss
   is ratcheted up to lock in gains (never moves down).

6. **Dynamic SL/TP adjustment**. ATR is recalculated each tick so stops widen in
   high-vol regimes and tighten in low-vol — but never move against the position.

7. **Trade analyzer feedback**. Confidence and size are adjusted based on recent
   win/loss history per (market, strategy) pair.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Optional

import pandas as pd

from config.settings import KST, settings
from src.indicators import atr
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    position_size_krw: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""


@dataclass
class _DailyState:
    day: date
    peak_equity: float
    starting_equity: float
    halted: bool = False


@dataclass
class RiskManager:
    capital: float                  # total portfolio equity in KRW
    max_position_pct: float = field(default_factory=lambda: settings.max_position_pct)
    stop_loss_atr_mult: float = field(default_factory=lambda: settings.stop_loss_atr_mult)
    take_profit_atr_mult: float = field(default_factory=lambda: settings.take_profit_atr_mult)
    max_daily_drawdown: float = field(default_factory=lambda: settings.max_daily_drawdown)
    risk_per_trade_pct: float = 0.01          # % of capital risked per trade
    flash_crash_threshold: float = -0.08      # -8% over 5 min -> kill switch
    cooldown_minutes: int = 60
    min_order_krw: float = field(default_factory=lambda: settings.active_min_order_krw)
    max_open_positions: int = 5               # max simultaneous open positions
    trailing_activate_atr: float = 1.0        # activate trailing after 1×ATR profit
    trailing_distance_atr: float = 1.5        # trail at 1.5×ATR below peak
    _open_position_count: int = field(default=0, init=False)

    _daily: Optional[_DailyState] = field(default=None, init=False)
    _cooldown_until: Optional[datetime] = field(default=None, init=False)
    _flash_tripped: bool = field(default=False, init=False)
    _position_peaks: Dict[str, float] = field(default_factory=dict, init=False)

    # ------------------------------------------------------------------
    # Equity / daily tracking
    # ------------------------------------------------------------------
    def update_equity(self, equity: float, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(KST)
        today = now.date()
        if self._daily is None or self._daily.day != today:
            self._daily = _DailyState(day=today, peak_equity=equity, starting_equity=equity)
            return
        if equity > self._daily.peak_equity:
            self._daily.peak_equity = equity
        # Halt if drawdown from daily peak exceeds threshold
        drawdown = (self._daily.peak_equity - equity) / self._daily.peak_equity
        if drawdown >= self.max_daily_drawdown and not self._daily.halted:
            self._daily.halted = True
            log.warning(
                "🛑 Daily MDD exceeded: %.2f%% (peak %.0f -> %.0f). Trading halted until UTC midnight.",
                drawdown * 100,
                self._daily.peak_equity,
                equity,
            )

    def is_halted(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(KST)
        if self._cooldown_until and now < self._cooldown_until:
            return True
        if self._daily and self._daily.halted:
            return True
        return False

    # ------------------------------------------------------------------
    # Flash-crash kill switch
    # ------------------------------------------------------------------
    def check_flash_crash(self, df: pd.DataFrame, lookback_bars: int = 5) -> bool:
        """Return True if we just tripped a flash-crash kill switch."""
        if len(df) < lookback_bars + 1:
            return False
        current = df["close"].iloc[-1]
        reference = df["close"].iloc[-(lookback_bars + 1)]
        if reference <= 0:
            return False
        change = (current / reference) - 1.0
        if change <= self.flash_crash_threshold and not self._flash_tripped:
            self._flash_tripped = True
            self._cooldown_until = datetime.now(KST) + pd.Timedelta(
                minutes=self.cooldown_minutes
            )
            log.warning(
                "⚡ Flash crash detected: %.2f%% over %d bars. Cooldown until %s.",
                change * 100, lookback_bars, self._cooldown_until.isoformat(),
            )
            return True
        # reset flag when price stabilises above threshold
        if change > self.flash_crash_threshold / 2:
            self._flash_tripped = False
        return False

    # ------------------------------------------------------------------
    # Entry sizing
    # ------------------------------------------------------------------
    def set_open_positions(self, count: int) -> None:
        self._open_position_count = count

    def evaluate_entry(
        self,
        df: pd.DataFrame,
        confidence: float = 1.0,
        available_krw: Optional[float] = None,
        signal_meta: Optional[Dict] = None,
    ) -> RiskDecision:
        """Evaluate entry. If signal_meta contains 'sl_suggest'/'tp_suggest',
        use structure-based levels instead of fixed ATR multiples.
        """
        if self.is_halted():
            return RiskDecision(False, reason="trading halted (MDD/cooldown)")

        if self._open_position_count >= self.max_open_positions:
            return RiskDecision(False, reason=f"max open positions ({self.max_open_positions}) reached")

        if self.check_flash_crash(df):
            return RiskDecision(False, reason="flash-crash kill switch")

        if len(df) < 20:
            return RiskDecision(False, reason="insufficient data for ATR")

        entry_price = float(df["close"].iloc[-1])
        a = atr(df["high"], df["low"], df["close"], period=14).iloc[-1]
        if pd.isna(a) or a <= 0:
            return RiskDecision(False, reason="ATR unavailable")

        sl_from_meta = (signal_meta or {}).get("sl_suggest")
        tp_from_meta = (signal_meta or {}).get("tp_suggest")
        used_structure = False

        if (sl_from_meta is not None and tp_from_meta is not None
                and sl_from_meta < entry_price < tp_from_meta):
            stop_loss = float(sl_from_meta)
            take_profit = float(tp_from_meta)
            stop_distance = entry_price - stop_loss
            used_structure = True
        else:
            stop_distance = float(a) * self.stop_loss_atr_mult
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + float(a) * self.take_profit_atr_mult

        if stop_distance <= 0:
            return RiskDecision(False, reason="invalid stop distance")

        # Volatility-targeted sizing: risk 1% of capital on the stop distance
        risk_amount = self.capital * self.risk_per_trade_pct * max(0.2, min(1.0, confidence))
        size_by_risk_krw = (risk_amount / stop_distance) * entry_price

        # Cap by max_position_pct and available cash
        cap_pct = self.capital * self.max_position_pct
        size_krw = min(size_by_risk_krw, cap_pct)
        if available_krw is not None:
            size_krw = min(size_krw, available_krw)

        if size_krw < self.min_order_krw:
            return RiskDecision(
                False,
                reason=f"size {size_krw:.0f} KRW below min order {self.min_order_krw:.0f}",
            )

        sizing_tag = "structure-sized" if used_structure else f"ATR-sized (atr={a:.2f})"
        return RiskDecision(
            approved=True,
            position_size_krw=round(size_krw, 0),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            reason=f"{sizing_tag}, risk={risk_amount:.0f} KRW",
        )

    # ------------------------------------------------------------------
    # Exit checks (called by bot each tick for open positions)
    # ------------------------------------------------------------------
    @staticmethod
    def should_stop_out(price: float, position: Dict) -> bool:
        sl = position.get("stop_loss")
        return sl is not None and price <= sl

    @staticmethod
    def should_take_profit(price: float, position: Dict) -> bool:
        tp = position.get("take_profit")
        return tp is not None and price >= tp

    # ------------------------------------------------------------------
    # Trailing stop-loss
    # ------------------------------------------------------------------
    def update_trailing_stop(
        self,
        market: str,
        current_price: float,
        position: Dict,
        df: Optional[pd.DataFrame] = None,
    ) -> Optional[float]:
        """Ratchet the stop-loss upward as price moves in our favour.

        Returns the new stop-loss price (or None if no update).
        The stop NEVER moves downward — only up to lock in gains.
        """
        avg_price = position.get("avg_price", 0)
        current_sl = position.get("stop_loss")
        if avg_price <= 0 or current_price <= avg_price:
            return None

        # Calculate current ATR for dynamic distance
        atr_val = None
        if df is not None and len(df) >= 20:
            a = atr(df["high"], df["low"], df["close"], period=14)
            if not pd.isna(a.iloc[-1]):
                atr_val = float(a.iloc[-1])

        if atr_val is None or atr_val <= 0:
            return None

        # Only activate trailing once profit >= trailing_activate_atr × ATR
        profit = current_price - avg_price
        if profit < atr_val * self.trailing_activate_atr:
            return None

        # Track highest price seen for this position
        peak = self._position_peaks.get(market, current_price)
        if current_price > peak:
            peak = current_price
            self._position_peaks[market] = peak

        # Trail stop at peak - trailing_distance_atr × ATR
        trail_stop = peak - atr_val * self.trailing_distance_atr

        # Never move stop-loss downward
        if current_sl is not None and trail_stop <= current_sl:
            return None

        # Ensure trailing stop is at least above entry
        if trail_stop <= avg_price:
            return None

        log.info(
            "Trailing stop %s: %.0f -> %.0f (peak=%.0f, ATR=%.0f)",
            market, current_sl or 0, trail_stop, peak, atr_val,
        )
        return round(trail_stop, 2)

    def clear_position_peak(self, market: str) -> None:
        """Call when a position is closed to clean up tracking."""
        self._position_peaks.pop(market, None)

    # ------------------------------------------------------------------
    # Dynamic SL/TP adjustment based on current volatility
    # ------------------------------------------------------------------
    def dynamic_adjust_stops(
        self,
        market: str,
        position: Dict,
        df: pd.DataFrame,
    ) -> Optional[Dict[str, float]]:
        """Recalculate SL/TP based on current ATR. Never moves SL down or TP up
        beyond reasonable limits (protects gains, doesn't widen risk).

        Returns {"stop_loss": new_sl, "take_profit": new_tp} or None.
        """
        if df is None or len(df) < 20:
            return None

        avg_price = position.get("avg_price", 0)
        current_sl = position.get("stop_loss")
        current_tp = position.get("take_profit")
        if avg_price <= 0:
            return None

        a = atr(df["high"], df["low"], df["close"], period=14)
        if pd.isna(a.iloc[-1]):
            return None
        atr_val = float(a.iloc[-1])
        if atr_val <= 0:
            return None

        new_sl = avg_price - atr_val * self.stop_loss_atr_mult
        new_tp = avg_price + atr_val * self.take_profit_atr_mult

        # Never widen the stop (move it further from entry than current)
        if current_sl is not None:
            new_sl = max(new_sl, current_sl)
        # Never move TP further away from entry (keep original target)
        if current_tp is not None:
            new_tp = min(new_tp, current_tp)

        changed = False
        if current_sl is not None and abs(new_sl - current_sl) > 0.01:
            changed = True
        if current_tp is not None and abs(new_tp - current_tp) > 0.01:
            changed = True

        if not changed:
            return None

        return {"stop_loss": round(new_sl, 2), "take_profit": round(new_tp, 2)}

    # ------------------------------------------------------------------
    # Analyzer-adjusted entry
    # ------------------------------------------------------------------
    def evaluate_entry_with_feedback(
        self,
        df: pd.DataFrame,
        confidence: float,
        available_krw: Optional[float],
        confidence_adj: float = 1.0,
        size_adj: float = 1.0,
        signal_meta: Optional[Dict] = None,
    ) -> RiskDecision:
        """Like evaluate_entry but with analyzer feedback adjustments.

        Parameters
        ----------
        confidence_adj : float
            Multiplier from TradeAnalyzer.get_confidence_adjustment()
        size_adj : float
            Multiplier from TradeAnalyzer.get_size_adjustment()
        signal_meta : dict
            Optional strategy metadata with 'sl_suggest'/'tp_suggest' for
            structure-based exit levels.
        """
        adjusted_confidence = confidence * max(0.0, min(1.0, confidence_adj))

        # If confidence after adjustment is near zero, reject
        if adjusted_confidence < 0.1:
            return RiskDecision(
                False,
                reason=f"confidence too low after feedback ({adjusted_confidence:.2f})",
            )

        decision = self.evaluate_entry(
            df, confidence=adjusted_confidence, available_krw=available_krw,
            signal_meta=signal_meta,
        )

        if decision.approved and size_adj != 1.0:
            decision.position_size_krw = round(
                decision.position_size_krw * max(0.1, min(1.0, size_adj)), 0,
            )
            if decision.position_size_krw < self.min_order_krw:
                return RiskDecision(
                    False,
                    reason=f"size {decision.position_size_krw:.0f} KRW below min after feedback adjustment",
                )

        return decision
