"""
Confidence calibration using historical Brier score analysis.

Adjusts raw confidence scores based on how well past predictions at
similar confidence levels actually performed. If the model says 65%
confidence but historically only wins 45% at that level, we scale down.

Requires at least 10 trades per tier to produce meaningful calibration.
Falls back to 1.0 (no adjustment) when insufficient data.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum trades needed for calibration to kick in
MIN_TRADES_FOR_CALIBRATION = 10


def get_calibration_factor(
    tier: str,
    trade_logger,
    days: int = 30,
) -> float:
    """
    Get calibration multiplier for a tier based on historical accuracy.

    If the model's confidence predictions are well-calibrated (confidence
    matches actual win rate), returns ~1.0. If overconfident, returns <1.0.
    If underconfident, returns >1.0 (capped at 1.2).

    Args:
        tier: Shot tier name (e.g. 'layup', 'three_pointer').
        trade_logger: TradeLogger instance with historical data.
        days: Lookback period in days.

    Returns:
        Calibration multiplier (0.7 to 1.2). Default 1.0 if insufficient data.
    """
    if trade_logger is None:
        return 1.0

    try:
        brier_data = trade_logger.compute_brier_score(days=days)
        if not brier_data or not brier_data.get("per_tier"):
            return 1.0

        tier_info = brier_data["per_tier"].get(tier)
        if not tier_info or tier_info["count"] < MIN_TRADES_FOR_CALIBRATION:
            return 1.0

        avg_conf = tier_info["avg_confidence"]
        win_rate = tier_info["win_rate"]

        if avg_conf <= 0:
            return 1.0

        # Calibration ratio: actual performance vs claimed confidence
        # If we claim 60% confidence but only win 40%, ratio = 0.67
        ratio = win_rate / avg_conf
        # Clamp to reasonable range
        factor = max(0.7, min(ratio, 1.2))

        if abs(factor - 1.0) > 0.05:
            logger.info(
                "Calibration %s: avg_conf=%.2f win_rate=%.2f → factor=%.2f (%d trades)",
                tier, avg_conf, win_rate, factor, tier_info["count"],
            )

        return factor

    except Exception as e:
        logger.warning("Calibration failed for %s: %s", tier, e)
        return 1.0


def get_all_calibration_factors(
    trade_logger,
    days: int = 30,
) -> dict:
    """
    Get calibration factors for all tiers at once (more efficient).

    Returns:
        Dict mapping tier name to calibration factor.
    """
    if trade_logger is None:
        return {}

    try:
        brier_data = trade_logger.compute_brier_score(days=days)
        if not brier_data or not brier_data.get("per_tier"):
            return {}

        factors = {}
        for tier, info in brier_data["per_tier"].items():
            if info["count"] < MIN_TRADES_FOR_CALIBRATION:
                continue

            avg_conf = info["avg_confidence"]
            if avg_conf <= 0:
                continue

            ratio = info["win_rate"] / avg_conf
            factors[tier] = max(0.7, min(ratio, 1.2))

        return factors

    except Exception as e:
        logger.warning("Batch calibration failed: %s", e)
        return {}
