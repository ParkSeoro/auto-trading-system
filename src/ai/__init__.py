"""AI / self-learning layer.

This module adds two capabilities on top of the base strategy engine:

1. **Online adaptation** (`AdaptiveEnsembleStrategy`):
   - Tracks per-member realized PnL attribution from the SQLite trade log.
   - Re-weights members with a Hedge / exponential-weights update so the
     committee leans harder on strategies that have been profitable *recently*.
   - Weights are persisted to JSON so they survive restarts.

2. **Offline evolution** (`StrategyEvolver`):
   - Walk-forward search that mutates strategy hyperparameters
     (VB ``k``, RSI thresholds, BB length/std) and keeps the child that
     improved the Sharpe ratio on the validation slice.
   - Runs independently of live trading; writes the best params back to
   ``weights.json`` for the live ensemble to pick up.

These two together give the bot a self-evolving feedback loop —
no external ML dependencies required.
"""
from src.ai.evolver import StrategyEvolver  # noqa: F401
from src.ai.adaptive import AdaptiveEnsembleStrategy, WeightStore  # noqa: F401
