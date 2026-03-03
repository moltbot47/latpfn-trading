"""
Polymarket-specific risk management.

Binary outcomes have fundamentally different risk characteristics:
- Max loss per trade = position size (outcome resolves to $0)
- Max gain per trade = (1 - entry_price) * shares
- No leverage, no liquidation, no margin calls
- Risk is entirely about position sizing and portfolio concentration
"""

import logging
from typing import Dict, Optional

from polymarket.positions import PositionManager

logger = logging.getLogger(__name__)


class PolymarketRisk:
    """Risk management for Polymarket prediction market trading."""

    def __init__(self, config: dict, position_mgr: PositionManager):
        pm_cfg = config.get("polymarket", {})
        self.budget = pm_cfg.get("budget_usdc", 15.0)
        self.max_concurrent = pm_cfg.get("max_concurrent_positions", 55)
        self.max_exposure = pm_cfg.get("max_portfolio_exposure", 0.80)
        self.daily_loss_limit_pct = pm_cfg.get("daily_loss_limit_pct", 25.0)
        self.positions = position_mgr

        # Per-strategy position limits
        self.strategy_limits = pm_cfg.get("strategy_limits", {
            "resolution_snipe": 5,
            "superforecaster": 5,
            "max_concurrent": 45,
            "crypto_scalp": 3,
            "turbo": 100,
        })

        # Track daily P&L
        self.daily_realized_pnl = 0.0
        self.starting_budget = self.budget

    def update_budget(self, new_budget: float):
        """Update budget from live balance.

        IMPORTANT: new_budget should be TOTAL capital (cash + deployed),
        not just available cash.  If you only have the cash balance from
        get_balance(), call sync_budget_from_cash() instead.
        """
        self.budget = new_budget

    def sync_budget_from_cash(self, cash_balance: float):
        """Sync budget from available cash balance.

        Total capital = cash in wallet + capital deployed in open positions.
        Using only cash would shrink the budget as positions are opened,
        eventually blocking all new trades.
        """
        deployed = self.positions.total_deployed()
        self.budget = cash_balance + deployed

    def can_trade(self, strategy: str = None) -> tuple[bool, str]:
        """
        Check if we're allowed to open a new position.

        Args:
            strategy: Optional strategy name for per-strategy limit checks.

        Returns:
            (allowed, reason)
        """
        # Check daily loss limit
        loss_limit = self.starting_budget * (self.daily_loss_limit_pct / 100)
        if self.daily_realized_pnl < -loss_limit:
            return False, (
                f"Daily loss limit hit: ${self.daily_realized_pnl:.2f} "
                f"(limit: -${loss_limit:.2f})"
            )

        # Per-strategy position limit
        if strategy and strategy in self.strategy_limits:
            strat_count = len(self.positions.get_positions_by_strategy(strategy))
            strat_limit = self.strategy_limits[strategy]
            if strat_count >= strat_limit:
                return False, (
                    f"{strategy} position limit: {strat_count}/{strat_limit}"
                )

        # Check overall concurrent positions
        open_count = self.positions.position_count()
        if open_count >= self.max_concurrent:
            return False, (
                f"Max concurrent positions: {open_count}/{self.max_concurrent}"
            )

        # Check portfolio exposure
        deployed = self.positions.total_deployed()
        max_deploy = self.budget * self.max_exposure
        if deployed >= max_deploy:
            return False, (
                f"Portfolio exposure limit: ${deployed:.2f} / ${max_deploy:.2f} "
                f"({self.max_exposure:.0%})"
            )

        return True, "OK"

    def max_position_size(self, strategy: str) -> float:
        """
        Calculate maximum position size for a new trade.

        Args:
            strategy: "resolution_snipe" or "superforecaster"

        Returns:
            Maximum USDC to allocate.
        """
        deployed = self.positions.total_deployed()
        max_deploy = self.budget * self.max_exposure
        available = max(0, max_deploy - deployed)

        # Per-strategy position limits are handled by the strategy classes
        return available

    def validate_trade(
        self,
        strategy: str,
        size_usdc: float,
        entry_price: float,
        market_id: str,
    ) -> tuple[bool, str]:
        """
        Validate a specific trade before execution.

        Args:
            strategy:    Strategy name.
            size_usdc:   Proposed position size in USDC.
            entry_price: Entry price (0-1 for Polymarket).
            market_id:   Market condition ID.

        Returns:
            (approved, reason)
        """
        # Basic gate check (forward strategy for per-strategy limits)
        allowed, reason = self.can_trade(strategy=strategy)
        if not allowed:
            return False, reason

        # Check duplicate position
        if self.positions.has_position_for_market(market_id):
            return False, f"Already have position on market {market_id[:12]}"

        # Check size (lower minimum for fixed $1 bet strategies)
        min_size = 0.50 if strategy in ("max_concurrent", "turbo") else 1.0
        if size_usdc < min_size:
            return False, f"Position size too small: ${size_usdc:.2f}"

        max_size = self.max_position_size(strategy)
        if size_usdc > max_size:
            return False, (
                f"Size ${size_usdc:.2f} exceeds available ${max_size:.2f}"
            )

        # Sanity check on entry price
        if entry_price <= 0 or entry_price >= 1:
            return False, f"Invalid entry price: {entry_price}"

        logger.info(
            "RISK APPROVED [%s]: $%.2f @ %.4f on %s",
            strategy, size_usdc, entry_price, market_id[:12],
        )
        return True, "Approved"

    def record_pnl(self, pnl: float):
        """Record realized P&L for daily tracking."""
        self.daily_realized_pnl += pnl

    def reset_daily(self):
        """Reset daily P&L counter (call at start of each day)."""
        self.daily_realized_pnl = 0.0

    def get_status(self) -> Dict:
        """Get current risk status summary."""
        deployed = self.positions.total_deployed()
        return {
            "budget": self.budget,
            "deployed": deployed,
            "available": max(0, self.budget * self.max_exposure - deployed),
            "exposure_pct": (deployed / self.budget * 100) if self.budget > 0 else 0,
            "open_positions": self.positions.position_count(),
            "max_positions": self.max_concurrent,
            "daily_pnl": self.daily_realized_pnl,
            "daily_loss_limit": self.starting_budget * (self.daily_loss_limit_pct / 100),
            "total_realized_pnl": self.positions.total_realized_pnl(),
        }
