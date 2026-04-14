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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Optional

import pandas as pd

from config.settings import settings
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
    min_order_krw: float = field(default_factory=lambda: settings.upbit_min_order_krw)

    _daily: Optional[_DailyState] = field(default=None, init=False)
    _cooldown_until: Optional[datetime] = field(default=None, init=False)
    _flash_tripped: bool = field(default=False, init=False)

    # ------------------------------------------------------------------
    # Equity / daily tracking
    # ------------------------------------------------------------------
    def update_equity(self, equity: float, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
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
        now = now or datetime.now(timezone.utc)
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
            self._cooldown_until = datetime.now(timezone.utc) + pd.Timedelta(
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
    def evaluate_entry(
        self,
        df: pd.DataFrame,
        confidence: float = 1.0,
        available_krw: Optional[float] = None,
    ) -> RiskDecision:
        if self.is_halted():
            return RiskDecision(False, reason="trading halted (MDD/cooldown)")

        if self.check_flash_crash(df):
            return RiskDecision(False, reason="flash-crash kill switch")

        if len(df) < 20:
            return RiskDecision(False, reason="insufficient data for ATR")

        entry_price = float(df["close"].iloc[-1])
        a = atr(df["high"], df["low"], df["close"], period=14).iloc[-1]
        if pd.isna(a) or a <= 0:
            return RiskDecision(False, reason="ATR unavailable")

        stop_distance = float(a) * self.stop_loss_atr_mult
        stop_loss = entry_price - stop_distance
        take_profit = entry_price + float(a) * self.take_profit_atr_mult

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

        return RiskDecision(
            approved=True,
            position_size_krw=round(size_krw, 0),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            reason=f"ATR-sized (atr={a:.2f}, risk={risk_amount:.0f} KRW)",
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
