"""Automatic parameter tuning — detects performance degradation and adjusts.

Runs after every N closed trades (default: 10). If the recent performance
drops below thresholds, it applies parameter adjustments (suggested by
Claude Advisor or by rule-based fallback).

Tunable parameters (per strategy):
- RSI range (low/high)
- Volume multiplier threshold
- SL/TP ATR multipliers
- Trade frequency (min_score threshold in screener)

Improvement target: expected value per trade +20%
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config.settings import KST
from typing import Dict, Optional

from config.settings import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class TuningRecord:
    ts: str
    strategy: str
    params_before: dict
    params_after: dict
    trigger: str              # "performance_drop" | "claude_suggestion" | "manual"
    expected_improvement: float = 0.0


class AutoTuner:
    """Monitors performance and applies parameter adjustments automatically.

    Parameters
    ----------
    tune_every_n_trades : int
        Evaluate performance after every N closed trades.
    min_expectancy : float
        If expected value per trade (KRW) falls below this, trigger tuning.
    min_win_rate : float
        Trigger tuning if win rate drops below this (0.4 = 40%).
    improvement_target : float
        Target improvement in expectancy (0.2 = 20%).
    """

    def __init__(
        self,
        tune_every_n_trades: int = 10,
        min_expectancy: float = 0.0,
        min_win_rate: float = 0.40,
        improvement_target: float = 0.20,
        tuning_log_path: Optional[Path] = None,
    ):
        self.tune_every_n_trades = tune_every_n_trades
        self.min_expectancy = min_expectancy
        self.min_win_rate = min_win_rate
        self.improvement_target = improvement_target
        self.tuning_log_path = Path(tuning_log_path or (settings.data_dir / "tuning_log.json"))
        self._trade_count_at_last_tune: Dict[str, int] = {}
        self._current_params: Dict[str, dict] = {}
        self._history: list = []

    # ------------------------------------------------------------------
    # Register / update strategy params
    # ------------------------------------------------------------------
    def register_strategy(self, strategy_name: str, params: dict) -> None:
        self._current_params[strategy_name] = dict(params)

    def get_params(self, strategy_name: str) -> dict:
        return dict(self._current_params.get(strategy_name, {}))

    # ------------------------------------------------------------------
    # Check if tuning is needed
    # ------------------------------------------------------------------
    def should_tune(self, strategy_name: str, stats: dict) -> bool:
        """Return True if enough trades have passed since last tuning."""
        total_trades = stats.get("total_trades", 0)
        last = self._trade_count_at_last_tune.get(strategy_name, 0)

        if total_trades - last < self.tune_every_n_trades:
            return False

        expectancy = stats.get("expectancy", 0.0)
        win_rate   = stats.get("win_rate", 0.5)

        if expectancy < self.min_expectancy:
            log.info(
                "[AutoTuner] %s: expectancy %.0f < %.0f — tuning needed",
                strategy_name, expectancy, self.min_expectancy,
            )
            return True
        if win_rate < self.min_win_rate:
            log.info(
                "[AutoTuner] %s: win_rate %.1f%% < %.1f%% — tuning needed",
                strategy_name, win_rate * 100, self.min_win_rate * 100,
            )
            return True

        # Periodic optimization even for winning strategies
        log.info(
            "[AutoTuner] %s: periodic review (trades=%d, wr=%.0f%%, exp=%.0f)",
            strategy_name, total_trades, win_rate * 100, expectancy,
        )
        return True

    # ------------------------------------------------------------------
    # Apply tuning (from Claude suggestion or rule-based fallback)
    # ------------------------------------------------------------------
    def apply_tuning(
        self,
        strategy_name: str,
        stats: dict,
        claude_advisor=None,
    ) -> dict:
        """Apply parameter adjustments. Returns new params dict."""
        params_before = self.get_params(strategy_name)
        total_trades  = stats.get("total_trades", 0)

        # Ask Claude for suggestions
        adjustments = {}
        expected_improvement = 0.0
        if claude_advisor and claude_advisor.available():
            result = claude_advisor.recommend_tuning(
                strategy_stats=stats,
                current_params=params_before,
            )
            adjustments = result.get("adjustments", {})
            expected_improvement = result.get("expected_improvement_pct", 0.0)
            trigger = "claude_suggestion"
        else:
            # Rule-based fallback
            adjustments, trigger = self._rule_based_adjustments(stats, params_before)
            expected_improvement = 15.0  # estimated

        # Apply non-null adjustments
        params_after = dict(params_before)
        for key, val in adjustments.items():
            if val is not None and key in params_after:
                # Validate bounds
                params_after[key] = self._clamp(key, val)

        if params_after == params_before:
            log.info("[AutoTuner] %s: no changes to apply", strategy_name)
            self._trade_count_at_last_tune[strategy_name] = total_trades
            return params_after

        # Record
        record = TuningRecord(
            ts=datetime.now(KST).isoformat(),
            strategy=strategy_name,
            params_before=params_before,
            params_after=params_after,
            trigger=trigger,
            expected_improvement=expected_improvement,
        )
        self._history.append(record)
        self._current_params[strategy_name] = params_after
        self._trade_count_at_last_tune[strategy_name] = total_trades
        self._save_log()

        log.info(
            "[AutoTuner] %s tuned (%s): %s → %s (expected +%.0f%%)",
            strategy_name, trigger, params_before, params_after, expected_improvement,
        )
        return params_after

    # ------------------------------------------------------------------
    # Rule-based fallback adjustments
    # ------------------------------------------------------------------
    def _rule_based_adjustments(self, stats: dict, params: dict) -> tuple[dict, str]:
        win_rate    = stats.get("win_rate", 0.5)
        expectancy  = stats.get("expectancy", 0.0)
        profit_factor = stats.get("profit_factor") or 0.0

        adj = {}
        is_crypto_regime = "adx_trend_threshold" in params

        if is_crypto_regime:
            # crypto_regime specific tuning
            if win_rate < 0.40:
                adj["rsi_oversold"] = params.get("rsi_oversold", 30.0) + 2
                adj["rsi_overbought"] = params.get("rsi_overbought", 72.0) - 2
                adj["adx_trend_threshold"] = params.get("adx_trend_threshold", 22.0) + 1
            if expectancy < 0:
                adj["sl_buffer_atr"] = max(0.1, params.get("sl_buffer_atr", 0.3) - 0.05)
                adj["min_rr_ratio"] = min(3.0, params.get("min_rr_ratio", 1.5) + 0.2)
            if profit_factor < 1.2:
                adj["volume_expansion_mult"] = min(2.5, params.get("volume_expansion_mult", 1.5) + 0.1)
        else:
            # Generic strategy tuning
            if win_rate < 0.40:
                rsi_low = params.get("rsi_low", 25.0)
                rsi_high = params.get("rsi_high", 40.0)
                adj["rsi_low"]  = rsi_low + 2
                adj["rsi_high"] = rsi_high - 2
            if expectancy < 0:
                sl = params.get("sl_atr_mult", 1.5)
                tp = params.get("tp_atr_mult", 2.5)
                adj["sl_atr_mult"] = max(1.0, sl - 0.2)
                adj["tp_atr_mult"] = min(4.0, tp + 0.3)
            if profit_factor < 1.2:
                vol = params.get("volume_min_mult", 1.5)
                adj["volume_min_mult"] = min(2.0, vol + 0.1)

        return adj, "rule_based"

    # ------------------------------------------------------------------
    # Param bounds
    # ------------------------------------------------------------------
    _BOUNDS = {
        "rsi_low":        (15.0, 35.0),
        "rsi_high":       (30.0, 50.0),
        "volume_min_mult":(1.2, 2.5),
        "volume_max_mult":(2.0, 5.0),
        "sl_atr_mult":    (0.8, 2.5),
        "tp_atr_mult":    (1.5, 5.0),
        # crypto_regime specific
        "adx_trend_threshold": (18.0, 30.0),
        "adx_range_threshold": (12.0, 22.0),
        "volume_expansion_mult": (1.2, 2.5),
        "min_rr_ratio":   (1.2, 3.0),
        "sl_buffer_atr":  (0.1, 0.8),
        "rsi_oversold":   (20.0, 40.0),
        "rsi_overbought": (65.0, 80.0),
        "ema_fast":       (10, 30),
        "ema_slow":       (30, 70),
        "swing_lookback": (5, 20),
    }

    def _clamp(self, key: str, val: float) -> float:
        lo, hi = self._BOUNDS.get(key, (val, val))
        return max(lo, min(hi, float(val)))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_log(self) -> None:
        try:
            self.tuning_log_path.parent.mkdir(parents=True, exist_ok=True)
            doc = [
                {
                    "ts": r.ts,
                    "strategy": r.strategy,
                    "params_before": r.params_before,
                    "params_after": r.params_after,
                    "trigger": r.trigger,
                    "expected_improvement": r.expected_improvement,
                }
                for r in self._history[-50:]  # keep last 50
            ]
            self.tuning_log_path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.debug("tuning log write failed: %s", exc)

    def get_history(self) -> list:
        return [
            {
                "ts": r.ts, "strategy": r.strategy,
                "trigger": r.trigger,
                "expected_improvement": r.expected_improvement,
            }
            for r in self._history[-10:]
        ]
