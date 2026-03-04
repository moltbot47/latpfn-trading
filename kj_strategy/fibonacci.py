"""Fibonacci retracement calculation from swing pairs."""

from __future__ import annotations

from kj_strategy.setup import FibLevels, SwingPoint


def compute_fib_levels(
    swing_a: SwingPoint,
    swing_b: SwingPoint,
) -> FibLevels:
    """
    Compute Fibonacci retracement levels from a swing pair.

    The direction is inferred from the order of swings:
      - swing_a=low, swing_b=high → bullish trend, looking for long on pullback
      - swing_a=high, swing_b=low → bearish trend, looking for short on pullback
    """
    if swing_a.swing_type == "low" and swing_b.swing_type == "high":
        direction = "bullish"
    elif swing_a.swing_type == "high" and swing_b.swing_type == "low":
        direction = "bearish"
    else:
        raise ValueError(
            f"Invalid swing pair: {swing_a.swing_type} → {swing_b.swing_type}. "
            "Need alternating high/low."
        )

    sh = max(swing_a.price, swing_b.price)
    sl = min(swing_a.price, swing_b.price)

    return FibLevels(swing_high=sh, swing_low=sl, direction=direction)


def pair_swings(
    swings: list[SwingPoint],
    min_range_pct: float = 0.005,
) -> list[tuple[SwingPoint, SwingPoint, FibLevels]]:
    """
    Create valid swing pairs for Fibonacci analysis.

    Pairs consecutive alternating swings (high-low or low-high).
    Filters out pairs where the swing range is too small.

    Returns:
        List of (swing_a, swing_b, fib_levels) tuples.
    """
    pairs = []

    for i in range(len(swings) - 1):
        a, b = swings[i], swings[i + 1]

        # Must be alternating types
        if a.swing_type == b.swing_type:
            continue

        # Check minimum range
        rng = abs(a.price - b.price)
        mid = (a.price + b.price) / 2
        if mid > 0 and rng / mid < min_range_pct:
            continue

        try:
            fib = compute_fib_levels(a, b)
            pairs.append((a, b, fib))
        except ValueError:
            continue

    return pairs
