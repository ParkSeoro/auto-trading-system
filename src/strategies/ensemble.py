"""Ensemble strategy — confidence-weighted vote of multiple strategies.

Consensus rule: BUY only when the weighted buy score exceeds a threshold AND no
strong sell signal exists. SELL when weighted sell score exceeds threshold
or any member raises a SELL with confidence >= 0.9 (risk-off).
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.strategies.base import Signal, SignalType, Strategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.bollinger_breakout import BollingerBreakoutStrategy


class EnsembleStrategy(Strategy):
    name = "ensemble"

    def __init__(self, members: Optional[List[Strategy]] = None, buy_threshold: float = 0.6):
        self.members: List[Strategy] = members or [
            VolatilityBreakoutStrategy(k=0.5),
            RSIMeanReversionStrategy(),
            BollingerBreakoutStrategy(),
        ]
        self.buy_threshold = buy_threshold
        self.required_bars = max((m.required_bars for m in self.members), default=50)

    def generate(self, df: pd.DataFrame, position: Optional[dict] = None) -> Signal:
        invalid = self._validate(df)
        if invalid:
            return invalid

        buy_score = 0.0
        sell_score = 0.0
        reasons = []
        meta = {}
        strong_sell = False

        for strat in self.members:
            sig = strat.generate(df, position=position)
            meta[strat.name] = {
                "type": sig.type.value,
                "confidence": round(sig.confidence, 3),
                "reason": sig.reason,
            }
            if sig.type == SignalType.BUY:
                buy_score += sig.confidence
                reasons.append(f"+{strat.name}({sig.confidence:.2f})")
            elif sig.type == SignalType.SELL:
                sell_score += sig.confidence
                reasons.append(f"-{strat.name}({sig.confidence:.2f})")
                if sig.confidence >= 0.9:
                    strong_sell = True

        n = len(self.members)
        buy_norm = buy_score / n
        sell_norm = sell_score / n

        has_position = bool(position and position.get("quantity", 0) > 0)

        if (sell_norm > buy_norm and sell_norm >= self.buy_threshold) or (has_position and strong_sell):
            return Signal(
                SignalType.SELL,
                confidence=min(1.0, sell_norm),
                reason="ensemble SELL | " + ", ".join(reasons),
                meta=meta,
            )

        if not has_position and buy_norm >= self.buy_threshold and buy_norm > sell_norm:
            return Signal(
                SignalType.BUY,
                confidence=min(1.0, buy_norm),
                reason="ensemble BUY | " + ", ".join(reasons),
                meta=meta,
            )

        return Signal(SignalType.HOLD, 0.0, f"ensemble HOLD (buy={buy_norm:.2f}, sell={sell_norm:.2f})", meta)
