"""Simple project-wide logger."""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from config.settings import settings

os.environ["TZ"] = "Asia/Seoul"
try:
    time.tzset()
except AttributeError:
    pass

_LOG_FORMAT = "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def get_logger(name: str = "crypto_bot") -> logging.Logger:
    """Return a configured logger. Safe to call multiple times."""
    global _initialized

    logger = logging.getLogger(name)

    if not _initialized:
        root = logging.getLogger()
        root.setLevel(settings.log_level)

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # clear any default handlers (e.g., from pytest)
        for h in list(root.handlers):
            root.removeHandler(h)

        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)

        try:
            log_path: Path = settings.log_dir / "bot.log"
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # running in a restricted env - stream only
            pass

        # In-memory ring buffer so the web dashboard can show live activity.
        try:
            from src.utils.log_buffer import attach_to_root
            attach_to_root(level=root.level or logging.INFO)
        except Exception:
            # Best-effort — logging must never crash the app.
            pass

        _initialized = True

    return logger
