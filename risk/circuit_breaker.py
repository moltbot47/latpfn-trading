"""
Circuit breaker: halts trading when risk limits are breached.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Tracks daily P&L and drawdown, halts trading when limits hit."""

    def __init__(self, config: dict):
        risk = config["risk"]
        self.max_daily_loss_pct = risk["max_daily_loss_pct"] / 100.0
        self.max_drawdown_pct = risk["max_drawdown_pct"] / 100.0
        self.max_concurrent = risk["max_concurrent_positions"]

        prop = risk.get("prop_firm", {})
        self.max_daily_loss_usd = prop.get("max_daily_loss_usd", float("inf"))
        self.max_total_drawdown_usd = prop.get("max_total_drawdown_usd", float("inf"))

        # State
        self._triggered = False
        self._reason = ""
        self._daily_pnl = 0.0
        self._peak_equity = 0.0
        self._current_date = date.today()

    def update(
        self,
        realized_pnl_today: float,
        current_equity: float,
        starting_equity: float,
        open_positions: int,
    ):
        """Call this after every fill or on a periodic check."""
        # Reset daily tracker on new day
        today = date.today()
        if today != self._current_date:
            self._daily_pnl = 0.0
            self._current_date = today
            if self._triggered:
                logger.info("New trading day — resetting circuit breaker")
                self._triggered = False
                self._reason = ""

        self._daily_pnl = realized_pnl_today

        # Update peak equity for drawdown
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # ── Check limits ──────────────────────────────────────────────

        # Daily loss (percentage)
        if starting_equity > 0:
            daily_loss_pct = -self._daily_pnl / starting_equity
            if daily_loss_pct > self.max_daily_loss_pct:
                self._trip("Daily loss %.2f%% exceeds limit" % (daily_loss_pct * 100))

        # Daily loss (absolute — prop firm)
        if -self._daily_pnl > self.max_daily_loss_usd:
            self._trip("Daily loss $%.2f exceeds prop firm limit" % -self._daily_pnl)

        # Max drawdown from peak (percentage)
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - current_equity) / self._peak_equity
            if dd_pct > self.max_drawdown_pct:
                self._trip("Drawdown %.2f%% exceeds limit" % (dd_pct * 100))

        # Max drawdown (absolute — prop firm)
        if self._peak_equity - current_equity > self.max_total_drawdown_usd:
            dd_usd = self._peak_equity - current_equity
            self._trip("Drawdown $%.2f exceeds prop firm limit" % dd_usd)

    def can_open_position(self, open_positions: int) -> tuple[bool, str]:
        """Check if a new position is allowed."""
        if self._triggered:
            return False, f"Circuit breaker: {self._reason}"
        if open_positions >= self.max_concurrent:
            return False, f"Max concurrent positions ({self.max_concurrent}) reached"
        return True, "OK"

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    @property
    def reason(self) -> str:
        return self._reason

    def _trip(self, reason: str):
        if not self._triggered:
            logger.warning("CIRCUIT BREAKER TRIPPED: %s", reason)
        self._triggered = True
        self._reason = reason
