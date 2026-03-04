"""Classify KJ setups as 'textbook' (>=75) or 'regular' (<75) on a 0-100 scale."""

from __future__ import annotations

import numpy as np
import pandas as pd

from kj_strategy.setup import KJSetup


def classify_setup(setup: KJSetup, df: pd.DataFrame) -> tuple[str, float]:
    """
    Score a KJ setup on how "textbook" it is.

    Returns:
        (classification, score) where classification is "textbook" or "regular".
    """
    score = 0.0

    # 1. Fib level precision (15 pts) — how close price came to the exact level
    fib_price = setup.fib_levels.levels[setup.active_fib_level]
    rng = abs(setup.fib_levels.swing_high - setup.fib_levels.swing_low)
    if rng > 0:
        # Find the closest bar low/high to the Fib level
        start = setup.swing_low.index if setup.swing_low.index > setup.swing_high.index else setup.swing_high.index
        end = setup.entry_bar_index + 1
        if start < end and start < len(df) and end <= len(df):
            slice_df = df.iloc[start:end]
            if setup.trend_direction == "bullish":
                closest = float(slice_df["Low"].min())
            else:
                closest = float(slice_df["High"].max())
            dist_pct = abs(closest - fib_price) / rng
            if dist_pct < 0.01:
                score += 15
            elif dist_pct < 0.03:
                score += 12
            elif dist_pct < 0.05:
                score += 8
            else:
                score += 3

    # 2. Pattern clarity (20 pts) — confidence of the best confirmation pattern
    if setup.patterns:
        best_conf = setup.patterns[0].confidence
        score += best_conf * 20

    # 3. Trend strength (15 pts) — ADX of the preceding trend
    adx = _simple_adx(df, setup.swing_high.index, setup.swing_low.index)
    if adx > 40:
        score += 15
    elif adx > 30:
        score += 12
    elif adx > 20:
        score += 8
    else:
        score += 3

    # 4. Clean pullback (15 pts) — orderly vs choppy
    pullback_score = _pullback_quality(df, setup)
    score += pullback_score * 15

    # 5. Volume confirmation (10 pts)
    vol_score = _volume_confirmation(df, setup)
    score += vol_score * 10

    # 6. Risk/Reward (15 pts)
    rr = setup.reward_risk_ratio
    if rr >= 4.0:
        score += 15
    elif rr >= 3.0:
        score += 12
    elif rr >= 2.0:
        score += 8
    elif rr >= 1.5:
        score += 5
    else:
        score += 2

    # 7. Multiple confirmations (10 pts)
    n_patterns = len(setup.patterns)
    if n_patterns >= 3:
        score += 10
    elif n_patterns == 2:
        score += 7
    elif n_patterns == 1:
        score += 3

    score = min(100, max(0, score))
    classification = "textbook" if score >= 75 else "regular"

    setup.textbook_score = score
    setup.classification = classification

    return classification, score


def _simple_adx(df: pd.DataFrame, idx_a: int, idx_b: int, period: int = 14) -> float:
    """Compute approximate ADX for the swing range."""
    start = min(idx_a, idx_b)
    end = max(idx_a, idx_b) + 1
    if end - start < period + 2:
        return 15.0  # default moderate

    h = df["High"].values[start:end].astype(float)
    l = df["Low"].values[start:end].astype(float)
    c = df["Close"].values[start:end].astype(float)
    n = len(h)

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = l[i - 1] - l[i]
        plus_dm[i] = up if (up > down and up > 0) else 0
        minus_dm[i] = down if (down > up and down > 0) else 0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    if np.sum(tr[1:period + 1]) == 0:
        return 15.0

    atr = np.mean(tr[1:period + 1])
    plus_di = np.mean(plus_dm[1:period + 1]) / atr * 100 if atr > 0 else 0
    minus_di = np.mean(minus_dm[1:period + 1]) / atr * 100 if atr > 0 else 0

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 15.0
    dx = abs(plus_di - minus_di) / di_sum * 100
    return dx


def _pullback_quality(df: pd.DataFrame, setup: KJSetup) -> float:
    """Score 0-1 for how orderly the pullback was (1 = clean, 0 = choppy)."""
    swing_end = max(setup.swing_high.index, setup.swing_low.index)
    entry = setup.entry_bar_index

    if entry <= swing_end + 2:
        return 0.5

    pb = df.iloc[swing_end:entry + 1]
    closes = pb["Close"].values.astype(float)

    if len(closes) < 3:
        return 0.5

    # Check if pullback was mostly one-directional (few reversals)
    diffs = np.diff(closes)
    if setup.trend_direction == "bullish":
        # Pullback should be mostly down (negative diffs)
        pct_correct = np.sum(diffs < 0) / len(diffs)
    else:
        pct_correct = np.sum(diffs > 0) / len(diffs)

    return min(1.0, pct_correct * 1.3)


def _volume_confirmation(df: pd.DataFrame, setup: KJSetup) -> float:
    """Score 0-1 for volume pattern (decreasing on pullback, increasing on reversal)."""
    if "Volume" not in df.columns:
        return 0.5

    swing_end = max(setup.swing_high.index, setup.swing_low.index)
    entry = setup.entry_bar_index

    if entry <= swing_end + 3 or entry >= len(df):
        return 0.5

    pb_vol = df["Volume"].values[swing_end:entry].astype(float)
    if len(pb_vol) < 2 or np.sum(pb_vol) == 0:
        return 0.5

    # Check if volume decreased during pullback
    first_half = np.mean(pb_vol[: len(pb_vol) // 2])
    second_half = np.mean(pb_vol[len(pb_vol) // 2 :])

    if first_half > 0 and second_half < first_half:
        return min(1.0, 0.6 + (first_half - second_half) / first_half * 0.4)
    return 0.3
