"""MACD crossover strategy — catches trend changes earlier than RSI/BB.

Generates BUY when MACD line crosses above signal line with positive histogram
growing. Generates SELL when MACD crosses below signal, or histogram turns
negative while in position. Works well on 1h~1d timeframes for crypto.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.indicators import macd, ema
from src.strategies.base import Signal, SignalType, Strategy


class MACDCrossoverStrategy(Strategy):
    name = "macd_crossover"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
        trend_ema: int = 50,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period
        self.trend_ema = trend_ema
        self.required_bars = max(slow + signal_period, trend_ema) + 5

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        close = df["close"]
        macd_line, sig_line, hist = macd(close, self.fast, self.slow, self.signal_period)

        curr_macd = macd_line.iloc[-1]
        curr_sig = sig_line.iloc[-1]
        curr_hist = hist.iloc[-1]
        prev_macd = macd_line.iloc[-2]
        prev_sig = sig_line.iloc[-2]
        prev_hist = hist.iloc[-2]

        if pd.isna(curr_macd) or pd.isna(prev_macd):
            return Signal.hold("MACD warming up")

        has_position = bool(position and position.get("quantity", 0) > 0)

        # Trend filter: only buy above the long EMA
        ema_long = ema(close, self.trend_ema)
        above_trend = close.iloc[-1] > ema_long.iloc[-1] if not pd.isna(ema_long.iloc[-1]) else True

        # SELL: MACD crosses below signal, or histogram turns negative
        if has_position:
            if curr_macd < curr_sig and prev_macd >= prev_sig:
                return Signal(
                    SignalType.SELL,
                    confidence=min(1.0, abs(curr_hist) / (abs(curr_macd) + 1e-10) + 0.5),
                    reason=f"MACD bearish cross (hist={curr_hist:.2f})",
                    meta={"macd": float(curr_macd), "signal": float(curr_sig), "hist": float(curr_hist)},
                )
            if curr_hist < 0 and prev_hist >= 0:
                return Signal(
                    SignalType.SELL,
                    confidence=0.7,
                    reason=f"MACD histogram turned negative ({curr_hist:.2f})",
                    meta={"macd": float(curr_macd), "signal": float(curr_sig), "hist": float(curr_hist)},
                )

        # BUY: MACD crosses above signal + above trend EMA + histogram growing
        if not has_position:
            if curr_macd > curr_sig and prev_macd <= prev_sig and above_trend:
                confidence = min(1.0, 0.5 + abs(curr_hist) / (abs(curr_macd) + 1e-10))
                return Signal(
                    SignalType.BUY,
                    confidence=confidence,
                    reason=f"MACD bullish cross (hist={curr_hist:.2f})",
                    meta={"macd": float(curr_macd), "signal": float(curr_sig), "hist": float(curr_hist)},
                )
            # Also buy if histogram is growing for 3 consecutive bars (momentum building)
            if (above_trend and curr_hist > 0 and prev_hist > 0
                    and len(hist) > 3 and hist.iloc[-3] < prev_hist < curr_hist):
                return Signal(
                    SignalType.BUY,
                    confidence=0.6,
                    reason=f"MACD momentum building (hist={curr_hist:.2f})",
                    meta={"macd": float(curr_macd), "signal": float(curr_sig), "hist": float(curr_hist)},
                )

        return Signal.hold(f"MACD={curr_macd:.2f}, sig={curr_sig:.2f}, hist={curr_hist:.2f}")
