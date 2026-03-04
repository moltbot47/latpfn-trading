"""Swing high/low detection from OHLCV data."""

from __future__ import annotations

import pandas as pd

from kj_strategy.setup import SwingPoint


def detect_swings(
    df: pd.DataFrame,
    lookback: int = 10,
    min_swing_pct: float = 0.003,
) -> list[SwingPoint]:
    """
    Find significant swing highs and lows using a rolling-window approach.

    A bar is a swing high if its High is the highest in `lookback` bars on both sides.
    A bar is a swing low if its Low is the lowest in `lookback` bars on both sides.

    Args:
        df: OHLCV DataFrame with columns: Open, High, Low, Close
        lookback: Number of bars on each side to check dominance
        min_swing_pct: Minimum swing size as fraction of price (filters noise)

    Returns:
        List of SwingPoint sorted by bar index.
    """
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    swings: list[SwingPoint] = []

    for i in range(lookback, n - lookback):
        # Check swing high
        window_highs = highs[i - lookback : i + lookback + 1]
        if highs[i] == window_highs.max() and highs[i] > highs[i - 1]:
            # Verify minimum swing size vs nearby lows
            nearby_low = lows[i - lookback : i + lookback + 1].min()
            swing_pct = (highs[i] - nearby_low) / highs[i]
            if swing_pct >= min_swing_pct:
                swings.append(
                    SwingPoint(
                        index=i,
                        timestamp=df.index[i],
                        price=float(highs[i]),
                        swing_type="high",
                        strength=lookback,
                    )
                )

        # Check swing low
        window_lows = lows[i - lookback : i + lookback + 1]
        if lows[i] == window_lows.min() and lows[i] < lows[i - 1]:
            # Verify minimum swing size vs nearby highs
            nearby_high = highs[i - lookback : i + lookback + 1].max()
            swing_pct = (nearby_high - lows[i]) / nearby_high
            if swing_pct >= min_swing_pct:
                swings.append(
                    SwingPoint(
                        index=i,
                        timestamp=df.index[i],
                        price=float(lows[i]),
                        swing_type="low",
                        strength=lookback,
                    )
                )

    # Remove duplicates: if multiple swing highs/lows are adjacent, keep the most extreme
    swings = _deduplicate_swings(swings, highs, lows, min_gap=lookback // 2)

    return sorted(swings, key=lambda s: s.index)


def _deduplicate_swings(
    swings: list[SwingPoint],
    highs,
    lows,
    min_gap: int = 5,
) -> list[SwingPoint]:
    """Remove adjacent swing points of the same type, keeping the most extreme."""
    if not swings:
        return swings

    swings = sorted(swings, key=lambda s: s.index)
    result: list[SwingPoint] = [swings[0]]

    for s in swings[1:]:
        prev = result[-1]
        if s.swing_type == prev.swing_type and abs(s.index - prev.index) < min_gap:
            # Same type, close together — keep the more extreme one
            if s.swing_type == "high" and s.price > prev.price:
                result[-1] = s
            elif s.swing_type == "low" and s.price < prev.price:
                result[-1] = s
        else:
            result.append(s)

    return result
