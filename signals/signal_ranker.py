"""
Signal ranker: scores and ranks trading signals across all instruments.

Each cycle the orchestrator generates candidate signals for every instrument.
This module ranks them by a composite score so the system always takes the
highest-conviction trades when position slots are limited.

Scoring formula:
    score = confidence × regime_multiplier × tier_weight × diversification_bonus

Higher score = higher priority for execution.
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tier priority weights — higher tiers are more desirable
TIER_WEIGHTS: Dict[str, float] = {
    "layup": 1.0,
    "short_range": 0.90,
    "free_throw": 0.75,
    "three_pointer": 0.60,
    "half_court": 0.40,
    "hail_mary": 0.20,
}

# Regime scoring — trending markets are preferred
REGIME_SCORES: Dict[str, float] = {
    "trending": 1.0,
    "ranging": 0.80,
    "volatile": 0.60,
}

# Asset class tags for diversification bonus
ASSET_CLASS: Dict[str, str] = {
    "MYM": "equity_index",
    "MNQ": "equity_index",
    "MES": "equity_index",
    "M2K": "equity_index",
    "MCL": "energy",
    "MGC": "metals",
    "M6E": "fx",
    "M6B": "fx",
    "M6A": "fx",
    "M6J": "fx",
    "MBT": "crypto",
    "MET": "crypto",
    "10Y": "bonds",
}


def rank_signals(
    candidates: List[dict],
    open_positions: Dict,
    available_slots: int,
) -> List[dict]:
    """
    Rank candidate signals and return the best ones that fit available slots.

    Args:
        candidates:      List of dicts with keys:
                         - instrument: str
                         - signal: TradingSignal object
                         - prediction: dict
                         - market_regime: dict (from detect_regime)
        open_positions:  Dict of instrument -> Position (currently open).
        available_slots: Number of position slots available.

    Returns:
        Sorted list of candidate dicts (best first), trimmed to available_slots.
        Each dict gets an added 'rank_score' field.
    """
    if not candidates or available_slots <= 0:
        return []

    # Determine which asset classes are already represented in open positions
    open_classes = set()
    for inst in open_positions:
        cls = ASSET_CLASS.get(inst, "unknown")
        open_classes.add(cls)

    scored = []
    for cand in candidates:
        signal = cand["signal"]
        regime_info = cand.get("market_regime", {})
        instrument = cand["instrument"]

        # Skip instruments we already have a position in
        if instrument in open_positions:
            continue

        # Base score: composite confidence (0-1)
        confidence = signal.confidence

        # Tier weight
        tier_w = TIER_WEIGHTS.get(signal.shot_type, 0.5)

        # Regime score
        regime_name = regime_info.get("regime", "ranging")
        regime_w = REGIME_SCORES.get(regime_name, 0.8)

        # Diversification bonus: +15% if this asset class isn't already open
        asset_class = ASSET_CLASS.get(instrument, "unknown")
        all_open_plus_scored = open_classes.copy()
        for prev in scored:
            all_open_plus_scored.add(ASSET_CLASS.get(prev["instrument"], "unknown"))
        diversification_bonus = 1.15 if asset_class not in all_open_plus_scored else 1.0

        # ADX bonus: strong trends get a small boost
        adx = regime_info.get("adx", 20)
        adx_bonus = 1.0 + min(max(adx - 25, 0), 25) / 100  # up to +25% for ADX 50+

        # Composite score
        score = confidence * tier_w * regime_w * diversification_bonus * adx_bonus

        cand["rank_score"] = round(score, 4)
        cand["rank_details"] = {
            "confidence": round(confidence, 3),
            "tier_weight": tier_w,
            "regime": regime_name,
            "regime_weight": regime_w,
            "diversification_bonus": diversification_bonus,
            "adx_bonus": round(adx_bonus, 2),
            "asset_class": asset_class,
        }
        scored.append(cand)

    # Sort by score descending
    scored.sort(key=lambda x: x["rank_score"], reverse=True)

    # Take top N that fit in available slots
    selected = scored[:available_slots]

    if scored:
        logger.info(
            "Signal ranking: %d candidates → top %d selected",
            len(scored), len(selected),
        )
        for i, s in enumerate(scored):
            marker = ">>>" if s in selected else "   "
            logger.info(
                "  %s #%d %s: score=%.4f (conf=%.3f tier=%s regime=%s div=%.2f adx=%.2f)",
                marker, i + 1, s["instrument"], s["rank_score"],
                s["rank_details"]["confidence"],
                s["signal"].shot_type,
                s["rank_details"]["regime"],
                s["rank_details"]["diversification_bonus"],
                s["rank_details"]["adx_bonus"],
            )

    return selected
