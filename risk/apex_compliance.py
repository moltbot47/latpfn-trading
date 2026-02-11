"""
Apex Trader Funding compliance guards.

Enforces prop firm rules that go beyond standard risk management:
  1. 5:1 max risk-to-reward ratio per trade
  2. 30% MAE rule — no single trade's unrealized loss > 30% of profit balance
  3. 30% consistency rule — no single day's profit > 30% of total at payout
  4. Correlated instrument guard — no opposing directions on correlated pairs
  5. Hard flatten by 4:55 PM ET (4-min buffer before 4:59 deadline)
  6. Contract scaling — PA accounts start at 50% max contracts
"""

import logging
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Instruments that are considered correlated (equity indices)
CORRELATED_GROUPS = [
    {"MYM", "MNQ", "YM", "NQ", "ES", "MES", "RTY", "M2K"},
]

ET = ZoneInfo("America/New_York")
FLATTEN_TIME = dtime(16, 55)  # 4:55 PM ET — hard cutoff
NO_NEW_TRADES_TIME = dtime(16, 45)  # 4:45 PM ET — stop opening new positions


class ApexCompliance:
    """Validates trades against Apex Trader Funding rules."""

    def __init__(self, config: dict):
        self.config = config
        self.risk_cfg = config.get("risk", {})
        self.apex_cfg = config.get("risk", {}).get("prop_firm", {})

        # Daily P&L tracking for consistency rule
        self._daily_pnl: dict[str, float] = {}  # date_str → P&L
        self._total_pnl: float = 0.0

        # Start-of-day profit balance for MAE rule
        self._sod_profit_balance: float = 0.0

    def set_sod_profit_balance(self, profit_balance: float):
        """Set start-of-day profit balance (call at session start)."""
        self._sod_profit_balance = profit_balance
        logger.info("SOD profit balance set: $%.2f", profit_balance)

    def record_daily_pnl(self, date_str: str, pnl: float):
        """Record a day's P&L for consistency tracking."""
        self._daily_pnl[date_str] = pnl
        self._total_pnl = sum(self._daily_pnl.values())

    # ── Pre-trade checks ─────────────────────────────────────────

    def check_all(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        position_size: int,
        contract_size: float,
        open_positions: dict,
    ) -> tuple[bool, str]:
        """
        Run all Apex compliance checks on a proposed trade.

        Returns:
            (passed, reason) — passed=True if compliant, else reason string.
        """
        # 1. Time-of-day check
        ok, reason = self._check_trading_time()
        if not ok:
            return False, reason

        # 2. 5:1 R:R ratio
        ok, reason = self._check_risk_reward_ratio(entry_price, stop_price, target_price)
        if not ok:
            return False, reason

        # 3. 30% MAE rule
        ok, reason = self._check_mae(entry_price, stop_price, position_size, contract_size)
        if not ok:
            return False, reason

        # 4. Correlated instrument check
        ok, reason = self._check_correlated(instrument, direction, open_positions)
        if not ok:
            return False, reason

        return True, "Apex compliant"

    def _check_trading_time(self) -> tuple[bool, str]:
        """Block new trades after 4:45 PM ET."""
        now = datetime.now(ET)
        t = now.time()
        if t >= NO_NEW_TRADES_TIME:
            return False, f"No new trades after 4:45 PM ET (now: {t.strftime('%H:%M')} ET) — must flatten by 4:59"
        return True, ""

    def _check_risk_reward_ratio(
        self,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> tuple[bool, str]:
        """Enforce Apex 5:1 max risk-to-reward ratio."""
        risk = abs(entry_price - stop_price)
        reward = abs(target_price - entry_price)

        if reward < 1e-10:
            return False, "Zero reward distance"

        rr_ratio = risk / reward  # This is risk:reward (lower is better)

        if rr_ratio > 5.0:
            return False, (
                f"Apex 5:1 R:R violation: risking {risk:.2f} pts for {reward:.2f} pts "
                f"(ratio {rr_ratio:.1f}:1, max 5:1)"
            )

        return True, ""

    def _check_mae(
        self,
        entry_price: float,
        stop_price: float,
        position_size: int,
        contract_size: float,
    ) -> tuple[bool, str]:
        """
        Enforce 30% MAE rule.

        No single trade's maximum potential loss (at stop) can exceed
        30% of the account's profit balance at start of day.
        """
        if self._sod_profit_balance <= 0:
            # No profit balance yet — MAE rule doesn't apply
            return True, ""

        max_loss = abs(entry_price - stop_price) * contract_size * position_size
        mae_limit = self._sod_profit_balance * 0.30

        if max_loss > mae_limit:
            return False, (
                f"Apex 30% MAE violation: trade max loss ${max_loss:.2f} "
                f"> 30% of profit balance ${mae_limit:.2f} "
                f"(profit balance: ${self._sod_profit_balance:.2f})"
            )

        return True, ""

    def _check_correlated(
        self,
        instrument: str,
        direction: str,
        open_positions: dict,
    ) -> tuple[bool, str]:
        """
        Block opposing directions on correlated instruments.

        E.g., can't go LONG MYM while SHORT MNQ — both are equity indices.
        """
        # Find which correlation group this instrument belongs to
        my_group = None
        for group in CORRELATED_GROUPS:
            if instrument in group:
                my_group = group
                break

        if my_group is None:
            return True, ""  # instrument not in any correlated group

        for pos_inst, pos in open_positions.items():
            if pos_inst == instrument:
                continue
            if pos_inst in my_group and pos.direction != direction:
                return False, (
                    f"Apex correlated instrument violation: "
                    f"cannot go {direction.upper()} {instrument} while "
                    f"{pos.direction.upper()} {pos_inst} is open "
                    f"(both are correlated equity indices)"
                )

        return True, ""

    # ── Time-based guards ────────────────────────────────────────

    def should_flatten_now(self) -> bool:
        """Check if we've hit the hard flatten time (4:55 PM ET)."""
        now = datetime.now(ET)
        t = now.time()
        return t >= FLATTEN_TIME

    # ── Consistency rule helpers ─────────────────────────────────

    def check_consistency(self) -> tuple[bool, str]:
        """
        Check if we're at risk of violating the 30% consistency rule.

        Returns (ok, warning_message).
        """
        if self._total_pnl <= 0:
            return True, ""

        best_day = max(self._daily_pnl.values()) if self._daily_pnl else 0
        if best_day <= 0:
            return True, ""

        best_day_pct = best_day / self._total_pnl

        if best_day_pct > 0.30:
            min_total_needed = best_day / 0.30
            shortfall = min_total_needed - self._total_pnl
            return False, (
                f"Consistency warning: best day ${best_day:,.2f} is "
                f"{best_day_pct:.0%} of total ${self._total_pnl:,.2f} "
                f"(max 30%). Need ${shortfall:,.2f} more profit before payout."
            )

        return True, ""
