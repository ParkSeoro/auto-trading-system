"""Order execution layer with live/paper modes.

Live mode: places real Upbit orders.
Paper mode: simulates fills against the last traded price and tracks virtual
positions/equity in memory (+ SQLite log via `src.storage.db`).

State is persisted to ``data/paper_state.json`` so cash, positions, and
stop-loss/take-profit survive bot restarts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import KST, settings
from src.exchanges.base import Exchange, Order, OrderSide, OrderType
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class Position:
    market: str
    quantity: float = 0.0
    avg_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[datetime] = None

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.quantity

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
        }


# ----------------------------------------------------------------------
# Paper broker — an in-process fake exchange for dry runs & backtests
# ----------------------------------------------------------------------
@dataclass
class PaperBroker:
    cash: float = field(default_factory=lambda: settings.paper_capital)
    fee_rate: float = field(default_factory=lambda: settings.active_fee_rate)
    min_order_krw: float = field(default_factory=lambda: settings.active_min_order_krw)
    positions: Dict[str, Position] = field(default_factory=dict)
    trade_log: List[dict] = field(default_factory=list)
    persist: bool = True

    def __post_init__(self):
        self._state_path: Path = settings.data_dir / "paper_state.json"
        if self.persist:
            self._load_state()

    def equity(self, prices: Dict[str, float]) -> float:
        total = self.cash
        for mkt, pos in self.positions.items():
            total += pos.quantity * prices.get(mkt, pos.avg_price)
        return total

    # -- persistence --
    def save_state(self) -> None:
        if not self.persist:
            return
        doc = {
            "cash": self.cash,
            "positions": {
                mkt: {
                    "quantity": pos.quantity,
                    "avg_price": pos.avg_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
                }
                for mkt, pos in self.positions.items()
                if pos.quantity > 1e-12
            },
            "saved_at": datetime.now(KST).isoformat(),
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("[paper] state save failed: %s", exc)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            doc = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.cash = doc.get("cash", self.cash)
            for mkt, pdata in doc.get("positions", {}).items():
                opened = None
                if pdata.get("opened_at"):
                    try:
                        opened = datetime.fromisoformat(pdata["opened_at"])
                    except (ValueError, TypeError):
                        pass
                self.positions[mkt] = Position(
                    market=mkt,
                    quantity=pdata.get("quantity", 0.0),
                    avg_price=pdata.get("avg_price", 0.0),
                    stop_loss=pdata.get("stop_loss"),
                    take_profit=pdata.get("take_profit"),
                    opened_at=opened,
                )
            log.info(
                "[paper] Restored state: cash=%.0f, positions=%d (%s)",
                self.cash, len(self.positions), list(self.positions.keys()),
            )
        except Exception as exc:
            log.warning("[paper] state load failed: %s", exc)

    def buy(self, market: str, funds_krw: float, price: float,
            stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Optional[Order]:
        if funds_krw > self.cash:
            funds_krw = self.cash
        if funds_krw < self.min_order_krw:
            log.warning("[paper] buy rejected, funds %.0f < min %.0f", funds_krw, self.min_order_krw)
            return None

        fee = funds_krw * self.fee_rate
        net = funds_krw - fee
        qty = net / price if price > 0 else 0.0

        pos = self.positions.get(market) or Position(market=market, opened_at=datetime.now(KST))
        new_qty = pos.quantity + qty
        if new_qty > 0:
            pos.avg_price = (pos.avg_price * pos.quantity + qty * price) / new_qty
        pos.quantity = new_qty
        pos.stop_loss = stop_loss
        pos.take_profit = take_profit
        self.positions[market] = pos

        self.cash -= funds_krw
        trade = {
            "ts": datetime.now(KST).isoformat(),
            "market": market,
            "side": "buy",
            "price": price,
            "quantity": qty,
            "funds": funds_krw,
            "fee": fee,
        }
        self.trade_log.append(trade)
        self.save_state()
        log.info("[paper] BUY %s qty=%.8f @ %.2f (funds=%.0f, fee=%.0f)", market, qty, price, funds_krw, fee)
        return Order(
            id=f"paper-{len(self.trade_log)}",
            market=market,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            price=price,
            volume=qty,
            funds=funds_krw,
            status="done",
            filled_volume=qty,
            filled_price=price,
            fee=fee,
        )

    def sell(self, market: str, quantity: float, price: float) -> Optional[Order]:
        pos = self.positions.get(market)
        if not pos or pos.quantity <= 0:
            log.warning("[paper] sell rejected, no position on %s", market)
            return None
        qty = min(quantity, pos.quantity)
        gross = qty * price
        fee = gross * self.fee_rate
        net = gross - fee

        pos.quantity -= qty
        if pos.quantity <= 1e-12:
            self.positions.pop(market, None)

        self.cash += net
        trade = {
            "ts": datetime.now(KST).isoformat(),
            "market": market,
            "side": "sell",
            "price": price,
            "quantity": qty,
            "funds": gross,
            "fee": fee,
        }
        self.trade_log.append(trade)
        self.save_state()
        log.info("[paper] SELL %s qty=%.8f @ %.2f (gross=%.0f, fee=%.0f)", market, qty, price, gross, fee)
        return Order(
            id=f"paper-{len(self.trade_log)}",
            market=market,
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            price=price,
            volume=qty,
            funds=gross,
            status="done",
            filled_volume=qty,
            filled_price=price,
            fee=fee,
        )


# ----------------------------------------------------------------------
# Executor — dispatches to live exchange or paper broker
# ----------------------------------------------------------------------
@dataclass
class Executor:
    exchange: Exchange
    mode: str = "paper"
    paper: PaperBroker = field(default_factory=PaperBroker)
    _live_positions: Dict[str, Position] = field(default_factory=dict)

    @property
    def is_paper(self) -> bool:
        return self.mode != "live"

    # -- position accessors --
    def get_position(self, market: str) -> Optional[Position]:
        if self.is_paper:
            return self.paper.positions.get(market)
        return self._live_positions.get(market)

    def set_stop_take(self, market: str, stop_loss: Optional[float], take_profit: Optional[float]) -> None:
        pos = self.get_position(market)
        if pos:
            pos.stop_loss = stop_loss
            pos.take_profit = take_profit

    # -- order routing --
    def market_buy(
        self,
        market: str,
        funds_krw: float,
        current_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Order]:
        if self.is_paper:
            return self.paper.buy(market, funds_krw, current_price, stop_loss, take_profit)

        # LIVE
        order = self.exchange.place_order(
            market=market, side=OrderSide.BUY, order_type=OrderType.MARKET, funds=funds_krw
        )
        # record position shell (live balances will be fetched by bot.sync_balances)
        pos = self._live_positions.setdefault(
            market, Position(market=market, opened_at=datetime.now(KST))
        )
        pos.stop_loss = stop_loss
        pos.take_profit = take_profit
        return order

    def market_sell(self, market: str, quantity: float, current_price: float) -> Optional[Order]:
        if self.is_paper:
            return self.paper.sell(market, quantity, current_price)
        order = self.exchange.place_order(
            market=market, side=OrderSide.SELL, order_type=OrderType.MARKET, volume=quantity
        )
        pos = self._live_positions.get(market)
        if pos:
            pos.quantity = max(0.0, pos.quantity - quantity)
            if pos.quantity <= 1e-12:
                self._live_positions.pop(market, None)
        return order

    def sync_live_positions(self) -> None:
        """Refresh live position snapshots from exchange balances."""
        if self.is_paper:
            return
        balances = {b.currency: b for b in self.exchange.get_balances()}
        for market in list(self._live_positions.keys()):
            currency = market.split("-")[1] if "-" in market else market
            bal = balances.get(currency)
            pos = self._live_positions[market]
            if bal:
                pos.quantity = bal.total
                if bal.avg_buy_price:
                    pos.avg_price = bal.avg_buy_price
            else:
                self._live_positions.pop(market, None)
