"""Tests for the market screener."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.screener.market_screener import MarketScreener, MarketScore


def _make_df(n=100, trend=True, volume=500, seed=42):
    rng = np.random.default_rng(seed)
    drift = 0.002 if trend else 0.0
    returns = rng.normal(drift, 0.02, n)
    close = 50_000_000.0 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    opens = np.concatenate([[50_000_000.0], close[:-1]])
    vol = rng.uniform(volume * 0.5, volume * 1.5, n)
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


def test_score_trending_market():
    screener = MarketScreener()
    df = _make_df(trend=True, volume=500)
    score = screener.score_market(df, market="KRW-BTC")
    assert score.market == "KRW-BTC"
    assert score.total_score > 0.0
    assert 0.0 <= score.volume_score <= 1.0
    assert 0.0 <= score.volatility_score <= 1.0
    assert 0.0 <= score.trend_score <= 1.0
    assert 0.0 <= score.momentum_score <= 1.0


def test_score_insufficient_data():
    screener = MarketScreener()
    df = pd.DataFrame(
        {"open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
         "close": [100] * 10, "volume": [1] * 10},
        index=pd.date_range("2024-01-01", periods=10, freq="D"),
    )
    score = screener.score_market(df, market="KRW-TEST")
    assert not score.tradeable
    assert "insufficient" in score.reasons[0]


def test_rank_markets():
    screener = MarketScreener(min_score=0.0)
    markets = {
        "KRW-BTC": _make_df(trend=True, volume=1000, seed=1),
        "KRW-FLAT": _make_df(trend=False, volume=10, seed=2),
    }
    ranked = screener.rank_markets(markets)
    assert len(ranked) == 2
    assert ranked[0].total_score >= ranked[1].total_score


def test_select_tradeable():
    screener = MarketScreener(min_score=0.0)
    markets = {
        "KRW-A": _make_df(trend=True, volume=500, seed=10),
        "KRW-B": _make_df(trend=True, volume=800, seed=20),
        "KRW-C": _make_df(trend=False, volume=5, seed=30),
    }
    selected = screener.select_tradeable(markets, max_markets=2)
    assert len(selected) <= 2
    assert isinstance(selected, list)


def test_to_dict():
    score = MarketScore(
        market="KRW-BTC",
        volume_score=0.8,
        volatility_score=0.6,
        trend_score=0.7,
        momentum_score=0.5,
        total_score=0.65,
        tradeable=True,
        reasons=["uptrend (EMA cross)"],
    )
    d = score.to_dict()
    assert d["market"] == "KRW-BTC"
    assert d["tradeable"] is True
    assert d["total_score"] == 0.65
