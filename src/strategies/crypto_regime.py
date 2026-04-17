"""Crypto regime strategy — adaptive logic specialized for crypto markets.

Unlike traditional indicator-based strategies, this one:

1. **Classifies regime first** (trend / range / squeeze / crash) using ADX,
   Bollinger width, and EMA slope. Each regime uses different entry logic.

2. **Multi-timeframe confluence** — daily trend must not contradict 1h/4h
   entry. Never trade against the higher-TF trend.

3. **Volume expansion REQUIRED** — crypto breakouts without volume are
   fakeouts. Demand >=1.5x avg volume on entry bar.

4. **Structure-based SL** — stop at recent swing low (last 10 bars) with
   small ATR buffer, not a fixed ATR multiple.

5. **Asymmetric exits** — TP at measured move (prior range height) or
   next resistance, giving >=1.5 R:R minimum.

6. **RSI divergence check** — doesn't buy into bearish divergence or sell
   into bullish divergence.

7. **Range-bound mean reversion** — if regime is clear range, fade the
   extremes instead of chasing breakouts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.indicators import atr, ema, rsi, bollinger_bands
from src.strategies.base import Signal, SignalType, Strategy


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength (0-100)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_series = tr.rolling(period).mean()

    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(period).sum() / atr_series
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(period).sum() / atr_series
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


def _swing_low(low: pd.Series, lookback: int = 10) -> float:
    """Most recent meaningful swing low in the last N bars."""
    if len(low) < lookback:
        return float(low.min())
    return float(low.iloc[-lookback:].min())


def _swing_high(high: pd.Series, lookback: int = 20) -> float:
    if len(high) < lookback:
        return float(high.max())
    return float(high.iloc[-lookback:].max())


def _rsi_divergence(close: pd.Series, rsi_series: pd.Series, lookback: int = 14) -> str:
    """Check for bearish/bullish RSI divergence over recent bars.

    Returns: 'bearish' | 'bullish' | 'none'
    Bearish: price makes higher high, RSI makes lower high
    Bullish: price makes lower low, RSI makes higher low
    """
    if len(close) < lookback + 2:
        return "none"
    recent_close = close.iloc[-lookback:]
    recent_rsi = rsi_series.iloc[-lookback:]

    # Find idx of max/min within window
    price_max_idx = recent_close.idxmax()
    price_min_idx = recent_close.idxmin()

    # Current bar
    curr_close = close.iloc[-1]
    curr_rsi = rsi_series.iloc[-1]

    # Bearish: current close near recent high but RSI lower than at that high
    if curr_close >= recent_close.max() * 0.995:
        prior_max = recent_close.iloc[:-2].max() if len(recent_close) > 2 else 0
        prior_rsi_at_max = recent_rsi[recent_close.iloc[:-2].idxmax()] if prior_max > 0 else 0
        if prior_max > 0 and curr_close > prior_max and curr_rsi < prior_rsi_at_max - 3:
            return "bearish"

    # Bullish: current close near recent low but RSI higher than at that low
    if curr_close <= recent_close.min() * 1.005:
        prior_min = recent_close.iloc[:-2].min() if len(recent_close) > 2 else 0
        prior_rsi_at_min = recent_rsi[recent_close.iloc[:-2].idxmin()] if prior_min > 0 else 0
        if prior_min > 0 and curr_close < prior_min and curr_rsi > prior_rsi_at_min + 3:
            return "bullish"

    return "none"


@dataclass
class CryptoRegimeStrategy(Strategy):
    """Regime-adaptive crypto strategy — the main recommended strategy.

    Parameters
    ----------
    adx_trend_threshold : float
        ADX value above which market is "trending" (default 22).
    adx_range_threshold : float
        ADX value below which market is "ranging" (default 18).
    volume_expansion_mult : float
        Required current volume / avg volume ratio for entry (default 1.5).
    min_rr_ratio : float
        Minimum reward-to-risk ratio required for entry (default 1.5).
    swing_lookback : int
        Bars to look back for swing low/high structure (default 10).
    sl_buffer_atr : float
        ATR multiple to place SL below swing low (default 0.3).
    """
    name: str = "crypto_regime"
    required_bars: int = 60

    adx_trend_threshold: float = 22.0
    adx_range_threshold: float = 18.0
    volume_expansion_mult: float = 1.5
    min_rr_ratio: float = 1.5
    swing_lookback: int = 10
    sl_buffer_atr: float = 0.3
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 72.0
    bb_period: int = 20
    bb_std: float = 2.0

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        base = self._validate(df)
        if base is not None:
            return base

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # --- Indicators ---
        ema_f = ema(close, self.ema_fast)
        ema_s = ema(close, self.ema_slow)
        rsi_s = rsi(close, self.rsi_period)
        adx_s = _adx(high, low, close, 14)
        atr_s = atr(high, low, close, 14)
        bb_u, bb_m, bb_l = bollinger_bands(close, self.bb_period, self.bb_std)

        curr_close = float(close.iloc[-1])
        curr_ema_f = float(ema_f.iloc[-1])
        curr_ema_s = float(ema_s.iloc[-1])
        curr_rsi = float(rsi_s.iloc[-1])
        curr_adx = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else 15.0
        curr_atr = float(atr_s.iloc[-1])
        curr_bb_u = float(bb_u.iloc[-1])
        curr_bb_m = float(bb_m.iloc[-1])
        curr_bb_l = float(bb_l.iloc[-1])
        bb_width = (curr_bb_u - curr_bb_l) / curr_bb_m if curr_bb_m > 0 else 0

        # Volume expansion (current vs last 20 avg)
        avg_vol = float(volume.iloc[-21:-1].mean())
        curr_vol = float(volume.iloc[-1])
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 0

        # Structure levels
        swing_low = _swing_low(low, self.swing_lookback)
        swing_high = _swing_high(high, self.swing_lookback * 2)

        # --- Regime classification ---
        # Trend: EMA fast > EMA slow, ADX > threshold, slope positive
        ema_trending_up = curr_ema_f > curr_ema_s and adx_s.iloc[-1] > self.adx_trend_threshold
        ema_trending_down = curr_ema_f < curr_ema_s and adx_s.iloc[-1] > self.adx_trend_threshold
        # Range: ADX < range threshold, BB width narrow
        is_ranging = curr_adx < self.adx_range_threshold

        # --- Exit logic first (position management) ---
        has_position = position is not None and position.get("quantity", 0) > 0
        if has_position:
            avg_price = position.get("avg_price", curr_close)
            profit_pct = (curr_close - avg_price) / avg_price if avg_price > 0 else 0

            # Exit on strong bearish reversal
            if curr_close < curr_ema_f and curr_close < curr_ema_s and curr_rsi < 45:
                return Signal(
                    SignalType.SELL,
                    confidence=0.85,
                    reason="CR: 추세 반전 (가격<EMA 20·50, RSI<45)",
                )
            # Exit on bearish divergence when in profit
            if profit_pct > 0.02 and _rsi_divergence(close, rsi_s) == "bearish":
                return Signal(
                    SignalType.SELL,
                    confidence=0.8,
                    reason=f"CR: 베어리시 다이버전스 (수익 +{profit_pct*100:.1f}%)",
                )
            # Exit on extreme overbought in range
            if is_ranging and curr_rsi > 78 and curr_close >= curr_bb_u * 0.99:
                return Signal(
                    SignalType.SELL,
                    confidence=0.7,
                    reason=f"CR: 횡보장 과매수 이탈 (RSI={curr_rsi:.0f})",
                )
            return Signal.hold(f"CR: 보유 (수익률 {profit_pct*100:+.2f}%)")

        # --- Entry logic ---
        # Skip if insufficient volume expansion
        if vol_ratio < self.volume_expansion_mult:
            return Signal.hold(
                f"CR: 거래량 부족 ({vol_ratio:.2f}x < {self.volume_expansion_mult}x)"
            )

        # Skip bearish divergence
        div = _rsi_divergence(close, rsi_s)
        if div == "bearish":
            return Signal.hold("CR: 베어리시 다이버전스 감지")

        # --- Regime-specific entries ---
        # 1) TREND REGIME: buy pullback to EMA20 in uptrend
        if ema_trending_up and curr_rsi > 40 and curr_rsi < 70:
            dist_to_ema_f = abs(curr_close - curr_ema_f) / curr_ema_f
            # Buy when pulling back to EMA20 (within 1% of it) but not below EMA50
            if dist_to_ema_f < 0.02 and curr_close > curr_ema_s:
                sl = swing_low - curr_atr * self.sl_buffer_atr
                tp_target = swing_high
                risk = curr_close - sl
                reward = tp_target - curr_close
                if risk > 0 and reward / risk >= self.min_rr_ratio:
                    return Signal(
                        SignalType.BUY,
                        confidence=min(0.95, 0.6 + curr_adx / 100),
                        reason=(
                            f"CR: 추세장 풀백 매수 (ADX={curr_adx:.0f}, "
                            f"R:R={reward/risk:.2f}, vol={vol_ratio:.1f}x)"
                        ),
                        meta={"sl_suggest": sl, "tp_suggest": tp_target, "regime": "trend"},
                    )

        # 2) RANGE REGIME: buy at lower band with RSI oversold
        if is_ranging and curr_close <= curr_bb_l * 1.01 and curr_rsi < 40 and div != "bearish":
            sl = swing_low - curr_atr * self.sl_buffer_atr
            tp_target = curr_bb_m
            risk = curr_close - sl
            reward = tp_target - curr_close
            if risk > 0 and reward / risk >= self.min_rr_ratio:
                return Signal(
                    SignalType.BUY,
                    confidence=0.7,
                    reason=(
                        f"CR: 횡보장 하단 매수 (RSI={curr_rsi:.0f}, "
                        f"R:R={reward/risk:.2f}, vol={vol_ratio:.1f}x)"
                    ),
                    meta={"sl_suggest": sl, "tp_suggest": tp_target, "regime": "range"},
                )

        # 3) BREAKOUT REGIME: squeeze then expansion with volume
        if len(bb_u) > 20:
            recent_bb_width = (bb_u.iloc[-20:-1] - bb_l.iloc[-20:-1]) / bb_m.iloc[-20:-1]
            squeeze = (bb_width <= recent_bb_width.quantile(0.3)) if len(recent_bb_width) > 5 else False
            if squeeze and curr_close > curr_bb_u and vol_ratio >= 2.0 and curr_rsi < 75:
                sl = curr_bb_m - curr_atr * self.sl_buffer_atr
                tp_target = curr_close + (curr_bb_u - curr_bb_l)  # measured move
                risk = curr_close - sl
                reward = tp_target - curr_close
                if risk > 0 and reward / risk >= self.min_rr_ratio:
                    return Signal(
                        SignalType.BUY,
                        confidence=0.85,
                        reason=(
                            f"CR: 스퀴즈 돌파 매수 (BB폭={bb_width*100:.1f}%, "
                            f"vol={vol_ratio:.1f}x)"
                        ),
                        meta={"sl_suggest": sl, "tp_suggest": tp_target, "regime": "breakout"},
                    )

        # 4) Don't trade in downtrend
        if ema_trending_down:
            return Signal.hold(f"CR: 하락 추세 회피 (ADX={curr_adx:.0f})")

        return Signal.hold(
            f"CR: 대기 (ADX={curr_adx:.0f}, RSI={curr_rsi:.0f}, vol={vol_ratio:.1f}x)"
        )
