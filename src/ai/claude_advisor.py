"""Claude Opus 4.7 AI Advisor — market analysis, strategy tuning, post-trade review.

Uses claude-opus-4-7 with extended thinking for:
1. Market regime analysis with structured output
2. Strategy parameter recommendations based on recent performance
3. Post-session trade review with improvement suggestions

Extended thinking allows the model to reason deeply before answering,
producing more accurate market analysis and parameter suggestions.
Responses are cached where possible to reduce API costs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config.settings import KST
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)

_MODEL = "claude-opus-4-7"


def _get_client():
    """Lazy-import Anthropic client so the SDK is optional at module load."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


class ClaudeAdvisor:
    """Wraps Claude Opus 4.7 for trading intelligence.

    Falls back gracefully when ANTHROPIC_API_KEY is not set or the SDK
    is unavailable — the bot continues without AI advice.
    """

    def __init__(
        self,
        advice_path: Optional[Path] = None,
        max_thinking_tokens: int = 8000,
    ):
        self.advice_path = Path(advice_path or (Path("data") / "claude_advice.json"))
        self.max_thinking_tokens = max_thinking_tokens
        self._client = _get_client()
        self._last_advice: dict = self._load_cached()

        if self._client:
            log.info("ClaudeAdvisor ready (%s)", _MODEL)
        else:
            log.info("ClaudeAdvisor: ANTHROPIC_API_KEY not set — AI advice disabled")

    def available(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # 1. Market analysis
    # ------------------------------------------------------------------
    def analyze_market(
        self,
        market: str,
        market_state: dict,
        recent_trades: list,
        defense_status: dict,
    ) -> dict:
        """Ask Claude to analyze current conditions and recommend action."""
        if not self._client:
            return self._fallback_analysis(market_state)

        prompt = f"""You are an expert crypto trading AI analyzing {market}.

Current Market Data:
- State: {market_state.get('state')} | Volatility: {market_state.get('volatility')}
- RSI: {market_state.get('rsi')} | ATR%: {market_state.get('atr_pct')}%
- Volume ratio: {market_state.get('volume_ratio')}x | 5-bar return: {market_state.get('return_5bar_pct')}%
- Volume trend: {market_state.get('volume_trend')}
- Trade allowed: {market_state.get('trade_allowed')} {('(BLOCKED: ' + market_state.get('block_reason','') + ')') if not market_state.get('trade_allowed') else ''}

Bot Status:
- Mode: {defense_status.get('mode')} | Daily PnL: {defense_status.get('session_pnl_pct')}%
- Consecutive losses: {defense_status.get('consecutive_losses')}

Recent trades (last 5): {json.dumps(recent_trades[-5:] if recent_trades else [], ensure_ascii=False)}

Analyze and respond in JSON with these exact keys:
{{
  "action": "BUY" | "HOLD" | "AVOID",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation in Korean (2 sentences max)",
  "risk_level": "low" | "medium" | "high",
  "key_factors": ["factor1", "factor2"],
  "suggested_sl_pct": 0.02,
  "suggested_tp_pct": 0.04
}}

Respond ONLY with the JSON object."""

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                thinking={
                    "type": "enabled",
                    "budget_tokens": self.max_thinking_tokens,
                },
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            for block in response.content:
                if block.type == "text":
                    text = block.text
                    break
            result = json.loads(text.strip())
            result["source"] = "claude-opus-4-7"
            result["ts"] = datetime.now(KST).isoformat()
            self._cache(result, "market_analysis")
            return result
        except Exception as exc:
            log.warning("Claude market analysis failed: %s", exc)
            return self._fallback_analysis(market_state)

    # ------------------------------------------------------------------
    # 2. Strategy auto-tuning recommendations
    # ------------------------------------------------------------------
    def recommend_tuning(
        self,
        strategy_stats: dict,
        current_params: dict,
        recent_backtest: Optional[dict] = None,
    ) -> dict:
        """Ask Claude to suggest parameter adjustments based on performance."""
        if not self._client:
            return {"adjustments": {}, "source": "disabled"}

        prompt = f"""You are a quantitative trading expert optimizing a crypto scalping strategy.

Current Parameters:
{json.dumps(current_params, indent=2)}

Recent Performance Stats:
{json.dumps(strategy_stats, indent=2)}

Recent Backtest (if available):
{json.dumps(recent_backtest or {}, indent=2)}

The strategy must follow these rules:
- Stop loss: -2% to -3% max
- Take profit: +2% to +5%
- RSI entry range: somewhere in [20, 45]
- Volume confirmation: 1.3x to 2.5x

Based on the performance data, suggest parameter adjustments to improve:
1. Win rate (target > 55%)
2. Profit factor (target > 1.5)
3. Expected value per trade

Respond ONLY with JSON:
{{
  "adjustments": {{
    "rsi_low": <number or null if no change>,
    "rsi_high": <number or null if no change>,
    "volume_min_mult": <number or null>,
    "sl_atr_mult": <number or null>,
    "tp_atr_mult": <number or null>
  }},
  "expected_improvement_pct": <0-100>,
  "reasoning": "Korean explanation of why these changes help",
  "priority": "high" | "medium" | "low"
}}"""

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                thinking={
                    "type": "enabled",
                    "budget_tokens": self.max_thinking_tokens,
                },
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            for block in response.content:
                if block.type == "text":
                    text = block.text
                    break
            result = json.loads(text.strip())
            result["source"] = "claude-opus-4-7"
            result["ts"] = datetime.now(KST).isoformat()
            self._cache(result, "tuning")
            log.info("Claude tuning: %s", result.get("reasoning", ""))
            return result
        except Exception as exc:
            log.warning("Claude tuning recommendation failed: %s", exc)
            return {"adjustments": {}, "source": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Post-session review
    # ------------------------------------------------------------------
    def session_review(self, session_summary: dict) -> str:
        """Ask Claude for a post-session improvement report."""
        if not self._client:
            return "AI 리뷰 비활성화 (ANTHROPIC_API_KEY 없음)"

        prompt = f"""You are a professional trading coach reviewing today's crypto bot session.

Session Summary:
{json.dumps(session_summary, indent=2, ensure_ascii=False)}

Write a brief review in Korean (3-4 bullet points) covering:
• 오늘의 잘한 점 (what went well)
• 개선이 필요한 점 (what needs improvement)
• 내일의 조정 사항 (adjustments for tomorrow)
• 전략 관련 특이사항 (strategy notes)

Keep it concise, actionable, and data-driven."""

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            review = response.content[0].text.strip()
            self._cache({"review": review, "ts": datetime.now(KST).isoformat()}, "session_review")
            return review
        except Exception as exc:
            log.warning("Claude session review failed: %s", exc)
            return f"리뷰 생성 실패: {exc}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _fallback_analysis(self, market_state: dict) -> dict:
        state = market_state.get("state", "")
        trade_allowed = market_state.get("trade_allowed", True)
        if not trade_allowed:
            action = "AVOID"
        elif "상승" in state:
            action = "BUY"
        else:
            action = "HOLD"
        return {
            "action": action,
            "confidence": 0.5,
            "reasoning": "AI 분석 비활성화. 시장 분류 기반 기본 판단.",
            "risk_level": "medium",
            "key_factors": [state],
            "suggested_sl_pct": 0.025,
            "suggested_tp_pct": 0.04,
            "source": "fallback",
        }

    def _cache(self, data: dict, key: str) -> None:
        try:
            self.advice_path.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if self.advice_path.exists():
                existing = json.loads(self.advice_path.read_text(encoding="utf-8"))
            existing[key] = data
            self.advice_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            self._last_advice = existing
        except Exception as exc:
            log.debug("cache write failed: %s", exc)

    def _load_cached(self) -> dict:
        try:
            if self.advice_path.exists():
                return json.loads(self.advice_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def last_advice(self) -> dict:
        return self._last_advice
