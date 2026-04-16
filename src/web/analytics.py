"""Performance analytics computed from the SQLite trade log.

Pure read-only helpers — safe to call from any request handler.
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import settings


# ----------------------------------------------------------------------
# Low-level readers
# ----------------------------------------------------------------------
def _rows(sql: str, params: tuple = ()) -> List[dict]:
    path = settings.db_path
    if not Path(path).exists():
        return []
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


# ----------------------------------------------------------------------
# FIFO PnL decomposition
# ----------------------------------------------------------------------
def compute_realised_pnl() -> tuple[List[float], Dict[str, float]]:
    """Walk the trade log, FIFO-match buys against sells, return per-trade PnL
    list and per-strategy realised PnL.
    """
    trades = _rows(
        "SELECT market, side, price, quantity, fee, strategy "
        "FROM trades ORDER BY id ASC"
    )
    lots: Dict[tuple, list] = {}
    per_trade: List[float] = []
    per_strat: Dict[str, float] = {}

    for t in trades:
        key = (t["market"], t["strategy"] or "unknown")
        if t["side"] == "buy":
            lots.setdefault(key, []).append(
                [float(t["quantity"]), float(t["price"]), float(t["fee"])]
            )
        else:
            rem = float(t["quantity"])
            gross = rem * float(t["price"]) - float(t["fee"])
            cost = 0.0
            buy_fee = 0.0
            lot_list = lots.get(key, [])
            while rem > 1e-12 and lot_list:
                lot_qty, lot_price, lot_fee = lot_list[0]
                take = min(rem, lot_qty)
                cost += take * lot_price
                buy_fee += lot_fee * (take / lot_qty) if lot_qty > 0 else 0.0
                lot_qty -= take
                rem -= take
                if lot_qty <= 1e-12:
                    lot_list.pop(0)
                else:
                    lot_list[0][0] = lot_qty
            pnl = gross - cost - buy_fee
            per_trade.append(pnl)
            per_strat[t["strategy"] or "unknown"] = (
                per_strat.get(t["strategy"] or "unknown", 0.0) + pnl
            )
    return per_trade, per_strat


# ----------------------------------------------------------------------
# Equity-derived stats
# ----------------------------------------------------------------------
def _equity_series() -> List[float]:
    rows = _rows(
        "SELECT equity FROM equity_history ORDER BY id ASC"
    )
    return [float(r["equity"]) for r in rows if r["equity"] is not None]


def compute_analytics() -> dict:
    """Return the full KPI bundle used by the dashboard."""
    equities = _equity_series()
    per_trade, per_strat = compute_realised_pnl()

    trades_count = len(per_trade)
    wins = [p for p in per_trade if p > 0]
    losses = [p for p in per_trade if p < 0]
    win_rate = (len(wins) / trades_count) if trades_count else 0.0

    total_loss = abs(sum(losses))
    if total_loss > 0:
        profit_factor = sum(wins) / total_loss
    elif wins:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    starting = equities[0] if equities else settings.paper_capital
    current = equities[-1] if equities else starting
    total_return = (current / starting - 1) if starting > 0 else 0.0

    # Rolling drawdown
    peak = starting
    max_dd = 0.0
    current_dd = 0.0
    for v in equities:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            current_dd = dd
            max_dd = max(max_dd, dd)

    # Bar-return Sharpe
    if len(equities) > 2:
        rets = [(b - a) / a for a, b in zip(equities, equities[1:]) if a > 0]
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
            std = math.sqrt(var)
            sharpe = (mean / std * math.sqrt(365)) if std > 0 else 0.0
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Safe JSON: replace infinities
    def _safe(v: float) -> Optional[float]:
        return None if (v is None or math.isinf(v) or math.isnan(v)) else float(v)

    return {
        "trades": trades_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _safe(win_rate),
        "profit_factor": _safe(profit_factor),
        "avg_win": _safe(avg_win),
        "avg_loss": _safe(avg_loss),
        "expectancy": _safe(expectancy),
        "total_realised_pnl": _safe(sum(per_trade)),
        "per_strategy_pnl": {k: _safe(v) for k, v in per_strat.items()},
        "starting_equity": _safe(starting),
        "current_equity": _safe(current),
        "total_return": _safe(total_return),
        "current_drawdown": _safe(current_dd),
        "max_drawdown": _safe(max_dd),
        "sharpe": _safe(sharpe),
    }
