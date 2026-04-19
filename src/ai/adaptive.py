"""Adaptive ensemble with online Hedge re-weighting.

Design notes
------------
- We do NOT spin up a heavyweight ML stack — the goal is a robust,
  auditable, deterministic update rule that works offline.
- The Hedge algorithm is a classic online-learning approach:
  ``w_i <- w_i * exp(eta * reward_i)``  (then renormalised).
  With ``reward_i`` = recent realized PnL attributable to strategy i,
  this strictly down-weights losing models and up-weights winning ones.
- Attribution: a strategy is "credited" with a trade's PnL when the
  trade's ``strategy`` column (logged at execution time) matches.

File layout
~~~~~~~~~~~
``weights.json`` under the project root::

    {
      "weights": {"volatility_breakout": 0.34, "rsi_mean_reversion": 0.33, ...},
      "last_trade_id": 1234,
      "updated_at": "2026-01-01T00:00:00Z"
    }
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from config.settings import KST, settings
from src.strategies.base import Signal, SignalType, Strategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.bollinger_breakout import BollingerBreakoutStrategy
from src.strategies.macd_crossover import MACDCrossoverStrategy
from src.strategies.multi_tf_momentum import MultiTFMomentumStrategy
from src.utils.logger import get_logger

log = get_logger(__name__)


# ----------------------------------------------------------------------
# Weight persistence
# ----------------------------------------------------------------------
@dataclass
class WeightStore:
    """JSON-backed weight store. Safe against missing / corrupt files."""
    path: Path

    def load(self) -> dict:
        if not self.path.exists():
            return {"weights": {}, "last_trade_id": 0, "updated_at": None}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("weights.json unreadable — starting fresh")
            return {"weights": {}, "last_trade_id": 0, "updated_at": None}

    def save(self, weights: Dict[str, float], last_trade_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "weights": {k: round(float(v), 6) for k, v in weights.items()},
            "last_trade_id": int(last_trade_id),
            "updated_at": datetime.now(KST).isoformat(),
        }
        self.path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# Hedge updater
# ----------------------------------------------------------------------
def hedge_update(
    weights: Dict[str, float],
    rewards: Dict[str, float],
    eta: float = 0.5,
    floor: float = 0.05,
) -> Dict[str, float]:
    """Multiplicative weights update. Always returns a normalized distribution.

    Parameters
    ----------
    weights : current weight vector (missing keys start at 1/N)
    rewards : per-strategy signed reward in [-1, +1] (e.g. normalized PnL)
    eta     : learning rate; larger = more aggressive
    floor   : minimum weight per strategy (prevents a dead model)
    """
    names = sorted(set(weights) | set(rewards))
    if not names:
        return {}
    base = {n: float(weights.get(n, 1.0 / len(names))) for n in names}

    # clip rewards to avoid explosions
    rew = {n: max(-1.0, min(1.0, float(rewards.get(n, 0.0)))) for n in names}

    raw = {n: base[n] * math.exp(eta * rew[n]) for n in names}
    total = sum(raw.values())
    if total <= 0:
        raw = {n: 1.0 / len(names) for n in names}

    # Water-filling: freeze any that would fall below floor at exactly ``floor``
    # and proportionally renormalise the rest. Guaranteed to sum to 1.
    floor = max(0.0, min(floor, 1.0 / len(names)))
    frozen: dict = {}
    active = dict(raw)
    while True:
        avail = 1.0 - sum(frozen.values())
        if not active or avail <= 0:
            break
        s = sum(active.values()) or 1.0
        new_frozen = {n: floor for n, v in active.items() if (v / s) * avail < floor}
        if not new_frozen:
            break
        frozen.update(new_frozen)
        for n in new_frozen:
            active.pop(n, None)

    remaining_budget = 1.0 - sum(frozen.values())
    s = sum(active.values()) or 1.0
    out = {n: frozen[n] for n in frozen}
    for n, v in active.items():
        out[n] = v / s * remaining_budget
    return out


# ----------------------------------------------------------------------
# Trade-log attribution
# ----------------------------------------------------------------------
def compute_strategy_rewards(
    db_path: Path,
    since_id: int = 0,
    scale_krw: float = 100_000.0,
) -> tuple[Dict[str, float], int]:
    """Aggregate realised PnL per strategy, FIFO-matched on (market, strategy).

    Returns (rewards_normalised, max_id_seen).

    Rewards are normalised by ``scale_krw`` (so a 100k KRW win ~= reward 1.0)
    and clipped to [-1, +1]. Unclosed positions are ignored.
    """
    if not Path(db_path).exists():
        return {}, since_id

    rows: List[tuple] = []
    max_id = since_id
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                "SELECT id, market, side, price, quantity, funds, fee, strategy "
                "FROM trades WHERE id > ? ORDER BY id ASC",
                (since_id,),
            )
            rows = cur.fetchall()
    except sqlite3.Error as exc:
        log.warning("trade-log read failed: %s", exc)
        return {}, since_id

    # FIFO lots keyed by (market, strategy)
    lots: Dict[tuple, list] = {}
    pnl: Dict[str, float] = {}
    for (tid, market, side, price, qty, funds, fee, strategy) in rows:
        max_id = max(max_id, tid or 0)
        key = (market, strategy or "unknown")
        if side == "buy":
            lots.setdefault(key, []).append([qty, price, fee])
        elif side == "sell":
            remaining = qty
            gross_sell = remaining * price - fee
            # match against earliest buys
            cost_basis = 0.0
            buy_fee_used = 0.0
            lot_list = lots.get(key, [])
            while remaining > 1e-12 and lot_list:
                lot_qty, lot_price, lot_fee = lot_list[0]
                take = min(remaining, lot_qty)
                cost_basis += take * lot_price
                buy_fee_used += lot_fee * (take / lot_qty) if lot_qty > 0 else 0.0
                lot_qty -= take
                remaining -= take
                if lot_qty <= 1e-12:
                    lot_list.pop(0)
                else:
                    lot_list[0][0] = lot_qty
            realised = gross_sell - cost_basis - buy_fee_used
            pnl[strategy or "unknown"] = pnl.get(strategy or "unknown", 0.0) + realised

    # Normalise & clip
    rewards = {
        s: max(-1.0, min(1.0, v / scale_krw if scale_krw > 0 else v))
        for s, v in pnl.items()
    }
    return rewards, max_id


# ----------------------------------------------------------------------
# Adaptive ensemble strategy
# ----------------------------------------------------------------------
class AdaptiveEnsembleStrategy(Strategy):
    """Same public interface as EnsembleStrategy but learns its member weights.

    Every ``adapt_every`` calls to :meth:`generate`, it re-reads the SQLite
    trade log, computes per-strategy realised PnL since last update and applies
    a Hedge-style multiplicative update to its weights.
    """

    name = "adaptive_ensemble"

    def __init__(
        self,
        members: Optional[List[Strategy]] = None,
        buy_threshold: float = 0.35,
        eta: float = 0.5,
        adapt_every: int = 10,
        weights_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        self.members: List[Strategy] = members or [
            VolatilityBreakoutStrategy(k=0.5),
            RSIMeanReversionStrategy(),
            BollingerBreakoutStrategy(),
            MACDCrossoverStrategy(),
            MultiTFMomentumStrategy(),
        ]
        self.buy_threshold = max(0.45, buy_threshold)
        self.eta = eta
        self._pending_adapt = False
        self.adapt_every = max(1, int(adapt_every))
        self.required_bars = max((m.required_bars for m in self.members), default=50)
        self.weights_path = Path(weights_path or (settings.data_dir / "weights.json"))
        self.db_path = Path(db_path or settings.db_path)
        self.store = WeightStore(self.weights_path)

        self._call_count = 0
        state = self.store.load()
        self._last_trade_id: int = int(state.get("last_trade_id") or 0)
        initial = state.get("weights") or {}
        self.weights: Dict[str, float] = self._seed_weights(initial)

    def _seed_weights(self, persisted: Dict[str, float]) -> Dict[str, float]:
        names = [m.name for m in self.members]
        if not persisted:
            return {n: 1.0 / len(names) for n in names}
        merged = {n: float(persisted.get(n, 1.0 / len(names))) for n in names}
        total = sum(merged.values()) or 1.0
        return {n: v / total for n, v in merged.items()}

    # ------------------------------------------------------------------
    # Adaptation
    # ------------------------------------------------------------------
    def adapt(self) -> Dict[str, float]:
        rewards, max_id = compute_strategy_rewards(self.db_path, self._last_trade_id)
        if not rewards or max_id <= self._last_trade_id:
            return self.weights

        # Cross-reference with trade analyzer for deeper feedback
        try:
            from src.ai.trade_analyzer import TradeAnalyzer
            analyzer = TradeAnalyzer(db_path=self.db_path)
            analyzer.update()
            # Penalise strategies with negative expectancy or loss streaks
            for name in list(rewards.keys()):
                for key, stat in analyzer.stats.items():
                    _, strat_name = key.split("|", 1) if "|" in key else ("", key)
                    if strat_name == name and stat.total_trades >= 3:
                        # Amplify negative rewards for strategies on loss streaks
                        if stat.current_streak < -2 and rewards[name] < 0:
                            rewards[name] = max(-1.0, rewards[name] * 1.5)
                            log.info("Amplified penalty for %s (streak=%d)", name, stat.current_streak)
                        # Slightly boost strategies with positive expectancy
                        elif stat.expectancy() > 0 and rewards[name] > 0:
                            rewards[name] = min(1.0, rewards[name] * 1.2)
        except Exception as exc:
            log.debug("trade analyzer feedback skipped: %s", exc)

        self.weights = hedge_update(self.weights, rewards, eta=self.eta)
        self._last_trade_id = max_id
        self.store.save(self.weights, self._last_trade_id)
        log.info("adaptive weights -> %s (rewards=%s)",
                 {k: round(v, 3) for k, v in self.weights.items()}, rewards)
        return self.weights

    def notify_trade_completed(self) -> None:
        """Called by bot after a sell. Triggers weight re-adaptation on next generate()."""
        self._pending_adapt = True

    # ------------------------------------------------------------------
    # Strategy API
    # ------------------------------------------------------------------
    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        self._call_count += 1
        if self._pending_adapt or self._call_count % self.adapt_every == 0:
            self.adapt()
            self._pending_adapt = False

        buy_score = 0.0
        sell_score = 0.0
        weight_used = 0.0
        reasons = []
        meta: dict = {"weights": dict(self.weights)}
        strong_sell_count = 0

        for strat in self.members:
            w = float(self.weights.get(strat.name, 0.0))
            sig = strat.generate(df, position=position)
            meta[strat.name] = {
                "type": sig.type.value,
                "confidence": round(sig.confidence, 3),
                "weight": round(w, 3),
                "reason": sig.reason,
            }
            weight_used += w
            if sig.type == SignalType.BUY:
                buy_score += w * sig.confidence
                reasons.append(f"+{strat.name}(w={w:.2f}, c={sig.confidence:.2f})")
            elif sig.type == SignalType.SELL:
                sell_score += w * sig.confidence
                reasons.append(f"-{strat.name}(w={w:.2f}, c={sig.confidence:.2f})")
                if sig.confidence >= 0.9:
                    strong_sell_count += 1

        denom = weight_used if weight_used > 0 else 1.0
        buy_norm = buy_score / denom
        sell_norm = sell_score / denom
        has_position = bool(position and position.get("quantity", 0) > 0)

        if sell_norm > buy_norm and sell_norm >= self.buy_threshold:
            return Signal(
                SignalType.SELL,
                confidence=min(1.0, sell_norm),
                reason="adaptive SELL | " + ", ".join(reasons),
                meta=meta,
            )

        if not has_position and buy_norm >= self.buy_threshold and buy_norm > sell_norm:
            return Signal(
                SignalType.BUY,
                confidence=min(1.0, buy_norm),
                reason="adaptive BUY | " + ", ".join(reasons),
                meta=meta,
            )

        return Signal(
            SignalType.HOLD,
            0.0,
            f"adaptive HOLD (buy={buy_norm:.2f}, sell={sell_norm:.2f})",
            meta,
        )
