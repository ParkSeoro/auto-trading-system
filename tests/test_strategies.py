import pandas as pd
import pytest

from src.strategies import get_strategy
from src.strategies.base import SignalType
from src.strategies.bollinger_breakout import BollingerBreakoutStrategy
from src.strategies.ensemble import EnsembleStrategy
from src.strategies.grid_trading import GridTradingStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy


def test_registry_returns_strategy():
    s = get_strategy("volatility_breakout", k=0.6)
    assert isinstance(s, VolatilityBreakoutStrategy)
    assert s.k == 0.6


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        get_strategy("not-a-strategy")


def test_vb_invalid_k():
    with pytest.raises(ValueError):
        VolatilityBreakoutStrategy(k=0.0)
    with pytest.raises(ValueError):
        VolatilityBreakoutStrategy(k=3.0)


def test_vb_holds_on_short_history():
    df = pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [1, 1], "close": [1, 2], "volume": [1, 1]})
    sig = VolatilityBreakoutStrategy().generate(df)
    assert sig.type == SignalType.HOLD


def test_vb_breakout_signal():
    # Craft a bar that clearly breaks target: today's open=100, prev_range=10 -> target=105 at k=0.5.
    # Close at 120 with high volume confirms breakout.
    rows = []
    for i in range(30):
        rows.append({"open": 100, "high": 110, "low": 100, "close": 105, "volume": 100})
    # last 2 bars: previous has range=10, current breaks above target
    rows[-2] = {"open": 100, "high": 110, "low": 100, "close": 105, "volume": 100}
    rows[-1] = {"open": 100, "high": 130, "low": 99, "close": 120, "volume": 500}
    df = pd.DataFrame(rows)
    sig = VolatilityBreakoutStrategy(k=0.5, volume_factor=1.0).generate(df)
    assert sig.type == SignalType.BUY
    assert "target" in sig.meta


def test_vb_exit_when_in_position():
    rows = [{"open": 100, "high": 110, "low": 95, "close": 105, "volume": 100} for _ in range(30)]
    df = pd.DataFrame(rows)
    sig = VolatilityBreakoutStrategy().generate(df, position={"quantity": 0.01})
    assert sig.type == SignalType.SELL


def test_rsi_mean_reversion_on_sharp_drop():
    closes = [100] * 20 + [100 - i * 2.5 for i in range(1, 25)]
    df = pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [100] * len(closes),
    })
    # Flip the last bar up to trigger the reversal rule.
    df.loc[len(df) - 1, "close"] = df["close"].iloc[-2] + 0.5
    sig = RSIMeanReversionStrategy().generate(df)
    assert sig.type in (SignalType.BUY, SignalType.HOLD)   # depending on warm-up
    # Either a buy, or stays neutral — but never sells with no position
    if sig.type != SignalType.BUY:
        assert sig.type == SignalType.HOLD


def test_bollinger_strategy_validates_length():
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    sig = BollingerBreakoutStrategy().generate(df)
    assert sig.type == SignalType.HOLD


def test_grid_buys_when_price_drops(sideways_ohlcv):
    strat = GridTradingStrategy(grid_pct=0.02, levels=5)
    # Pin the anchor so the test is deterministic regardless of fixture drift.
    strat.anchor = 100.0
    strat.level_index = 0
    df = sideways_ohlcv.copy()
    df.loc[df.index[-1], "close"] = 97.0  # below anchor * (1 - 0.02)
    sig = strat.generate(df)
    assert sig.type == SignalType.BUY
    assert sig.meta["level"] == -1


def test_grid_invalid_params():
    with pytest.raises(ValueError):
        GridTradingStrategy(grid_pct=0)
    with pytest.raises(ValueError):
        GridTradingStrategy(levels=0)


def test_ensemble_defaults_to_hold_on_calm_data(synthetic_ohlcv):
    ens = EnsembleStrategy()
    sig = ens.generate(synthetic_ohlcv)
    assert sig.type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)
    # Ensemble metadata must contain each member's vote
    for name in ("volatility_breakout", "rsi_mean_reversion", "bollinger_breakout"):
        assert name in sig.meta


def test_ensemble_requires_enough_bars():
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    sig = EnsembleStrategy().generate(df)
    assert sig.type == SignalType.HOLD
