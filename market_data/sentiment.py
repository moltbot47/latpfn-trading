"""
Crypto Fear & Greed Index integration.

Polls the Alternative.me API for the daily Fear & Greed Index
and uses it as a contrarian confidence multiplier:
  - Extreme Fear (<25): boost long confidence (contrarian buy)
  - Extreme Greed (>75): boost short confidence (contrarian sell)
  - Neutral (25-75): no adjustment

API: https://api.alternative.me/fng/
Updates daily, cached for 1 hour.
"""

import logging
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Cache TTL: 1 hour (index updates daily, no need to poll frequently)
CACHE_TTL_SECONDS = 3600

# API endpoint (free, no auth required)
FNG_API_URL = "https://api.alternative.me/fng/?limit=1"


class SentimentFilter:
    """Crypto Fear & Greed Index-based sentiment filter."""

    def __init__(self):
        self._cached_value: Optional[int] = None
        self._cached_label: str = "unknown"
        self._last_fetch: float = 0

    def get_fear_greed(self) -> Dict:
        """
        Fetch the current Fear & Greed Index value.

        Returns:
            Dict with value (0-100), label, and timestamp.
            Returns cached value if within TTL.
        """
        now = time.time()
        if self._cached_value is not None and (now - self._last_fetch) < CACHE_TTL_SECONDS:
            return {
                "value": self._cached_value,
                "label": self._cached_label,
                "cached": True,
            }

        try:
            import urllib.request
            import json

            req = urllib.request.Request(FNG_API_URL)
            req.add_header("User-Agent", "LaT-PFN-Trading/1.0")

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())

            if "data" in data and len(data["data"]) > 0:
                entry = data["data"][0]
                self._cached_value = int(entry["value"])
                self._cached_label = entry.get("value_classification", "unknown")
                self._last_fetch = now

                logger.info(
                    "Fear & Greed Index: %d (%s)",
                    self._cached_value, self._cached_label,
                )

                return {
                    "value": self._cached_value,
                    "label": self._cached_label,
                    "cached": False,
                }

        except Exception as e:
            logger.debug("Fear & Greed fetch failed: %s", e)

        # Return cached or default
        if self._cached_value is not None:
            return {
                "value": self._cached_value,
                "label": self._cached_label,
                "cached": True,
            }

        return {"value": 50, "label": "neutral", "cached": True}

    def get_confidence_multiplier(self, direction: str) -> float:
        """
        Get contrarian confidence multiplier based on sentiment.

        Extreme fear = boost longs (crowd is too bearish, likely bounce)
        Extreme greed = boost shorts (crowd is too bullish, likely correction)

        Args:
            direction: 'long' or 'short'.

        Returns:
            Multiplier (0.90 to 1.15). Default 1.0 for neutral sentiment.
        """
        fng = self.get_fear_greed()
        value = fng["value"]

        if value <= 20:
            # Extreme fear — contrarian long opportunity
            if direction == "long":
                return 1.15  # 15% boost
            else:
                return 0.90  # 10% penalty for shorting into fear
        elif value <= 35:
            # Fear — mild contrarian long signal
            if direction == "long":
                return 1.05
            else:
                return 0.95
        elif value >= 80:
            # Extreme greed — contrarian short opportunity
            if direction == "short":
                return 1.15
            else:
                return 0.90
        elif value >= 65:
            # Greed — mild contrarian short signal
            if direction == "short":
                return 1.05
            else:
                return 0.95

        # Neutral zone (35-65) — no adjustment
        return 1.0
