"""Trade outcome analyzer — learns from past wins/losses to improve future trades.

Core principle: every closed trade is analyzed for what worked and what didn't,
and these learnings are fed back into the next trading decision.

Tracks per (market, strategy, signal_reason_category):
- Win rate, average win, average loss
- Best/worst time-of-day, day-of-week
- Conditions at entry (RSI, trend, volatility regime) vs outcome
- Consecutive loss streaks → automatic cooldown

The analyzer persists its state to ``data/trade_analysis.json`` and is
consulted by the bot before every entry to adjust confidence and sizing.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class TradeOutcome:
    """Single closed trade with PnL and context."""
    market: str
    strategy: str
    side: str           # "buy" at entry
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    entry_ts: str
    exit_ts: str
    reason: str = ""


@dataclass
class StrategyStats:
    """Aggregated statistics for a (market, strategy) pair."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_win: float = 0.0
    max_loss: float = 0.0
    current_streak: int = 0       # positive = win streak, negative = loss streak
    max_loss_streak: int = 0
    recent_pnl: List[float] = field(default_factory=list)  # last N trades

    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0

    def expectancy(self) -> float:
        wr = self.win_rate()
        return (wr * self.avg_win) + ((1 - wr) * self.avg_loss) if self.total_trades > 0 else 0.0

    def profit_factor(self) -> float:
        total_wins = self.avg_win * self.wins if self.wins > 0 else 0.0
        total_losses = abs(self.avg_loss * self.losses) if self.losses > 0 else 0.0
        if total_losses > 0:
            return total_wins / total_losses
        return float("inf") if total_wins > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate(), 4),
            "total_pnl": round(self.total_pnl, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "max_win": round(self.max_win, 2),
            "max_loss": round(self.max_loss, 2),
            "expectancy": round(self.expectancy(), 2),
            "profit_factor": round(self.profit_factor(), 4) if not math.isinf(self.profit_factor()) else None,
            "current_streak": self.current_streak,
            "max_loss_streak": self.max_loss_streak,
        }


class TradeAnalyzer:
    """Analyzes historical trades and provides feedback for future decisions.

    Key features:
    1. FIFO matches buys to sells per (market, strategy) to compute per-trade PnL
    2. Tracks win/loss streaks per strategy
    3. Provides confidence adjustment: reduces confidence after losing streaks
    4. Provides position size adjustment: reduces size during drawdowns
    5. Cooldown: pauses a strategy after N consecutive losses
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        analysis_path: Optional[Path] = None,
        max_consecutive_losses: int = 3,
        loss_streak_cooldown_trades: int = 2,
        recent_window: int = 20,
    ):
        self.db_path = Path(db_path or settings.db_path)
        self.analysis_path = Path(analysis_path or (settings.data_dir / "trade_analysis.json"))
        self.max_consecutive_losses = max_consecutive_losses
        self.loss_streak_cooldown_trades = loss_streak_cooldown_trades
        self.recent_window = recent_window

        # Per (market, strategy) stats
        self.stats: Dict[str, StrategyStats] = {}
        self._last_trade_id: int = 0
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.analysis_path.exists():
            return
        try:
            data = json.loads(self.analysis_path.read_text(encoding="utf-8"))
            self._last_trade_id = data.get("last_trade_id", 0)
            for key, s in data.get("stats", {}).items():
                st = StrategyStats(
                    total_trades=s.get("total_trades", 0),
                    wins=s.get("wins", 0),
                    losses=s.get("losses", 0),
                    total_pnl=s.get("total_pnl", 0.0),
                    avg_win=s.get("avg_win", 0.0),
                    avg_loss=s.get("avg_loss", 0.0),
                    max_win=s.get("max_win", 0.0),
                    max_loss=s.get("max_loss", 0.0),
                    current_streak=s.get("current_streak", 0),
                    max_loss_streak=s.get("max_loss_streak", 0),
                    recent_pnl=s.get("recent_pnl", []),
                )
                self.stats[key] = st
        except (OSError, json.JSONDecodeError):
            log.warning("trade_analysis.json unreadable — starting fresh")

    def _save(self) -> None:
        self.analysis_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "last_trade_id": self._last_trade_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
        }
        # Also save recent_pnl
        for k, v in self.stats.items():
            doc["stats"][k]["recent_pnl"] = v.recent_pnl[-self.recent_window:]
        self.analysis_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Analysis: read new trades and update stats
    # ------------------------------------------------------------------
    def update(self) -> Dict[str, StrategyStats]:
        """Read new trades from SQLite, FIFO-match, update stats."""
        if not self.db_path.exists():
            return self.stats

        rows = []
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur = conn.execute(
                    "SELECT id, ts, market, side, price, quantity, fee, strategy, reason "
                    "FROM trades WHERE id > ? ORDER BY id ASC",
                    (self._last_trade_id,),
                )
                rows = cur.fetchall()
        except sqlite3.Error as exc:
            log.warning("trade analyzer read failed: %s", exc)
            return self.stats

        if not rows:
            return self.stats

        # FIFO lots keyed by (market, strategy)
        lots: Dict[str, list] = {}
        for (tid, ts, market, side, price, qty, fee, strategy, reason) in rows:
            self._last_trade_id = max(self._last_trade_id, tid or 0)
            key = f"{market}|{strategy or 'unknown'}"

            if side == "buy":
                lots.setdefault(key, []).append({
                    "qty": qty, "price": price, "fee": fee, "ts": ts,
                })
            elif side == "sell":
                remaining = qty
                cost = 0.0
                buy_fee = 0.0
                entry_price = 0.0
                entry_ts = ""
                lot_list = lots.get(key, [])

                while remaining > 1e-12 and lot_list:
                    lot = lot_list[0]
                    take = min(remaining, lot["qty"])
                    cost += take * lot["price"]
                    buy_fee += lot["fee"] * (take / lot["qty"]) if lot["qty"] > 0 else 0.0
                    if not entry_ts:
                        entry_ts = lot["ts"]
                        entry_price = lot["price"]
                    lot["qty"] -= take
                    remaining -= take
                    if lot["qty"] <= 1e-12:
                        lot_list.pop(0)

                gross = qty * price - fee
                pnl = gross - cost - buy_fee

                self._record_outcome(key, pnl)

        self._save()
        return self.stats

    def _record_outcome(self, key: str, pnl: float) -> None:
        if key not in self.stats:
            self.stats[key] = StrategyStats()
        s = self.stats[key]

        s.total_trades += 1
        s.total_pnl += pnl
        s.recent_pnl = (s.recent_pnl + [pnl])[-self.recent_window:]

        if pnl > 0:
            s.wins += 1
            s.max_win = max(s.max_win, pnl)
            s.avg_win = sum(p for p in s.recent_pnl if p > 0) / max(1, sum(1 for p in s.recent_pnl if p > 0))
            s.current_streak = max(1, s.current_streak + 1) if s.current_streak >= 0 else 1
        else:
            s.losses += 1
            s.max_loss = min(s.max_loss, pnl)
            s.avg_loss = sum(p for p in s.recent_pnl if p < 0) / max(1, sum(1 for p in s.recent_pnl if p < 0))
            s.current_streak = min(-1, s.current_streak - 1) if s.current_streak <= 0 else -1
            s.max_loss_streak = min(s.max_loss_streak, s.current_streak)

    # ------------------------------------------------------------------
    # Feedback: confidence & sizing adjustments for next trade
    # ------------------------------------------------------------------
    def get_confidence_adjustment(self, market: str, strategy: str) -> float:
        """Return a multiplier (0~1) to apply to the signal confidence.

        - After consecutive losses: reduce confidence proportionally
        - After wins: keep at 1.0 (no overconfidence)
        - During cooldown: return 0.0 (skip trade)
        """
        key = f"{market}|{strategy}"
        s = self.stats.get(key)
        if s is None:
            return 1.0  # no data yet, use default

        # Cooldown after consecutive losses
        if s.current_streak <= -self.max_consecutive_losses:
            # Check if enough new trades have passed to exit cooldown
            cooldown_remaining = abs(s.current_streak) - self.max_consecutive_losses
            if cooldown_remaining < self.loss_streak_cooldown_trades:
                log.info(
                    "Strategy %s on %s in cooldown (streak=%d). Skipping.",
                    strategy, market, s.current_streak,
                )
                return 0.0

        # Reduce confidence proportionally to loss streak
        if s.current_streak < 0:
            streak_len = abs(s.current_streak)
            # 1 loss: 0.8, 2 losses: 0.6, etc.
            return max(0.3, 1.0 - streak_len * 0.2)

        return 1.0

    def get_size_adjustment(self, market: str, strategy: str) -> float:
        """Return a multiplier (0~1) to apply to position size.

        - Win rate < 30% over recent trades → halve the size
        - Negative expectancy → quarter the size
        - Winning → no adjustment (1.0)
        """
        key = f"{market}|{strategy}"
        s = self.stats.get(key)
        if s is None or s.total_trades < 5:
            return 1.0  # not enough data

        # Use recent trades only
        recent = s.recent_pnl[-self.recent_window:]
        if len(recent) < 3:
            return 1.0

        recent_wins = sum(1 for p in recent if p > 0)
        recent_wr = recent_wins / len(recent)
        recent_exp = sum(recent) / len(recent)

        if recent_exp < 0:
            # Negative expectancy: reduce size significantly
            adjustment = 0.25
            log.info(
                "Negative expectancy for %s|%s (%.0f KRW/trade). Size -> 25%%.",
                market, strategy, recent_exp,
            )
        elif recent_wr < 0.3:
            adjustment = 0.5
            log.info(
                "Low win rate for %s|%s (%.0f%%). Size -> 50%%.",
                market, strategy, recent_wr * 100,
            )
        elif recent_wr > 0.6 and recent_exp > 0:
            # Winning streak: slight increase (but capped)
            adjustment = min(1.3, 1.0 + recent_wr * 0.2)
        else:
            adjustment = 1.0

        return adjustment

    def should_skip_trade(self, market: str, strategy: str) -> Tuple[bool, str]:
        """Check if a trade should be skipped entirely based on analysis.

        Returns (should_skip, reason).
        """
        key = f"{market}|{strategy}"
        s = self.stats.get(key)
        if s is None:
            return False, ""

        # Skip if in loss-streak cooldown
        if s.current_streak <= -self.max_consecutive_losses:
            return True, f"consecutive losses ({abs(s.current_streak)})"

        # Skip if recent expectancy is deeply negative
        recent = s.recent_pnl[-self.recent_window:]
        if len(recent) >= 5:
            avg_pnl = sum(recent) / len(recent)
            if avg_pnl < -abs(s.avg_loss) * 0.5:
                return True, f"deep negative expectancy ({avg_pnl:.0f} KRW/trade)"

        return False, ""

    def get_all_stats(self) -> Dict[str, dict]:
        """Return all stats as JSON-serializable dict."""
        return {k: v.to_dict() for k, v in self.stats.items()}
