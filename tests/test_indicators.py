import numpy as np
import pandas as pd
import pytest

from src.indicators import atr, bollinger_bands, ema, macd, obv, rsi, sma, true_range, vwap


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    result = sma(s, 3)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[-1] == pytest.approx(4.0)


def test_ema_smoothing():
    s = pd.Series([1.0] * 10)
    assert ema(s, 3).iloc[-1] == pytest.approx(1.0)


def test_rsi_range_bounds(synthetic_ohlcv):
    r = rsi(synthetic_ohlcv["close"], period=14)
    valid = r.dropna()
    assert len(valid) > 100
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_rsi_all_up_moves_rsi_near_100():
    series = pd.Series(np.linspace(1, 100, 60))
    r = rsi(series, period=14)
    assert r.iloc[-1] > 90


def test_rsi_all_down_moves_rsi_near_0():
    series = pd.Series(np.linspace(100, 1, 60))
    r = rsi(series, period=14)
    assert r.iloc[-1] < 10


def test_macd_shape(synthetic_ohlcv):
    macd_line, signal_line, hist = macd(synthetic_ohlcv["close"])
    assert len(macd_line) == len(synthetic_ohlcv)
    assert len(signal_line) == len(synthetic_ohlcv)
    # hist = macd - signal
    tail = (macd_line - signal_line).dropna().tail(20)
    hist_tail = hist.dropna().tail(20)
    pd.testing.assert_series_equal(tail, hist_tail, check_names=False)


def test_bollinger_bands_order(synthetic_ohlcv):
    upper, mid, lower = bollinger_bands(synthetic_ohlcv["close"])
    valid = upper.dropna().index
    for i in valid:
        assert upper.loc[i] >= mid.loc[i] >= lower.loc[i]


def test_true_range_non_negative(synthetic_ohlcv):
    tr = true_range(synthetic_ohlcv["high"], synthetic_ohlcv["low"], synthetic_ohlcv["close"])
    assert (tr.dropna() >= 0).all()


def test_atr_positive(synthetic_ohlcv):
    a = atr(synthetic_ohlcv["high"], synthetic_ohlcv["low"], synthetic_ohlcv["close"])
    valid = a.dropna()
    assert len(valid) > 0
    assert (valid > 0).all()


def test_obv_monotone_when_price_only_rises():
    close = pd.Series([1, 2, 3, 4, 5], dtype=float)
    volume = pd.Series([10, 10, 10, 10, 10], dtype=float)
    series = obv(close, volume)
    # First entry = 0 because diff is NaN; subsequent values add volume every up-move
    assert series.iloc[-1] == 40


def test_vwap_returns_series(synthetic_ohlcv):
    v = vwap(synthetic_ohlcv)
    assert len(v) == len(synthetic_ohlcv)
    assert v.iloc[-1] > 0
