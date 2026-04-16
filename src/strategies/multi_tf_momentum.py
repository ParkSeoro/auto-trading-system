"""Multi-indicator momentum strategy — designed to trade more frequently.

Combines multiple lighter-weight signals to find entries that the individual
strategies miss. Instead of requiring extreme conditions (RSI < 25, BB squeeze),
this uses moderate thresholds across several indicators to find confluence.

Entry when 3+ of these conditions align:
- Price above EMA(20)
- RSI between 40-60 and rising (momentum building, not overbought)
- MACD histogram positive and growing
- Volume above average
- Price making higher lows (HH/HL pattern)

Exit when 2+ bearish conditions appear.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.indicators import rsi, ema, sma, macd, atr
from src.strategies.base import Signal, SignalType, Strategy


class MultiTFMomentumStrategy(Strategy):
    name = "multi_tf_momentum"

    def __init__(
        self,
        ema_short: int = 10,
        ema_mid: int = 20,
        rsi_period: int = 14,
        min_bullish_signals: int = 3,
        min_bearish_signals: int = 2,
    ):
        self.ema_short = ema_short
        self.ema_mid = ema_mid
        self.rsi_period = rsi_period
        self.min_bullish = min_bullish_signals
        self.min_bearish = min_bearish_signals
        self.required_bars = 50

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        current = float(close.iloc[-1])

        has_position = bool(position and position.get("quantity", 0) > 0)
        bullish = 0
        bearish = 0
        reasons = []

        # 1. Price above EMA(20)
        ema_20 = ema(close, self.ema_mid)
        ema_10 = ema(close, self.ema_short)
        e20 = float(ema_20.iloc[-1]) if not pd.isna(ema_20.iloc[-1]) else 0
        e10 = float(ema_10.iloc[-1]) if not pd.isna(ema_10.iloc[-1]) else 0

        if e20 > 0 and current > e20:
            bullish += 1
            reasons.append("above EMA20")
        elif e20 > 0 and current < e20:
            bearish += 1

        # 2. EMA(10) > EMA(20) (trend direction)
        if e10 > 0 and e20 > 0 and e10 > e20:
            bullish += 1
            reasons.append("EMA10>20")
        elif e10 > 0 and e20 > 0 and e20 > e10:
            bearish += 1

        # 3. RSI rising and in healthy range
        r = rsi(close, self.rsi_period)
        rsi_now = float(r.iloc[-1]) if not pd.isna(r.iloc[-1]) else 50
        rsi_prev = float(r.iloc[-2]) if not pd.isna(r.iloc[-2]) else 50

        if 35 <= rsi_now <= 65 and rsi_now > rsi_prev:
            bullish += 1
            reasons.append(f"RSI rising({rsi_now:.0f})")
        elif rsi_now > 75:
            bearish += 1
        elif rsi_now < 30:
            bearish += 1

        # 4. MACD histogram positive and growing
        macd_line, sig_line, hist = macd(close, 12, 26, 9)
        h_now = float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else 0
        h_prev = float(hist.iloc[-2]) if not pd.isna(hist.iloc[-2]) else 0

        if h_now > 0 and h_now > h_prev:
            bullish += 1
            reasons.append("MACD+")
        elif h_now < 0 and h_now < h_prev:
            bearish += 1

        # 5. Volume above average
        vol_avg = float(volume.iloc[-21:-1].mean()) if len(volume) > 21 else float(volume.mean())
        vol_now = float(volume.iloc[-1])
        if vol_avg > 0 and vol_now > vol_avg * 0.9:
            bullish += 1
            reasons.append("vol OK")
        elif vol_avg > 0 and vol_now < vol_avg * 0.5:
            bearish += 1

        # 6. Higher lows pattern (last 3 bars)
        if len(low) >= 4:
            if float(low.iloc[-1]) > float(low.iloc[-2]) > float(low.iloc[-3]):
                bullish += 1
                reasons.append("HL pattern")
            elif float(low.iloc[-1]) < float(low.iloc[-2]) < float(low.iloc[-3]):
                bearish += 1

        # Decision
        total_signals = 6
        bull_conf = bullish / total_signals
        bear_conf = bearish / total_signals

        if has_position and bearish >= self.min_bearish:
            return Signal(
                SignalType.SELL,
                confidence=min(1.0, bear_conf + 0.3),
                reason=f"momentum exit ({bearish}/{total_signals} bearish)",
                meta={"bullish": bullish, "bearish": bearish, "rsi": rsi_now},
            )

        if not has_position and bullish >= self.min_bullish:
            return Signal(
                SignalType.BUY,
                confidence=min(1.0, bull_conf + 0.2),
                reason=f"momentum entry ({bullish}/{total_signals}: {', '.join(reasons)})",
                meta={"bullish": bullish, "bearish": bearish, "rsi": rsi_now},
            )

        return Signal.hold(f"momentum wait (bull={bullish}, bear={bearish})")
