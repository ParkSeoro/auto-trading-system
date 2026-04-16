"""Bollinger Band squeeze + breakout.

Crypto markets often have extended consolidation periods followed by violent
breakouts. This strategy detects low-volatility squeezes (bandwidth < threshold)
and enters on breaks above the upper band with volume confirmation.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.indicators import bollinger_bands
from src.strategies.base import Signal, SignalType, Strategy


class BollingerBreakoutStrategy(Strategy):
    name = "bollinger_breakout"

    def __init__(
        self,
        period: int = 20,
        num_std: float = 2.0,
        squeeze_pct: float = 0.06,       # bandwidth/middle threshold for squeeze
        volume_factor: float = 0.9,
    ):
        self.period = period
        self.num_std = num_std
        self.squeeze_pct = squeeze_pct
        self.volume_factor = volume_factor
        self.required_bars = period * 2

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        upper, middle, lower = bollinger_bands(df["close"], self.period, self.num_std)
        current_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        u, m, l = upper.iloc[-1], middle.iloc[-1], lower.iloc[-1]

        if pd.isna(u) or pd.isna(m) or pd.isna(l) or m == 0:
            return Signal.hold("bands warming up")

        bandwidth = (u - l) / m
        vol_avg = df["volume"].iloc[-self.period:-1].mean()
        vol_now = df["volume"].iloc[-1]

        has_position = bool(position and position.get("quantity", 0) > 0)

        # Exit: close below middle band
        if has_position and current_close < m:
            return Signal(
                SignalType.SELL,
                confidence=1.0,
                reason="BB exit: close below middle",
                meta={"middle": float(m)},
            )

        # Entry: squeeze released + breakout above upper w/ volume
        if (
            not has_position
            and current_close > u
            and prev_close <= upper.iloc[-2]
            and bandwidth < self.squeeze_pct * 3       # not already expanded too wide
            and vol_now >= (vol_avg or 0) * self.volume_factor
        ):
            return Signal(
                SignalType.BUY,
                confidence=min(1.0, 0.5 + bandwidth * 10),
                reason="BB squeeze breakout",
                meta={
                    "bandwidth": float(bandwidth),
                    "upper": float(u),
                    "volume_ratio": float(vol_now / (vol_avg or 1)),
                },
            )

        return Signal.hold(f"bandwidth={bandwidth:.4f}")
