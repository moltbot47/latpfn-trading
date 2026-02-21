"""
Polymarket market scanner — discovers and filters tradeable markets.

Uses the Gamma API for market discovery and the CLOB API for
real-time pricing.  Two filter modes:
  1. Resolution candidates: markets resolving soon with high YES price
  2. Divergence candidates: markets where LLM probability differs from price
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MarketScanner:
    """Discovers and filters Polymarket prediction markets."""

    def __init__(self, client, config: dict):
        """
        Args:
            client: PolymarketClient instance (for API calls).
            config: Full config dict (reads polymarket section).
        """
        self.client = client
        self.config = config
        pm_cfg = config.get("polymarket", {})
        self.sniper_cfg = pm_cfg.get("sniper", {})
        self.forecaster_cfg = pm_cfg.get("forecaster", {})

    def scan_markets(self, min_volume: float = 10000) -> List[Dict]:
        """Fetch all active CLOB-tradeable markets from Gamma API."""
        markets = self.client.get_all_active_markets(min_volume=min_volume)
        logger.info("Scanned %d active markets (min_volume=$%.0f)", len(markets), min_volume)
        return markets

    def filter_resolution_candidates(
        self, markets: List[Dict]
    ) -> List[Dict]:
        """
        Find markets suitable for resolution sniping.

        Criteria:
        - Market has an end date within max_hours_to_resolution
        - YES price is between min_yes_price and max_yes_price
        - 24h volume exceeds min_volume_24h
        - Market is not closed/archived
        """
        min_price = self.sniper_cfg.get("min_yes_price", 0.85)
        max_price = self.sniper_cfg.get("max_yes_price", 0.97)
        max_hours = self.sniper_cfg.get("max_hours_to_resolution", 48)
        min_vol = self.sniper_cfg.get("min_volume_24h", 10000)

        now = datetime.now(timezone.utc)
        candidates = []

        for m in markets:
            end_date_str = m.get("endDate")
            if not end_date_str:
                continue

            # Parse end date
            try:
                end_date = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue

            hours_to_resolution = (end_date - now).total_seconds() / 3600
            if hours_to_resolution <= 0 or hours_to_resolution > max_hours:
                continue

            # Check volume
            vol_24h = float(m.get("volume24hr", 0) or 0)
            if vol_24h < min_vol:
                continue

            # Get YES price
            prices = m.get("outcomePrices", [])
            if not prices or len(prices) < 2:
                continue
            yes_price = float(prices[0])

            if yes_price < min_price or yes_price > max_price:
                continue

            # Get token IDs
            token_ids = m.get("clobTokenIds", [])
            if not token_ids or len(token_ids) < 2:
                continue

            edge_pct = (1.0 - yes_price) / yes_price * 100  # % return if resolves YES

            candidates.append({
                "market_id": m.get("conditionId", ""),
                "question": m.get("question", ""),
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1],
                "yes_price": yes_price,
                "no_price": float(prices[1]),
                "edge_pct": edge_pct,
                "hours_to_resolution": hours_to_resolution,
                "end_date": end_date_str,
                "volume_24h": vol_24h,
                "liquidity": float(m.get("liquidityNum", 0) or 0),
                "category": m.get("category", ""),
                "slug": m.get("slug", ""),
                "raw": m,
            })

        # Sort by edge (highest return first)
        candidates.sort(key=lambda c: c["edge_pct"], reverse=True)
        logger.info(
            "Resolution snipe candidates: %d (from %d markets)",
            len(candidates), len(markets),
        )
        return candidates

    def filter_divergence_candidates(
        self,
        markets: List[Dict],
        forecasts: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict]:
        """
        Find markets where LLM probability diverges from market price.

        Args:
            markets:   List of Gamma API market dicts.
            forecasts: Dict of condition_id → forecast result from LLM.
                       If None, returns markets suitable for forecasting.

        Returns:
            List of candidate dicts sorted by |divergence|.
        """
        min_div = self.forecaster_cfg.get("min_divergence", 0.10)
        max_div = self.forecaster_cfg.get("max_divergence", 0.40)
        min_vol = self.forecaster_cfg.get("min_market_volume", 5000)
        confidence_threshold = self.forecaster_cfg.get("confidence_threshold", 0.70)

        candidates = []

        for m in markets:
            vol = float(m.get("volumeNum", 0) or 0)
            if vol < min_vol:
                continue

            prices = m.get("outcomePrices", [])
            if not prices or len(prices) < 2:
                continue

            token_ids = m.get("clobTokenIds", [])
            if not token_ids or len(token_ids) < 2:
                continue

            condition_id = m.get("conditionId", "")
            market_yes_price = float(prices[0])

            # If no forecasts provided, return all viable markets for forecasting
            if forecasts is None:
                candidates.append({
                    "market_id": condition_id,
                    "question": m.get("question", ""),
                    "yes_token_id": token_ids[0],
                    "no_token_id": token_ids[1],
                    "yes_price": market_yes_price,
                    "volume": vol,
                    "end_date": m.get("endDate", ""),
                    "category": m.get("category", ""),
                    "raw": m,
                })
                continue

            # Check if we have a forecast for this market
            forecast = forecasts.get(condition_id)
            if not forecast:
                continue

            llm_prob = forecast.get("probability", 0.5)
            llm_confidence = forecast.get("confidence", 0.0)

            if llm_confidence < confidence_threshold:
                continue

            divergence = llm_prob - market_yes_price
            abs_div = abs(divergence)

            if abs_div < min_div or abs_div > max_div:
                continue

            # Determine trade direction
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
                "volume": vol,
                "end_date": m.get("endDate", ""),
                "category": m.get("category", ""),
                "reasoning": forecast.get("reasoning", ""),
                "raw": m,
            })

        candidates.sort(key=lambda c: c.get("abs_divergence", 0), reverse=True)
        logger.info(
            "Divergence candidates: %d (from %d markets)",
            len(candidates), len(markets),
        )
        return candidates

    def get_forecastable_markets(
        self, markets: Optional[List[Dict]] = None, limit: int = 50
    ) -> List[Dict]:
        """
        Get markets suitable for LLM forecasting.

        Filters for: active, sufficient volume, has end date, not too close
        to resolution (>2h), not too far out (< 30 days).
        """
        if markets is None:
            markets = self.scan_markets()

        min_vol = self.forecaster_cfg.get("min_market_volume", 5000)
        now = datetime.now(timezone.utc)
        result = []

        for m in markets:
            vol = float(m.get("volumeNum", 0) or 0)
            if vol < min_vol:
                continue

            end_str = m.get("endDate")
            if not end_str:
                continue

            try:
                end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            hours_left = (end_date - now).total_seconds() / 3600
            if hours_left < 2 or hours_left > 30 * 24:
                continue

            prices = m.get("outcomePrices", [])
            token_ids = m.get("clobTokenIds", [])
            if not prices or not token_ids or len(prices) < 2 or len(token_ids) < 2:
                continue

            result.append({
                "market_id": m.get("conditionId", ""),
                "question": m.get("question", ""),
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1],
                "yes_price": float(prices[0]),
                "volume": vol,
                "hours_left": hours_left,
                "end_date": end_str,
                "category": m.get("category", ""),
                "raw": m,
            })

        # Sort by volume (most liquid first)
        result.sort(key=lambda x: x["volume"], reverse=True)
        return result[:limit]
