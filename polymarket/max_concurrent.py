"""
Max Concurrent strategy — places many small ($1) bets across all markets
where Claude's probability estimate diverges from the market price.

Unlike the Superforecaster strategy which uses Kelly sizing and targets
high-conviction plays, this strategy spreads risk across many positions
with fixed $1 sizing and a lower divergence threshold (7% vs 10%).

Budget: 35% of account balance, allocated independently from other strategies.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from polymarket.positions import PolyPosition

logger = logging.getLogger(__name__)


class MaxConcurrentStrategy:
    """Places many small divergence bets across Polymarket."""

    def __init__(self, client, scanner, forecaster, position_mgr, config: dict):
        self.client = client
        self.scanner = scanner
        self.forecaster = forecaster
        self.positions = position_mgr
        pm_cfg = config.get("polymarket", {})
        self.mc_cfg = pm_cfg.get("max_concurrent", {})
        self.budget = pm_cfg.get("budget_usdc", 15.0) * self.mc_cfg.get("budget_pct", 0.35)
        self.bet_size = self.mc_cfg.get("bet_size_usdc", 1.0)
        self.min_divergence = self.mc_cfg.get("min_divergence", 0.07)
        self.max_divergence = self.mc_cfg.get("max_divergence", 0.40)
        self.max_positions = self.mc_cfg.get("max_positions", 45)
        self.scan_limit = self.mc_cfg.get("scan_limit", 100)
        self.max_concurrent_forecasts = self.mc_cfg.get("max_concurrent_forecasts", 8)
        self.confidence_threshold = self.mc_cfg.get("confidence_threshold", 0.60)
        self.exit_hours = self.mc_cfg.get("exit_hours", 4)
        self.stop_loss_pct = self.mc_cfg.get("stop_loss_pct", 30)
        self.convergence_threshold = 0.03

    async def find_candidates(
        self, markets: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Scan markets, forecast with LLM, find divergence opportunities.

        Uses lower divergence threshold and scans more markets than
        the superforecaster to maximize the number of positions.
        """
        forecastable = self.scanner.get_forecastable_markets(
            markets, limit=self.scan_limit
        )
        if not forecastable:
            logger.info("[MC] No forecastable markets found")
            return []

        logger.info("[MC] Forecasting %d markets...", len(forecastable))
        forecasts = await self.forecaster.batch_forecast(
            forecastable,
            max_concurrent=self.max_concurrent_forecasts,
        )

        # Build divergence candidates with our lower threshold
        raw_markets = [m.get("raw", m) for m in forecastable]
        candidates = self._filter_candidates(raw_markets, forecasts)

        # Filter out markets we already have positions on (any strategy)
        candidates = [
            c for c in candidates
            if not self.positions.has_position_for_market(c["market_id"])
        ]

        # Add fixed sizing
        for c in candidates:
            self._add_sizing(c)

        # Remove candidates that can't meet minimum share requirement
        candidates = [c for c in candidates if c.get("size_usdc", 0) >= 0.50]

        # Cap to max_positions minus current mc positions
        current_mc = len(self.positions.get_positions_by_strategy("max_concurrent"))
        slots = max(0, self.max_positions - current_mc)
        candidates = candidates[:slots]

        logger.info(
            "[MC] %d candidates (slots=%d, current=%d)",
            len(candidates), slots, current_mc,
        )
        return candidates

    def _filter_candidates(
        self, markets: List[Dict], forecasts: Dict[str, Dict]
    ) -> List[Dict]:
        """Filter for divergence using our lower threshold."""
        candidates = []

        for m in markets:
            prices = m.get("outcomePrices", [])
            if not prices or len(prices) < 2:
                continue

            token_ids = m.get("clobTokenIds", [])
            if not token_ids or len(token_ids) < 2:
                continue

            condition_id = m.get("conditionId", "")
            forecast = forecasts.get(condition_id)
            if not forecast:
                continue

            llm_prob = forecast.get("probability", 0.5)
            llm_confidence = forecast.get("confidence", 0.0)

            if llm_confidence < self.confidence_threshold:
                continue

            market_yes_price = float(prices[0])
            divergence = llm_prob - market_yes_price
            abs_div = abs(divergence)

            if abs_div < self.min_divergence or abs_div > self.max_divergence:
                continue

            if divergence > 0:
                direction = "YES"
                token_id = token_ids[0]
                entry_price = market_yes_price
            else:
                direction = "NO"
                token_id = token_ids[1]
                entry_price = float(prices[1])

            candidates.append({
                "market_id": condition_id,
                "question": m.get("question", ""),
                "token_id": token_id,
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1],
                "direction": direction,
                "market_yes_price": market_yes_price,
                "llm_probability": llm_prob,
                "llm_confidence": llm_confidence,
                "divergence": divergence,
                "abs_divergence": abs_div,
                "entry_price": entry_price,
                "volume": float(m.get("volumeNum", 0) or 0),
                "end_date": m.get("endDate", ""),
                "category": m.get("category", ""),
                "reasoning": forecast.get("reasoning", ""),
                "raw": m,
            })

        candidates.sort(key=lambda c: c["abs_divergence"], reverse=True)
        return candidates

    def _add_sizing(self, candidate: Dict):
        """Add fixed $1 sizing to candidate."""
        entry_price = candidate["entry_price"]
        if entry_price <= 0:
            candidate["size_usdc"] = 0
            candidate["shares"] = 0
            return

        shares = self.bet_size / entry_price

        # Polymarket minimum order: 5 shares
        if shares < 5.0:
            min_cost = 5.0 * entry_price
            mc_deployed = sum(
                p.size_usdc
                for p in self.positions.get_positions_by_strategy("max_concurrent").values()
            )
            if min_cost <= self.budget - mc_deployed:
                shares = 5.0
                candidate["size_usdc"] = min_cost
            else:
                candidate["size_usdc"] = 0
                candidate["shares"] = 0
                return
        else:
            candidate["size_usdc"] = self.bet_size

        candidate["shares"] = shares

    async def execute(self, candidate: Dict) -> Optional[Dict]:
        """Execute a max-concurrent trade — fixed $1 bet."""
        size_usdc = candidate.get("size_usdc", 0)
        if size_usdc < 0.50:
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
            logger.error("[MC] Trade failed: %s", e)
            return None

        if not result.get("orderID"):
            logger.error("[MC] Order missing orderID: %s", result)
            return None

        order_id = result.get("orderID", "")

        pos = PolyPosition(
            market_id=candidate["market_id"],
            token_id=token_id,
            question=candidate["question"],
            strategy="max_concurrent",
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
            },
        )
        key = self.positions.open_position(pos)

        logger.info(
            "[MC] TRADE: '%s' %s @ %.4f  LLM=%.2f  mkt=%.2f  div=%+.2f  $%.2f",
            candidate["question"][:40], direction, entry_price,
            candidate["llm_probability"], candidate["market_yes_price"],
            candidate["divergence"], size_usdc,
        )

        return {
            "position_key": key,
            "order_id": order_id,
            "question": candidate["question"],
            "strategy": "max_concurrent",
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
        Check if a max-concurrent position should be closed.

        Exit conditions:
        1. Convergence: price within 3% of LLM estimate
        2. Time-based: position open > exit_hours
        3. Stop loss: price down > stop_loss_pct from entry
        4. Resolution imminent: < 1 hour to end_date
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

        # 1. Convergence exit
        divergence = abs(current_price - target)
        if divergence < self.convergence_threshold:
            return True, f"converged (div={divergence:.3f})"

        # 2. Time-based exit
        if pos.opened_at:
            try:
                opened = datetime.fromisoformat(
                    pos.opened_at.replace("Z", "+00:00")
                )
                hours_open = (
                    datetime.now(timezone.utc) - opened
                ).total_seconds() / 3600
                if hours_open >= self.exit_hours:
                    return True, f"time exit ({hours_open:.1f}h)"
            except (ValueError, TypeError):
                pass

        # 3. Stop loss
        if pos.entry_price > 0:
            loss_pct = (pos.entry_price - current_price) / pos.entry_price * 100
            if loss_pct >= self.stop_loss_pct:
                return True, f"stop loss ({loss_pct:.0f}% down)"

        # 4. Resolution imminent
        if pos.resolution_date:
            try:
                end = datetime.fromisoformat(
                    pos.resolution_date.replace("Z", "+00:00")
                )
                hours_left = (end - datetime.now(timezone.utc)).total_seconds() / 3600
                if 0 < hours_left < 1:
                    return True, "resolution imminent (<1h)"
            except (ValueError, TypeError):
                pass

        return False, ""

    async def check_and_exit(
        self, key: str, current_yes_price: float
    ) -> Optional[Dict]:
        """Exit a max-concurrent position if exit conditions are met."""
        should_exit, reason = self.should_exit(key, current_yes_price)
        if not should_exit:
            return None

        pos = self.positions.positions[key]
        if pos.direction == "YES":
            current_price = current_yes_price
        else:
            current_price = 1 - current_yes_price

        try:
            self.client.sell_market(pos.token_id, pos.shares)
            realized_pnl = (current_price - pos.entry_price) * pos.shares
            self.positions.close_position(key, current_price, realized_pnl)
            logger.info(
                "[MC] EXIT (%s): '%s' @ %.4f  PnL=$%.4f",
                reason, pos.question[:40], current_price, realized_pnl,
            )
            return {
                "key": key,
                "strategy": "max_concurrent",
                "exit_price": current_price,
                "pnl": realized_pnl,
                "reason": reason,
                "question": pos.question,
            }
        except Exception as e:
            logger.error("[MC] Failed to exit %s: %s", key, e)
            return None
