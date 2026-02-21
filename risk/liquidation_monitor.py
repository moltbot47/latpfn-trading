"""
Liquidation cascade detection for Hyperliquid.

Monitors aggregate open interest changes between cycles. A rapid OI drop
(>5% in one cycle) signals a liquidation cascade in progress — leveraged
positions being force-closed, causing a waterfall effect.

During cascades:
  - Skip new entries (don't trade into a liquidation flush)
  - Optionally alert via Discord
  - Track cascade state for recovery detection
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# OI drop threshold for cascade detection
CASCADE_OI_DROP_PCT = 5.0    # 5% OI drop in one cycle = cascade
CASCADE_COOLDOWN_CYCLES = 3  # Wait 3 cycles after cascade before trading


class LiquidationMonitor:
    """Monitor aggregate open interest for liquidation cascade detection."""

    def __init__(self):
        self._prev_oi: Dict[str, float] = {}  # coin → previous OI
        self._cascade_active: Dict[str, int] = {}  # coin → cycles since cascade
        self._global_cascade: bool = False
        self._global_cascade_cooldown: int = 0

    def update(self, asset_contexts: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        Check for liquidation cascades by comparing current OI to previous cycle.

        Args:
            asset_contexts: Dict of coin → {open_interest, ...} from PairScanner.

        Returns:
            Dict of coins experiencing cascades with details.
        """
        cascades = {}

        # Track aggregate OI for global cascade detection
        total_oi_now = 0
        total_oi_prev = 0

        for coin, ctx in asset_contexts.items():
            oi_now = ctx.get("open_interest", 0)
            total_oi_now += oi_now

            if coin in self._prev_oi:
                oi_prev = self._prev_oi[coin]
                total_oi_prev += oi_prev

                if oi_prev > 0:
                    oi_change_pct = (oi_now - oi_prev) / oi_prev * 100

                    if oi_change_pct < -CASCADE_OI_DROP_PCT:
                        cascades[coin] = {
                            "oi_drop_pct": abs(oi_change_pct),
                            "oi_prev": oi_prev,
                            "oi_now": oi_now,
                            "oi_lost": oi_prev - oi_now,
                        }
                        self._cascade_active[coin] = CASCADE_COOLDOWN_CYCLES
                        logger.warning(
                            "LIQUIDATION CASCADE: %s OI dropped %.1f%% "
                            "($%.0f → $%.0f, -$%.0f)",
                            coin, abs(oi_change_pct), oi_prev, oi_now,
                            oi_prev - oi_now,
                        )

            self._prev_oi[coin] = oi_now

        # Global cascade: total market OI drop
        if total_oi_prev > 0:
            total_change_pct = (total_oi_now - total_oi_prev) / total_oi_prev * 100
            if total_change_pct < -CASCADE_OI_DROP_PCT:
                self._global_cascade = True
                self._global_cascade_cooldown = CASCADE_COOLDOWN_CYCLES
                logger.warning(
                    "GLOBAL LIQUIDATION CASCADE: Total OI dropped %.1f%% "
                    "($%.0fM → $%.0fM)",
                    abs(total_change_pct),
                    total_oi_prev / 1e6,
                    total_oi_now / 1e6,
                )

        # Decrement cooldowns
        expired = []
        for coin, remaining in self._cascade_active.items():
            if remaining <= 1:
                expired.append(coin)
            else:
                self._cascade_active[coin] = remaining - 1

        for coin in expired:
            del self._cascade_active[coin]
            logger.info("Cascade cooldown expired for %s", coin)

        if self._global_cascade_cooldown > 0:
            self._global_cascade_cooldown -= 1
            if self._global_cascade_cooldown <= 0:
                self._global_cascade = False
                logger.info("Global cascade cooldown expired")

        return cascades

    def is_safe_to_trade(self, coin: str) -> bool:
        """Check if it's safe to enter a new position for this coin."""
        if self._global_cascade:
            return False
        if coin in self._cascade_active:
            return False
        return True

    def get_status(self) -> Dict:
        """Get current cascade monitoring status."""
        return {
            "global_cascade": self._global_cascade,
            "global_cooldown": self._global_cascade_cooldown,
            "active_cascades": dict(self._cascade_active),
            "monitored_pairs": len(self._prev_oi),
        }
