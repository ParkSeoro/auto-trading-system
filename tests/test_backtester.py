from src.backtesting import Backtester
from src.risk.risk_manager import RiskManager
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy


def test_backtester_runs_vb(synthetic_ohlcv):
    bt = Backtester(
        strategy=VolatilityBreakoutStrategy(k=0.5),
        starting_capital=1_000_000,
    )
    result = bt.run(synthetic_ohlcv)
    assert result.starting_equity == 1_000_000
    assert result.final_equity > 0
    assert result.equity_curve is not None
    assert len(result.equity_curve) > 0
    # num_trades is realized pnl count, non-negative
    assert result.num_trades >= 0


def test_backtester_runs_rsi(synthetic_ohlcv):
    bt = Backtester(strategy=RSIMeanReversionStrategy(), starting_capital=1_000_000)
    result = bt.run(synthetic_ohlcv)
    # sanity: summary string contains key metrics
    summary = result.summary()
    assert "Total return" in summary
    assert "Max drawdown" in summary


def test_backtester_uses_risk_manager(synthetic_ohlcv):
    rm = RiskManager(capital=1_000_000, max_position_pct=0.5, risk_per_trade_pct=0.02)
    bt = Backtester(
        strategy=VolatilityBreakoutStrategy(k=0.3),
        starting_capital=1_000_000,
        risk=rm,
    )
    result = bt.run(synthetic_ohlcv)
    # No crashes, equity curve never NaN
    assert result.equity_curve.isna().sum() == 0


def test_backtester_raises_on_too_little_data():
    import pandas as pd
    df = pd.DataFrame({
        "open": [1, 2], "high": [2, 3], "low": [1, 1],
        "close": [2, 3], "volume": [1, 1],
    })
    bt = Backtester(strategy=VolatilityBreakoutStrategy(), starting_capital=1_000_000)
    try:
        bt.run(df)
    except ValueError as exc:
        assert "at least" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
