"""Optional notification sender (Discord webhook)."""
from __future__ import annotations

from typing import Optional

import requests

from config.settings import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


def send_alert(message: str, webhook_url: Optional[str] = None, timeout: float = 5.0) -> bool:
    """Send a lightweight alert to a Discord webhook. Fails silently."""
    url = webhook_url or settings.discord_webhook_url
    if not url:
        return False
    try:
        response = requests.post(url, json={"content": message[:1800]}, timeout=timeout)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:  # pragma: no cover - network
        log.warning("Notifier failed: %s", exc)
        return False
