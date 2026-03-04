"""Main KJ strategy scanner — orchestrates swing detection, Fib levels, and pattern matching."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import numpy as np
import pandas as pd

from kj_strategy.setup import KJSetup, SwingPoint, FibLevels, CandlePattern
from kj_strategy.swing_detector import detect_swings
from kj_strategy.fibonacci import pair_swings
from kj_strategy.candlestick_patterns import detect_patterns
from kj_strategy.classifier import classify_setup

logger = logging.getLogger(__name__)

KEY_FIB_LEVELS = ["38.2", "50.0", "61.8"]


def scan_kj_setups(
    instrument: str,
    df: pd.DataFrame,
    min_rr: float = 1.5,
    lookback: int = 10,
    min_swing_pct: float = 0.003,
    fib_tolerance_pct: float = 0.5,
    max_outcome_bars: int = 120,
) -> list[KJSetup]:
    """
    Scan historical OHLCV data for KJ strategy setups.

    Args:
        instrument: Symbol name (e.g. "MNQ")
        df: OHLCV DataFrame with DatetimeIndex
        min_rr: Minimum reward:risk ratio to include
        lookback: Swing detection lookback window
        min_swing_pct: Minimum swing size as % of price
        fib_tolerance_pct: Fib zone tolerance as % of swing range
        max_outcome_bars: Max bars to simulate trade outcome

    Returns:
        List of KJSetup objects sorted by entry timestamp.
    """
    # Step 1: Detect swing highs and lows
    swings = detect_swings(df, lookback=lookback, min_swing_pct=min_swing_pct)
    logger.info("%s: found %d swings", instrument, len(swings))

    if len(swings) < 2:
        return []

    # Step 2: Pair swings and compute Fibonacci levels
    pairs = pair_swings(swings, min_range_pct=min_swing_pct)
    logger.info("%s: found %d valid swing pairs", instrument, len(pairs))

    # Step 3: For each pair, scan for confirmations at Fib levels
    setups: list[KJSetup] = []

    for swing_a, swing_b, fib in pairs:
        # The pullback starts after swing_b (the end of the trend move)
        pullback_start = swing_b.index + 1
        if pullback_start >= len(df) - 5:
            continue

        for level_key in KEY_FIB_LEVELS:
            zone_lo, zone_hi = fib.zone(level_key, tolerance_pct=fib_tolerance_pct)

            # Get pullback data (bars after the swing)
            pullback_end = min(pullback_start + 30, len(df))
            pullback_df = df.iloc[pullback_start:pullback_end].copy()

            if len(pullback_df) < 3:
                continue

            # Check if price reaches this Fib zone
            if fib.direction == "bullish":
                if pullback_df["Low"].min() > zone_hi:
                    continue  # Price didn't pull back far enough
            else:
                if pullback_df["High"].max() < zone_lo:
                    continue

            # Detect patterns within the zone
            patterns = detect_patterns(
                pullback_df, zone_lo, zone_hi, fib.direction, window=15
            )

            if not patterns:
                continue

            # Best confirmation pattern
            best = patterns[0]
            confirm_idx = pullback_start + best.bar_index

            # Calculate trade parameters
            entry, sl, tp, risk, reward = _calc_trade_params(
                df, confirm_idx, fib, level_key, swing_a, swing_b
            )

            if risk <= 0 or reward <= 0:
                continue

            rr = reward / risk
            if rr < min_rr:
                continue

            # Generate setup ID
            setup_id = hashlib.md5(
                f"{instrument}_{swing_a.index}_{swing_b.index}_{level_key}".encode()
            ).hexdigest()[:12]

            setup = KJSetup(
                instrument=instrument,
                setup_id=setup_id,
                swing_high=swing_a if swing_a.swing_type == "high" else swing_b,
                swing_low=swing_a if swing_a.swing_type == "low" else swing_b,
                trend_direction=fib.direction,
                fib_levels=fib,
                active_fib_level=level_key,
                patterns=patterns,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                risk_points=risk,
                reward_points=reward,
                reward_risk_ratio=rr,
                entry_bar_index=confirm_idx,
                entry_timestamp=df.index[confirm_idx],
            )

            # Classify setup quality
            classify_setup(setup, df)

            # Simulate trade outcome
            _simulate_outcome(setup, df, max_bars=max_outcome_bars)

            setups.append(setup)

    logger.info("%s: found %d KJ setups", instrument, len(setups))
    return sorted(setups, key=lambda s: s.entry_bar_index)


def _calc_trade_params(
    df: pd.DataFrame,
    confirm_idx: int,
    fib: FibLevels,
    level_key: str,
    swing_a: SwingPoint,
    swing_b: SwingPoint,
) -> tuple[float, float, float, float, float]:
    """Calculate entry, stop, target, risk, and reward for a setup."""
    entry = float(df["Close"].iloc[confirm_idx])

    if fib.direction == "bullish":
        # Long: stop below pattern low or 78.6% Fib
        pattern_low = float(df["Low"].iloc[max(0, confirm_idx - 2) : confirm_idx + 1].min())
        fib_786 = fib.levels["78.6"]
        sl = min(pattern_low, fib_786) - abs(entry - pattern_low) * 0.1  # small buffer

        # Target: prior swing high (conservative)
        tp = fib.levels["0.0"]  # back to swing high

        risk = abs(entry - sl)
        reward = abs(tp - entry)
    else:
        # Short: stop above pattern high or 78.6% Fib
        pattern_high = float(df["High"].iloc[max(0, confirm_idx - 2) : confirm_idx + 1].max())
        fib_786 = fib.levels["78.6"]
        sl = max(pattern_high, fib_786) + abs(pattern_high - entry) * 0.1

        # Target: prior swing low (conservative)
        tp = fib.levels["0.0"]

        risk = abs(sl - entry)
        reward = abs(entry - tp)

    return entry, sl, tp, risk, reward


def _simulate_outcome(
    setup: KJSetup,
    df: pd.DataFrame,
    max_bars: int = 120,
) -> None:
    """Walk forward through bars after entry to determine trade outcome."""
    start = setup.entry_bar_index + 1
    end = min(start + max_bars, len(df))

    if start >= len(df):
        setup.outcome = "timeout"
        return

    best_price = setup.entry_price
    worst_price = setup.entry_price

    for i in range(start, end):
        bar_h = float(df["High"].iloc[i])
        bar_l = float(df["Low"].iloc[i])

        if setup.trend_direction == "bullish":
            best_price = max(best_price, bar_h)
            worst_price = min(worst_price, bar_l)

            # Stop hit
            if bar_l <= setup.stop_loss:
                setup.outcome = "loss"
                setup.exit_price = setup.stop_loss
                setup.actual_rr = -1.0
                setup.bars_to_exit = i - setup.entry_bar_index
                break

            # Target hit
            if bar_h >= setup.take_profit:
                setup.outcome = "win"
                setup.exit_price = setup.take_profit
                setup.actual_rr = setup.reward_risk_ratio
                setup.bars_to_exit = i - setup.entry_bar_index
                break
        else:
            best_price = min(best_price, bar_l)
            worst_price = max(worst_price, bar_h)

            # Stop hit
            if bar_h >= setup.stop_loss:
                setup.outcome = "loss"
                setup.exit_price = setup.stop_loss
                setup.actual_rr = -1.0
                setup.bars_to_exit = i - setup.entry_bar_index
                break

            # Target hit
            if bar_l <= setup.take_profit:
                setup.outcome = "win"
                setup.exit_price = setup.take_profit
                setup.actual_rr = setup.reward_risk_ratio
                setup.bars_to_exit = i - setup.entry_bar_index
                break
    else:
        # Timed out
        setup.outcome = "timeout"
        setup.exit_price = float(df["Close"].iloc[end - 1])
        pnl = (
            (setup.exit_price - setup.entry_price)
            if setup.trend_direction == "bullish"
            else (setup.entry_price - setup.exit_price)
        )
        setup.actual_rr = pnl / setup.risk_points if setup.risk_points > 0 else 0
        setup.bars_to_exit = end - setup.entry_bar_index

    setup.max_favorable = best_price
    setup.max_adverse = worst_price
