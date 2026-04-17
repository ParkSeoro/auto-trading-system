"""Thread-safe bot lifecycle manager for the web dashboard.

The dashboard never blocks on the bot's 24/7 loop; instead it spawns
the bot in a daemon thread and keeps a reference so the UI can query
status or send stop/start commands.

Only one bot runs at a time. Starting a new bot while one is running
stops the previous one first.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from src.bot import TradingBot, build_bot
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BotStatus:
    running: bool = False
    mode: str = "paper"
    exchange: str = ""
    markets: List[str] = field(default_factory=list)
    strategy: str = ""
    timeframe: str = "1d"
    started_at: Optional[str] = None
    error: Optional[str] = None
    auto_discover: bool = False

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "mode": self.mode,
            "exchange": self.exchange,
            "markets": self.markets,
            "strategy": self.strategy,
            "timeframe": self.timeframe,
            "started_at": self.started_at,
            "error": self.error,
            "auto_discover": self.auto_discover,
        }


class BotManager:
    """Singleton-ish manager. One bot at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bot: Optional[TradingBot] = None
        self._thread: Optional[threading.Thread] = None
        self._status = BotStatus()

    # ------------------------------------------------------------------
    def status(self) -> BotStatus:
        with self._lock:
            # thread might have died silently
            if self._status.running and (self._thread is None or not self._thread.is_alive()):
                self._status.running = False
            # Reflect live auto-discovered markets
            if self._bot is not None and self._status.running:
                self._status.markets = list(self._bot._active_markets)
            return self._status

    def current_bot(self) -> Optional[TradingBot]:
        with self._lock:
            return self._bot

    # ------------------------------------------------------------------
    def start(
        self,
        *,
        mode: str,
        markets: List[str],
        strategy: str,
        timeframe: str = "1d",
        exchange: Optional[str] = None,
        auto_discover: bool = False,
        max_auto_markets: int = 10,
    ) -> BotStatus:
        with self._lock:
            if self._status.running:
                raise RuntimeError("Bot is already running. Stop it first.")
            is_auto = auto_discover or not markets or markets == ["AUTO"]
            try:
                bot = build_bot(
                    mode=mode,
                    markets=markets if not is_auto else [],
                    strategy_name=strategy,
                    timeframe=timeframe,
                    exchange_name=exchange,
                    auto_discover=is_auto,
                    max_auto_markets=max_auto_markets,
                )
            except Exception as exc:
                self._status.error = f"build failed: {exc}"
                log.exception("bot build failed")
                raise

            self._bot = bot
            self._status = BotStatus(
                running=True,
                mode=mode,
                exchange=bot.exchange.name,
                markets=list(markets) if not is_auto else [],
                strategy=strategy,
                timeframe=timeframe,
                started_at=datetime.now(timezone.utc).isoformat(),
                auto_discover=is_auto,
            )

            def _runner():
                try:
                    bot.run()
                except Exception as exc:  # pragma: no cover - runtime
                    log.exception("bot crashed: %s", exc)
                    with self._lock:
                        self._status.error = str(exc)
                finally:
                    with self._lock:
                        self._status.running = False

            t = threading.Thread(target=_runner, name="bot-loop", daemon=True)
            self._thread = t
            t.start()
            return self._status

    def stop(self, timeout: float = 5.0) -> BotStatus:
        with self._lock:
            bot = self._bot
            thread = self._thread
        if bot is not None:
            bot.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            self._status.running = False
            self._bot = None
            self._thread = None
            return self._status
