"""Tests for the trade outcome analyzer."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.ai.trade_analyzer import TradeAnalyzer, StrategyStats


def _create_trade_db(db_path: Path, trades: list) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, "
        "market TEXT, side TEXT, price REAL, quantity REAL, funds REAL, fee REAL, "
        "mode TEXT, strategy TEXT, reason TEXT, order_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO trades(ts,market,side,price,quantity,fee,strategy,funds,mode,reason,order_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        trades,
    )
    conn.commit()
    conn.close()


def _winning_trades():
    return [
        ("2024-01-01", "KRW-BTC", "buy", 50_000_000, 0.01, 250, "vb", 500000, "paper", "", "1"),
        ("2024-01-02", "KRW-BTC", "sell", 55_000_000, 0.01, 275, "vb", 550000, "paper", "", "2"),
        ("2024-01-03", "KRW-BTC", "buy", 55_000_000, 0.01, 275, "vb", 550000, "paper", "", "3"),
        ("2024-01-04", "KRW-BTC", "sell", 58_000_000, 0.01, 290, "vb", 580000, "paper", "", "4"),
    ]


def _losing_trades():
    return [
        ("2024-01-01", "KRW-BTC", "buy", 50_000_000, 0.01, 250, "rsi", 500000, "paper", "", "1"),
        ("2024-01-02", "KRW-BTC", "sell", 48_000_000, 0.01, 240, "rsi", 480000, "paper", "", "2"),
        ("2024-01-03", "KRW-BTC", "buy", 48_000_000, 0.01, 240, "rsi", 480000, "paper", "", "3"),
        ("2024-01-04", "KRW-BTC", "sell", 45_000_000, 0.01, 225, "rsi", 450000, "paper", "", "4"),
        ("2024-01-05", "KRW-BTC", "buy", 45_000_000, 0.01, 225, "rsi", 450000, "paper", "", "5"),
        ("2024-01-06", "KRW-BTC", "sell", 43_000_000, 0.01, 215, "rsi", 430000, "paper", "", "6"),
        ("2024-01-07", "KRW-BTC", "buy", 43_000_000, 0.01, 215, "rsi", 430000, "paper", "", "7"),
        ("2024-01-08", "KRW-BTC", "sell", 41_000_000, 0.01, 205, "rsi", 410000, "paper", "", "8"),
        ("2024-01-09", "KRW-BTC", "buy", 41_000_000, 0.01, 205, "rsi", 410000, "paper", "", "9"),
        ("2024-01-10", "KRW-BTC", "sell", 39_000_000, 0.01, 195, "rsi", 390000, "paper", "", "10"),
        ("2024-01-11", "KRW-BTC", "buy", 39_000_000, 0.01, 195, "rsi", 390000, "paper", "", "11"),
        ("2024-01-12", "KRW-BTC", "sell", 37_000_000, 0.01, 185, "rsi", 370000, "paper", "", "12"),
    ]


def test_analyzer_tracks_wins(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _winning_trades())
    analyzer = TradeAnalyzer(db_path=db, analysis_path=tmp_path / "analysis.json")
    stats = analyzer.update()
    key = "KRW-BTC|vb"
    assert key in stats
    assert stats[key].wins == 2
    assert stats[key].losses == 0
    assert stats[key].total_pnl > 0
    assert stats[key].current_streak > 0


def test_analyzer_tracks_losses(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _losing_trades())
    analyzer = TradeAnalyzer(
        db_path=db, analysis_path=tmp_path / "analysis.json",
        max_consecutive_losses=3,
    )
    stats = analyzer.update()
    key = "KRW-BTC|rsi"
    assert key in stats
    assert stats[key].losses == 6
    assert stats[key].current_streak <= -3


def test_confidence_adjustment_after_losses(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _losing_trades())
    analyzer = TradeAnalyzer(
        db_path=db, analysis_path=tmp_path / "analysis.json",
        max_consecutive_losses=3,
        loss_streak_cooldown_trades=10,  # long cooldown so 6 losses triggers it
    )
    analyzer.update()
    # Should be in cooldown after 6 consecutive losses (> max_consecutive_losses=3)
    adj = analyzer.get_confidence_adjustment("KRW-BTC", "rsi")
    assert adj == 0.0  # cooldown


def test_confidence_adjustment_no_data(tmp_path):
    analyzer = TradeAnalyzer(
        db_path=tmp_path / "missing.sqlite",
        analysis_path=tmp_path / "analysis.json",
    )
    adj = analyzer.get_confidence_adjustment("KRW-BTC", "vb")
    assert adj == 1.0  # no data, full confidence


def test_size_adjustment_negative_expectancy(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _losing_trades())
    analyzer = TradeAnalyzer(
        db_path=db, analysis_path=tmp_path / "analysis.json",
        max_consecutive_losses=10,  # don't trigger cooldown
    )
    analyzer.update()
    adj = analyzer.get_size_adjustment("KRW-BTC", "rsi")
    assert adj < 1.0  # reduced due to losses


def test_should_skip_trade_on_loss_streak(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _losing_trades())
    analyzer = TradeAnalyzer(
        db_path=db, analysis_path=tmp_path / "analysis.json",
        max_consecutive_losses=3,
    )
    analyzer.update()
    skip, reason = analyzer.should_skip_trade("KRW-BTC", "rsi")
    assert skip
    assert "consecutive" in reason


def test_persistence_roundtrip(tmp_path):
    db = tmp_path / "trades.sqlite"
    _create_trade_db(db, _winning_trades())
    analysis_path = tmp_path / "analysis.json"

    analyzer1 = TradeAnalyzer(db_path=db, analysis_path=analysis_path)
    analyzer1.update()
    assert analysis_path.exists()

    # Load from saved state
    analyzer2 = TradeAnalyzer(db_path=db, analysis_path=analysis_path)
    key = "KRW-BTC|vb"
    assert key in analyzer2.stats
    assert analyzer2.stats[key].total_trades == 2


def test_strategy_stats_metrics():
    s = StrategyStats(
        total_trades=10, wins=7, losses=3,
        total_pnl=50000, avg_win=10000, avg_loss=-5000,
        current_streak=2, max_loss_streak=-2,
    )
    assert s.win_rate() == 0.7
    assert s.expectancy() == 0.7 * 10000 + 0.3 * (-5000)
    assert s.profit_factor() == (10000 * 7) / (5000 * 3)
    d = s.to_dict()
    assert d["win_rate"] == 0.7
    assert d["total_trades"] == 10
