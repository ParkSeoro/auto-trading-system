"""Strategy abstraction."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    type: SignalType
    confidence: float = 1.0   # 0..1
    reason: str = ""
    meta: dict = field(default_factory=dict)

    @classmethod
    def hold(cls, reason: str = "") -> "Signal":
        return cls(SignalType.HOLD, 0.0, reason)


class Strategy(ABC):
    """Crypto strategy base class.

    Concrete strategies consume an OHLCV DataFrame (indexed by timestamp, columns
    open/high/low/close/volume) and optionally the current position, and emit a Signal.
    """

    name: str = "strategy"
    required_bars: int = 50   # minimum bars of history needed

    @abstractmethod
    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        ...

    # Convenience: make sure we have enough data
    def _validate(self, df: pd.DataFrame) -> Optional[Signal]:
        if df is None or len(df) < self.required_bars:
            return Signal.hold(f"insufficient bars ({len(df) if df is not None else 0}/"
                               f"{self.required_bars})")
        return None
