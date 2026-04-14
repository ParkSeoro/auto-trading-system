"""Event-driven backtester for crypto strategies.

Walks through each bar, feeding the strategy only historical data available
up to that point to avoid look-ahead bias. Fills happen at next bar's open
for realism. Fees and crypto-specific constraints (min order amount, fractional
quantities) are applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from config.settings import settings
from src.risk.risk_manager import RiskManager
from src.strategies.base import SignalType, Strategy


@dataclass
class BacktestResult:
    trades: List[dict] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    final_equity: float = 0.0
    starting_equity: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0

    def summary(self) -> str:
        return (
            f"\n==== Backtest Result ====\n"
            f"Starting equity : {self.starting_equity:>15,.0f} KRW\n"
            f"Final equity    : {self.final_equity:>15,.0f} KRW\n"
            f"Total return    : {self.total_return*100:>14.2f}%\n"
            f"Max drawdown    : {self.max_drawdown*100:>14.2f}%\n"
            f"Sharpe ratio    : {self.sharpe_ratio:>15.2f}\n"
            f"Profit factor   : {self.profit_factor:>15.2f}\n"
            f"Trades          : {self.num_trades:>15d}\n"
            f"Win rate        : {self.win_rate*100:>14.2f}%\n"
            f"=========================\n"
        )


@dataclass
class Backtester:
    strategy: Strategy
    starting_capital: float = 1_000_000.0
    fee_rate: float = field(default_factory=lambda: settings.upbit_fee_rate)
    risk: Optional[RiskManager] = None

    def run(self, df: pd.DataFrame) -> BacktestResult:
        if len(df) < self.strategy.required_bars + 1:
            raise ValueError(
                f"Need at least {self.strategy.required_bars + 1} bars, got {len(df)}"
            )

        cash = self.starting_capital
        qty = 0.0
        avg_price = 0.0
        stop_loss: Optional[float] = None
        take_profit: Optional[float] = None

        trades: List[dict] = []
        equity_points: List[tuple] = []
        realized_pnls: List[float] = []

        risk = self.risk or RiskManager(capital=self.starting_capital)

        for i in range(self.strategy.required_bars, len(df) - 1):
            window = df.iloc[: i + 1]
            next_bar = df.iloc[i + 1]
            # fill at next bar's open
            fill_price = float(next_bar["open"])
            ts = df.index[i + 1]

            position = {
                "quantity": qty,
                "avg_price": avg_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

            # 1. Exit checks on actual position
            if qty > 0:
                low = float(next_bar["low"])
                high = float(next_bar["high"])
                # Stop loss first (conservative assumption)
                if stop_loss is not None and low <= stop_loss:
                    proceeds = qty * stop_loss * (1 - self.fee_rate)
                    pnl = proceeds - qty * avg_price
                    realized_pnls.append(pnl)
                    trades.append({
                        "ts": ts, "side": "sell", "reason": "stop_loss",
                        "price": stop_loss, "qty": qty, "pnl": pnl,
                    })
                    cash += proceeds
                    qty = 0.0
                    avg_price = 0.0
                    stop_loss = take_profit = None
                    self._record_equity(equity_points, ts, cash, qty, fill_price)
                    continue
                if take_profit is not None and high >= take_profit:
                    proceeds = qty * take_profit * (1 - self.fee_rate)
                    pnl = proceeds - qty * avg_price
                    realized_pnls.append(pnl)
                    trades.append({
                        "ts": ts, "side": "sell", "reason": "take_profit",
                        "price": take_profit, "qty": qty, "pnl": pnl,
                    })
                    cash += proceeds
                    qty = 0.0
                    avg_price = 0.0
                    stop_loss = take_profit = None
                    self._record_equity(equity_points, ts, cash, qty, fill_price)
                    continue

            # 2. Strategy signal
            signal = self.strategy.generate(window, position=position)

            if signal.type == SignalType.BUY and qty == 0 and cash > 0:
                equity = cash + qty * fill_price
                risk.capital = equity
                decision = risk.evaluate_entry(window, confidence=signal.confidence,
                                               available_krw=cash)
                if decision.approved:
                    funds = min(decision.position_size_krw, cash)
                    fee = funds * self.fee_rate
                    qty = (funds - fee) / fill_price
                    avg_price = fill_price
                    cash -= funds
                    stop_loss = decision.stop_loss
                    take_profit = decision.take_profit
                    trades.append({
                        "ts": ts, "side": "buy", "reason": signal.reason,
                        "price": fill_price, "qty": qty, "funds": funds,
                    })

            elif signal.type == SignalType.SELL and qty > 0:
                proceeds = qty * fill_price * (1 - self.fee_rate)
                pnl = proceeds - qty * avg_price
                realized_pnls.append(pnl)
                trades.append({
                    "ts": ts, "side": "sell", "reason": signal.reason,
                    "price": fill_price, "qty": qty, "pnl": pnl,
                })
                cash += proceeds
                qty = 0.0
                avg_price = 0.0
                stop_loss = take_profit = None

            self._record_equity(equity_points, ts, cash, qty, fill_price)
            equity_now = cash + qty * fill_price
            risk.update_equity(equity_now, now=pd.Timestamp(ts).to_pydatetime())

        # Liquidate open position at last close for final equity
        last_price = float(df["close"].iloc[-1])
        if qty > 0:
            proceeds = qty * last_price * (1 - self.fee_rate)
            pnl = proceeds - qty * avg_price
            realized_pnls.append(pnl)
            trades.append({
                "ts": df.index[-1], "side": "sell", "reason": "mark_to_close",
                "price": last_price, "qty": qty, "pnl": pnl,
            })
            cash += proceeds
            qty = 0.0

        equity_series = self._equity_series(equity_points, df, cash)
        return self._build_result(trades, equity_series, realized_pnls)

    @staticmethod
    def _record_equity(points, ts, cash, qty, price) -> None:
        points.append((ts, cash + qty * price))

    def _equity_series(self, points, df, final_cash) -> pd.Series:
        if not points:
            return pd.Series([self.starting_capital, final_cash], index=[df.index[0], df.index[-1]])
        idx = [p[0] for p in points]
        vals = [p[1] for p in points]
        return pd.Series(vals, index=idx)

    def _build_result(self, trades, equity_series, realized_pnls) -> BacktestResult:
        start = self.starting_capital
        end = equity_series.iloc[-1] if len(equity_series) else start
        total_return = (end / start) - 1 if start else 0.0

        # Max drawdown
        peak = equity_series.cummax() if len(equity_series) else pd.Series([start])
        dd = (peak - equity_series) / peak
        max_dd = float(dd.max()) if len(dd) else 0.0

        # Sharpe (annualized, assuming bar returns)
        returns = equity_series.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            sharpe = float(returns.mean() / returns.std() * np.sqrt(365))
        else:
            sharpe = 0.0

        wins = [p for p in realized_pnls if p > 0]
        losses = [p for p in realized_pnls if p < 0]
        total_loss = abs(sum(losses))
        profit_factor = (sum(wins) / total_loss) if total_loss > 0 else float("inf") if wins else 0.0
        win_rate = (len(wins) / len(realized_pnls)) if realized_pnls else 0.0

        return BacktestResult(
            trades=trades,
            equity_curve=equity_series,
            final_equity=float(end),
            starting_equity=float(start),
            total_return=float(total_return),
            max_drawdown=max_dd,
            win_rate=win_rate,
            num_trades=len(realized_pnls),
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
        )
