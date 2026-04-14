"""Shared pytest fixtures."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root on sys.path so "config" and "src" resolve
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_ohlcv(
    n: int = 250,
    start_price: float = 50_000_000.0,
    drift: float = 0.0005,
    vol: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministic synthetic OHLCV that looks like a crypto daily bar."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n)
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2, n)))
    opens = np.concatenate([[start_price], close[:-1]])
    volume = rng.uniform(100, 1000, n)
    idx = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
    df = pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.Index(idx, name="timestamp"),
    )
    return df


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    return _make_ohlcv()


@pytest.fixture
def trending_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(drift=0.01, vol=0.015, seed=7)


@pytest.fixture
def sideways_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(drift=0.0, vol=0.01, seed=21)


@pytest.fixture
def flash_crash_ohlcv() -> pd.DataFrame:
    df = _make_ohlcv(n=100, vol=0.01, seed=11)
    # Introduce a -12% plunge over the last 5 bars
    crash = df.iloc[-6]["close"]
    for i, frac in enumerate([0.97, 0.94, 0.91, 0.89, 0.88]):
        idx = df.index[-5 + i]
        df.loc[idx, "close"] = crash * frac
        df.loc[idx, "low"] = crash * frac * 0.99
        df.loc[idx, "high"] = crash * frac * 1.005
        df.loc[idx, "open"] = crash * (frac + 0.005)
    return df
