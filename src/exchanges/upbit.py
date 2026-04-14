"""Upbit REST client (public + authenticated endpoints).

Docs: https://docs.upbit.com/reference
"""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlencode

import jwt
import requests

from src.exchanges.base import Balance, Candle, Exchange, Order, OrderSide, OrderType
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.upbit.com"

# timeframe -> (endpoint, unit for minute candles)
_TIMEFRAME_MAP = {
    "1m":  ("/v1/candles/minutes/1",   None),
    "3m":  ("/v1/candles/minutes/3",   None),
    "5m":  ("/v1/candles/minutes/5",   None),
    "15m": ("/v1/candles/minutes/15",  None),
    "30m": ("/v1/candles/minutes/30",  None),
    "1h":  ("/v1/candles/minutes/60",  None),
    "4h":  ("/v1/candles/minutes/240", None),
    "1d":  ("/v1/candles/days",        None),
    "1w":  ("/v1/candles/weeks",       None),
}


class UpbitError(RuntimeError):
    pass


class UpbitExchange(Exchange):
    name = "upbit"

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def _auth_headers(self, query: Optional[dict] = None) -> dict:
        if not self.access_key or not self.secret_key:
            raise UpbitError("Upbit API keys not configured.")

        payload = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
        }

        if query:
            query_string = urlencode(query, doseq=True).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        if isinstance(token, bytes):  # older PyJWT returns bytes
            token = token.decode()
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, params: Optional[dict] = None, authed: bool = False):
        url = BASE_URL + path
        headers = {"Accept": "application/json"}
        if authed:
            headers.update(self._auth_headers(params if method != "GET" else params))

        try:
            if method == "GET":
                resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
            elif method == "POST":
                resp = self._session.post(url, json=params, headers=headers, timeout=self.timeout)
            elif method == "DELETE":
                resp = self._session.delete(url, params=params, headers=headers, timeout=self.timeout)
            else:
                raise UpbitError(f"Unsupported method: {method}")
        except requests.RequestException as exc:
            raise UpbitError(f"Network error: {exc}") from exc

        if resp.status_code >= 400:
            raise UpbitError(f"Upbit API {resp.status_code}: {resp.text}")
        return resp.json()

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------
    def list_markets(self) -> List[str]:
        data = self._request("GET", "/v1/market/all", {"isDetails": "false"})
        return [item["market"] for item in data if item["market"].startswith("KRW-")]

    def get_ticker(self, market: str) -> dict:
        data = self._request("GET", "/v1/ticker", {"markets": market})
        if not data:
            raise UpbitError(f"Ticker empty for {market}")
        return data[0]

    def fetch_ohlcv(self, market: str, timeframe: str = "1d", count: int = 200) -> List[Candle]:
        if timeframe not in _TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        endpoint, _ = _TIMEFRAME_MAP[timeframe]

        # Upbit limits 200 per call; chunk if caller asks for more.
        remaining = count
        to_time: Optional[str] = None
        all_rows: List[dict] = []
        while remaining > 0:
            req_count = min(200, remaining)
            params = {"market": market, "count": req_count}
            if to_time:
                params["to"] = to_time
            chunk = self._request("GET", endpoint, params)
            if not chunk:
                break
            all_rows.extend(chunk)
            # next 'to' = oldest candle's time (UTC)
            to_time = chunk[-1]["candle_date_time_utc"] + "Z"
            remaining -= req_count
            if len(chunk) < req_count:
                break
            time.sleep(0.1)  # courtesy rate limit

        # API returns newest first; we want oldest first
        all_rows.reverse()
        return [self._parse_candle(r) for r in all_rows]

    @staticmethod
    def _parse_candle(row: dict) -> Candle:
        ts = datetime.strptime(row["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return Candle(
            timestamp=ts,
            open=float(row["opening_price"]),
            high=float(row["high_price"]),
            low=float(row["low_price"]),
            close=float(row["trade_price"]),
            volume=float(row["candle_acc_trade_volume"]),
        )

    # ------------------------------------------------------------------
    # Private / authenticated endpoints
    # ------------------------------------------------------------------
    def get_balances(self) -> List[Balance]:
        data = self._request("GET", "/v1/accounts", authed=True)
        out = []
        for item in data:
            out.append(
                Balance(
                    currency=item["currency"],
                    balance=float(item.get("balance") or 0),
                    locked=float(item.get("locked") or 0),
                    avg_buy_price=float(item.get("avg_buy_price") or 0),
                )
            )
        return out

    def place_order(
        self,
        market: str,
        side: OrderSide,
        order_type: OrderType,
        volume: Optional[float] = None,
        price: Optional[float] = None,
        funds: Optional[float] = None,
    ) -> Order:
        """Map generic order to Upbit's ord_type semantics.

        - Limit:         volume + price       -> ord_type="limit"
        - Market buy:    funds (KRW amount)   -> ord_type="price"
        - Market sell:   volume (coin qty)    -> ord_type="market"
        """
        params: dict = {
            "market": market,
            "side": "bid" if side == OrderSide.BUY else "ask",
        }

        if order_type == OrderType.LIMIT:
            if volume is None or price is None:
                raise ValueError("Limit orders require volume and price.")
            params["ord_type"] = "limit"
            params["volume"] = f"{volume:.8f}"
            params["price"] = str(int(price)) if price.is_integer() else str(price)
        elif order_type == OrderType.MARKET and side == OrderSide.BUY:
            if funds is None:
                raise ValueError("Market buy requires 'funds' (KRW total).")
            params["ord_type"] = "price"
            params["price"] = str(int(funds))
        elif order_type == OrderType.MARKET and side == OrderSide.SELL:
            if volume is None:
                raise ValueError("Market sell requires 'volume'.")
            params["ord_type"] = "market"
            params["volume"] = f"{volume:.8f}"
        else:
            raise ValueError("Unsupported order parameters.")

        data = self._request("POST", "/v1/orders", params, authed=True)
        return self._parse_order(data)

    def cancel_order(self, order_id: str) -> bool:
        self._request("DELETE", "/v1/order", {"uuid": order_id}, authed=True)
        return True

    def get_order(self, order_id: str) -> Order:
        data = self._request("GET", "/v1/order", {"uuid": order_id}, authed=True)
        return self._parse_order(data)

    @staticmethod
    def _parse_order(data: dict) -> Order:
        side = OrderSide.BUY if data["side"] == "bid" else OrderSide.SELL
        ord_type = data.get("ord_type", "limit")
        otype = OrderType.LIMIT if ord_type == "limit" else OrderType.MARKET

        created = None
        if "created_at" in data:
            try:
                created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            except ValueError:
                created = None

        def _f(key: str) -> float:
            v = data.get(key)
            try:
                return float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        volume = _f("volume") or None
        price = _f("price") or None
        return Order(
            id=data["uuid"],
            market=data["market"],
            side=side,
            type=otype,
            price=price,
            volume=volume,
            funds=None,
            status=data.get("state", "unknown"),
            created_at=created,
            filled_volume=_f("executed_volume"),
            filled_price=_f("avg_price") if "avg_price" in data else 0.0,
            fee=_f("paid_fee"),
        )
