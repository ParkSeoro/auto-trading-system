"""Live / paper trading entry point.

Usage:
    python -m scripts.run_bot --mode paper --markets KRW-BTC,KRW-ETH --strategy ensemble
"""
from __future__ import annotations

import argparse
import sys

from src.bot import build_bot
from src.utils.logger import get_logger

log = get_logger("run_bot")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crypto auto-trading bot (Bithumb/Upbit)")
    parser.add_argument("--exchange", choices=["bithumb", "upbit"], default=None,
                        help="Exchange to use (overrides EXCHANGE env; default from .env)")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper",
                        help="Trading mode (default: paper)")
    parser.add_argument("--markets", default="KRW-BTC",
                        help="Comma-separated market codes, e.g. KRW-BTC,KRW-ETH")
    parser.add_argument("--strategy", default="ensemble",
                        help="Strategy name (volatility_breakout|rsi_mean_reversion|"
                             "bollinger_breakout|grid|ensemble)")
    parser.add_argument("--timeframe", default="1d",
                        help="Primary timeframe (Bithumb: 1m,3m,5m,10m,30m,1h,6h,12h,1d / "
                             "Upbit: 1m,5m,15m,30m,1h,4h,1d,1w)")
    args = parser.parse_args()

    markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    if args.mode == "live":
        log.warning("LIVE MODE ENABLED - real money will be used.")

    bot = build_bot(
        mode=args.mode, markets=markets,
        strategy_name=args.strategy, timeframe=args.timeframe,
        exchange_name=args.exchange,
    )
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
