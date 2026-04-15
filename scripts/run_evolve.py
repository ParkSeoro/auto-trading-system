"""Offline hyperparameter evolution (self-tuning brain).

Pulls OHLCV history from the active exchange and walks a genetic
algorithm over each strategy's parameter space. The best params found
on the held-out validation window are written to
``data/best_params.json`` — which the live bot (via AdaptiveEnsemble)
picks up on the next tick.

Example::

    python -m scripts.run_evolve --market KRW-BTC --count 1000 \
        --strategies volatility_breakout,rsi_mean_reversion,bollinger_breakout \
        --generations 10 --population 16
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from src.ai.evolver import StrategyEvolver, EvolveResult, persist_best_params
from src.data import candles_to_dataframe
from src.exchanges import build_exchange
from src.utils.logger import get_logger

log = get_logger("run_evolve")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evolve strategy hyperparameters")
    parser.add_argument("--exchange", choices=["bithumb", "upbit"], default=None)
    parser.add_argument("--market", default="KRW-BTC")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--count", type=int, default=800)
    parser.add_argument(
        "--strategies",
        default="volatility_breakout,rsi_mean_reversion,bollinger_breakout",
        help="Comma-separated strategy names to evolve.",
    )
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("--population", type=int, default=12)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    exchange = build_exchange(args.exchange)
    log.info("Using exchange: %s", exchange.name)
    log.info("Fetching %d %s bars of %s...", args.count, args.timeframe, args.market)
    candles = exchange.fetch_ohlcv(args.market, timeframe=args.timeframe, count=args.count)
    df = candles_to_dataframe(candles)
    if df.empty:
        log.error("No data returned from exchange.")
        return 2

    evolver = StrategyEvolver(
        population_size=args.population,
        generations=args.generations,
        starting_capital=args.capital,
        seed=args.seed,
    )

    results: List[EvolveResult] = []
    for name in [s.strip() for s in args.strategies.split(",") if s.strip()]:
        log.info("--- evolving %s ---", name)
        try:
            res = evolver.evolve(name, df)
            results.append(res)
            print(
                f"[{name}] best train={res.train_fitness:.3f}  "
                f"val={res.val_fitness:.3f}  params={res.best_params}"
            )
        except ValueError as exc:
            log.error("skip %s: %s", name, exc)

    if not results:
        log.error("No strategies evolved successfully.")
        return 3

    out = persist_best_params(results)
    log.info("Best params written to %s", out)
    print(f"\nWritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
