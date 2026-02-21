"""
Orderbook imbalance scoring using Hyperliquid L2 snapshots.

Measures bid/ask volume imbalance at the top of book to detect
buying/selling pressure. Used as an additional confidence factor
in the signal pipeline.

Imbalance > 0 = more bids (buying pressure, bullish)
Imbalance < 0 = more asks (selling pressure, bearish)
"""

import logging
from typing import Optional, Dict

from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)


class OrderbookScorer:
    """Compute orderbook imbalance scores from Hyperliquid L2 data."""

    def __init__(self, network: str = "mainnet"):
        base_url = (
            constants.MAINNET_API_URL
            if network == "mainnet"
            else constants.TESTNET_API_URL
        )
        self._info = Info(base_url, skip_ws=True)
        self._cache: Dict[str, Dict] = {}

    def get_imbalance(self, coin: str, depth: int = 5) -> Optional[Dict]:
        """
        Compute bid/ask imbalance for a coin.

        Args:
            coin: Coin symbol (e.g. 'BTC', 'ETH').
            depth: Number of price levels to consider (default 5).

        Returns:
            Dict with imbalance (-1 to 1), bid_volume, ask_volume,
            spread_pct, or None on failure.
        """
        try:
            book = self._info.l2_snapshot(coin)

            if not book or "levels" not in book:
                return None

            levels = book["levels"]
            if len(levels) < 2:
                return None

            bids = levels[0][:depth]  # [[price, size], ...]
            asks = levels[1][:depth]

            bid_volume = sum(float(level.get("sz", 0)) for level in bids)
            ask_volume = sum(float(level.get("sz", 0)) for level in asks)

            total = bid_volume + ask_volume
            if total <= 0:
                return None

            # Imbalance: positive = more bids (bullish), negative = more asks (bearish)
            imbalance = (bid_volume - ask_volume) / total

            # Spread
            best_bid = float(bids[0].get("px", 0)) if bids else 0
            best_ask = float(asks[0].get("px", 0)) if asks else 0
            mid = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 1
            spread_pct = (best_ask - best_bid) / mid * 100 if mid > 0 else 0

            result = {
                "imbalance": imbalance,
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "spread_pct": spread_pct,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "depth": depth,
            }

            self._cache[coin] = result
            return result

        except Exception as e:
            logger.debug("Orderbook fetch failed for %s: %s", coin, e)
            return self._cache.get(coin)

    def get_confidence_boost(
        self, coin: str, direction: str, depth: int = 5
    ) -> float:
        """
        Get confidence multiplier based on orderbook alignment.

        If direction matches orderbook pressure, returns positive boost.
        If direction opposes orderbook, returns negative penalty.

        Args:
            coin: Coin symbol.
            direction: 'long' or 'short'.
            depth: Orderbook depth levels.

        Returns:
            Multiplier adjustment (-0.05 to +0.05).
        """
        data = self.get_imbalance(coin, depth)
        if data is None:
            return 0.0

        imbalance = data["imbalance"]

        # Align imbalance with direction
        if direction == "long":
            # Positive imbalance (more bids) = aligned = boost
            boost = imbalance * 0.05  # scale to max ±5% confidence adjustment
        else:
            # Negative imbalance (more asks) = aligned for shorts = boost
            boost = -imbalance * 0.05

        return boost
