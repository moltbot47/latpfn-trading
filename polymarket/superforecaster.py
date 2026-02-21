"""
LLM Superforecaster strategy — trade probability divergences between
Claude's estimate and the market price.

When Claude estimates a probability significantly different from the
market (>10% divergence), we trade in the direction of Claude's estimate
and exit when the market converges or at resolution.
"""

import logging
import math
from typing import Dict, List, Optional

from polymarket.positions import PolyPosition

logger = logging.getLogger(__name__)


class SuperforecasterStrategy:
    """Trades LLM probability divergences on Polymarket."""

    def __init__(self, client, scanner, forecaster, position_mgr, config: dict):
        """
        Args:
            client:       PolymarketClient instance.
            scanner:      MarketScanner instance.
            forecaster:   LLMForecaster instance.
            position_mgr: PositionManager instance.
            config:       Full config dict.
        """
        self.client = client
        self.scanner = scanner
        self.forecaster = forecaster
        self.positions = position_mgr
        pm_cfg = config.get("polymarket", {})
        self.fc_cfg = pm_cfg.get("forecaster", {})
        self.budget = pm_cfg.get("budget_usdc", 15.0)
        self.max_position_pct = self.fc_cfg.get("max_position_pct", 0.15)
        self.convergence_threshold = 0.03  # Exit when divergence < 3%

    async def find_candidates(
        self, markets: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Scan markets, forecast with LLM, find divergence opportunities.

        Returns:
            List of candidate dicts sorted by |divergence|.
        """
        # Get forecastable markets
        forecastable = self.scanner.get_forecastable_markets(markets)
        if not forecastable:
            logger.info("No forecastable markets found")
            return []

        # Batch forecast with Claude
        forecasts = await self.forecaster.batch_forecast(
            forecastable,
            max_concurrent=self.fc_cfg.get("max_concurrent_forecasts", 5),
        )

        # Rebuild full market list for divergence filtering
        raw_markets = [m.get("raw", m) for m in forecastable]
        candidates = self.scanner.filter_divergence_candidates(
            raw_markets, forecasts
        )

        # Filter out markets we already have positions on
        candidates = [
            c for c in candidates
            if not self.positions.has_position_for_market(c["market_id"])
        ]

        # Add sizing info
        for c in candidates:
            self._add_sizing(c)

        return candidates

    def _add_sizing(self, candidate: Dict):
        """Add Kelly-inspired position sizing to candidate."""
        llm_prob = candidate["llm_probability"]
        market_price = candidate["market_yes_price"]
        direction = candidate["direction"]

        # Kelly sizing for binary outcomes
        size_fraction = self._kelly_size(llm_prob, market_price, direction)

        available = self.budget - self.positions.total_deployed()
        max_size = self.budget * self.max_position_pct
        size_usdc = min(max_size, available) * size_fraction

        entry_price = candidate["entry_price"]
        shares = size_usdc / entry_price if entry_price > 0 else 0

        # Polymarket minimum order size is 5 shares
        if shares < 5.0:
            min_cost = 5.0 * entry_price
            available_total = self.budget - self.positions.total_deployed()
            if min_cost <= available_total:
                shares = 5.0
                size_usdc = min_cost
            else:
                size_usdc = 0

        candidate.update({
            "size_usdc": size_usdc,
            "shares": shares,
            "kelly_fraction": size_fraction,
        })

    def _kelly_size(
        self, llm_prob: float, market_price: float, direction: str
    ) -> float:
        """
        Quarter-Kelly sizing for binary outcome markets.

        For buying YES at price p when we estimate true prob = q:
          Kelly f* = (q * (1/p - 1) - (1-q)) / (1/p - 1)
                   = (q - p) / (1 - p)
        Use quarter-Kelly for safety.
        """
        if direction == "YES":
            p = market_price
            q = llm_prob
        else:
            # Buying NO: invert probabilities
            p = 1 - market_price
            q = 1 - llm_prob

        if p <= 0 or p >= 1:
            return 0.25  # Fallback: 25% of max position

        edge = q - p
        if edge <= 0:
            return 0.0  # No edge

        kelly_full = edge / (1 - p)
        kelly_quarter = kelly_full * 0.25

        # Clamp between 10% and 100% of max position
        return max(0.10, min(kelly_quarter, 1.0))

    async def execute(self, candidate: Dict) -> Optional[Dict]:
        """
        Execute a divergence trade.

        Buys YES or NO tokens depending on direction of divergence.
        """
        size_usdc = candidate.get("size_usdc", 0)
        if size_usdc < 1.0:
            logger.warning("Divergence trade size too small: $%.2f", size_usdc)
            return None

        direction = candidate["direction"]
        token_id = candidate["token_id"]
        entry_price = candidate["entry_price"]
        shares = candidate["shares"]

        try:
            result = self.client.buy_limit(
                token_id=token_id,
                price=entry_price,
                size=shares,
            )
        except Exception as e:
            logger.error("Divergence trade failed: %s", e)
            return None

        if not result.get("orderID"):
            logger.error("Divergence order missing orderID: %s", result)
            return None

        order_id = result.get("orderID", "")

        pos = PolyPosition(
            market_id=candidate["market_id"],
            token_id=token_id,
            question=candidate["question"],
            strategy="superforecaster",
            direction=direction,
            entry_price=entry_price,
            size_usdc=size_usdc,
            shares=shares,
            target_exit=candidate["llm_probability"] if direction == "YES"
                        else 1 - candidate["llm_probability"],
            expected_pnl_pct=candidate["abs_divergence"] * 100,
            resolution_date=candidate.get("end_date", ""),
            llm_probability=candidate["llm_probability"],
            market_probability=candidate["market_yes_price"],
            order_id=order_id,
            metadata={
                "reasoning": candidate.get("reasoning", ""),
                "llm_confidence": candidate.get("llm_confidence", 0),
                "kelly_fraction": candidate.get("kelly_fraction", 0),
            },
        )
        key = self.positions.open_position(pos)

        logger.info(
            "DIVERGENCE TRADE: '%s' %s @ %.4f  LLM=%.2f  mkt=%.2f  div=%+.2f  $%.2f",
            candidate["question"][:40], direction, entry_price,
            candidate["llm_probability"], candidate["market_yes_price"],
            candidate["divergence"], size_usdc,
        )

        return {
            "position_key": key,
            "order_id": order_id,
            "question": candidate["question"],
            "direction": direction,
            "entry_price": entry_price,
            "size_usdc": size_usdc,
            "llm_probability": candidate["llm_probability"],
            "market_price": candidate["market_yes_price"],
            "divergence": candidate["divergence"],
        }

    def should_exit(
        self, key: str, current_yes_price: float
    ) -> tuple[bool, str]:
        """
        Check if a divergence position should be closed.

        Exit conditions:
        1. Price converged to within 3% of LLM estimate
        2. Position is up >15% and trailing stop hit

        Returns:
            (should_exit, reason)
        """
        pos = self.positions.positions.get(key)
        if not pos or pos.status != "open":
            return False, ""

        if pos.direction == "YES":
            current_price = current_yes_price
            target = pos.llm_probability
        else:
            current_price = 1 - current_yes_price
            target = 1 - pos.llm_probability

        # Check convergence
        divergence = abs(current_price - target)
        if divergence < self.convergence_threshold:
            return True, f"converged (div={divergence:.3f})"

        # Check trailing profit protection
        gain_pct = (current_price - pos.entry_price) / pos.entry_price
        if gain_pct > 0.15:
            # Protect 50% of gains: if price retraces below 50% of max gain
            protected_price = pos.entry_price + (current_price - pos.entry_price) * 0.5
            if current_price < protected_price:
                return True, f"trailing stop (gain was {gain_pct:.0%})"

        return False, ""

    async def check_and_exit(
        self, key: str, current_yes_price: float
    ) -> Optional[Dict]:
        """Exit a divergence position if exit conditions are met."""
        should_exit, reason = self.should_exit(key, current_yes_price)
        if not should_exit:
            return None

        pos = self.positions.positions[key]
        if pos.direction == "YES":
            current_price = current_yes_price
        else:
            current_price = 1 - current_yes_price

        try:
            result = self.client.sell_market(pos.token_id, pos.shares)
            realized_pnl = (current_price - pos.entry_price) * pos.shares
            self.positions.close_position(key, current_price, realized_pnl)
            logger.info(
                "DIVERGENCE EXIT (%s): '%s' @ %.4f  PnL=$%.4f",
                reason, pos.question[:40], current_price, realized_pnl,
            )
            return {"key": key, "exit_price": current_price, "pnl": realized_pnl, "reason": reason}
        except Exception as e:
            logger.error("Failed to exit divergence trade %s: %s", key, e)
            return None

    async def re_evaluate_positions(self) -> List[Dict]:
        """
        Re-forecast open positions and close if LLM flipped direction.

        Called periodically (every cache_hours) to update convictions.
        """
        exits = []
        open_positions = self.positions.get_positions_by_strategy("superforecaster")

        for key, pos in open_positions.items():
            forecast = await self.forecaster.forecast(
                question=pos.question,
                market_id=pos.market_id,
                market_price=pos.market_probability,
                end_date=pos.resolution_date,
            )

            new_prob = forecast["probability"]
            old_direction_correct = (
                (pos.direction == "YES" and new_prob > pos.market_probability) or
                (pos.direction == "NO" and new_prob < pos.market_probability)
            )

            if not old_direction_correct:
                # LLM flipped — exit immediately
                try:
                    current_price = pos.entry_price
                    mid = self.client.get_midpoint(pos.token_id)
                    if mid > 0:
                        current_price = mid

                    result = self.client.sell_market(pos.token_id, pos.shares)
                    if not result.get("orderID"):
                        logger.error(
                            "LLM flip sell may not have filled for %s: %s",
                            pos.question[:40], result,
                        )
                        continue

                    realized_pnl = (current_price - pos.entry_price) * pos.shares
                    self.positions.close_position(key, current_price, realized_pnl)
                    exits.append({
                        "key": key,
                        "reason": f"LLM flipped: was {pos.direction}, now P={new_prob:.2f}",
                        "pnl": realized_pnl,
                    })
                    logger.warning(
                        "LLM FLIP: '%s' — closing %s position (new P=%.2f)",
                        pos.question[:40], pos.direction, new_prob,
                    )
                except Exception as e:
                    logger.error("Failed to exit flipped position %s: %s", key, e)

        return exits
