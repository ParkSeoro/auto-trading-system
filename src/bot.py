"""Main trading bot — 24/7 loop that ties all layers together.

Lifecycle per tick (default 60 s):
  1. Fetch fresh OHLCV (daily + hourly for multi-TF).
  2. Check flash-crash kill switch / daily MDD halt.
  3. For each managed market: check stop-loss / take-profit.
  4. Ask strategy for a Signal.
  5. If BUY: risk-size the position, place a market buy.
     If SELL: close the position at market.
  6. Log trade & equity to SQLite.

Paper mode is the default and completely safe; switch to live by setting
TRADING_MODE=live in `.env` or via CLI.
"""
from __future__ import annotations

import signal as signal_lib
import time
from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import settings
from src.data import MarketData
from src.exchanges.base import Exchange
from src.execution import Executor
from src.risk import RiskManager
from src.storage import TradeLog
from src.strategies import Strategy, get_strategy
from src.strategies.base import SignalType
from src.utils.logger import get_logger
from src.utils.notifier import send_alert

log = get_logger("bot")


@dataclass
class TradingBot:
    exchange: Exchange
    markets: List[str]
    strategy: Strategy
    mode: str = "paper"
    timeframe: str = "1d"
    loop_interval: int = field(default_factory=lambda: settings.loop_interval)
    starting_capital: float = field(default_factory=lambda: settings.paper_capital)

    executor: Executor = field(init=False)
    market_data: MarketData = field(init=False)
    risk: RiskManager = field(init=False)
    trade_log: TradeLog = field(init=False)
    _running: bool = field(default=False, init=False)

    def __post_init__(self):
        self.executor = Executor(exchange=self.exchange, mode=self.mode)
        self.market_data = MarketData(exchange=self.exchange, ttl_sec=15)
        self.risk = RiskManager(capital=self.starting_capital)
        self.trade_log = TradeLog(settings.db_path)

    # ------------------------------------------------------------------
    # Bot loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._running = True
        self._install_signal_handlers()
        log.info(
            "🚀 Bot started | mode=%s | markets=%s | strategy=%s | tf=%s | interval=%ds",
            self.mode, self.markets, self.strategy.name, self.timeframe, self.loop_interval,
        )
        send_alert(f"Crypto bot started ({self.mode}) on {self.markets} / {self.strategy.name}")
        try:
            while self._running:
                try:
                    self.tick()
                except Exception as exc:  # pragma: no cover - runtime only
                    log.exception("tick failed: %s", exc)
                time.sleep(self.loop_interval)
        finally:
            log.info("Bot stopped.")
            send_alert("Crypto bot stopped.")

    def tick(self) -> None:
        if self.mode == "live":
            self.executor.sync_live_positions()

        # Compute current equity for risk tracking
        prices = {}
        for market in self.markets:
            p = self.market_data.get_current_price(market)
            if p is not None:
                prices[market] = p

        equity = self._current_equity(prices)
        self.risk.update_equity(equity)
        self.trade_log.log_equity(
            equity=equity,
            cash=self.executor.paper.cash if self.executor.is_paper else equity,
            mode=self.mode,
        )

        if self.risk.is_halted():
            log.info("Trading halted. Equity=%.0f KRW.", equity)
            return

        for market in self.markets:
            try:
                self._process_market(market, prices.get(market))
            except Exception as exc:
                log.exception("market %s failed: %s", market, exc)

    # ------------------------------------------------------------------
    # Per-market processing
    # ------------------------------------------------------------------
    def _process_market(self, market: str, current_price: Optional[float]) -> None:
        df = self.market_data.get_ohlcv(market, timeframe=self.timeframe, count=200)
        if df.empty:
            log.warning("No OHLCV for %s", market)
            return

        if current_price is None:
            current_price = float(df["close"].iloc[-1])

        position = self.executor.get_position(market)
        pos_dict = position.to_dict() if position else None

        # Stop-loss / take-profit (pre-strategy, hard rules)
        if position and position.quantity > 0:
            if RiskManager.should_stop_out(current_price, pos_dict):
                self._execute_sell(market, position.quantity, current_price, reason="stop_loss")
                return
            if RiskManager.should_take_profit(current_price, pos_dict):
                self._execute_sell(market, position.quantity, current_price, reason="take_profit")
                return

        # Flash-crash kill switch on fine-grained bars
        fine_df = self.market_data.get_ohlcv(market, timeframe="5m", count=30)
        if not fine_df.empty and self.risk.check_flash_crash(fine_df):
            if position and position.quantity > 0:
                self._execute_sell(market, position.quantity, current_price, reason="flash_crash")
            return

        signal = self.strategy.generate(df, position=pos_dict)
        log.debug("signal %s on %s: %s %s", self.strategy.name, market, signal.type.value, signal.reason)

        if signal.type == SignalType.BUY and (not position or position.quantity == 0):
            available_cash = self._available_cash()
            decision = self.risk.evaluate_entry(
                df, confidence=signal.confidence, available_krw=available_cash
            )
            if not decision.approved:
                log.info("BUY rejected on %s: %s", market, decision.reason)
                return
            self._execute_buy(
                market=market,
                funds_krw=decision.position_size_krw,
                price=current_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                reason=signal.reason,
            )

        elif signal.type == SignalType.SELL and position and position.quantity > 0:
            self._execute_sell(market, position.quantity, current_price, reason=signal.reason)

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_buy(self, market, funds_krw, price, stop_loss, take_profit, reason):
        order = self.executor.market_buy(
            market=market,
            funds_krw=funds_krw,
            current_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        if order:
            self.trade_log.log_trade(
                market=market, side="buy",
                price=order.filled_price or price,
                quantity=order.filled_volume or (funds_krw / price),
                funds=order.funds or funds_krw,
                fee=order.fee, mode=self.mode,
                strategy=self.strategy.name, reason=reason,
                order_id=order.id,
            )
            send_alert(
                f"BUY {market} @ {price:,.0f} KRW | funds={funds_krw:,.0f} | SL={stop_loss} | TP={take_profit}"
            )

    def _execute_sell(self, market, quantity, price, reason):
        order = self.executor.market_sell(market=market, quantity=quantity, current_price=price)
        if order:
            self.trade_log.log_trade(
                market=market, side="sell",
                price=order.filled_price or price,
                quantity=order.filled_volume or quantity,
                funds=order.funds or quantity * price,
                fee=order.fee, mode=self.mode,
                strategy=self.strategy.name, reason=reason,
                order_id=order.id,
            )
            send_alert(f"SELL {market} qty={quantity:.8f} @ {price:,.0f} KRW | {reason}")

    # ------------------------------------------------------------------
    # Equity / cash helpers
    # ------------------------------------------------------------------
    def _current_equity(self, prices: dict) -> float:
        if self.executor.is_paper:
            return self.executor.paper.equity(prices)
        # Live: sum KRW balance + positions valued at last price
        balances = self.exchange.get_balances()
        total = 0.0
        for b in balances:
            if b.currency == "KRW":
                total += b.total
            else:
                market = f"KRW-{b.currency}"
                px = prices.get(market)
                if px is not None:
                    total += b.total * px
                else:
                    total += b.total * (b.avg_buy_price or 0)
        return total

    def _available_cash(self) -> float:
        if self.executor.is_paper:
            return self.executor.paper.cash
        for b in self.exchange.get_balances():
            if b.currency == "KRW":
                return b.balance
        return 0.0

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def stop(self) -> None:
        log.info("Stop signal received.")
        self._running = False

    def _install_signal_handlers(self) -> None:
        for sig in (signal_lib.SIGINT, signal_lib.SIGTERM):
            try:
                signal_lib.signal(sig, lambda *_: self.stop())
            except (ValueError, OSError):  # not main thread
                pass


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
def build_bot(
    mode: str,
    markets: List[str],
    strategy_name: str,
    timeframe: str = "1d",
) -> TradingBot:
    from src.exchanges import UpbitExchange
    exchange = UpbitExchange(
        access_key=settings.upbit_access_key,
        secret_key=settings.upbit_secret_key,
    )
    strategy = get_strategy(strategy_name)
    return TradingBot(
        exchange=exchange,
        markets=markets,
        strategy=strategy,
        mode=mode,
        timeframe=timeframe,
    )
