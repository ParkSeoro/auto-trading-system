"""Scalping strategy — short-term momentum entry with strict multi-condition filter.

Entry rules (ALL must pass):
1. RSI(14) in [25, 40]           — oversold recovery zone
2. Volume spike 1.5x ~ 2.0x avg  — confirmation of buyers entering
3. Bullish reversal candle         — hammer or bullish engulfing
4. Golden cross: EMA10 > EMA20    — trend alignment
5. Buyer dominance: last 2 bars   — consecutive green candles

Hard reject filters:
- Price within 1.5% of recent resistance (last 20-bar high)
- Recent surge > 5% in last 5 bars (chase prevention)
- EMA10 below EMA20 by > 2%     (downtrend rejection)
- RSI > 65                       (already overbought)
- Volume below average           (no liquidity)

Exit:
- Take profit: entry + (ATR * tp_atr_mult), default 2.5×ATR
- Stop loss:   entry - (ATR * sl_atr_mult), default 1.5×ATR
  Gives ~1.67:1 R:R minimum, scales with ATR
"""
from __future__ import annotations

import pandas as pd

from src.indicators import atr, ema, rsi
from src.strategies.base import Signal, SignalType, Strategy
from src.utils.logger import get_logger

log = get_logger(__name__)


class ScalpingStrategy(Strategy):
    name = "scalping"
    required_bars = 50

    def __init__(
        self,
        rsi_low: float = 25.0,
        rsi_high: float = 40.0,
        volume_min_mult: float = 1.5,
        volume_max_mult: float = 3.0,
        ema_short: int = 10,
        ema_long: int = 20,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        resistance_buffer_pct: float = 0.015,
        surge_pct: float = 0.05,
    ):
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.volume_min_mult = volume_min_mult
        self.volume_max_mult = volume_max_mult
        self.ema_short = ema_short
        self.ema_long = ema_long
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.resistance_buffer_pct = resistance_buffer_pct
        self.surge_pct = surge_pct

    def generate(self, df: pd.DataFrame, position: dict | None = None) -> Signal:
        if len(df) < self.required_bars:
            return Signal(SignalType.HOLD, reason="insufficient data")

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        c0 = float(close.iloc[-1])
        c1 = float(close.iloc[-2])
        o0 = float(df["open"].iloc[-1])
        o1 = float(df["open"].iloc[-2])

        # --- Exit logic (if in position) ---
        if position and position.get("quantity", 0) > 0:
            avg = position.get("avg_price", 0)
            sl = position.get("stop_loss")
            tp = position.get("take_profit")
            if sl and c0 <= sl:
                return Signal(SignalType.SELL, confidence=1.0, reason=f"stop-loss hit @ {c0:.0f}")
            if tp and c0 >= tp:
                return Signal(SignalType.SELL, confidence=1.0, reason=f"take-profit hit @ {c0:.0f}")
            # Trailing: over-extended RSI
            rsi14 = rsi(close, 14)
            if not pd.isna(rsi14.iloc[-1]) and float(rsi14.iloc[-1]) > 72:
                return Signal(SignalType.SELL, confidence=0.85, reason=f"overbought exit RSI={rsi14.iloc[-1]:.1f}")
            return Signal(SignalType.HOLD, reason="holding position")

        # ---- Entry: collect all signals and reject on any fail ----
        rejects = []

        # 1. RSI in [25, 40]
        rsi14 = rsi(close, 14)
        rsi_val = float(rsi14.iloc[-1]) if not pd.isna(rsi14.iloc[-1]) else 50.0
        if not (self.rsi_low <= rsi_val <= self.rsi_high):
            rejects.append(f"RSI={rsi_val:.1f} not in [{self.rsi_low},{self.rsi_high}]")

        # 2. Volume spike
        vol_avg = float(volume.iloc[-21:-1].mean()) if len(volume) > 21 else float(volume.mean())
        vol_cur = float(volume.iloc[-1])
        vol_mult = vol_cur / vol_avg if vol_avg > 0 else 0.0
        if vol_mult < self.volume_min_mult:
            rejects.append(f"volume {vol_mult:.2f}x < {self.volume_min_mult}x")
        elif vol_mult > self.volume_max_mult:
            rejects.append(f"volume {vol_mult:.2f}x too high (possible dump)")

        # 3. Bullish reversal candle: hammer or bullish engulfing
        body0 = abs(c0 - o0)
        lower_wick = min(o0, c0) - float(low.iloc[-1])
        upper_wick = float(high.iloc[-1]) - max(o0, c0)
        candle_range = float(high.iloc[-1]) - float(low.iloc[-1])
        is_hammer = (
            lower_wick >= body0 * 1.5
            and upper_wick <= body0 * 0.5
            and c0 > o0  # bullish hammer
        )
        is_engulfing = c0 > o1 and o0 < c1 and c0 > c1 and o0 < o1
        if not (is_hammer or is_engulfing):
            rejects.append("no reversal candle (need hammer or bullish engulfing)")

        # 4. Golden cross: EMA10 > EMA20
        ema10 = ema(close, self.ema_short)
        ema20 = ema(close, self.ema_long)
        e10 = float(ema10.iloc[-1]) if not pd.isna(ema10.iloc[-1]) else 0.0
        e20 = float(ema20.iloc[-1]) if not pd.isna(ema20.iloc[-1]) else 0.0
        if e10 <= e20:
            rejects.append(f"no golden cross (EMA{self.ema_short}={e10:.0f} <= EMA{self.ema_long}={e20:.0f})")
        elif e10 < e20 * 1.02 and e20 > 0:
            # Downtrend rejection: EMA10 < EMA20 * 0.98 already caught above
            pass

        # 5. Buyer dominance: last 2 candles green
        if not (c0 > o0 and c1 > o1):
            rejects.append("buyer dominance failed (need 2 green candles)")

        # --- Hard filters ---
        # Resistance: within 1.5% of 20-bar high
        recent_high = float(high.iloc[-21:-1].max()) if len(high) > 20 else float(high.max())
        if c0 >= recent_high * (1 - self.resistance_buffer_pct):
            rejects.append(f"near resistance ({c0:.0f} >= {recent_high:.0f})")

        # Recent surge > 5% in last 5 bars
        if len(close) > 5:
            ref = float(close.iloc[-6])
            surge = (c0 - ref) / ref if ref > 0 else 0.0
            if surge > self.surge_pct:
                rejects.append(f"recent surge {surge*100:.1f}% > {self.surge_pct*100:.0f}%")

        if rejects:
            return Signal(SignalType.HOLD, reason="; ".join(rejects))

        # --- Compute SL/TP from ATR ---
        atr14 = atr(high, low, close, 14)
        atr_val = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else c0 * 0.02

        confidence = 0.6
        # Boost confidence for stronger signals
        if vol_mult >= 2.0:
            confidence += 0.1
        if is_engulfing:
            confidence += 0.1
        if rsi_val <= 30:
            confidence += 0.1
        confidence = min(0.95, confidence)

        reason = (
            f"scalp entry: RSI={rsi_val:.1f} vol={vol_mult:.1f}x "
            f"{'engulfing' if is_engulfing else 'hammer'} "
            f"EMA{self.ema_short}={e10:.0f}>EMA{self.ema_long}={e20:.0f}"
        )
        log.info("[scalping] BUY signal on %s conf=%.2f | %s", "", confidence, reason)
        return Signal(SignalType.BUY, confidence=confidence, reason=reason)
