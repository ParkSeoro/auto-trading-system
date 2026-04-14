"""SQLite trade log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    market      TEXT    NOT NULL,
    side        TEXT    NOT NULL,
    price       REAL    NOT NULL,
    quantity    REAL    NOT NULL,
    funds       REAL    NOT NULL,
    fee         REAL    NOT NULL,
    mode        TEXT    NOT NULL,
    strategy    TEXT,
    reason      TEXT,
    order_id    TEXT
);

CREATE TABLE IF NOT EXISTS equity_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    NOT NULL,
    equity    REAL    NOT NULL,
    cash      REAL    NOT NULL,
    mode      TEXT    NOT NULL
);
"""


class TradeLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def log_trade(
        self,
        *,
        market: str,
        side: str,
        price: float,
        quantity: float,
        funds: float,
        fee: float,
        mode: str,
        strategy: Optional[str] = None,
        reason: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO trades(ts,market,side,price,quantity,funds,fee,mode,strategy,reason,order_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    market, side, price, quantity, funds, fee, mode,
                    strategy, reason, order_id,
                ),
            )

    def log_equity(self, equity: float, cash: float, mode: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO equity_history(ts,equity,cash,mode) VALUES (?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), equity, cash, mode),
            )
