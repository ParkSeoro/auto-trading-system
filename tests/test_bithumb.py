"""Unit tests for Bithumb client - covers parsing, signing, and order mapping.
No network: HTTP is monkey-patched.
"""
import base64
import hashlib
import hmac
import urllib.parse
from unittest.mock import patch

import pytest

from src.exchanges.base import OrderSide, OrderType
from src.exchanges.bithumb import BithumbError, BithumbExchange, parse_market


# ------------------------------------------------------------------
# Market parsing
# ------------------------------------------------------------------
def test_parse_market_upbit_style():
    assert parse_market("KRW-BTC") == ("BTC", "KRW")


def test_parse_market_bithumb_style():
    assert parse_market("BTC_KRW") == ("BTC", "KRW")


def test_parse_market_bare_symbol_defaults_krw():
    assert parse_market("ETH") == ("ETH", "KRW")


def test_parse_market_lowercase_is_normalized():
    assert parse_market("krw-xrp") == ("XRP", "KRW")


# ------------------------------------------------------------------
# Auth / signing
# ------------------------------------------------------------------
def test_auth_headers_require_keys():
    ex = BithumbExchange()
    with pytest.raises(BithumbError):
        ex._require_keys()


def test_sign_matches_manual_computation():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    endpoint = "/info/balance"
    body = urllib.parse.urlencode({"endpoint": endpoint, "currency": "ALL"})
    nonce = "1700000000000"

    expected = base64.b64encode(
        hmac.new(
            ("sk" * 16).encode(),
            (endpoint + chr(0) + body + chr(0) + nonce).encode(),
            hashlib.sha512,
        ).hexdigest().encode()
    ).decode()

    assert ex._sign(endpoint, body, nonce) == expected


def test_auth_headers_include_required_fields():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    headers, body = ex._auth_headers("/info/balance", {"currency": "ALL"})
    assert headers["Api-Key"] == "ak"
    assert "Api-Sign" in headers and headers["Api-Sign"]
    assert "Api-Nonce" in headers and headers["Api-Nonce"].isdigit()
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    # body contains the endpoint and currency
    parsed = dict(urllib.parse.parse_qsl(body))
    assert parsed["endpoint"] == "/info/balance"
    assert parsed["currency"] == "ALL"


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------
def test_parse_candle_from_bithumb_row():
    # [timestamp_ms, open, close, high, low, volume]
    row = [1700000000000, "50000", "50500", "51000", "49500", "12.34"]
    c = BithumbExchange._parse_candle(row)
    assert c.open == 50000
    assert c.close == 50500
    assert c.high == 51000
    assert c.low == 49500
    assert c.volume == pytest.approx(12.34)


def test_unsupported_timeframe_raises():
    ex = BithumbExchange()
    with pytest.raises(ValueError):
        ex.fetch_ohlcv("KRW-BTC", timeframe="7m")


def test_list_markets_filters_date_key():
    ex = BithumbExchange()
    fake_ticker = {
        "status": "0000",
        "data": {
            "BTC": {"closing_price": "50000000"},
            "ETH": {"closing_price": "3000000"},
            "date": "1700000000000",
        },
    }
    with patch.object(BithumbExchange, "_get", return_value=fake_ticker):
        markets = ex.list_markets()
        assert "KRW-BTC" in markets
        assert "KRW-ETH" in markets
        assert all(m.startswith("KRW-") for m in markets)
        assert "KRW-DATE" not in markets


def test_get_ticker_normalizes_fields():
    ex = BithumbExchange()
    fake = {
        "status": "0000",
        "data": {
            "closing_price": "50000000",
            "opening_price": "49000000",
            "max_price": "51000000",
            "min_price": "48000000",
            "units_traded_24H": "1000.5",
        },
    }
    with patch.object(BithumbExchange, "_get", return_value=fake):
        t = ex.get_ticker("KRW-BTC")
        assert t["trade_price"] == 50_000_000
        assert t["high_price"] == 51_000_000
        assert t["low_price"] == 48_000_000
        assert t["acc_trade_volume_24h"] == pytest.approx(1000.5)


def test_get_balances_groups_currency_prefixes():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    fake = {
        "status": "0000",
        "data": {
            "total_krw": "1000000", "available_krw": "900000", "in_use_krw": "100000",
            "total_btc": "0.01",    "available_btc": "0.005",  "in_use_btc": "0.005",
            "total_eth": "0",       "available_eth": "0",      "in_use_eth": "0",
            "xcoin_last_btc": "50000000",  # ignored
        },
    }
    with patch.object(BithumbExchange, "_post", return_value=fake):
        balances = ex.get_balances()
        by_curr = {b.currency: b for b in balances}
        assert "KRW" in by_curr and "BTC" in by_curr and "ETH" in by_curr
        assert by_curr["KRW"].balance == 900_000
        assert by_curr["KRW"].locked == 100_000
        assert by_curr["BTC"].balance == pytest.approx(0.005)
        assert by_curr["BTC"].locked == pytest.approx(0.005)


# ------------------------------------------------------------------
# Order routing
# ------------------------------------------------------------------
def test_place_order_limit_requires_volume_and_price():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    with pytest.raises(ValueError):
        ex.place_order("KRW-BTC", OrderSide.BUY, OrderType.LIMIT)


def test_place_order_market_buy_converts_funds_to_units():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    captured = {}

    def fake_get(path):
        # best-ask lookup
        return {"status": "0000", "data": {"closing_price": "50000000"}}

    def fake_post(endpoint, params):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {"status": "0000", "order_id": "abc123"}

    with patch.object(BithumbExchange, "_get", side_effect=fake_get), \
         patch.object(BithumbExchange, "_post", side_effect=fake_post):
        order = ex.place_order("KRW-BTC", OrderSide.BUY, OrderType.MARKET, funds=10_000)

    assert captured["endpoint"] == "/trade/market_buy"
    # funds=10000 / price=50_000_000 * 0.998 -> tiny units
    assert float(captured["params"]["units"]) == pytest.approx(0.000199600, abs=1e-7)
    assert captured["params"]["order_currency"] == "BTC"
    assert captured["params"]["payment_currency"] == "KRW"
    assert order.id == "abc123"
    assert order.side == OrderSide.BUY


def test_place_order_market_sell_uses_volume():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    captured = {}

    def fake_post(endpoint, params):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {"status": "0000", "order_id": "sell1"}

    with patch.object(BithumbExchange, "_post", side_effect=fake_post):
        order = ex.place_order(
            "BTC_KRW", OrderSide.SELL, OrderType.MARKET, volume=0.01
        )
    assert captured["endpoint"] == "/trade/market_sell"
    assert float(captured["params"]["units"]) == pytest.approx(0.01)
    assert order.side == OrderSide.SELL


def test_place_order_limit_bid_has_correct_type_param():
    ex = BithumbExchange(api_key="ak", secret_key="sk" * 16)
    captured = {}

    def fake_post(endpoint, params):
        captured.update(endpoint=endpoint, params=params)
        return {"status": "0000", "order_id": "lim1"}

    with patch.object(BithumbExchange, "_post", side_effect=fake_post):
        ex.place_order(
            "KRW-BTC", OrderSide.BUY, OrderType.LIMIT,
            volume=0.001, price=50_000_000,
        )
    assert captured["endpoint"] == "/trade/place"
    assert captured["params"]["type"] == "bid"
    assert captured["params"]["order_currency"] == "BTC"
    assert captured["params"]["units"] == "0.00100000"
    assert captured["params"]["price"] == "50000000"


def test_factory_builds_bithumb_by_default(monkeypatch):
    monkeypatch.setenv("EXCHANGE", "bithumb")
    # Re-import settings + factory to pick up env
    from importlib import reload
    import config.settings as cfg
    import src.exchanges as ex_mod
    reload(cfg)
    reload(ex_mod)
    ex = ex_mod.build_exchange()
    assert ex.name == "bithumb"
