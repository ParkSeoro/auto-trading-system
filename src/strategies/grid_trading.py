"""Grid trading strategy — popular in sideways crypto markets.

Sets up N buy/sell levels around a reference (anchor) price. On each bar:
- Buy when price crosses down through an unfilled buy level (below anchor).
- Sell when price crosses up through an unfilled sell level (above anchor).

This strategy performs especially well in mean-reverting range markets
and is uncommon in equity trading because of fractional-share/tax frictions
that don't apply to crypto.
"""
from __future__ import annotations

from typing import Dict, Optional

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

        # Per-market state to avoid cross-market interference
        self._anchors: Dict[str, float] = {}
        self._level_indices: Dict[str, int] = {}

    def _get_market_key(self, df: pd.DataFrame) -> str:
        if hasattr(df.index, 'name') and df.index.name:
            return str(df.index.name)
        return str(id(df))

    def _init_anchor(self, key: str, df: pd.DataFrame) -> None:
        self._anchors[key] = float(df["close"].iloc[-self.required_bars:].mean())
        self._level_indices[key] = 0

    def _level_price(self, anchor: float, index: int) -> float:
        return anchor * (1.0 + self.grid_pct * index)

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        key = self._get_market_key(df)
        if key not in self._anchors:
            self._init_anchor(key, df)

        anchor = self._anchors[key]
        level_index = self._level_indices[key]
        price = float(df["close"].iloc[-1])

        next_buy_level = level_index - 1
        next_sell_level = level_index + 1

        # Buy when price touches the next lower grid level
        if next_buy_level >= -self.levels and price <= self._level_price(anchor, next_buy_level):
            self._level_indices[key] = next_buy_level
            return Signal(
                SignalType.BUY,
                confidence=0.7,
                reason=f"grid buy L{next_buy_level}",
                meta={"anchor": anchor, "level": next_buy_level, "price": price},
            )

        # Sell when price touches the next upper grid level
        if (
            next_sell_level <= self.levels
            and price >= self._level_price(anchor, next_sell_level)
            and position
            and position.get("quantity", 0) > 0
        ):
            self._level_indices[key] = next_sell_level
            return Signal(
                SignalType.SELL,
                confidence=0.7,
                reason=f"grid sell L{next_sell_level}",
                meta={"anchor": anchor, "level": next_sell_level, "price": price},
            )

        return Signal.hold(f"grid idle L{level_index} @ {price:.2f}")

    def reset(self) -> None:
        self._anchors.clear()
        self._level_indices.clear()
