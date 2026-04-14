"""Abstract exchange interface + data classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"       # 지정가
    MARKET = "market"     # 시장가(매도) / 가격지정(매수: KRW 총액)
    # Upbit-specific: price = 시장가 매수(금액 지정), market = 시장가 매도(수량 지정)


@dataclass
class Candle:
    """OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class Order:
    id: str
    market: str
    side: OrderSide
    type: OrderType
    price: Optional[float]
    volume: Optional[float]
    funds: Optional[float]
    status: str
    created_at: Optional[datetime] = None
    filled_volume: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0


@dataclass
class Balance:
    currency: str
    balance: float          # available
    locked: float           # tied up in open orders
    avg_buy_price: float = 0.0

    @property
    def total(self) -> float:
        return self.balance + self.locked


class Exchange(ABC):
    """Minimal interface the bot needs from any exchange."""

    name: str = "abstract"

    # --- Public (no auth) ---
    @abstractmethod
    def list_markets(self) -> List[str]:
        ...

    @abstractmethod
    def get_ticker(self, market: str) -> dict:
        ...

    @abstractmethod
    def fetch_ohlcv(self, market: str, timeframe: str = "1d", count: int = 200) -> List[Candle]:
        """timeframe: '1m','3m','5m','15m','30m','1h','4h','1d','1w'"""
        ...

    # --- Private (auth required) ---
    @abstractmethod
    def get_balances(self) -> List[Balance]:
        ...

    @abstractmethod
    def place_order(
        self,
        market: str,
        side: OrderSide,
        order_type: OrderType,
        volume: Optional[float] = None,
        price: Optional[float] = None,
        funds: Optional[float] = None,
    ) -> Order:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order:
        ...
