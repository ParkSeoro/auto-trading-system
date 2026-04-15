"""Exchange adapters."""
from src.exchanges.base import Exchange, Candle, Order, OrderSide, OrderType, Balance  # noqa: F401
from src.exchanges.bithumb import BithumbExchange  # noqa: F401
from src.exchanges.upbit import UpbitExchange  # noqa: F401


def build_exchange(name: str = None) -> Exchange:
    """Build an exchange client based on config (or explicit name)."""
    from config.settings import settings

    active = (name or settings.exchange or "bithumb").lower()
    if active == "bithumb":
        return BithumbExchange(
            api_key=settings.bithumb_api_key,
            secret_key=settings.bithumb_secret_key,
        )
    if active == "upbit":
        return UpbitExchange(
            access_key=settings.upbit_access_key,
            secret_key=settings.upbit_secret_key,
        )
    raise ValueError(f"Unknown exchange: {active}. Use 'bithumb' or 'upbit'.")
