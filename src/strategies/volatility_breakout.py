"""Larry Williams-style Volatility Breakout — adapted for 24/7 crypto.

Buy signal: today's price breaks above (today_open + K * previous_range),
where range = previous_high - previous_low.

This is one of the most popular quant strategies in Korean crypto communities
because crypto markets exhibit large intraday range expansions (unlike stocks
with overnight gaps and fixed hours). The strategy naturally flattens at the
end of each 'day' bar (UTC) to ride trend bursts without overnight risk.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategies.base import Signal, SignalType, Strategy


class VolatilityBreakoutStrategy(Strategy):
    name = "volatility_breakout"

    def __init__(self, k: float = 0.4, volume_factor: float = 0.8):
        """
        :param k: breakout coefficient (0.3–0.7 typical for crypto).
        :param volume_factor: today's volume must exceed 20-bar avg * this.
        """
        if not (0.0 < k < 2.0):
            raise ValueError("k must be in (0, 2).")
        self.k = k
        self.volume_factor = volume_factor
        self.required_bars = 30

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        prev_range = prev["high"] - prev["low"]
        if prev_range <= 0:
            return Signal.hold("zero previous range")

        target = curr["open"] + self.k * prev_range
        vol_avg = df["volume"].iloc[-21:-1].mean()

        has_position = bool(position and position.get("quantity", 0) > 0)

        if has_position:
            # Only sell if current price has fallen below the breakout target
            if curr["close"] < target:
                return Signal(
                    SignalType.SELL,
                    confidence=0.7,
                    reason="VB: price below breakout target",
                    meta={"target": target},
                )
            return Signal.hold("VB: holding above breakout target")

        # Entry: current price has broken target AND volume confirms
        if curr["close"] >= target and curr["volume"] >= vol_avg * self.volume_factor:
            strength = min(1.0, (curr["close"] - target) / (prev_range or 1.0) + 0.5)
            return Signal(
                SignalType.BUY,
                confidence=strength,
                reason=f"VB breakout k={self.k}",
                meta={
                    "target": target,
                    "prev_range": prev_range,
                    "volume_ratio": curr["volume"] / (vol_avg or 1.0),
                },
            )

        return Signal.hold(f"no breakout (close={curr['close']:.2f} < target={target:.2f})")
