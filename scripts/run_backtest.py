"""Backtest a strategy on Upbit historical candles.

Usage:
    python -m scripts.run_backtest --market KRW-BTC --strategy volatility_breakout \
        --from 2024-01-01 --to 2024-12-31 --capital 1000000
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config.settings import settings
from src.backtesting import Backtester
from src.data import candles_to_dataframe
from src.exchanges import UpbitExchange
from src.risk.risk_manager import RiskManager
from src.strategies import get_strategy
from src.utils.logger import get_logger

log = get_logger("run_backtest")


def _slice_by_date(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if df.empty:
        return df
    tz = df.index.tz
    s = pd.Timestamp(start, tz=tz) if tz is not None else pd.Timestamp(start)
    e = pd.Timestamp(end, tz=tz) if tz is not None else pd.Timestamp(end)
    return df.loc[(df.index >= s) & (df.index <= e)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest a crypto strategy")
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--strategy", default="volatility_breakout")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--count", type=int, default=1000, help="Bars to fetch (max)")
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--csv", type=str, default=None,
                        help="Optional path to save equity curve + trades CSV")
    args = parser.parse_args()

    exchange = UpbitExchange(
        access_key=settings.upbit_access_key,
        secret_key=settings.upbit_secret_key,
    )
    log.info("Fetching %d bars of %s (%s)...", args.count, args.market, args.timeframe)
    candles = exchange.fetch_ohlcv(args.market, timeframe=args.timeframe, count=args.count)
    df = candles_to_dataframe(candles)

    if args.start or args.end:
        df = _slice_by_date(
            df,
            args.start or df.index.min().strftime("%Y-%m-%d"),
            args.end or df.index.max().strftime("%Y-%m-%d"),
        )

    log.info("Running backtest on %d bars (%s -> %s)", len(df),
             df.index.min() if len(df) else "n/a",
             df.index.max() if len(df) else "n/a")

    strategy = get_strategy(args.strategy)
    risk = RiskManager(capital=args.capital)
    bt = Backtester(strategy=strategy, starting_capital=args.capital, risk=risk)
    result = bt.run(df)

    print(result.summary())

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        result.equity_curve.to_frame("equity").to_csv(out)
        trades_df = pd.DataFrame(result.trades)
        trades_df.to_csv(out.with_suffix(".trades.csv"), index=False)
        log.info("Saved: %s and %s", out, out.with_suffix(".trades.csv"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
