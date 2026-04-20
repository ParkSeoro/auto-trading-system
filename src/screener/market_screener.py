"""Market screener — automated asset selection based on quantitative criteria.

Scores each market on four dimensions:
1. **Volume** — 24h traded volume relative to recent average (liquidity)
2. **Volatility** — ATR% suitable for swing trading (not too flat, not too wild)
3. **Trend** — Price above key moving averages with positive momentum
4. **Risk-adjusted** — Recent Sharpe-like metric on hourly returns

Markets that score above the threshold are considered "tradeable".
Markets in a clear downtrend or with insufficient volume are filtered out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.indicators import atr, ema, rsi, sma
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class MarketScore:
    market: str
    volume_score: float = 0.0       # 0~1: liquidity
    volatility_score: float = 0.0   # 0~1: tradeable volatility
    trend_score: float = 0.0        # 0~1: uptrend strength
    momentum_score: float = 0.0     # 0~1: recent momentum
    total_score: float = 0.0
    tradeable: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "volume_score": round(self.volume_score, 3),
            "volatility_score": round(self.volatility_score, 3),
            "trend_score": round(self.trend_score, 3),
            "momentum_score": round(self.momentum_score, 3),
            "total_score": round(self.total_score, 3),
            "tradeable": self.tradeable,
            "reasons": self.reasons,
        }


class MarketScreener:
    """Score and rank markets for automated selection.

    Parameters
    ----------
    min_volume_ratio : float
        Minimum ratio of current volume to 20-bar average to consider liquid.
    atr_pct_min : float
        Minimum ATR as % of price — markets below this are too flat.
    atr_pct_max : float
        Maximum ATR as % of price — markets above this are too volatile/risky.
    trend_ema_short : int
        Short EMA period for trend detection.
    trend_ema_long : int
        Long EMA period for trend detection.
    min_score : float
        Minimum total score (0~1) to be considered tradeable.
    weights : dict
        Weight for each score dimension.
    """

    def __init__(
        self,
        min_volume_ratio: float = 0.8,
        atr_pct_min: float = 0.005,    # 0.5% minimum volatility
        atr_pct_max: float = 0.15,     # 15% maximum volatility
        trend_ema_short: int = 10,
        trend_ema_long: int = 50,
        min_score: float = 0.4,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.min_volume_ratio = min_volume_ratio
        self.atr_pct_min = atr_pct_min
        self.atr_pct_max = atr_pct_max
        self.trend_ema_short = trend_ema_short
        self.trend_ema_long = trend_ema_long
        self.min_score = min_score
        self.weights = weights or {
            "volume": 0.20,
            "volatility": 0.25,
            "trend": 0.30,
            "momentum": 0.25,
        }

    def score_market(self, df: pd.DataFrame, market: str = "") -> MarketScore:
        """Score a single market from its OHLCV dataframe."""
        result = MarketScore(market=market)

        if df is None or len(df) < 60:
            result.reasons.append("insufficient data")
            return result

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        current_price = float(close.iloc[-1])

        if current_price <= 0:
            result.reasons.append("invalid price")
            return result

        # --- Volume score ---
        vol_avg = float(volume.iloc[-21:-1].mean()) if len(volume) > 21 else float(volume.mean())
        vol_current = float(volume.iloc[-1])
        if vol_avg > 0:
            vol_ratio = vol_current / vol_avg
            result.volume_score = min(1.0, vol_ratio / 2.0)
            if vol_ratio < self.min_volume_ratio:
                result.volume_score = max(0.05, result.volume_score)
                result.reasons.append(f"low volume ({vol_ratio:.2f}x avg)")
        else:
            result.reasons.append("no volume data")

        # --- Volatility score ---
        atr14 = atr(high, low, close, 14)
        atr_val = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else 0.0
        atr_pct = atr_val / current_price if current_price > 0 else 0.0

        if atr_pct < self.atr_pct_min:
            result.volatility_score = 0.1
            result.reasons.append(f"too flat (ATR%={atr_pct:.3f})")
        elif atr_pct > self.atr_pct_max:
            result.volatility_score = 0.1
            result.reasons.append(f"too volatile (ATR%={atr_pct:.3f})")
        else:
            # Sweet spot: score peaks at middle of the range
            mid = (self.atr_pct_min + self.atr_pct_max) / 2
            span = (self.atr_pct_max - self.atr_pct_min) / 2
            result.volatility_score = max(0.2, 1.0 - abs(atr_pct - mid) / span)

        # --- Trend score ---
        ema_s = ema(close, self.trend_ema_short)
        ema_l = ema(close, self.trend_ema_long)
        sma_20 = sma(close, 20)

        ema_s_val = float(ema_s.iloc[-1]) if not pd.isna(ema_s.iloc[-1]) else 0.0
        ema_l_val = float(ema_l.iloc[-1]) if not pd.isna(ema_l.iloc[-1]) else 0.0
        sma_20_val = float(sma_20.iloc[-1]) if not pd.isna(sma_20.iloc[-1]) else 0.0

        trend_pts = 0.0
        if current_price > ema_s_val > 0:
            trend_pts += 0.3
        if ema_s_val > ema_l_val > 0:
            trend_pts += 0.4
            result.reasons.append("uptrend (EMA cross)")
        if current_price > sma_20_val > 0:
            trend_pts += 0.3

        # Penalise downtrend
        if ema_s_val > 0 and ema_l_val > 0 and ema_s_val < ema_l_val * 0.97:
            trend_pts = max(0.0, trend_pts - 0.4)
            result.reasons.append("downtrend detected")

        result.trend_score = min(1.0, trend_pts)

        # --- Momentum score (RSI + recent returns) ---
        rsi14 = rsi(close, 14)
        rsi_val = float(rsi14.iloc[-1]) if not pd.isna(rsi14.iloc[-1]) else 50.0

        # RSI in 40-65 is ideal for entries (not overbought, not oversold)
        if 40 <= rsi_val <= 65:
            rsi_score = 1.0
        elif 30 <= rsi_val < 40 or 65 < rsi_val <= 75:
            rsi_score = 0.6
        else:
            rsi_score = 0.2
            if rsi_val > 75:
                result.reasons.append(f"overbought RSI={rsi_val:.0f}")
            elif rsi_val < 30:
                result.reasons.append(f"oversold RSI={rsi_val:.0f}")

        # Recent 5-bar return
        if len(close) > 5:
            ret_5 = (float(close.iloc[-1]) / float(close.iloc[-6])) - 1.0
            ret_score = min(1.0, max(0.0, (ret_5 + 0.05) / 0.10))  # -5%->0, +5%->1
        else:
            ret_score = 0.5

        result.momentum_score = 0.5 * rsi_score + 0.5 * ret_score

        # --- Total weighted score ---
        w = self.weights
        result.total_score = (
            w.get("volume", 0.25) * result.volume_score
            + w.get("volatility", 0.25) * result.volatility_score
            + w.get("trend", 0.25) * result.trend_score
            + w.get("momentum", 0.25) * result.momentum_score
        )

        result.tradeable = result.total_score >= self.min_score
        if not result.tradeable and not result.reasons:
            result.reasons.append(f"score too low ({result.total_score:.2f})")

        return result

    def rank_markets(
        self, market_data: Dict[str, pd.DataFrame]
    ) -> List[MarketScore]:
        """Score and rank multiple markets, returning sorted by total_score descending."""
        scores = []
        for market, df in market_data.items():
            score = self.score_market(df, market=market)
            scores.append(score)

        scores.sort(key=lambda s: s.total_score, reverse=True)
        return scores

    def select_tradeable(
        self, market_data: Dict[str, pd.DataFrame], max_markets: int = 5
    ) -> List[str]:
        """Return the top-N tradeable markets sorted by score."""
        ranked = self.rank_markets(market_data)
        tradeable = [s.market for s in ranked if s.tradeable]
        selected = tradeable[:max_markets]
        log.info(
            "Screener selected %d/%d markets: %s",
            len(selected), len(market_data), selected,
        )
        return selected

    def auto_discover(
        self,
        exchange,
        max_markets: int = 10,
        timeframe: str = "1d",
        count: int = 100,
        exclude: Optional[List[str]] = None,
    ) -> Tuple[List[str], List[MarketScore]]:
        """Discover all markets from exchange, score them, return top-N.

        Returns (selected_markets, all_scores) so callers can inspect why
        markets were selected or rejected.
        """
        exclude_set = set(exclude or [])
        try:
            all_markets = exchange.list_markets()
        except Exception as exc:
            log.warning("Failed to list markets: %s", exc)
            return [], []

        log.info("Auto-discovery: found %d markets on %s", len(all_markets), exchange.name)

        market_data: Dict[str, pd.DataFrame] = {}
        from src.data import candles_to_dataframe

        for market in all_markets:
            if market in exclude_set:
                continue
            try:
                candles = exchange.fetch_ohlcv(market, timeframe=timeframe, count=count)
                df = candles_to_dataframe(candles)
                if not df.empty and len(df) >= 60:
                    market_data[market] = df
            except Exception as exc:
                log.debug("Skipping %s: %s", market, exc)

        log.info("Auto-discovery: fetched OHLCV for %d/%d markets", len(market_data), len(all_markets))

        all_scores = self.rank_markets(market_data)
        tradeable = [s.market for s in all_scores if s.tradeable]
        selected = tradeable[:max_markets]

        log.info(
            "Auto-discovery complete: %d tradeable, selected top %d: %s",
            len(tradeable), len(selected), selected,
        )
        return selected, all_scores
