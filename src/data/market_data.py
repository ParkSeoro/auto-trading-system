"""Market data fetcher with a small in-memory cache.

Crypto OHLCV is typically fetched every loop tick; a cache avoids hammering
the exchange rate limits. We refresh when the cache is older than `ttl_sec`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.exchanges.base import Candle, Exchange


def candles_to_dataframe(candles: List[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([c.as_dict() for c in candles])
    df = df.set_index("timestamp").sort_index()
    df[["open", "high", "low", "close", "volume"]] = df[
        ["open", "high", "low", "close", "volume"]
    ].astype(float)
    return df


@dataclass
class _CacheEntry:
    df: pd.DataFrame
    fetched_at: float


@dataclass
class MarketData:
    exchange: Exchange
    ttl_sec: int = 30
    _cache: Dict[Tuple[str, str, int], _CacheEntry] = field(default_factory=dict)

    def get_ohlcv(
        self,
        market: str,
        timeframe: str = "1d",
        count: int = 200,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        key = (market, timeframe, count)
        now = time.time()
        entry = self._cache.get(key)
        if (
            not force_refresh
            and entry is not None
            and (now - entry.fetched_at) < self.ttl_sec
        ):
            return entry.df

        candles = self.exchange.fetch_ohlcv(market, timeframe=timeframe, count=count)
        df = candles_to_dataframe(candles)
        self._cache[key] = _CacheEntry(df=df, fetched_at=now)
        return df

    def get_current_price(self, market: str) -> Optional[float]:
        try:
            ticker = self.exchange.get_ticker(market)
            return float(ticker.get("trade_price"))
        except Exception:  # pragma: no cover - network
            return None
