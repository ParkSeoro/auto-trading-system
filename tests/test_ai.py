"""Tests for the AI layer: Hedge updater, trade attribution, evolver."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ai.adaptive import (
    AdaptiveEnsembleStrategy,
    WeightStore,
    compute_strategy_rewards,
    hedge_update,
)
from src.ai.evolver import StrategyEvolver


# ------------------------------------------------------------------
# hedge_update
# ------------------------------------------------------------------
def test_hedge_update_normalises_and_penalises_loser():
    w = {"a": 0.5, "b": 0.5}
    new = hedge_update(w, {"a": 1.0, "b": -1.0}, eta=0.5, floor=0.0)
    # weights still sum to 1
    assert pytest.approx(sum(new.values()), rel=1e-6) == 1.0
    # winner beats loser
    assert new["a"] > new["b"]


def test_hedge_update_respects_floor():
    w = {"a": 0.9, "b": 0.1}
    new = hedge_update(w, {"a": 1.0, "b": -1.0}, eta=3.0, floor=0.1)
    assert new["b"] >= 0.1 - 1e-6
    assert pytest.approx(sum(new.values()), rel=1e-6) == 1.0


def test_hedge_update_no_data_returns_uniform():
    new = hedge_update({}, {})
    assert new == {}


# ------------------------------------------------------------------
# compute_strategy_rewards — FIFO PnL attribution
# ------------------------------------------------------------------
def _seed_trades(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, market TEXT, "
        "side TEXT, price REAL, quantity REAL, funds REAL, fee REAL, mode TEXT, "
        "strategy TEXT, reason TEXT, order_id TEXT)"
    )
    rows = [
        # VB: buy 0.01 @ 50M, sell 0.01 @ 55M   -> +50k
        ("2024-01-01", "KRW-BTC", "buy", 50_000_000, 0.01, 500_000, 250, "paper", "vb", "", "1"),
        ("2024-01-02", "KRW-BTC", "sell", 55_000_000, 0.01, 550_000, 275, "paper", "vb", "", "2"),
        # RSI: buy 0.01 @ 60M, sell 0.01 @ 55M  -> -50k
        ("2024-01-03", "KRW-BTC", "buy", 60_000_000, 0.01, 600_000, 300, "paper", "rsi", "", "3"),
        ("2024-01-04", "KRW-BTC", "sell", 55_000_000, 0.01, 550_000, 275, "paper", "rsi", "", "4"),
    ]
    conn.executemany(
        "INSERT INTO trades(ts,market,side,price,quantity,funds,fee,mode,strategy,reason,order_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_compute_rewards_attributes_pnl_per_strategy(tmp_path):
    db = tmp_path / "t.sqlite"
    _seed_trades(db)
    rewards, max_id = compute_strategy_rewards(db, since_id=0, scale_krw=100_000.0)
    assert max_id == 4
    # vb profitable, rsi losing
    assert rewards["vb"] > 0
    assert rewards["rsi"] < 0
    # clipped to [-1, 1]
    assert -1.0 <= rewards["rsi"] <= 1.0
    assert -1.0 <= rewards["vb"] <= 1.0


def test_compute_rewards_ignores_earlier_ids(tmp_path):
    db = tmp_path / "t.sqlite"
    _seed_trades(db)
    rewards, max_id = compute_strategy_rewards(db, since_id=100)
    # Nothing newer than id=100
    assert rewards == {}
    assert max_id == 100


# ------------------------------------------------------------------
# WeightStore round-trip
# ------------------------------------------------------------------
def test_weight_store_roundtrip(tmp_path):
    p = tmp_path / "w.json"
    store = WeightStore(p)
    assert store.load()["weights"] == {}
    store.save({"a": 0.4, "b": 0.6}, last_trade_id=42)
    again = store.load()
    assert again["weights"] == {"a": 0.4, "b": 0.6}
    assert again["last_trade_id"] == 42


# ------------------------------------------------------------------
# AdaptiveEnsembleStrategy
# ------------------------------------------------------------------
def test_adaptive_ensemble_uses_equal_weights_initially(tmp_path):
    strat = AdaptiveEnsembleStrategy(
        weights_path=tmp_path / "w.json",
        db_path=tmp_path / "missing.sqlite",
    )
    # Three default members -> ~1/3 each
    assert len(strat.weights) == 3
    assert pytest.approx(sum(strat.weights.values()), rel=1e-6) == 1.0
    for v in strat.weights.values():
        assert 0.0 < v < 1.0


def test_adaptive_ensemble_adapts_from_trade_log(tmp_path):
    db = tmp_path / "trades.sqlite"
    _seed_trades(db)
    # Rename strategies in DB to match ensemble member names
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE trades SET strategy='volatility_breakout' WHERE strategy='vb'")
    conn.execute("UPDATE trades SET strategy='rsi_mean_reversion' WHERE strategy='rsi'")
    conn.commit()
    conn.close()

    strat = AdaptiveEnsembleStrategy(
        weights_path=tmp_path / "w.json",
        db_path=db,
        eta=1.0,
    )
    before = dict(strat.weights)
    updated = strat.adapt()
    assert updated["volatility_breakout"] > before["volatility_breakout"]
    assert updated["rsi_mean_reversion"] < before["rsi_mean_reversion"]
    assert pytest.approx(sum(updated.values()), rel=1e-6) == 1.0


def test_adaptive_ensemble_holds_on_short_history(tmp_path):
    strat = AdaptiveEnsembleStrategy(
        weights_path=tmp_path / "w.json",
        db_path=tmp_path / "none.sqlite",
    )
    df = pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.0] * 5, "low": [1.0] * 5,
         "close": [1.0] * 5, "volume": [1.0] * 5},
        index=pd.date_range("2024-01-01", periods=5, freq="D"),
    )
    sig = strat.generate(df)
    assert sig.type.value == "hold"


# ------------------------------------------------------------------
# StrategyEvolver
# ------------------------------------------------------------------
def _synthetic_ohlcv(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Trending walk + noise so strategies actually have edges to find
    steps = rng.normal(0.001, 0.02, size=n).cumsum()
    price = 50_000_000.0 * np.exp(steps)
    high = price * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = price * (1 - np.abs(rng.normal(0, 0.01, n)))
    openp = np.roll(price, 1)
    openp[0] = price[0]
    vol = rng.uniform(1, 10, n)
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": price, "volume": vol},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


def test_evolver_returns_valid_params_in_bounds():
    ev = StrategyEvolver(population_size=6, generations=2, seed=7)
    df = _synthetic_ohlcv(250)
    res = ev.evolve("rsi_mean_reversion", df)
    assert set(res.best_params) >= {"period", "oversold", "overbought"}
    assert 7 <= res.best_params["period"] <= 30
    assert 15.0 <= res.best_params["oversold"] <= 35.0
    assert 65.0 <= res.best_params["overbought"] <= 85.0
    assert len(res.history) == 2


def test_evolver_rejects_unknown_strategy():
    ev = StrategyEvolver(population_size=4, generations=1)
    with pytest.raises(ValueError):
        ev.evolve("nope", _synthetic_ohlcv(100))


def test_evolver_raises_on_too_little_data():
    ev = StrategyEvolver(population_size=4, generations=1)
    with pytest.raises(ValueError):
        ev.evolve("volatility_breakout", _synthetic_ohlcv(20))
