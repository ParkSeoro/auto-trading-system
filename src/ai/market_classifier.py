"""Market state classifier — 5-level regime detection.

Classifies the market into one of:
  STRONG_UP / WEAK_UP / SIDEWAYS / WEAK_DOWN / STRONG_DOWN

Used by the bot to:
- Block trades in SIDEWAYS (low volume) or STRONG_DOWN
- Adjust position sizing per regime
- Feed state into Claude Advisor for context

Classification uses:
- EMA trend alignment (10/20/50)
- RSI zone
- ATR % (volatility)
- Volume trend (5-bar vs 20-bar avg)
- Recent return (5-bar close-to-close)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from src.indicators import atr, ema, rsi
from src.utils.logger import get_logger

log = get_logger(__name__)


class MarketState(str, Enum):
    STRONG_UP   = "강한_상승"
    WEAK_UP     = "약한_상승"
    SIDEWAYS    = "횡보"
    WEAK_DOWN   = "약한_하락"
    STRONG_DOWN = "강한_하락"


@dataclass
class MarketAnalysis:
    state: MarketState
    volatility: str          # "low" | "medium" | "high"
    volume_trend: str        # "increasing" | "stable" | "decreasing"
    rsi_val: float
    atr_pct: float
    vol_ratio: float         # current vs 20-bar avg
    ret_5bar: float          # 5-bar return
    trade_allowed: bool
    block_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "volatility": self.volatility,
            "volume_trend": self.volume_trend,
            "rsi": round(self.rsi_val, 1),
            "atr_pct": round(self.atr_pct * 100, 2),
            "volume_ratio": round(self.vol_ratio, 2),
            "return_5bar_pct": round(self.ret_5bar * 100, 2),
            "trade_allowed": self.trade_allowed,
            "block_reason": self.block_reason,
        }


class MarketClassifier:
    """Classify market regime and determine if trading is allowed."""

    def __init__(
        self,
        ema_short: int = 10,
        ema_mid: int = 20,
        ema_long: int = 50,
        sideways_atr_pct_max: float = 0.008,   # below 0.8% ATR = too flat
        high_vol_atr_pct: float = 0.06,          # above 6% ATR = dangerous
        volume_decline_ratio: float = 0.7,        # < 70% of avg = declining
        volume_surge_ratio: float = 1.5,
    ):
        self.ema_short = ema_short
        self.ema_mid = ema_mid
        self.ema_long = ema_long
        self.sideways_atr_pct_max = sideways_atr_pct_max
        self.high_vol_atr_pct = high_vol_atr_pct
        self.volume_decline_ratio = volume_decline_ratio
        self.volume_surge_ratio = volume_surge_ratio

    def classify(self, df: pd.DataFrame) -> MarketAnalysis:
        if df is None or len(df) < 55:
            return MarketAnalysis(
                state=MarketState.SIDEWAYS,
                volatility="unknown",
                volume_trend="unknown",
                rsi_val=50.0, atr_pct=0.0, vol_ratio=1.0, ret_5bar=0.0,
                trade_allowed=False, block_reason="insufficient data",
            )

        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        vol   = df["volume"]
        c     = float(close.iloc[-1])

        # EMAs
        e10 = float(ema(close, self.ema_short).iloc[-1])
        e20 = float(ema(close, self.ema_mid).iloc[-1])
        e50 = float(ema(close, self.ema_long).iloc[-1])

        # RSI
        rsi14  = rsi(close, 14)
        rsi_val = float(rsi14.iloc[-1]) if not pd.isna(rsi14.iloc[-1]) else 50.0

        # ATR%
        atr14   = atr(high, low, close, 14)
        atr_val = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else 0.0
        atr_pct = atr_val / c if c > 0 else 0.0

        # Volume
        vol_avg    = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else float(vol.mean())
        vol_cur    = float(vol.iloc[-1])
        vol_ratio  = vol_cur / vol_avg if vol_avg > 0 else 1.0
        vol_avg5   = float(vol.iloc[-6:-1].mean()) if len(vol) > 5 else vol_cur
        vol_trend  = (
            "increasing" if vol_avg5 > vol_avg * self.volume_surge_ratio
            else "decreasing" if vol_avg5 < vol_avg * self.volume_decline_ratio
            else "stable"
        )

        # 5-bar return
        ret_5 = (c / float(close.iloc[-6]) - 1.0) if len(close) > 5 else 0.0

        # Volatility label
        if atr_pct < self.sideways_atr_pct_max:
            volatility = "low"
        elif atr_pct > self.high_vol_atr_pct:
            volatility = "high"
        else:
            volatility = "medium"

        # --- State classification ---
        # Count bull/bear signals
        bull_pts = 0
        bear_pts = 0

        if c > e10 > 0:        bull_pts += 1
        else:                   bear_pts += 1

        if e10 > e20 > 0:      bull_pts += 1
        else:                   bear_pts += 1

        if e20 > e50 > 0:      bull_pts += 1
        else:                   bear_pts += 1

        if rsi_val > 55:       bull_pts += 1
        elif rsi_val < 45:     bear_pts += 1

        if ret_5 > 0.02:       bull_pts += 1
        elif ret_5 < -0.02:    bear_pts += 1

        if vol_trend == "increasing":
            if ret_5 > 0:      bull_pts += 1
            else:              bear_pts += 1

        score = bull_pts - bear_pts  # range: -6 to +6
        if score >= 4:
            state = MarketState.STRONG_UP
        elif score >= 1:
            state = MarketState.WEAK_UP
        elif score <= -4:
            state = MarketState.STRONG_DOWN
        elif score <= -1:
            state = MarketState.WEAK_DOWN
        else:
            state = MarketState.SIDEWAYS

        # --- Trade-allowed rules ---
        block_reason = ""
        if state == MarketState.SIDEWAYS and vol_trend == "decreasing":
            block_reason = "횡보 + 거래량 감소 — 방향성 없음"
        elif state == MarketState.STRONG_DOWN:
            block_reason = "강한 하락 추세 — 진입 금지"
        elif volatility == "high" and ret_5 > self.high_vol_atr_pct:
            block_reason = f"급등 과열 구간 (5봉 수익률={ret_5*100:.1f}%)"

        trade_allowed = not bool(block_reason)

        result = MarketAnalysis(
            state=state,
            volatility=volatility,
            volume_trend=vol_trend,
            rsi_val=rsi_val,
            atr_pct=atr_pct,
            vol_ratio=vol_ratio,
            ret_5bar=ret_5,
            trade_allowed=trade_allowed,
            block_reason=block_reason,
        )
        log.debug(
            "Market state: %s | vol=%s | vol_trend=%s | trade=%s%s",
            state.value, volatility, vol_trend, trade_allowed,
            f" BLOCKED: {block_reason}" if block_reason else "",
        )
        return result
