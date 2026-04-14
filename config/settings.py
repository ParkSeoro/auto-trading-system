"""Centralized configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    upbit_access_key: Optional[str] = field(default_factory=lambda: os.getenv("UPBIT_ACCESS_KEY"))
    upbit_secret_key: Optional[str] = field(default_factory=lambda: os.getenv("UPBIT_SECRET_KEY"))

    trading_mode: str = field(default_factory=lambda: os.getenv("TRADING_MODE", "paper").lower())
    paper_capital: float = field(default_factory=lambda: _get_float("PAPER_CAPITAL", 1_000_000.0))

    max_position_pct: float = field(default_factory=lambda: _get_float("MAX_POSITION_PCT", 0.20))
    stop_loss_atr_mult: float = field(default_factory=lambda: _get_float("STOP_LOSS_ATR_MULT", 2.0))
    take_profit_atr_mult: float = field(default_factory=lambda: _get_float("TAKE_PROFIT_ATR_MULT", 3.0))
    max_daily_drawdown: float = field(default_factory=lambda: _get_float("MAX_DAILY_DRAWDOWN", 0.05))

    loop_interval: int = field(default_factory=lambda: _get_int("LOOP_INTERVAL", 60))

    discord_webhook_url: Optional[str] = field(default_factory=lambda: os.getenv("DISCORD_WEBHOOK_URL"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Upbit specifics
    upbit_fee_rate: float = 0.0005  # 0.05% taker (typical)
    upbit_min_order_krw: float = 5_000.0

    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "trades.sqlite3")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def is_live(self) -> bool:
        return self.trading_mode == "live"


settings = Settings()
settings.ensure_dirs()
