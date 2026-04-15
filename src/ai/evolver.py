"""Walk-forward genetic hyperparameter evolver.

Given a DataFrame of OHLCV history, we:
  1. Split into sequential (train, validation) windows ("walk-forward").
  2. Seed a small population of parameter vectors per strategy.
  3. For each window, backtest each individual on the train window,
     take the top-k fittest by Sharpe, then mutate/crossover to produce
     the next generation.
  4. The best individual of the final generation is scored on the held-out
     validation window. That validation Sharpe is the fitness used to
     write the winning params to ``data/best_params.json``.

Deterministic when seeded. No external ML library required.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from config.settings import settings
from src.backtesting import Backtester
from src.strategies.base import Strategy
from src.strategies.bollinger_breakout import BollingerBreakoutStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy
from src.utils.logger import get_logger

log = get_logger(__name__)


# ----------------------------------------------------------------------
# Parameter specs: per-strategy (name -> (default, low, high, kind))
# ----------------------------------------------------------------------
ParamSpec = Dict[str, Tuple[float, float, float, str]]  # default, low, high, kind

STRATEGY_SPECS: Dict[str, Tuple[type, ParamSpec]] = {
    "volatility_breakout": (
        VolatilityBreakoutStrategy,
        {
            "k": (0.5, 0.2, 1.0, "float"),
            "volume_factor": (1.0, 0.5, 2.0, "float"),
        },
    ),
    "rsi_mean_reversion": (
        RSIMeanReversionStrategy,
        {
            "period": (14, 7, 30, "int"),
            "oversold": (25.0, 15.0, 35.0, "float"),
            "overbought": (75.0, 65.0, 85.0, "float"),
        },
    ),
    "bollinger_breakout": (
        BollingerBreakoutStrategy,
        {
            "period": (20, 10, 40, "int"),
            "num_std": (2.0, 1.5, 3.0, "float"),
            "squeeze_pct": (0.04, 0.01, 0.10, "float"),
            "volume_factor": (1.2, 0.8, 2.0, "float"),
        },
    ),
}


# ----------------------------------------------------------------------
# Individual = parameter dict + fitness
# ----------------------------------------------------------------------
@dataclass
class Individual:
    params: Dict[str, float]
    fitness: float = float("-inf")

    def copy(self) -> "Individual":
        return Individual(params=dict(self.params), fitness=self.fitness)


# ----------------------------------------------------------------------
# Genetic operations
# ----------------------------------------------------------------------
def _random_param(spec: ParamSpec, rng: random.Random) -> Dict[str, float]:
    params: Dict[str, float] = {}
    for name, (_default, low, high, kind) in spec.items():
        if kind == "int":
            params[name] = int(rng.uniform(low, high + 0.999))
        else:
            params[name] = round(rng.uniform(low, high), 4)
    return params


def _mutate(
    params: Dict[str, float],
    spec: ParamSpec,
    rng: random.Random,
    rate: float = 0.3,
    sigma: float = 0.15,
) -> Dict[str, float]:
    new = dict(params)
    for name, (_d, low, high, kind) in spec.items():
        if rng.random() > rate:
            continue
        span = high - low
        delta = rng.gauss(0, sigma) * span
        v = new[name] + delta
        v = max(low, min(high, v))
        if kind == "int":
            v = int(round(v))
        else:
            v = round(v, 4)
        new[name] = v
    return new


def _crossover(
    a: Dict[str, float], b: Dict[str, float], rng: random.Random
) -> Dict[str, float]:
    return {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a}


# ----------------------------------------------------------------------
# Evolver
# ----------------------------------------------------------------------
@dataclass
class EvolveResult:
    strategy: str
    best_params: Dict[str, float]
    train_fitness: float
    val_fitness: float
    generations: int
    history: List[float] = field(default_factory=list)  # best-of-gen train fitness


class StrategyEvolver:
    """GA over strategy hyperparameters with walk-forward validation."""

    def __init__(
        self,
        population_size: int = 12,
        generations: int = 8,
        elite_ratio: float = 0.25,
        mutation_rate: float = 0.3,
        train_ratio: float = 0.7,
        starting_capital: float = 1_000_000.0,
        seed: Optional[int] = 42,
        fitness_fn: Optional[Callable] = None,
    ):
        self.population_size = max(4, population_size)
        self.generations = max(1, generations)
        # Need at least 2 elites for crossover sampling.
        self.elite_n = max(2, int(self.population_size * elite_ratio))
        self.mutation_rate = mutation_rate
        self.train_ratio = train_ratio
        self.starting_capital = starting_capital
        self.rng = random.Random(seed)
        # default fitness = Sharpe, tie-break by total_return, penalised by drawdown
        self.fitness_fn = fitness_fn or self._default_fitness

    @staticmethod
    def _default_fitness(result) -> float:
        # Reject trivial (no-trade) runs
        if result.num_trades == 0:
            return -1.0
        return (
            result.sharpe_ratio
            + 0.25 * result.total_return
            - 0.5 * result.max_drawdown
        )

    # ------------------------------------------------------------------
    def evolve(self, strategy_name: str, df: pd.DataFrame) -> EvolveResult:
        if strategy_name not in STRATEGY_SPECS:
            raise ValueError(
                f"Unknown strategy '{strategy_name}'. "
                f"Supported: {list(STRATEGY_SPECS)}"
            )
        StratCls, spec = STRATEGY_SPECS[strategy_name]

        split = max(StratCls().required_bars + 10, int(len(df) * self.train_ratio))
        if split >= len(df) - 10:
            raise ValueError(
                f"Not enough data. Need at least {split + 10} bars, got {len(df)}."
            )
        train_df = df.iloc[:split]
        val_df = df.iloc[split:]

        # Seed population: include defaults + random individuals
        population: List[Individual] = [
            Individual(params={k: v[0] for k, v in spec.items()})
        ]
        while len(population) < self.population_size:
            population.append(Individual(params=_random_param(spec, self.rng)))

        history: List[float] = []

        for gen in range(self.generations):
            for ind in population:
                if ind.fitness == float("-inf"):
                    ind.fitness = self._score(StratCls, ind.params, train_df)
            population.sort(key=lambda i: i.fitness, reverse=True)
            best_now = population[0]
            history.append(best_now.fitness)
            log.info(
                "[%s] gen %d/%d best train-fitness=%.3f params=%s",
                strategy_name, gen + 1, self.generations, best_now.fitness, best_now.params,
            )

            # Next generation: elites + children
            elites = population[: self.elite_n]
            children: List[Individual] = []
            while len(children) < self.population_size - self.elite_n:
                if len(elites) >= 2:
                    a, b = self.rng.sample(elites, 2)
                else:
                    a = b = elites[0]
                child_params = _crossover(a.params, b.params, self.rng)
                child_params = _mutate(child_params, spec, self.rng, rate=self.mutation_rate)
                children.append(Individual(params=child_params))
            population = [e.copy() for e in elites] + children
            # elites keep fitness; children need re-scoring (handled next loop iter)
            for c in children:
                c.fitness = float("-inf")

        # Score all on train, pick best, then validate
        for ind in population:
            if ind.fitness == float("-inf"):
                ind.fitness = self._score(StratCls, ind.params, train_df)
        population.sort(key=lambda i: i.fitness, reverse=True)
        best = population[0]
        val_fitness = self._score(StratCls, best.params, val_df)

        log.info(
            "[%s] DONE. train-fit=%.3f  val-fit=%.3f  params=%s",
            strategy_name, best.fitness, val_fitness, best.params,
        )

        return EvolveResult(
            strategy=strategy_name,
            best_params=best.params,
            train_fitness=best.fitness,
            val_fitness=val_fitness,
            generations=self.generations,
            history=history,
        )

    # ------------------------------------------------------------------
    def _score(self, StratCls: type, params: Dict[str, float], df: pd.DataFrame) -> float:
        try:
            strat = StratCls(**params)
        except (TypeError, ValueError) as exc:
            log.debug("invalid params %s: %s", params, exc)
            return -10.0
        bt = Backtester(strategy=strat, starting_capital=self.starting_capital)
        try:
            result = bt.run(df)
        except ValueError as exc:
            log.debug("backtest failed: %s", exc)
            return -10.0
        return self.fitness_fn(result)


# ----------------------------------------------------------------------
# Persist winner
# ----------------------------------------------------------------------
def persist_best_params(results: List[EvolveResult], path: Optional[Path] = None) -> Path:
    out_path = Path(path or (settings.data_dir / "best_params.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        r.strategy: {
            "params": r.best_params,
            "train_fitness": round(r.train_fitness, 4),
            "val_fitness": round(r.val_fitness, 4),
            "generations": r.generations,
            "history": [round(h, 4) for h in r.history],
        }
        for r in results
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out_path
