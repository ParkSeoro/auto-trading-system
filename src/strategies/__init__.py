from src.strategies.base import Strategy, Signal, SignalType  # noqa: F401
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy  # noqa: F401
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy  # noqa: F401
from src.strategies.bollinger_breakout import BollingerBreakoutStrategy  # noqa: F401
from src.strategies.grid_trading import GridTradingStrategy  # noqa: F401
from src.strategies.ensemble import EnsembleStrategy  # noqa: F401


STRATEGY_REGISTRY = {
    "volatility_breakout": VolatilityBreakoutStrategy,
    "rsi_mean_reversion": RSIMeanReversionStrategy,
    "bollinger_breakout": BollingerBreakoutStrategy,
    "grid": GridTradingStrategy,
    "ensemble": EnsembleStrategy,
}


def get_strategy(name: str, **kwargs) -> Strategy:
    name = name.lower()
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY)}")
    return STRATEGY_REGISTRY[name](**kwargs)
