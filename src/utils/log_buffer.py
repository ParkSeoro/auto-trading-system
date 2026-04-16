"""In-memory circular log buffer for the web dashboard.

Attaches as a standard :class:`logging.Handler` so every ``get_logger(...)``
call automatically streams into the buffer. Thread-safe via deque + lock.

The web layer reads from the singleton ``LOG_BUFFER`` to power the activity
feed — letting the user *see* what the bot is doing in real time without
having to open a terminal.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List


class RingLogHandler(logging.Handler):
    """Keep the last ``capacity`` log records in a ring buffer."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.capacity = capacity
        self._buf: Deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - logging infra
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        entry = {
            "seq": 0,
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": msg,
        }
        with self._lock:
            self._seq += 1
            entry["seq"] = self._seq
            self._buf.append(entry)

    def tail(self, limit: int = 100, since_seq: int = 0) -> List[dict]:
        with self._lock:
            data = list(self._buf)
        if since_seq > 0:
            data = [e for e in data if e["seq"] > since_seq]
        if limit > 0:
            data = data[-limit:]
        return data

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._seq = 0


# Module-level singleton attached lazily to the root logger.
LOG_BUFFER = RingLogHandler(capacity=500)


def attach_to_root(level: int = logging.INFO) -> RingLogHandler:
    """Attach the singleton handler to the root logger exactly once."""
    root = logging.getLogger()
    if LOG_BUFFER not in root.handlers:
        LOG_BUFFER.setLevel(level)
        LOG_BUFFER.setFormatter(
            logging.Formatter("%(name)s: %(message)s")
        )
        root.addHandler(LOG_BUFFER)
    return LOG_BUFFER
