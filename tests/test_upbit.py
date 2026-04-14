"""Unit tests for Upbit client - covers parsing, JWT headers, and order mapping.
No network: HTTP is monkey-patched.
"""
from unittest.mock import patch

import pytest

from src.exchanges.base import OrderSide, OrderType
from src.exchanges.upbit import UpbitExchange, UpbitError


def test_auth_headers_require_keys():
    ex = UpbitExchange()
    with pytest.raises(UpbitError):
        ex._auth_headers()


def test_auth_headers_with_query():
    ex = UpbitExchange(access_key="a", secret_key="b" * 32)
    h = ex._auth_headers({"uuid": "123"})
    assert "Authorization" in h
    assert h["Authorization"].startswith("Bearer ")


def test_parse_candle_from_upbit_payload():
    row = {
        "candle_date_time_utc": "2024-05-01T00:00:00",
        "opening_price": 50000,
        "high_price": 51000,
        "low_price": 49500,
        "trade_price": 50500,
        "candle_acc_trade_volume": 12.34,
    }
    c = UpbitExchange._parse_candle(row)
    assert c.open == 50000
    assert c.high == 51000
    assert c.low == 49500
    assert c.close == 50500
    assert c.volume == pytest.approx(12.34)


def test_parse_order_bid_limit():
    ex = UpbitExchange()
    order = ex._parse_order({
        "uuid": "abc", "market": "KRW-BTC", "side": "bid", "ord_type": "limit",
        "state": "done", "price": "50000000", "volume": "0.001",
        "executed_volume": "0.001", "avg_price": "50000000", "paid_fee": "25",
        "created_at": "2024-05-01T00:00:00+09:00",
    })
    assert order.id == "abc"
    assert order.side == OrderSide.BUY
    assert order.type == OrderType.LIMIT
    assert order.filled_volume == 0.001
    assert order.fee == 25


def test_place_order_limit_requires_volume_and_price():
    ex = UpbitExchange(access_key="a", secret_key="b" * 32)
    with pytest.raises(ValueError):
        ex.place_order("KRW-BTC", OrderSide.BUY, OrderType.LIMIT)


def test_place_order_market_buy_uses_funds():
    ex = UpbitExchange(access_key="a", secret_key="b" * 32)

    captured = {}

    def fake_request(method, path, params=None, authed=False):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        captured["authed"] = authed
        return {
            "uuid": "o1", "market": params["market"], "side": params["side"],
            "ord_type": params["ord_type"], "state": "wait",
            "price": params.get("price", "0"), "volume": "0",
            "executed_volume": "0", "paid_fee": "0",
        }

    with patch.object(UpbitExchange, "_request", side_effect=fake_request):
        order = ex.place_order("KRW-BTC", OrderSide.BUY, OrderType.MARKET, funds=10_000)
        assert captured["method"] == "POST"
        assert captured["authed"] is True
        assert captured["params"]["ord_type"] == "price"
        assert captured["params"]["price"] == "10000"
        assert order.id == "o1"


def test_place_order_market_sell_uses_volume():
    ex = UpbitExchange(access_key="a", secret_key="b" * 32)

    def fake_request(method, path, params=None, authed=False):
        return {
            "uuid": "o2", "market": params["market"], "side": params["side"],
            "ord_type": params["ord_type"], "state": "wait",
            "price": "0", "volume": params["volume"],
            "executed_volume": "0", "paid_fee": "0",
        }

    with patch.object(UpbitExchange, "_request", side_effect=fake_request):
        order = ex.place_order(
            "KRW-BTC", OrderSide.SELL, OrderType.MARKET, volume=0.001
        )
        assert order.side == OrderSide.SELL
        assert order.type == OrderType.MARKET


def test_unsupported_timeframe_raises():
    ex = UpbitExchange()
    with pytest.raises(ValueError):
        ex.fetch_ohlcv("KRW-BTC", timeframe="7m")
