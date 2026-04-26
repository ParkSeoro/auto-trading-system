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
from datetime import datetime, timedelta
from typing import List, Optional

from config.settings import KST, settings
from src.ai.trade_analyzer import TradeAnalyzer
from src.ai.market_classifier import MarketClassifier, MarketAnalysis
from src.ai.claude_advisor import ClaudeAdvisor
from src.ai.auto_tuner import AutoTuner
from src.ai.btc_filter import BTCFilter
from src.data import MarketData
from src.exchanges.base import Exchange
from src.execution import Executor
from src.risk import RiskManager
from src.risk.defense_manager import DefenseManager, TradingMode
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
    auto_discover: bool = field(default=False, init=True)
    max_auto_markets: int = 10

    executor: Executor = field(init=False)
    market_data: MarketData = field(init=False)
    risk: RiskManager = field(init=False)
    trade_log: TradeLog = field(init=False)
    analyzer: TradeAnalyzer = field(init=False)
    screener: MarketScreener = field(init=False)
    defense: DefenseManager = field(init=False)
    classifier: MarketClassifier = field(init=False)
    claude: ClaudeAdvisor = field(init=False)
    tuner: AutoTuner = field(init=False)
    btc_filter: BTCFilter = field(init=False)
    _running: bool = field(default=False, init=False)
    _tick_count: int = field(default=0, init=False)
    _analyze_every: int = 10       # run analyzer every N ticks
    _screen_every: int = 30        # re-screen markets every N ticks
    _save_every: int = 5           # persist paper state every N ticks
    _claude_every: int = 60        # ask Claude for analysis every N ticks
    _active_markets: List[str] = field(default_factory=list, init=False)
    _last_scores: list = field(default_factory=list, init=False)
    _last_market_states: dict = field(default_factory=dict, init=False)
    _min_hold_seconds: int = 300  # 5 minutes minimum hold time
    _last_trade_time: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.executor = Executor(exchange=self.exchange, mode=self.mode)
        self.market_data = MarketData(exchange=self.exchange, ttl_sec=15)
        if self.executor.is_paper:
            loaded_equity = self.executor.paper.cash + sum(
                p.quantity * p.avg_price for p in self.executor.paper.positions.values()
            )
            if loaded_equity > 0 and loaded_equity != self.starting_capital:
                log.info(
                    "Using loaded equity %.0f (not default %.0f) for risk sizing",
                    loaded_equity, self.starting_capital,
                )
                self.starting_capital = loaded_equity
        self.risk = RiskManager(capital=self.starting_capital)
        self.trade_log = TradeLog(settings.db_path)
        self.analyzer = TradeAnalyzer()
        self.screener = MarketScreener()
        self.defense = DefenseManager()
        self.classifier = MarketClassifier()
        self.claude = ClaudeAdvisor()
        self.tuner = AutoTuner()
        self.btc_filter = BTCFilter(market_data=self.market_data)
        if not self.markets or self.markets == ["AUTO"]:
            self.auto_discover = True
            self.markets = []
        self._active_markets = list(self.markets)
        self._register_strategy_params()

    def _register_strategy_params(self) -> None:
        """Register current strategy parameters with the AutoTuner."""
        params = {}
        strat = self.strategy
        # Common strategy params
        for attr in ("rsi_low", "rsi_high", "volume_min_mult", "volume_max_mult",
                      "sl_atr_mult", "tp_atr_mult", "k", "volume_factor"):
            if hasattr(strat, attr):
                params[attr] = getattr(strat, attr)
        # crypto_regime specific params
        for attr in ("adx_trend_threshold", "adx_range_threshold",
                      "volume_expansion_mult", "min_rr_ratio",
                      "sl_buffer_atr", "rsi_oversold", "rsi_overbought",
                      "ema_fast", "ema_slow", "swing_lookback"):
            if hasattr(strat, attr):
                params[attr] = getattr(strat, attr)
        if hasattr(strat, "members"):
            for member in strat.members:
                for attr in ("rsi_low", "rsi_high", "k", "volume_factor"):
                    if hasattr(member, attr):
                        params[f"{member.name}.{attr}"] = getattr(member, attr)
        if params:
            self.tuner.register_strategy(self.strategy.name, params)
            log.info("AutoTuner registered: %s params=%s", self.strategy.name, params)
            self._persist_best_params(params)

    def _persist_best_params(self, params: dict) -> None:
        """Write current strategy params to best_params.json for dashboard display."""
        import json
        bp_path = settings.data_dir / "best_params.json"
        try:
            existing = {}
            if bp_path.exists():
                existing = json.loads(bp_path.read_text(encoding="utf-8"))
            existing[self.strategy.name] = {
                "strategy": self.strategy.name,
                "params": params,
            }
            bp_path.parent.mkdir(parents=True, exist_ok=True)
            bp_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.debug("best_params write failed: %s", exc)

    # ------------------------------------------------------------------
    # Bot loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._running = True
        self._install_signal_handlers()

        if self.auto_discover:
            log.info("🔍 Auto-discovery mode: scanning all markets on %s", self.exchange.name)
            self._run_auto_discovery()

        log.info(
            "🚀 Bot started | mode=%s | markets=%s | auto=%s | strategy=%s | tf=%s | interval=%ds",
            self.mode, self._active_markets, self.auto_discover, self.strategy.name,
            self.timeframe, self.loop_interval,
        )
        send_alert(
            f"Crypto bot started ({self.mode}) | auto={self.auto_discover} | "
            f"{len(self._active_markets)} markets / {self.strategy.name}"
        )
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

        # Periodically re-scan markets in auto-discovery mode
        if self.auto_discover and self._tick_count % self._screen_every == 0:
            try:
                self._run_auto_discovery()
            except Exception as exc:
                log.warning("auto-discovery re-scan failed: %s", exc)

        # Periodic paper state save (crash protection)
        if self.executor.is_paper and self._tick_count % self._save_every == 0:
            try:
                self.executor.paper.save_state()
            except Exception:
                pass

        # Periodic Claude AI market analysis
        if self._tick_count % self._claude_every == 0 and self.claude.available():
            self._run_claude_analysis()

        # BTC regime update — guards all alt-coin trades this tick
        try:
            btc_state = self.btc_filter.update(exchange=self.exchange)
            if btc_state.force_exit:
                log.warning(
                    "⚠️ BTC crash detected (%s). Force-exiting alt positions.",
                    btc_state.reason,
                )
                self._force_exit_alts(reason=f"btc_crash: {btc_state.reason}")
        except Exception as exc:
            log.debug("BTC filter update failed: %s", exc)

        # Build full market set: active markets + all held positions
        active = list(self._active_markets)
        if self.executor.is_paper:
            held_positions = self.executor.paper.positions
        else:
            held_positions = self.executor._live_positions
        for mkt, pos in held_positions.items():
            if pos.quantity > 1e-12 and mkt not in active:
                active.append(mkt)

        prices = {}
        for market in active:
            p = self.market_data.get_current_price(market)
            if p is not None:
                prices[market] = p

        equity = self._current_equity(prices)
        self.risk.update_equity(equity)
        self.risk.capital = equity
        defense_mode = self.defense.update_equity(equity)

        # Track open position count for max_open_positions limit
        open_count = sum(
            1 for m in active
            if self.executor.get_position(m) and self.executor.get_position(m).quantity > 0
        )
        self.risk.set_open_positions(open_count)
        self.trade_log.log_equity(
            equity=equity,
            cash=self.executor.paper.cash if self.executor.is_paper else equity,
            mode=self.mode,
        )

        if self.risk.is_halted():
            log.info("Trading halted (RiskManager). Equity=%.0f KRW.", equity)
            return

        # Defense halt check
        can_enter, halt_reason = self.defense.can_enter()
        if not can_enter:
            log.info("Trading blocked (%s): %s", defense_mode, halt_reason)
            return

        for market in active:
            try:
                self._process_market(market, prices.get(market))
            except Exception as exc:
                log.exception("market %s failed: %s", market, exc)

    # ------------------------------------------------------------------
    # Claude AI analysis
    # ------------------------------------------------------------------
    def _run_claude_analysis(self) -> None:
        """Ask Claude to analyze top active markets and cache advice."""
        markets_to_analyze = self._active_markets[:3]
        for market in markets_to_analyze:
            try:
                market_state = self._last_market_states.get(market, {})
                recent_trades = []
                try:
                    import sqlite3
                    with sqlite3.connect(str(settings.db_path)) as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            "SELECT ts, market, side, price, quantity, fee, strategy, reason "
                            "FROM trades WHERE market=? ORDER BY id DESC LIMIT 5",
                            (market,),
                        ).fetchall()
                        recent_trades = [dict(r) for r in rows]
                except Exception:
                    pass

                advice = self.claude.analyze_market(
                    market=market,
                    market_state=market_state,
                    recent_trades=recent_trades,
                    defense_status=self.defense.status_report(),
                )
                log.info(
                    "Claude advice for %s: %s (confidence=%.2f) — %s",
                    market, advice.get("action"), advice.get("confidence", 0),
                    advice.get("reasoning", ""),
                )
            except Exception as exc:
                log.debug("Claude analysis failed for %s: %s", market, exc)

    # ------------------------------------------------------------------
    # Auto-tuning (after trades)
    # ------------------------------------------------------------------
    def _check_auto_tuning(self) -> None:
        """Check if strategy parameters need tuning based on recent performance."""
        try:
            all_stats = self.analyzer.get_all_stats()
            total_trades = 0
            total_wins = 0
            total_losses = 0
            total_pnl = 0.0
            all_recent_pnl = []

            for key, stat in all_stats.items():
                if "|" in key:
                    _, strat_name = key.split("|", 1)
                    if strat_name == self.strategy.name:
                        total_trades += stat.get("total_trades", 0)
                        total_wins += stat.get("wins", 0)
                        total_losses += stat.get("losses", 0)
                        total_pnl += stat.get("total_pnl", 0.0)
                        all_recent_pnl.extend(stat.get("recent_pnl", []))

            if total_trades < 5:
                return

            win_rate = total_wins / total_trades if total_trades > 0 else 0.0
            expectancy = total_pnl / total_trades if total_trades > 0 else 0.0
            gross_wins = sum(p for p in all_recent_pnl if p > 0)
            gross_losses = abs(sum(p for p in all_recent_pnl if p < 0))
            if gross_losses > 0:
                profit_factor = gross_wins / gross_losses
            elif gross_wins > 0:
                profit_factor = float("inf")
            else:
                profit_factor = 0.0
            strategy_stats = {
                "total_trades": total_trades,
                "wins": total_wins,
                "losses": total_losses,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "total_pnl": total_pnl,
                "expectancy": expectancy,
                "recent_pnl": all_recent_pnl[-20:],
            }

            if self.tuner.should_tune(self.strategy.name, strategy_stats):
                new_params = self.tuner.apply_tuning(
                    self.strategy.name,
                    strategy_stats,
                    claude_advisor=self.claude,
                )
                self._apply_params_to_strategy(new_params)
                self._register_strategy_params()
        except Exception as exc:
            log.debug("auto-tuning check failed: %s", exc)

    def _apply_params_to_strategy(self, params: dict) -> None:
        """Apply tuned parameters to the running strategy instance."""
        strat = self.strategy
        applied = []
        for key, val in params.items():
            if "." in key:
                member_name, attr = key.split(".", 1)
                if hasattr(strat, "members"):
                    for member in strat.members:
                        if member.name == member_name and hasattr(member, attr):
                            setattr(member, attr, val)
                            applied.append(f"{key}={val}")
            elif hasattr(strat, key):
                setattr(strat, key, val)
                applied.append(f"{key}={val}")
        if applied:
            log.info("Auto-tuning applied to %s: %s", strat.name, ", ".join(applied))
            send_alert(f"Auto-tuning: {', '.join(applied)}")

    # ------------------------------------------------------------------
    # Auto-discovery
    # ------------------------------------------------------------------
    def _run_auto_discovery(self) -> None:
        """Scan all exchange markets and select the best candidates."""
        # Keep markets with open positions so we don't abandon them
        held_markets = set()
        # Check ALL executor positions, not just _active_markets
        if self.executor.is_paper:
            all_positions = self.executor.paper.positions
        else:
            all_positions = self.executor._live_positions
        for m, pos in all_positions.items():
            if pos.quantity > 1e-12:
                held_markets.add(m)
        # Also check _active_markets for positions
        for m in self._active_markets:
            pos = self.executor.get_position(m)
            if pos and pos.quantity > 0:
                held_markets.add(m)

        selected, scores = self.screener.auto_discover(
            exchange=self.exchange,
            max_markets=self.max_auto_markets,
            timeframe=self.timeframe,
            count=100,
        )
        self._last_scores = scores

        # Merge: always keep held positions + add new top picks
        new_active = list(held_markets)
        for m in selected:
            if m not in new_active:
                new_active.append(m)

        # Cap total active markets
        new_active = new_active[: self.max_auto_markets + len(held_markets)]

        if set(new_active) != set(self._active_markets):
            added = set(new_active) - set(self._active_markets)
            removed = set(self._active_markets) - set(new_active) - held_markets
            log.info(
                "🔄 Market rotation: +%s -%s | active=%d",
                list(added) if added else "[]",
                list(removed) if removed else "[]",
                len(new_active),
            )
            if added:
                send_alert(f"Market rotation: added {list(added)}, total {len(new_active)}")

        self._active_markets = new_active
        self.markets = list(new_active)

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

        # Market state classification — blocks trades in bad regimes
        mkt_analysis = self.classifier.classify(df)
        self._last_market_states[market] = mkt_analysis.to_dict()

        signal = self.strategy.generate(df, position=pos_dict)
        log.debug(
            "signal %s on %s: %s %s | market=%s trade_ok=%s",
            self.strategy.name, market, signal.type.value, signal.reason,
            mkt_analysis.state.value, mkt_analysis.trade_allowed,
        )

        if signal.type == SignalType.BUY and (not position or position.quantity == 0):
            # Cooldown: prevent re-entry too soon after last trade on this market
            last_trade = self._last_trade_time.get(market)
            if last_trade:
                cooldown_secs = (datetime.now(KST) - last_trade).total_seconds()
                if cooldown_secs < self._min_hold_seconds:
                    log.debug("BUY skipped on %s — cooldown %.0fs", market, cooldown_secs)
                    return

            # Block entry in prohibited market regimes
            if not mkt_analysis.trade_allowed:
                log.info("BUY blocked on %s — %s", market, mkt_analysis.block_reason)
                return

            # Consult defense manager for halt/cooldown
            can_enter, block_msg = self.defense.can_enter()
            if not can_enter:
                log.info("BUY blocked (defense): %s", block_msg)
                return

            # Consult trade analyzer: should we skip this trade?
            should_skip, skip_reason = self.analyzer.should_skip_trade(
                market, self.strategy.name,
            )
            if should_skip:
                log.info("BUY skipped on %s: %s", market, skip_reason)
                return

            # Consult Claude AI advice (if available and cached)
            claude_advice = self.claude.last_advice().get("market_analysis", {})
            if claude_advice.get("action") == "AVOID" and claude_advice.get("confidence", 0) >= 0.7:
                log.info("BUY blocked by Claude AI: %s", claude_advice.get("reasoning", ""))
                return

            # BTC regime filter — most important for alt coins
            btc_ok, btc_size_mult, btc_reason = self.btc_filter.check_alt_entry(market)
            if not btc_ok:
                log.info("BUY blocked on %s by BTC filter: %s", market, btc_reason)
                return

            # Get feedback adjustments from past trade analysis
            conf_adj = self.analyzer.get_confidence_adjustment(
                market, self.strategy.name,
            )
            size_adj = self.analyzer.get_size_adjustment(
                market, self.strategy.name,
            )
            # Apply defense size multiplier + BTC regime scaling
            defense_mult = self.defense.size_multiplier()
            size_adj = size_adj * defense_mult * btc_size_mult

            available_cash = self._available_cash()
            decision = self.risk.evaluate_entry_with_feedback(
                df,
                confidence=signal.confidence,
                available_krw=available_cash,
                confidence_adj=conf_adj,
                size_adj=size_adj,
                signal_meta=signal.meta,
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
                reason=f"{signal.reason} | {btc_reason}" if btc_reason else signal.reason,
            )

        elif signal.type == SignalType.SELL and position and position.quantity > 0:
            # Enforce minimum hold time for strategy-driven exits
            if position.opened_at:
                held_secs = (datetime.now(KST) - position.opened_at).total_seconds()
                if held_secs < self._min_hold_seconds:
                    log.debug(
                        "SELL skipped on %s — held %.0fs < min %ds",
                        market, held_secs, self._min_hold_seconds,
                    )
                    return
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
            self._last_trade_time[market] = datetime.now(KST)
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
        position = self.executor.get_position(market)
        avg_price = position.avg_price if position and position.avg_price > 0 else price

        order = self.executor.market_sell(market=market, quantity=quantity, current_price=price)
        if order:
            self._last_trade_time[market] = datetime.now(KST)
            sell_price = order.filled_price or price
            sell_qty = order.filled_volume or quantity
            sell_fee = order.fee or 0.0
            self.trade_log.log_trade(
                market=market, side="sell",
                price=sell_price,
                quantity=sell_qty,
                funds=order.funds or quantity * price,
                fee=sell_fee, mode=self.mode,
                strategy=self.strategy.name, reason=reason,
                order_id=order.id,
            )
            # PnL with fees: sell proceeds - buy cost (both include fees)
            buy_fee_est = avg_price * sell_qty * settings.active_fee_rate
            realized_pnl = (sell_price * sell_qty - sell_fee) - (avg_price * sell_qty + buy_fee_est)
            self.defense.record_trade_outcome(realized_pnl)
            # Re-analyze immediately so feedback is available for next trade
            try:
                self.analyzer.update()
            except Exception:
                pass
            # Trigger adaptive weights update for next signal generation
            if hasattr(self.strategy, 'notify_trade_completed'):
                self.strategy.notify_trade_completed()
            # Check if auto-tuning is needed after this trade
            self._check_auto_tuning()
            pnl_sign = "+" if realized_pnl >= 0 else ""
            send_alert(
                f"SELL {market} qty={sell_qty:.8f} @ {sell_price:,.0f} KRW | {reason} | "
                f"PnL≈{pnl_sign}{realized_pnl:,.0f} KRW | mode={self.defense.mode}"
            )

    # ------------------------------------------------------------------
    # Emergency exits
    # ------------------------------------------------------------------
    def _force_exit_alts(self, reason: str) -> None:
        """Force-close all non-BTC positions. Used on BTC crash."""
        if self.executor.is_paper:
            positions = dict(self.executor.paper.positions)
        else:
            positions = dict(self.executor._live_positions)
        for mkt, pos in positions.items():
            if mkt.upper() == "KRW-BTC":
                continue
            if pos.quantity <= 1e-12:
                continue
            px = self.market_data.get_current_price(mkt) or pos.avg_price
            try:
                self._execute_sell(mkt, pos.quantity, px, reason=reason)
                self.risk.clear_position_peak(mkt)
            except Exception as exc:
                log.warning("Force exit failed on %s: %s", mkt, exc)

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
        if self.executor.is_paper:
            self.executor.paper.save_state()
        self.defense.save_state()

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
    auto_discover: bool = False,
    max_auto_markets: int = 10,
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
        auto_discover=auto_discover or not markets or markets == ["AUTO"],
        max_auto_markets=max_auto_markets,
    )
