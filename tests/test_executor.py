"""Paper broker / executor tests (no network)."""
import pytest

from src.exchanges.base import Exchange, Balance, Candle, Order, OrderSide, OrderType
from src.execution import Executor, PaperBroker


class _StubExchange(Exchange):
    name = "stub"

    def list_markets(self): return ["KRW-BTC"]
    def get_ticker(self, market): return {"trade_price": 50_000_000}
    def fetch_ohlcv(self, market, timeframe="1d", count=200): return []
    def get_balances(self): return []
    def place_order(self, market, side, order_type, volume=None, price=None, funds=None):
        return Order(id="x", market=market, side=side, type=order_type,
                     price=price, volume=volume, funds=funds, status="done",
                     filled_volume=volume or 0, filled_price=price or 0)
    def cancel_order(self, order_id): return True
    def get_order(self, order_id): raise NotImplementedError


def test_paper_buy_and_sell_roundtrip():
    broker = PaperBroker(cash=1_000_000, fee_rate=0.0005)
    order = broker.buy("KRW-BTC", funds_krw=500_000, price=50_000_000)
    assert order is not None
    bought_qty = broker.positions["KRW-BTC"].quantity
    assert bought_qty > 0
    assert broker.cash < 1_000_000

    # sell half
    half = bought_qty / 2
    order = broker.sell("KRW-BTC", quantity=half, price=51_000_000)
    assert order is not None
    assert broker.positions["KRW-BTC"].quantity == pytest.approx(bought_qty - half)


def test_paper_buy_below_min_rejected():
    broker = PaperBroker(cash=10_000)
    order = broker.buy("KRW-BTC", funds_krw=1_000, price=50_000_000)
    assert order is None
    assert "KRW-BTC" not in broker.positions


def test_executor_paper_mode_defaults_paper():
    ex = Executor(exchange=_StubExchange(), mode="paper")
    assert ex.is_paper
    assert ex.get_position("KRW-BTC") is None
    order = ex.market_buy("KRW-BTC", funds_krw=500_000, current_price=50_000_000,
                           stop_loss=48_000_000, take_profit=52_000_000)
    assert order is not None
    pos = ex.get_position("KRW-BTC")
    assert pos.stop_loss == 48_000_000
    assert pos.take_profit == 52_000_000
