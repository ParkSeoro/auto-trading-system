"""Main trading bot — 24/7 loop that ties all layers together.

Lifecycle per tick (default 60 s):
  1. Fetch fresh OHLCV (daily + hourly for multi-TF).
  2. Check flash-crash kill switch / daily MDD halt.
  3. For each managed market: check stop-loss / take-profit.
  4. Update trailing stops on open positions.
  5. Consult TradeAnalyzer for confidence/size adjustments.
  6. Ask strategy for a Signal.
  7. If BUY: risk-size with feedback adjustments, place a market buy.
     If SELL: close the position at market.
  8. Log trade & equity to SQLite.
  9. Periodically re-screen markets and re-analyze outcomes.

Paper mode is the default and completely safe; switch to live by setting
TRADING_MODE=live in `.env` or via CLI.
"""
from __future__ import annotations

import signal as signal_lib
import time
from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import settings
from src.ai.trade_analyzer import TradeAnalyzer
from src.data import MarketData
from src.exchanges.base import Exchange
from src.execution import Executor
from src.risk import RiskManager
from src.screener import MarketScreener
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
    analyzer: TradeAnalyzer = field(init=False)
    screener: MarketScreener = field(init=False)
    _running: bool = field(default=False, init=False)
    _tick_count: int = field(default=0, init=False)
    _analyze_every: int = 10       # run analyzer every N ticks
    _screen_every: int = 60        # re-screen markets every N ticks

    def __post_init__(self):
        self.executor = Executor(exchange=self.exchange, mode=self.mode)
        self.market_data = MarketData(exchange=self.exchange, ttl_sec=15)
        self.risk = RiskManager(capital=self.starting_capital)
        self.trade_log = TradeLog(settings.db_path)
        self.analyzer = TradeAnalyzer()
        self.screener = MarketScreener()

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
        self._tick_count += 1

        if self.mode == "live":
            self.executor.sync_live_positions()

        # Periodically update trade analyzer (learn from outcomes)
        if self._tick_count % self._analyze_every == 0:
            try:
                self.analyzer.update()
                log.debug("Trade analyzer updated: %d strategies tracked",
                          len(self.analyzer.stats))
            except Exception as exc:
                log.warning("analyzer update failed: %s", exc)

        # Compute current equity for risk tracking
        prices = {}
        for market in self.markets:
            p = self.market_data.get_current_price(market)
            if p is not None:
                prices[market] = p

        equity = self._current_equity(prices)
        self.risk.update_equity(equity)

        # Track open position count for max_open_positions limit
        open_count = sum(
            1 for m in self.markets
            if self.executor.get_position(m) and self.executor.get_position(m).quantity > 0
        )
        self.risk.set_open_positions(open_count)
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
            # Update trailing stop-loss (ratchets up, never down)
            new_sl = self.risk.update_trailing_stop(
                market, current_price, pos_dict, df=df,
            )
            if new_sl is not None:
                self.executor.set_stop_take(market, stop_loss=new_sl, take_profit=pos_dict.get("take_profit"))
                pos_dict["stop_loss"] = new_sl

            # Dynamic SL/TP tightening based on current volatility
            adj = self.risk.dynamic_adjust_stops(market, pos_dict, df)
            if adj is not None:
                self.executor.set_stop_take(
                    market,
                    stop_loss=adj["stop_loss"],
                    take_profit=adj["take_profit"],
                )
                pos_dict["stop_loss"] = adj["stop_loss"]
                pos_dict["take_profit"] = adj["take_profit"]

            if RiskManager.should_stop_out(current_price, pos_dict):
                self._execute_sell(market, position.quantity, current_price, reason="stop_loss")
                self.risk.clear_position_peak(market)
                return
            if RiskManager.should_take_profit(current_price, pos_dict):
                self._execute_sell(market, position.quantity, current_price, reason="take_profit")
                self.risk.clear_position_peak(market)
                return

        # Flash-crash kill switch on fine-grained bars
        fine_df = self.market_data.get_ohlcv(market, timeframe="5m", count=30)
        if not fine_df.empty and self.risk.check_flash_crash(fine_df):
            if position and position.quantity > 0:
                self._execute_sell(market, position.quantity, current_price, reason="flash_crash")
                self.risk.clear_position_peak(market)
            return

        signal = self.strategy.generate(df, position=pos_dict)
        log.debug("signal %s on %s: %s %s", self.strategy.name, market, signal.type.value, signal.reason)

        if signal.type == SignalType.BUY and (not position or position.quantity == 0):
            # Consult trade analyzer: should we skip this trade?
            should_skip, skip_reason = self.analyzer.should_skip_trade(
                market, self.strategy.name,
            )
            if should_skip:
                log.info("BUY skipped on %s: %s", market, skip_reason)
                return

            # Get feedback adjustments from past trade analysis
            conf_adj = self.analyzer.get_confidence_adjustment(
                market, self.strategy.name,
            )
            size_adj = self.analyzer.get_size_adjustment(
                market, self.strategy.name,
            )

            available_cash = self._available_cash()
            decision = self.risk.evaluate_entry_with_feedback(
                df,
                confidence=signal.confidence,
                available_krw=available_cash,
                confidence_adj=conf_adj,
                size_adj=size_adj,
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
            self.risk.clear_position_peak(market)

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
    exchange_name: Optional[str] = None,
) -> TradingBot:
    from src.exchanges import build_exchange
    exchange = build_exchange(exchange_name)
    log.info("Using exchange: %s", exchange.name)
    strategy = get_strategy(strategy_name)
    return TradingBot(
        exchange=exchange,
        markets=markets,
        strategy=strategy,
        mode=mode,
        timeframe=timeframe,
    )
