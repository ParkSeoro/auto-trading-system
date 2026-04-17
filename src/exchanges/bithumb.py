"""Bithumb REST client (public + authenticated endpoints).

Docs: https://apidocs.bithumb.com/

Key differences from Upbit that this adapter handles:
- Market naming: Bithumb uses ``BTC_KRW`` (order_currency_payment_currency).
  We also accept Upbit-style ``KRW-BTC`` for convenience.
- Signed requests use HMAC-SHA512 (not JWT) with a microsecond nonce.
  Signature = base64(hex_digest(HMAC_SHA512(secret, endpoint + \\0 + body + \\0 + nonce))).
- Market-buy orders take ``units`` (quantity) instead of KRW funds, so this
  adapter converts ``funds`` → ``units`` by fetching the current ticker ask.
- Candlestick endpoint returns oldest-first (no reversal needed).
- Default taker fee is 0.25% (API discount coupons can lower it; override in env).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

from src.exchanges.base import Balance, Candle, Exchange, Order, OrderSide, OrderType
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.bithumb.com"

# Our canonical timeframes -> Bithumb chart intervals
_TIMEFRAME_MAP = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "10m": "10m",
    "30m": "30m",
    "1h":  "1h",
    "6h":  "6h",
    "12h": "12h",
    "24h": "24h",
    "1d":  "24h",     # alias
}


class BithumbError(RuntimeError):
    pass


def parse_market(market: str) -> Tuple[str, str]:
    """Return (order_currency, payment_currency).

    Accepts either Bithumb native ``BTC_KRW`` or Upbit-style ``KRW-BTC``.
    Bare ``BTC`` defaults to ``KRW`` payment currency.
    """
    m = market.strip().upper()
    if "-" in m:
        payment, order = m.split("-", 1)
        return order, payment
    if "_" in m:
        order, payment = m.split("_", 1)
        return order, payment
    return m, "KRW"


class BithumbExchange(Exchange):
    name = "bithumb"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def _require_keys(self) -> None:
        if not self.api_key or not self.secret_key:
            raise BithumbError("Bithumb API keys not configured.")

    @staticmethod
    def _nonce() -> str:
        # microsecond timestamp in milliseconds (Bithumb convention)
        return str(int(time.time() * 1000))

    def _sign(self, endpoint: str, body: str, nonce: str) -> str:
        message = endpoint + chr(0) + body + chr(0) + nonce
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return base64.b64encode(digest.encode("utf-8")).decode("utf-8")

    def _auth_headers(self, endpoint: str, params: dict) -> Tuple[dict, str]:
        """Build headers + urlencoded body for a signed POST call."""
        self._require_keys()
        # Bithumb requires endpoint to be part of the body too
        body_params = {"endpoint": endpoint, **params}
        body_str = urllib.parse.urlencode(body_params)
        nonce = self._nonce()
        signature = self._sign(endpoint, body_str, nonce)
        headers = {
            "Api-Key": self.api_key,
            "Api-Sign": signature,
            "Api-Nonce": nonce,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return headers, body_str

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _get(self, path: str) -> dict:
        url = BASE_URL + path
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BithumbError(f"Network error: {exc}") from exc
        if resp.status_code >= 400:
            raise BithumbError(f"Bithumb {resp.status_code}: {resp.text}")
        data = resp.json()
        status = data.get("status")
        if status != "0000":
            raise BithumbError(f"Bithumb error status={status}: {data.get('message', data)}")
        return data

    def _post(self, endpoint: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        headers, body = self._auth_headers(endpoint, params)
        url = BASE_URL + endpoint
        try:
            resp = self._session.post(url, data=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BithumbError(f"Network error: {exc}") from exc
        if resp.status_code >= 400:
            raise BithumbError(f"Bithumb {resp.status_code}: {resp.text}")
        data = resp.json()
        status = data.get("status")
        if status != "0000":
            raise BithumbError(f"Bithumb error status={status}: {data.get('message', data)}")
        return data

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------
    def list_markets(self) -> List[str]:
        """List all KRW markets as canonical KRW-XXX strings."""
        data = self._get("/public/ticker/ALL_KRW")["data"]
        markets = []
        for symbol in data.keys():
            if symbol == "date":
                continue
            markets.append(f"KRW-{symbol.upper()}")
        return markets

    def get_ticker(self, market: str) -> dict:
        order, payment = parse_market(market)
        data = self._get(f"/public/ticker/{order}_{payment}")["data"]
        # Normalize to look a bit like Upbit so callers can do ticker["trade_price"]
        return {
            "trade_price": float(data.get("closing_price", 0)),
            "opening_price": float(data.get("opening_price", 0)),
            "high_price": float(data.get("max_price", 0)),
            "low_price": float(data.get("min_price", 0)),
            "acc_trade_volume_24h": float(data.get("units_traded_24H", 0)),
            "raw": data,
        }

    def fetch_ohlcv(self, market: str, timeframe: str = "1d", count: int = 200) -> List[Candle]:
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. "
                f"Bithumb supports: {sorted(set(_TIMEFRAME_MAP))}"
            )
        interval = _TIMEFRAME_MAP[timeframe]
        order, payment = parse_market(market)
        data = self._get(f"/public/candlestick/{order}_{payment}/{interval}")["data"]
        # Bithumb returns oldest-first; each row is [ms_ts, open, close, high, low, volume]
        rows = data[-count:] if count else data
        return [self._parse_candle(r) for r in rows]

    @staticmethod
    def _parse_candle(row: list) -> Candle:
        from config.settings import KST
        ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=KST)
        return Candle(
            timestamp=ts,
            open=float(row[1]),
            close=float(row[2]),
            high=float(row[3]),
            low=float(row[4]),
            volume=float(row[5]),
        )

    # ------------------------------------------------------------------
    # Private / authenticated endpoints
    # ------------------------------------------------------------------
    def get_balances(self) -> List[Balance]:
        """Bithumb `/info/balance` with currency=ALL returns flat keys like
        `total_btc`, `available_btc`, `in_use_btc` for every currency traded.
        """
        data = self._post("/info/balance", {"currency": "ALL"})["data"]
        # Group by currency suffix
        currencies = set()
        for key in data.keys():
            for prefix in ("total_", "available_", "in_use_"):
                if key.startswith(prefix):
                    currencies.add(key[len(prefix):])
                    break

        balances: List[Balance] = []
        for curr in sorted(currencies):
            total = _safe_float(data.get(f"total_{curr}"))
            available = _safe_float(data.get(f"available_{curr}"))
            in_use = _safe_float(data.get(f"in_use_{curr}"))
            balances.append(
                Balance(
                    currency=curr.upper(),
                    balance=available,
                    locked=in_use,
                    avg_buy_price=0.0,  # Bithumb does not expose avg buy price
                )
            )
        return balances

    def place_order(
        self,
        market: str,
        side: OrderSide,
        order_type: OrderType,
        volume: Optional[float] = None,
        price: Optional[float] = None,
        funds: Optional[float] = None,
    ) -> Order:
        order_currency, payment_currency = parse_market(market)

        if order_type == OrderType.LIMIT:
            if volume is None or price is None:
                raise ValueError("Limit orders require volume and price.")
            endpoint = "/trade/place"
            params = {
                "order_currency": order_currency,
                "payment_currency": payment_currency,
                "units": _fmt_units(volume),
                "price": _fmt_price(price),
                "type": "bid" if side == OrderSide.BUY else "ask",
            }
            data = self._post(endpoint, params)
            return self._parse_order_response(
                data, market, side, order_type, price=price, volume=volume
            )

        if order_type == OrderType.MARKET and side == OrderSide.BUY:
            if funds is None:
                raise ValueError("Market buy requires 'funds' (KRW total).")
            # Bithumb's market_buy takes `units`; convert with a small safety margin
            current_price = self._best_ask(order_currency, payment_currency)
            if current_price <= 0:
                raise BithumbError("Cannot compute units; ticker price unavailable.")
            units = (funds * 0.998) / current_price  # -0.2% for slippage headroom
            endpoint = "/trade/market_buy"
            params = {
                "order_currency": order_currency,
                "payment_currency": payment_currency,
                "units": _fmt_units(units),
            }
            data = self._post(endpoint, params)
            return self._parse_order_response(
                data, market, side, order_type,
                price=current_price, volume=units, funds=funds,
            )

        if order_type == OrderType.MARKET and side == OrderSide.SELL:
            if volume is None:
                raise ValueError("Market sell requires 'volume'.")
            endpoint = "/trade/market_sell"
            params = {
                "order_currency": order_currency,
                "payment_currency": payment_currency,
                "units": _fmt_units(volume),
            }
            data = self._post(endpoint, params)
            return self._parse_order_response(
                data, market, side, order_type, volume=volume
            )

        raise ValueError("Unsupported order parameters.")

    def _best_ask(self, order_currency: str, payment_currency: str) -> float:
        """Best ask price from the ticker closing price (sufficient for market orders)."""
        data = self._get(f"/public/ticker/{order_currency}_{payment_currency}")["data"]
        return float(data.get("closing_price") or 0)

    def cancel_order(self, order_id: str, market: str = "", side: OrderSide = OrderSide.BUY) -> bool:
        """Cancel a limit order by its Bithumb order_id.

        Bithumb's /trade/cancel requires order_currency, payment_currency and type
        in addition to order_id. Pass ``market`` in KRW-BTC or BTC_KRW form and
        ``side`` = BUY/SELL so the adapter knows what to cancel.
        """
        order_currency, payment_currency = parse_market(market or "KRW-BTC")
        self._post(
            "/trade/cancel",
            {
                "type": "bid" if side == OrderSide.BUY else "ask",
                "order_id": order_id,
                "order_currency": order_currency,
                "payment_currency": payment_currency,
            },
        )
        return True

    def get_order(self, order_id: str, market: str = "KRW-BTC") -> Order:
        order_currency, payment_currency = parse_market(market)
        data = self._post(
            "/info/order_detail",
            {
                "order_id": order_id,
                "order_currency": order_currency,
                "payment_currency": payment_currency,
            },
        )["data"]
        side = OrderSide.BUY if data.get("type") == "bid" else OrderSide.SELL
        filled = _safe_float(data.get("order_qty"))
        avg = _safe_float(data.get("order_price"))
        fee = _safe_float(data.get("fee"))
        return Order(
            id=order_id,
            market=f"KRW-{order_currency}" if payment_currency == "KRW" else f"{order_currency}_{payment_currency}",
            side=side,
            type=OrderType.LIMIT,
            price=avg or None,
            volume=filled or None,
            funds=None,
            status=data.get("order_status", "unknown"),
            filled_volume=filled,
            filled_price=avg,
            fee=fee,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_order_response(
        data: dict,
        market: str,
        side: OrderSide,
        order_type: OrderType,
        price: Optional[float] = None,
        volume: Optional[float] = None,
        funds: Optional[float] = None,
    ) -> Order:
        # Place endpoints return {"status": "0000", "order_id": "..."}
        order_id = data.get("order_id") or data.get("data", {}).get("order_id", "unknown")
        return Order(
            id=str(order_id),
            market=market,
            side=side,
            type=order_type,
            price=price,
            volume=volume,
            funds=funds,
            status="done" if order_type == OrderType.MARKET else "wait",
            filled_volume=volume or 0.0,
            filled_price=price or 0.0,
            fee=0.0,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _safe_float(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fmt_units(units: float) -> str:
    # Bithumb accepts up to 8 decimal places for most coins.
    return f"{units:.8f}"


def _fmt_price(price: float) -> str:
    # KRW prices are integers; coin/coin prices can have decimals.
    if float(price).is_integer():
        return str(int(price))
    return f"{price:.8f}"
