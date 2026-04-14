from datetime import datetime, timezone

import pandas as pd
import pytest

from src.risk.risk_manager import RiskManager


def test_atr_sized_entry(synthetic_ohlcv):
    rm = RiskManager(capital=1_000_000, risk_per_trade_pct=0.01)
    decision = rm.evaluate_entry(synthetic_ohlcv, confidence=1.0, available_krw=1_000_000)
    assert decision.approved
    assert decision.position_size_krw > 0
    assert decision.stop_loss < synthetic_ohlcv["close"].iloc[-1]
    assert decision.take_profit > synthetic_ohlcv["close"].iloc[-1]


def test_entry_rejected_when_halted(synthetic_ohlcv):
    rm = RiskManager(capital=1_000_000, max_daily_drawdown=0.01)
    # prime daily peak, then push equity down to trigger halt
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rm.update_equity(1_000_000, now=now)
    rm.update_equity(980_000, now=now)  # 2% drawdown > 1%
    assert rm.is_halted()
    decision = rm.evaluate_entry(synthetic_ohlcv, available_krw=1_000_000)
    assert not decision.approved
    assert "halt" in decision.reason.lower()


def test_flash_crash_trips(flash_crash_ohlcv):
    rm = RiskManager(capital=1_000_000, flash_crash_threshold=-0.08, cooldown_minutes=5)
    tripped = rm.check_flash_crash(flash_crash_ohlcv, lookback_bars=5)
    assert tripped
    assert rm.is_halted()


def test_min_order_rejection():
    rm = RiskManager(capital=1_000, max_position_pct=0.01, min_order_krw=5_000)
    # force small ATR -> small size
    df = pd.DataFrame({
        "open": [100] * 20, "high": [100.5] * 20, "low": [99.5] * 20,
        "close": [100] * 20, "volume": [1] * 20,
    })
    decision = rm.evaluate_entry(df, available_krw=1_000)
    assert not decision.approved
    assert "min order" in decision.reason.lower() or "size" in decision.reason.lower()


def test_stop_out_helper():
    pos = {"stop_loss": 100.0, "take_profit": 110.0}
    assert RiskManager.should_stop_out(99.0, pos)
    assert not RiskManager.should_stop_out(101.0, pos)
    assert RiskManager.should_take_profit(111.0, pos)
    assert not RiskManager.should_take_profit(105.0, pos)


def test_mdd_halt_resets_next_day(synthetic_ohlcv):
    rm = RiskManager(capital=1_000_000, max_daily_drawdown=0.03)
    day1 = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    day2 = datetime(2024, 1, 2, 0, 30, tzinfo=timezone.utc)
    rm.update_equity(1_000_000, now=day1)
    rm.update_equity(960_000, now=day1)  # -4% -> halt
    assert rm.is_halted()
    # New UTC day resets daily state
    rm.update_equity(960_000, now=day2)
    assert not rm.is_halted()
