"""Tests for the FastAPI dashboard — use TestClient, no network."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.bot_manager import BotManager


@pytest.fixture
def client():
    # A fresh manager per test keeps state isolated.
    app = create_app(manager=BotManager())
    with TestClient(app) as c:
        yield c


def test_status_returns_idle_by_default(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["running"] is False
    assert "server_time" in data
    assert data["default_exchange"] in ("bithumb", "upbit")


def test_exchanges_endpoint_lists_both(client):
    r = client.get("/api/exchanges")
    assert r.status_code == 200
    body = r.json()
    assert set(body["exchanges"]) == {"bithumb", "upbit"}
    assert body["bithumb_fee"] > 0
    assert body["upbit_fee"] > 0


def test_strategies_includes_adaptive(client):
    r = client.get("/api/strategies")
    assert r.status_code == 200
    names = r.json()["strategies"]
    assert "adaptive_ensemble" in names
    assert "ensemble" in names
    assert "volatility_breakout" in names


def test_equity_and_trades_return_lists(client):
    # Even with no DB / empty DB, endpoints should return a JSON envelope.
    r1 = client.get("/api/equity")
    assert r1.status_code == 200
    assert isinstance(r1.json().get("equity"), list)

    r2 = client.get("/api/trades")
    assert r2.status_code == 200
    assert isinstance(r2.json().get("trades"), list)


def test_positions_empty_when_no_bot(client):
    r = client.get("/api/positions")
    assert r.status_code == 200
    assert r.json() == {"positions": []}


def test_weights_endpoint_returns_envelope(client):
    r = client.get("/api/weights")
    assert r.status_code == 200
    body = r.json()
    assert "weights" in body
    assert "best_params" in body


def test_start_validates_mode(client):
    r = client.post("/api/start", json={"mode": "wrong", "markets": ["KRW-BTC"]})
    assert r.status_code == 422  # pydantic rejects invalid pattern


def test_stop_is_idempotent_when_not_running(client):
    r = client.post("/api/stop")
    assert r.status_code == 200
    assert r.json()["running"] is False


def test_start_stop_roundtrip(client, monkeypatch):
    """Use a stub exchange so we don't hit the network."""
    import src.web.bot_manager as bm

    class _FakeExchange:
        name = "fake"
        def list_markets(self): return ["KRW-BTC"]
        def get_ticker(self, m): return {"trade_price": 1.0}
        def fetch_ohlcv(self, m, timeframe="1d", count=200): return []
        def get_balances(self): return []
        def place_order(self, *a, **kw): raise NotImplementedError
        def cancel_order(self, *a): return True
        def get_order(self, *a): raise NotImplementedError

    # Patch the exchange factory used by build_bot
    import src.exchanges as ex_mod
    monkeypatch.setattr(ex_mod, "build_exchange", lambda name=None: _FakeExchange())

    # The bot.py imports build_exchange lazily at build_bot() call; its
    # reference is ``from src.exchanges import build_exchange`` inside the
    # function body, so the monkeypatch above is effective.

    r = client.post(
        "/api/start",
        json={
            "mode": "paper",
            "markets": ["KRW-BTC"],
            "strategy": "volatility_breakout",
            "timeframe": "1d",
        },
    )
    # It should start (thread spawns, loop runs but sleeps on .get_ohlcv returning empty)
    assert r.status_code == 200, r.text
    status = r.json()
    assert status["running"] is True
    assert status["exchange"] == "fake"

    # Conflict when starting again
    r2 = client.post(
        "/api/start",
        json={"mode": "paper", "markets": ["KRW-BTC"], "strategy": "volatility_breakout"},
    )
    assert r2.status_code == 409

    # Stop cleanly
    r3 = client.post("/api/stop")
    assert r3.status_code == 200
    assert r3.json()["running"] is False
