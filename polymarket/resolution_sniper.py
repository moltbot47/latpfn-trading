"""
Resolution Sniping strategy — buy near-certain outcomes approaching resolution.

Targets markets where YES price is $0.85-0.97 and resolution is within 48h.
Expected return: 3-17% per trade over 12-48h holding period.
Risk: market resolves NO → lose full position (mitigated by high-probability filter).
"""

import logging
from typing import Dict, List, Optional

from polymarket.positions import PolyPosition

logger = logging.getLogger(__name__)


class ResolutionSniper:
    """Finds and executes resolution sniping opportunities."""

    def __init__(self, client, scanner, position_mgr, config: dict):
        """
        Args:
            client:       PolymarketClient instance.
            scanner:      MarketScanner instance.
            position_mgr: PositionManager instance.
            config:       Full config dict.
        """
        self.client = client
        self.scanner = scanner
        self.positions = position_mgr
        pm_cfg = config.get("polymarket", {})
        self.sniper_cfg = pm_cfg.get("sniper", {})
        self.budget = pm_cfg.get("budget_usdc", 15.0)
        self.max_position_pct = self.sniper_cfg.get("max_position_pct", 0.20)
        self.stop_price = self.sniper_cfg.get("stop_price", 0.80)

    def find_candidates(
        self, markets: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Scan for resolution sniping opportunities.

        Args:
            markets: Pre-fetched markets (or None to scan fresh).

        Returns:
            List of candidate dicts sorted by edge.
        """
        if markets is None:
            markets = self.scanner.scan_markets()

        candidates = self.scanner.filter_resolution_candidates(markets)

        # Filter out markets we already have positions on
        candidates = [
            c for c in candidates
            if not self.positions.has_position_for_market(c["market_id"])
        ]

        return candidates

    def evaluate(self, candidate: Dict) -> Dict:
        """
        Evaluate a single snipe candidate with risk assessment.

        Returns enriched candidate dict with sizing info.
        """
        yes_price = candidate["yes_price"]
        edge_pct = candidate["edge_pct"]
        hours_left = candidate["hours_to_resolution"]

        # Risk assessment
        if hours_left < 1:
            risk_level = "high"  # Too close, might not fill
        elif hours_left < 6:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Annualized return (for comparison)
        annual_factor = 8760 / max(hours_left, 1)  # hours in year / hours to resolution
        annualized_return = edge_pct * annual_factor

        # Position sizing
        available = self.budget - self.positions.total_deployed()
        max_size = self.budget * self.max_position_pct
        size_usdc = min(max_size, available)

        shares = size_usdc / yes_price if yes_price > 0 else 0

        # Polymarket minimum order size is 5 shares
        if shares < 5.0:
            min_cost = 5.0 * yes_price
            if min_cost <= available:
                shares = 5.0
                size_usdc = min_cost
            else:
                size_usdc = 0  # Can't meet minimum

        candidate.update({
            "risk_level": risk_level,
            "annualized_return": annualized_return,
            "size_usdc": size_usdc,
            "shares": shares,
            "expected_pnl": size_usdc * (edge_pct / 100),
        })
        return candidate

    async def execute(self, candidate: Dict) -> Optional[Dict]:
        """
        Execute a resolution snipe trade.

        Args:
            candidate: Evaluated candidate dict from evaluate().

        Returns:
            Trade result dict or None on failure.
        """
        size_usdc = candidate.get("size_usdc", 0)
        if size_usdc < 1.0:
            logger.warning("Snipe size too small: $%.2f", size_usdc)
            return None

        token_id = candidate["yes_token_id"]
        yes_price = candidate["yes_price"]

        # Place limit buy at current YES price
        try:
            result = self.client.buy_limit(
                token_id=token_id,
                price=yes_price,
                size=candidate["shares"],
            )
        except Exception as e:
            logger.error("Snipe order failed: %s", e)
            return None

        if not result.get("orderID"):
            logger.error("Snipe order missing orderID: %s", result)
            return None

        order_id = result.get("orderID", "")

        # Record position
        pos = PolyPosition(
            market_id=candidate["market_id"],
            token_id=token_id,
            question=candidate["question"],
            strategy="resolution_snipe",
            direction="YES",
            entry_price=yes_price,
            size_usdc=size_usdc,
            shares=candidate["shares"],
            target_exit=1.0,
            expected_pnl_pct=candidate["edge_pct"],
            resolution_date=candidate["end_date"],
            market_probability=yes_price,
            order_id=order_id,
        )
        key = self.positions.open_position(pos)

        logger.info(
            "SNIPE EXECUTED: '%s' YES @ %.4f  $%.2f  edge=%.1f%%  hours=%.0f",
            candidate["question"][:50], yes_price, size_usdc,
            candidate["edge_pct"], candidate["hours_to_resolution"],
        )

        return {
            "position_key": key,
            "order_id": order_id,
            "question": candidate["question"],
            "direction": "YES",
            "entry_price": yes_price,
            "size_usdc": size_usdc,
            "edge_pct": candidate["edge_pct"],
            "hours_to_resolution": candidate["hours_to_resolution"],
        }

    def should_exit(self, key: str, current_price: float) -> bool:
        """
        Check if a snipe position should be emergency-exited.

        Exit if price drops below stop_price (default 0.80) — means
        resolution is no longer near-certain.
        """
        pos = self.positions.positions.get(key)
        if not pos or pos.status != "open":
            return False
        return current_price < self.stop_price

    async def check_and_exit(self, key: str, current_price: float) -> Optional[Dict]:
        """Exit a snipe position if stop is hit."""
        if not self.should_exit(key, current_price):
            return None

        pos = self.positions.positions[key]
        try:
            result = self.client.sell_market(pos.token_id, pos.shares)
            realized_pnl = (current_price - pos.entry_price) * pos.shares
            self.positions.close_position(key, current_price, realized_pnl)
            logger.warning(
                "SNIPE STOP HIT: '%s' exit @ %.4f (entry %.4f) PnL=$%.4f",
                pos.question[:40], current_price, pos.entry_price, realized_pnl,
            )
            return {"key": key, "exit_price": current_price, "pnl": realized_pnl}
        except Exception as e:
            logger.error("Failed to exit snipe %s: %s", key, e)
            return None
