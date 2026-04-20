"""BTC regime filter — the single most important guard for crypto trading.

Crypto altcoins have 0.7~0.95 correlation with BTC during trending moves.
When BTC dumps, ALL alts dump harder (beta 1.2~2.0). Trading alts without
checking BTC is the #1 reason for synchronized portfolio drawdowns.

This filter continuously monitors BTC and returns a "safety score" that
determines whether alt trading is allowed:

  1.0  = BTC bullish       → alt longs OK at full size
  0.5  = BTC neutral/range → alt longs OK at reduced size (50%)
  0.0  = BTC bearish       → block all alt longs
  -1.0 = BTC crash/panic   → force-exit alt longs

Signals checked:
- 1h trend: 20EMA vs 50EMA slope
- 4h trend: 50EMA slope (confirmation)
- 1h RSI: overbought (>75) / oversold (<30) extremes
- Recent return: -3% in 1h = panic, -5% in 4h = cascade
- Volume: abnormal sell volume spikes
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import pandas as pd

from src.data import MarketData
from src.exchanges.base import Exchange
from src.indicators import atr, ema, rsi
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BTCState:
    regime: str = "unknown"         # bullish / neutral / bearish / crash
    score: float = 0.5              # 0..1 safety score for alt longs
    trend_1h: str = "neutral"       # up / down / neutral
    trend_4h: str = "neutral"
    rsi_1h: float = 50.0
    return_1h: float = 0.0          # last-1h return
    return_4h: float = 0.0
    atr_pct_1h: float = 0.0
    volume_spike: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "score": round(self.score, 3),
            "trend_1h": self.trend_1h,
            "trend_4h": self.trend_4h,
            "rsi_1h": round(self.rsi_1h, 1),
            "return_1h_pct": round(self.return_1h * 100, 2),
            "return_4h_pct": round(self.return_4h * 100, 2),
            "atr_pct_1h": round(self.atr_pct_1h, 2),
            "volume_spike": self.volume_spike,
            "reason": self.reason,
        }

    @property
    def allow_alt_long(self) -> bool:
        return self.score > 0.25 and self.regime not in ("crash", "bearish")

    @property
    def force_exit(self) -> bool:
        return self.regime == "crash"


@dataclass
class BTCFilter:
    """Stateful BTC regime monitor. Call update() each tick."""
    market_data: Optional[MarketData] = None
    btc_market: str = "KRW-BTC"
    cache_ttl_sec: int = 60
    _last_state: BTCState = field(default_factory=BTCState)
    _last_update: float = 0.0

    def update(self, exchange: Optional[Exchange] = None) -> BTCState:
        """Fetch BTC 1h and 4h data, compute regime state."""
        now = time.time()
        if (now - self._last_update) < self.cache_ttl_sec and self._last_state.regime != "unknown":
            return self._last_state

        md = self.market_data
        if md is None and exchange is not None:
            md = MarketData(exchange=exchange, ttl_sec=60)
        if md is None:
            return self._last_state

        try:
            df_1h = md.get_ohlcv(self.btc_market, timeframe="1h", count=100)
            df_4h = md.get_ohlcv(self.btc_market, timeframe="6h", count=60)
        except Exception as exc:
            log.warning("BTC filter fetch failed: %s", exc)
            return self._last_state

        if df_1h.empty or len(df_1h) < 20:
            log.debug("BTC filter: insufficient 1h data (%d bars)", len(df_1h) if not df_1h.empty else 0)
            return self._last_state
        if df_4h.empty or len(df_4h) < 10:
            log.debug("BTC filter: insufficient 6h data (%d bars), using 1h only", len(df_4h) if not df_4h.empty else 0)
            df_4h = df_1h

        state = self._classify(df_1h, df_4h)
        self._last_state = state
        self._last_update = now
        log.debug(
            "BTC filter: regime=%s score=%.2f trend_1h=%s trend_4h=%s ret_1h=%.2f%% rsi=%.0f",
            state.regime, state.score, state.trend_1h, state.trend_4h,
            state.return_1h * 100, state.rsi_1h,
        )
        return state

    @staticmethod
    def _classify(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> BTCState:
        close_1h = df_1h["close"]
        close_4h = df_4h["close"]

        ema20_1h = ema(close_1h, 20)
        ema50_1h = ema(close_1h, 50)
        ema50_4h = ema(close_4h, 50)

        last_1h = float(close_1h.iloc[-1])
        last_ema20_1h = float(ema20_1h.iloc[-1]) if pd.notna(ema20_1h.iloc[-1]) else last_1h
        last_ema50_1h = float(ema50_1h.iloc[-1]) if pd.notna(ema50_1h.iloc[-1]) else last_1h
        last_ema50_4h = float(ema50_4h.iloc[-1]) if pd.notna(ema50_4h.iloc[-1]) else last_1h

        # Trend: price > EMA20 > EMA50 = up; price < EMA20 < EMA50 = down
        if last_1h > last_ema20_1h > last_ema50_1h:
            trend_1h = "up"
        elif last_1h < last_ema20_1h < last_ema50_1h:
            trend_1h = "down"
        else:
            trend_1h = "neutral"

        # 4h EMA50 slope over last 3 bars
        if len(ema50_4h) >= 4 and pd.notna(ema50_4h.iloc[-4]):
            slope_4h = (ema50_4h.iloc[-1] - ema50_4h.iloc[-4]) / ema50_4h.iloc[-4]
            if slope_4h > 0.003:
                trend_4h = "up"
            elif slope_4h < -0.003:
                trend_4h = "down"
            else:
                trend_4h = "neutral"
        else:
            trend_4h = "neutral"

        # RSI 1h
        rsi_1h = float(rsi(close_1h, 14).iloc[-1]) if len(close_1h) > 14 else 50.0

        # Recent returns
        ret_1h = (close_1h.iloc[-1] / close_1h.iloc[-2]) - 1.0 if len(close_1h) >= 2 else 0.0
        ret_4h = (close_4h.iloc[-1] / close_4h.iloc[-2]) - 1.0 if len(close_4h) >= 2 else 0.0

        # ATR% (volatility)
        atr_1h = atr(df_1h["high"], df_1h["low"], close_1h, 14)
        atr_pct = float(atr_1h.iloc[-1] / last_1h * 100) if pd.notna(atr_1h.iloc[-1]) else 0.0

        # Volume spike (current 1h > 2x of recent avg)
        recent_vol = df_1h["volume"].iloc[-20:-1].mean()
        current_vol = df_1h["volume"].iloc[-1]
        volume_spike = current_vol > recent_vol * 2.0

        # --- Regime classification ---
        regime = "neutral"
        score = 0.5
        reasons = []

        # Crash: panic dump
        if ret_1h <= -0.03 or ret_4h <= -0.05:
            regime = "crash"
            score = -1.0
            reasons.append(f"BTC 급락 ({ret_1h*100:.1f}%/1h, {ret_4h*100:.1f}%/4h)")
        # Bearish: confirmed downtrend
        elif trend_1h == "down" and trend_4h == "down":
            regime = "bearish"
            score = 0.0
            reasons.append("BTC 하락 추세 (1h+4h)")
        elif trend_1h == "down" and rsi_1h < 40:
            regime = "bearish"
            score = 0.1
            reasons.append(f"BTC 약세 (RSI={rsi_1h:.0f})")
        # Overheated: likely short-term reversal soon
        elif rsi_1h > 80 and ret_1h > 0.02:
            regime = "overheated"
            score = 0.3
            reasons.append(f"BTC 과열 (RSI={rsi_1h:.0f}, +{ret_1h*100:.1f}%)")
        # Bullish: healthy uptrend
        elif trend_1h == "up" and trend_4h == "up" and 40 < rsi_1h < 75:
            regime = "bullish"
            score = 1.0
            reasons.append("BTC 상승 추세 (1h+4h)")
        elif trend_1h == "up" and rsi_1h > 45:
            regime = "bullish"
            score = 0.8
            reasons.append("BTC 상승 추세 (1h)")
        # Neutral: sideways
        elif abs(ret_4h) < 0.02 and 40 < rsi_1h < 65:
            regime = "neutral"
            score = 0.5
            reasons.append("BTC 횡보")
        else:
            regime = "mixed"
            score = 0.4
            reasons.append("BTC 혼조")

        return BTCState(
            regime=regime,
            score=score,
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            rsi_1h=rsi_1h,
            return_1h=ret_1h,
            return_4h=ret_4h,
            atr_pct_1h=atr_pct,
            volume_spike=volume_spike,
            reason=" | ".join(reasons),
        )

    def check_alt_entry(self, market: str) -> Tuple[bool, float, str]:
        """Decide if an alt-coin long is allowed right now.

        Returns (allowed, size_multiplier, reason).
        Size multiplier: 1.0 in bullish, 0.5 in neutral, 0.0 when blocked.
        """
        # BTC itself is not filtered by BTC regime
        if market.upper() == self.btc_market:
            return True, 1.0, ""

        s = self._last_state
        if s.regime == "unknown":
            return True, 0.7, "BTC 데이터 대기 중 (기본 사이즈 70%)"
        if not s.allow_alt_long:
            return False, 0.0, f"BTC 필터 차단: {s.reason}"
        # Scale size by score
        return True, s.score, f"BTC {s.regime} (size×{s.score:.2f})"

    @property
    def state(self) -> BTCState:
        return self._last_state
