"""RSI-based mean reversion, tuned for crypto.

Crypto RSI thresholds are more extreme than stocks because of the high volatility:
- Oversold at 25 (vs 30 in stocks)
- Overbought at 75 (vs 70)
Also uses volume confirmation to avoid knife-catching during dumps.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.indicators import rsi
from src.strategies.base import Signal, SignalType, Strategy


class RSIMeanReversionStrategy(Strategy):
    name = "rsi_mean_reversion"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 35.0,
        overbought: float = 70.0,
        confirm_bars: int = 1,
    ):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.confirm_bars = confirm_bars
        self.required_bars = period * 3

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        r = rsi(df["close"], self.period)
        current = r.iloc[-1]
        if pd.isna(current):
            return Signal.hold("rsi warming up")

        has_position = bool(position and position.get("quantity", 0) > 0)

        # Exit overbought
        if has_position and current >= self.overbought:
            return Signal(
                SignalType.SELL,
                confidence=min(1.0, (current - self.overbought) / 25.0 + 0.5),
                reason=f"RSI overbought ({current:.1f})",
                meta={"rsi": float(current)},
            )

        # Entry oversold with upward reversal + volume confirmation
        if not has_position and current <= self.oversold:
            prev = r.iloc[-2]
            if not pd.isna(prev) and current > prev:
                vol_now = float(df["volume"].iloc[-1])
                vol_avg = float(df["volume"].iloc[-21:-1].mean()) if len(df) > 21 else float(df["volume"].mean())
                if vol_avg > 0 and vol_now < vol_avg * 0.5:
                    return Signal.hold(f"RSI oversold but low volume ({vol_now/vol_avg:.1f}x)")
                confidence = min(1.0, (self.oversold - current) / 25.0 + 0.5)
                return Signal(
                    SignalType.BUY,
                    confidence=confidence,
                    reason=f"RSI oversold reversal ({current:.1f}, vol={vol_now/vol_avg:.1f}x)" if vol_avg > 0 else f"RSI oversold reversal ({current:.1f})",
                    meta={"rsi": float(current)},
                )

        return Signal.hold(f"rsi={current:.1f}")
