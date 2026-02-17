"""
NBA Shot-Tier Trade Classification System.

Maps composite confidence to a trade tier, each with its own
target distance, stop distance, position size, and R:R requirements.

Tiers (from highest to lowest confidence):
  Layup       → tight target, full size, bread & butter
  Short Range → small-med target, full size
  Free Throw  → medium target, 3/4 size
  3-Pointer   → large target, 1/2 size
  Half Court  → very large target, 1/4 size
  Hail Mary   → huge target, minimum size, lottery ticket

Every tier should be EV-positive: target scales inversely with probability.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Display colors for dashboard (rich markup)
TIER_COLORS = {
    "dunk":         "bold bright_white",
    "alley_oop":    "bold bright_cyan",
    "layup":        "bold bright_green",
    "short_range":  "bold green",
    "free_throw":   "bold yellow",
    "three_pointer": "bold cyan",
    "half_court":   "bold magenta",
    "hail_mary":    "bold red",
}


def classify(confidence: float, tiers_config: dict) -> tuple[str, dict]:
    """
    Classify a confidence score into the appropriate shot tier.

    Tiers are checked from highest confidence_min downward.
    Only enabled tiers are considered.

    Args:
        confidence:   Composite confidence score (0..1).
        tiers_config: config["shot_tiers"] dict.

    Returns:
        (tier_name, tier_params) if a tier matches.
        ("no_trade", {}) if confidence is below all enabled tiers.
    """
    # Sort tiers by confidence_min descending so we match the highest first
    sorted_tiers = sorted(
        tiers_config.items(),
        key=lambda item: item[1]["confidence_min"],
        reverse=True,
    )

    for tier_name, params in sorted_tiers:
        if not params.get("enabled", True):
            continue
        if confidence >= params["confidence_min"]:
            logger.info(
                "Shot classification: %.3f → %s (%s)",
                confidence, params["label"], tier_name,
            )
            return tier_name, params

    logger.debug("Shot classification: %.3f → no_trade (below all tiers)", confidence)
    return "no_trade", {}


def get_tier_color(tier_name: str) -> str:
    """Get Rich markup color for a tier."""
    return TIER_COLORS.get(tier_name, "dim")


def nearest_tier_above(confidence: float, tiers_config: dict) -> tuple[str, float]:
    """
    Find the nearest enabled tier whose threshold is above *confidence*.

    Returns:
        (tier_name, tier_threshold) or ("", 0.0) if already in a tier
        or no enabled tiers exist.
    """
    sorted_tiers = sorted(
        tiers_config.items(),
        key=lambda item: item[1]["confidence_min"],
    )

    for tier_name, params in sorted_tiers:
        if not params.get("enabled", True):
            continue
        threshold = params["confidence_min"]
        if confidence < threshold:
            return tier_name, threshold

    return "", 0.0
