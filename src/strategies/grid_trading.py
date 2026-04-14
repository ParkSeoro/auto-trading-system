"""Grid trading strategy — popular in sideways crypto markets.

Sets up N buy/sell levels around a reference (anchor) price. On each bar:
- Buy when price crosses down through an unfilled buy level (below anchor).
- Sell when price crosses up through an unfilled sell level (above anchor).

This strategy performs especially well in mean-reverting range markets
and is uncommon in equity trading because of fractional-share/tax frictions
that don't apply to crypto.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.strategies.base import Signal, SignalType, Strategy


class GridTradingStrategy(Strategy):
    name = "grid"

    def __init__(
        self,
        grid_pct: float = 0.01,   # 1% spacing between levels
        levels: int = 5,          # number of levels on each side
    ):
        if grid_pct <= 0 or levels <= 0:
            raise ValueError("grid_pct and levels must be positive.")
        self.grid_pct = grid_pct
        self.levels = levels
        self.required_bars = 30

        self.anchor: Optional[float] = None
        # track which relative level we are currently on (0 = anchor, +n = sold, -n = bought)
        self.level_index: int = 0

    def _init_anchor(self, df: pd.DataFrame) -> None:
        # anchor = 30-bar mean to avoid latching onto a volatile wick
        self.anchor = float(df["close"].iloc[-self.required_bars:].mean())
        self.level_index = 0

    def _level_price(self, index: int) -> float:
        assert self.anchor is not None
        return self.anchor * (1.0 + self.grid_pct * index)

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        if self.anchor is None:
            self._init_anchor(df)

        price = float(df["close"].iloc[-1])

        next_buy_level = self.level_index - 1
        next_sell_level = self.level_index + 1

        # Buy when price touches the next lower grid level
        if next_buy_level >= -self.levels and price <= self._level_price(next_buy_level):
            self.level_index = next_buy_level
            return Signal(
                SignalType.BUY,
                confidence=0.7,
                reason=f"grid buy L{next_buy_level}",
                meta={"anchor": self.anchor, "level": next_buy_level, "price": price},
            )

        # Sell when price touches the next upper grid level
        if (
            next_sell_level <= self.levels
            and price >= self._level_price(next_sell_level)
            and position
            and position.get("quantity", 0) > 0
        ):
            self.level_index = next_sell_level
            return Signal(
                SignalType.SELL,
                confidence=0.7,
                reason=f"grid sell L{next_sell_level}",
                meta={"anchor": self.anchor, "level": next_sell_level, "price": price},
            )

        return Signal.hold(f"grid idle L{self.level_index} @ {price:.2f}")

    def reset(self) -> None:
        self.anchor = None
        self.level_index = 0
