"""Defense and Recovery Mode manager — protects account survival.

Rules:
- Normal mode:    No restrictions. Full position sizing.
- Defense mode:   Triggered by daily loss >= -3% OR 2 consecutive losses.
                  Position size reduced. Entry threshold raised.
- Halt mode:      Triggered by daily loss >= -5% OR 4 consecutive losses.
                  All new entries blocked for `halt_duration_minutes`.
- Recovery mode:  After halt ends. Only 1:2+ R:R trades allowed.
                  Reduced size. Until 50% of session loss is recovered.

Absolute prohibitions:
- Martingale / averaging down: NEVER allowed
- Oversizing to recover: NEVER allowed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from src.utils.logger import get_logger
from src.utils.notifier import send_alert

log = get_logger(__name__)


class TradingMode(str, Enum):
    NORMAL   = "normal"
    DEFENSE  = "defense"
    HALT     = "halt"
    RECOVERY = "recovery"


@dataclass
class DefenseState:
    mode: TradingMode = TradingMode.NORMAL
    day: Optional[date] = None

    # Daily tracking
    starting_equity: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0

    # Consecutive losses across ALL strategies (global)
    consecutive_losses: int = 0
    consecutive_wins: int = 0

    # Halt timing
    halt_until: Optional[datetime] = None
    halt_reason: str = ""

    # Recovery tracking
    loss_at_halt: float = 0.0  # equity at the time halt was triggered
    recovery_target: float = 0.0  # recover 50% of loss from this level

    def session_pnl_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return (self.current_equity - self.starting_equity) / self.starting_equity

    def is_halted_now(self, now: Optional[datetime] = None) -> bool:
        if self.mode != TradingMode.HALT:
            return False
        if self.halt_until is None:
            return False
        now = now or datetime.now(timezone.utc)
        return now < self.halt_until

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "day": str(self.day) if self.day else None,
            "session_pnl_pct": round(self.session_pnl_pct() * 100, 2),
            "consecutive_losses": self.consecutive_losses,
            "consecutive_wins": self.consecutive_wins,
            "halt_until": self.halt_until.isoformat() if self.halt_until else None,
            "halt_reason": self.halt_reason,
            "current_equity": round(self.current_equity, 0),
            "starting_equity": round(self.starting_equity, 0),
        }


class DefenseManager:
    """Stateful daily guard that escalates restrictions as losses accumulate.

    Parameters
    ----------
    defense_loss_pct : float
        Daily loss threshold to enter defense mode (default -3%).
    halt_loss_pct : float
        Daily loss threshold to halt all trading (default -5%).
    defense_consecutive : int
        Consecutive loss count to trigger defense mode (default 2).
    halt_consecutive : int
        Consecutive loss count to halt all trading (default 4).
    halt_duration_minutes : int
        Minutes to pause after halt trigger (default 60).
    recovery_ratio : float
        Fraction of loss that must be recovered before returning to normal (0.5 = 50%).
    min_rr_in_recovery : float
        Minimum reward-to-risk ratio required in recovery mode (default 2.0).
    """

    def __init__(
        self,
        defense_loss_pct: float = 0.03,
        halt_loss_pct: float = 0.05,
        defense_consecutive: int = 2,
        halt_consecutive: int = 4,
        halt_duration_minutes: int = 60,
        recovery_ratio: float = 0.5,
        min_rr_in_recovery: float = 2.0,
    ):
        self.defense_loss_pct = defense_loss_pct
        self.halt_loss_pct = halt_loss_pct
        self.defense_consecutive = defense_consecutive
        self.halt_consecutive = halt_consecutive
        self.halt_duration_minutes = halt_duration_minutes
        self.recovery_ratio = recovery_ratio
        self.min_rr_in_recovery = min_rr_in_recovery
        self._state = DefenseState()

    @property
    def state(self) -> DefenseState:
        return self._state

    @property
    def mode(self) -> TradingMode:
        return self._state.mode

    # ------------------------------------------------------------------
    # Equity update (called each tick)
    # ------------------------------------------------------------------
    def update_equity(self, equity: float, now: Optional[datetime] = None) -> TradingMode:
        now = now or datetime.now(timezone.utc)
        today = now.date()
        s = self._state

        # Reset on new day
        if s.day != today:
            s.day = today
            s.starting_equity = equity
            s.peak_equity = equity
            s.current_equity = equity
            # Clear daily halt state (but keep loss streak)
            if s.mode == TradingMode.HALT and not s.is_halted_now(now):
                s.mode = TradingMode.RECOVERY
                s.loss_at_halt = equity
                s.recovery_target = equity + abs(s.starting_equity - equity) * self.recovery_ratio
            log.info("New trading day — resetting equity tracking. Starting=%.0f", equity)
            return s.mode

        s.current_equity = equity
        if equity > s.peak_equity:
            s.peak_equity = equity

        pnl_pct = s.session_pnl_pct()

        # --- Check recovery completion ---
        if s.mode == TradingMode.RECOVERY:
            if equity >= s.recovery_target:
                old_mode = s.mode
                s.mode = TradingMode.NORMAL
                s.consecutive_losses = 0
                log.info("✅ Recovery complete! Returning to NORMAL mode. Equity=%.0f", equity)
                send_alert(f"Recovery complete — returning to normal trading. Equity={equity:,.0f} KRW")
            return s.mode

        # --- Check halt expiry ---
        if s.mode == TradingMode.HALT:
            if not s.is_halted_now(now):
                s.mode = TradingMode.RECOVERY
                s.loss_at_halt = equity
                s.recovery_target = equity + abs(equity - s.starting_equity) * self.recovery_ratio
                log.info("Halt expired → RECOVERY mode. Target=%.0f", s.recovery_target)
                send_alert(f"Halt expired → Recovery mode. Target equity: {s.recovery_target:,.0f} KRW")
            return s.mode

        # --- Escalation checks ---
        if pnl_pct <= -self.halt_loss_pct or s.consecutive_losses >= self.halt_consecutive:
            self._trigger_halt(
                reason=(
                    f"일일 손실 {pnl_pct*100:.1f}%" if pnl_pct <= -self.halt_loss_pct
                    else f"연속 {s.consecutive_losses}회 손실"
                ),
                now=now,
                equity=equity,
            )
        elif pnl_pct <= -self.defense_loss_pct or s.consecutive_losses >= self.defense_consecutive:
            if s.mode == TradingMode.NORMAL:
                s.mode = TradingMode.DEFENSE
                log.warning(
                    "🛡️ Defense mode ON — daily_loss=%.1f%% consecutive=%d",
                    pnl_pct * 100, s.consecutive_losses,
                )
                send_alert(f"방어 모드 진입 | 일일 손실 {pnl_pct*100:.1f}% | 연속손실 {s.consecutive_losses}회")

        return s.mode

    def _trigger_halt(self, reason: str, now: datetime, equity: float) -> None:
        s = self._state
        if s.mode == TradingMode.HALT:
            return
        s.mode = TradingMode.HALT
        s.halt_reason = reason
        s.halt_until = now.__class__(
            now.year, now.month, now.day,
            now.hour, now.minute, now.second,
            tzinfo=now.tzinfo,
        )
        import datetime as _dt
        s.halt_until = now + _dt.timedelta(minutes=self.halt_duration_minutes)
        log.warning(
            "🛑 HALT triggered: %s. Pausing until %s",
            reason, s.halt_until.isoformat(),
        )
        send_alert(f"거래 중단! {reason} | {self.halt_duration_minutes}분 후 복구 모드 전환")

    # ------------------------------------------------------------------
    # Trade outcome recording
    # ------------------------------------------------------------------
    def record_trade_outcome(self, pnl: float) -> None:
        s = self._state
        if pnl > 0:
            s.consecutive_losses = 0
            s.consecutive_wins += 1
            # Exit defense mode after a win (if not triggered by daily loss)
            if s.mode == TradingMode.DEFENSE and s.session_pnl_pct() > -self.defense_loss_pct:
                s.mode = TradingMode.NORMAL
                log.info("Defense mode lifted after win. PnL=%.0f KRW", pnl)
        else:
            s.consecutive_wins = 0
            s.consecutive_losses += 1
            log.warning(
                "Trade loss #%d recorded. PnL=%.0f KRW",
                s.consecutive_losses, pnl,
            )

    # ------------------------------------------------------------------
    # Entry gate — bot calls this before every trade
    # ------------------------------------------------------------------
    def can_enter(
        self,
        now: Optional[datetime] = None,
        rr_ratio: Optional[float] = None,
    ) -> tuple[bool, str]:
        """Return (allowed, reason). Bot must call before entry."""
        now = now or datetime.now(timezone.utc)
        s = self._state

        if s.mode == TradingMode.HALT and s.is_halted_now(now):
            remaining = int((s.halt_until - now).total_seconds() / 60)
            return False, f"거래 중단 중 ({remaining}분 남음): {s.halt_reason}"

        if s.mode == TradingMode.RECOVERY:
            if rr_ratio is not None and rr_ratio < self.min_rr_in_recovery:
                return False, f"복구 모드: R:R={rr_ratio:.1f} < 최소 {self.min_rr_in_recovery:.1f} 필요"

        return True, ""

    # ------------------------------------------------------------------
    # Size adjustment — applies loss-streak scaling
    # ------------------------------------------------------------------
    def size_multiplier(self) -> float:
        """Return position size multiplier based on current mode and streak.

        Normal:   1.0  (5~10% of capital via RiskManager)
        Defense:  0.7  (2패)
        Halt:     0.0  (거래 금지)
        Recovery: 0.5  (고확률만, 작게)
        """
        s = self._state
        if s.mode == TradingMode.HALT:
            return 0.0
        if s.mode == TradingMode.RECOVERY:
            return 0.5
        if s.mode == TradingMode.DEFENSE:
            # Scale: 2패→0.7, 3패→0.5
            if s.consecutive_losses >= 3:
                return 0.5
            return 0.7
        # Normal — scale by consecutive losses
        if s.consecutive_losses >= 3:
            return 0.5
        if s.consecutive_losses >= 2:
            return 0.7
        return 1.0

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status_report(self) -> dict:
        return self._state.to_dict()
