"""Price action pattern detection at Fibonacci retracement zones."""

from __future__ import annotations

import numpy as np
import pandas as pd

from kj_strategy.setup import CandlePattern


def detect_patterns(
    df: pd.DataFrame,
    zone_low: float,
    zone_high: float,
    direction: str,
    window: int = 8,
) -> list[CandlePattern]:
    """
    Detect price action confirmation patterns within a Fib zone.

    Args:
        df: OHLCV DataFrame (the pullback + reversal portion)
        zone_low: Lower bound of the Fib zone
        zone_high: Upper bound of the Fib zone
        direction: "bullish" (looking for buy patterns) or "bearish" (sell patterns)
        window: Max bars to look for patterns after price enters the zone

    Returns:
        List of detected patterns, sorted by confidence (highest first).
    """
    patterns: list[CandlePattern] = []

    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values  # noqa: E741
    c = df["Close"].values
    n = len(df)

    for i in range(1, min(n, window)):
        bar_low = float(l[i])
        bar_high = float(h[i])

        # Check if this bar touches the Fib zone
        in_zone = bar_low <= zone_high and bar_high >= zone_low
        if not in_zone:
            continue

        # Run all pattern detectors
        for detector in _DETECTORS:
            result = detector(df, i, zone_low, zone_high, direction)
            if result is not None:
                patterns.append(result)

    # Deduplicate: keep highest confidence per bar
    seen: dict[int, CandlePattern] = {}
    for p in patterns:
        if p.bar_index not in seen or p.confidence > seen[p.bar_index].confidence:
            seen[p.bar_index] = p

    return sorted(seen.values(), key=lambda p: p.confidence, reverse=True)


# ── Pattern Detectors ──────────────────────────────────────────────


def _detect_hammer(
    df: pd.DataFrame, i: int, zone_low: float, zone_high: float, direction: str
) -> CandlePattern | None:
    """Hammer (bullish) or inverted hammer (bearish) at Fib level."""
    o, h, l, c = (
        float(df["Open"].iloc[i]),
        float(df["High"].iloc[i]),
        float(df["Low"].iloc[i]),
        float(df["Close"].iloc[i]),
    )

    body = abs(c - o)
    full_range = h - l
    if full_range < 1e-10:
        return None

    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)

    if direction == "bullish":
        # Hammer: long lower wick, small body at top
        if lower_wick < body * 1.5:
            return None
        wick_ratio = lower_wick / full_range
        if wick_ratio < 0.55:
            return None
        confidence = min(1.0, wick_ratio * 0.8 + (0.2 if c > o else 0.0))
        return CandlePattern(
            pattern_type="hammer",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Hammer with {wick_ratio:.0%} lower wick rejection",
        )
    else:
        # Inverted hammer / shooting star: long upper wick
        if upper_wick < body * 1.5:
            return None
        wick_ratio = upper_wick / full_range
        if wick_ratio < 0.55:
            return None
        confidence = min(1.0, wick_ratio * 0.8 + (0.2 if c < o else 0.0))
        return CandlePattern(
            pattern_type="shooting_star",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Shooting star with {wick_ratio:.0%} upper wick rejection",
        )


def _detect_engulfing(
    df: pd.DataFrame, i: int, zone_low: float, zone_high: float, direction: str
) -> CandlePattern | None:
    """Bullish or bearish engulfing pattern."""
    if i < 1:
        return None

    o0 = float(df["Open"].iloc[i - 1])
    c0 = float(df["Close"].iloc[i - 1])
    o1 = float(df["Open"].iloc[i])
    c1 = float(df["Close"].iloc[i])

    body0 = abs(c0 - o0)
    body1 = abs(c1 - o1)

    if body0 < 1e-10 or body1 < body0 * 1.1:
        return None

    if direction == "bullish":
        # Bearish candle followed by larger bullish candle
        if c0 >= o0 or c1 <= o1:
            return None
        if not (o1 <= c0 and c1 >= o0):
            return None
        engulf_ratio = body1 / body0
        confidence = min(1.0, 0.5 + engulf_ratio * 0.15)
        return CandlePattern(
            pattern_type="bullish_engulfing",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Bullish engulfing ({engulf_ratio:.1f}x body ratio)",
        )
    else:
        # Bullish candle followed by larger bearish candle
        if c0 <= o0 or c1 >= o1:
            return None
        if not (o1 >= c0 and c1 <= o0):
            return None
        engulf_ratio = body1 / body0
        confidence = min(1.0, 0.5 + engulf_ratio * 0.15)
        return CandlePattern(
            pattern_type="bearish_engulfing",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Bearish engulfing ({engulf_ratio:.1f}x body ratio)",
        )


def _detect_wick_rejection(
    df: pd.DataFrame, i: int, zone_low: float, zone_high: float, direction: str
) -> CandlePattern | None:
    """Long wick into the Fib zone followed by close outside."""
    o = float(df["Open"].iloc[i])
    h = float(df["High"].iloc[i])
    l = float(df["Low"].iloc[i])  # noqa: E741
    c = float(df["Close"].iloc[i])

    full_range = h - l
    if full_range < 1e-10:
        return None

    if direction == "bullish":
        # Wick dips into zone but closes above it
        if l > zone_high or c < zone_high:
            return None
        penetration = zone_high - l
        rejection_pct = penetration / full_range
        if rejection_pct < 0.3:
            return None
        confidence = min(1.0, rejection_pct * 0.9 + (0.1 if c > o else 0.0))
        return CandlePattern(
            pattern_type="wick_rejection",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Wick rejection — {rejection_pct:.0%} of range rejected from zone",
        )
    else:
        # Wick pokes into zone but closes below it
        if h < zone_low or c > zone_low:
            return None
        penetration = h - zone_low
        rejection_pct = penetration / full_range
        if rejection_pct < 0.3:
            return None
        confidence = min(1.0, rejection_pct * 0.9 + (0.1 if c < o else 0.0))
        return CandlePattern(
            pattern_type="wick_rejection",
            bar_index=i,
            timestamp=df.index[i],
            confidence=confidence,
            description=f"Wick rejection — {rejection_pct:.0%} of range rejected from zone",
        )


def _detect_double_bottom_top(
    df: pd.DataFrame, i: int, zone_low: float, zone_high: float, direction: str
) -> CandlePattern | None:
    """Double bottom (bullish) or double top (bearish) within the Fib zone."""
    if i < 3:
        return None

    l_arr = df["Low"].values  # noqa: E741
    h_arr = df["High"].values

    if direction == "bullish":
        # Look for a prior low in the zone within the last 3-8 bars
        current_low = float(l_arr[i])
        if current_low > zone_high:
            return None
        for j in range(max(0, i - 8), i - 1):
            prior_low = float(l_arr[j])
            if prior_low > zone_high:
                continue
            # Both lows in the zone, second doesn't make new low
            diff_pct = abs(current_low - prior_low) / max(abs(current_low), 1e-10)
            if diff_pct < 0.003 and current_low >= prior_low * 0.998:
                # Rally between the two lows
                mid_high = float(np.max(h_arr[j : i + 1]))
                rally = mid_high - min(current_low, prior_low)
                if rally > 0:
                    confidence = min(1.0, 0.6 + (1.0 - diff_pct) * 0.4)
                    return CandlePattern(
                        pattern_type="double_bottom",
                        bar_index=i,
                        timestamp=df.index[i],
                        confidence=confidence,
                        description=f"Double bottom at {current_low:.2f} (prior: {prior_low:.2f})",
                        metadata={
                            "prior_bar_index": j,
                            "prior_price": prior_low,
                            "current_price": current_low,
                            "prior_timestamp": df.index[j],
                        },
                    )
    else:
        current_high = float(h_arr[i])
        if current_high < zone_low:
            return None
        for j in range(max(0, i - 8), i - 1):
            prior_high = float(h_arr[j])
            if prior_high < zone_low:
                continue
            diff_pct = abs(current_high - prior_high) / max(abs(current_high), 1e-10)
            if diff_pct < 0.003 and current_high <= prior_high * 1.002:
                mid_low = float(np.min(l_arr[j : i + 1]))
                dip = max(current_high, prior_high) - mid_low
                if dip > 0:
                    confidence = min(1.0, 0.6 + (1.0 - diff_pct) * 0.4)
                    return CandlePattern(
                        pattern_type="double_top",
                        bar_index=i,
                        timestamp=df.index[i],
                        confidence=confidence,
                        description=f"Double top at {current_high:.2f} (prior: {prior_high:.2f})",
                        metadata={
                            "prior_bar_index": j,
                            "prior_price": prior_high,
                            "current_price": current_high,
                            "prior_timestamp": df.index[j],
                        },
                    )

    return None


def _detect_doji(
    df: pd.DataFrame, i: int, zone_low: float, zone_high: float, direction: str
) -> CandlePattern | None:
    """Doji candle (tiny body) at a Fib level indicating indecision."""
    o = float(df["Open"].iloc[i])
    h = float(df["High"].iloc[i])
    l = float(df["Low"].iloc[i])  # noqa: E741
    c = float(df["Close"].iloc[i])

    body = abs(c - o)
    full_range = h - l
    if full_range < 1e-10:
        return None

    body_pct = body / full_range
    if body_pct > 0.10:  # body must be < 10% of range
        return None

    # Must be in the zone
    mid = (o + c) / 2
    if mid < zone_low or mid > zone_high:
        return None

    confidence = min(1.0, (0.10 - body_pct) * 8)  # smaller body = higher conf
    return CandlePattern(
        pattern_type="doji",
        bar_index=i,
        timestamp=df.index[i],
        confidence=confidence,
        description=f"Doji at Fib level (body {body_pct:.1%} of range)",
    )


# Registry of all pattern detectors
_DETECTORS = [
    _detect_hammer,
    _detect_engulfing,
    _detect_wick_rejection,
    _detect_double_bottom_top,
    _detect_doji,
]
