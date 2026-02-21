"""
EMA-based trend filter to prevent counter-trend trades.

Computes fast/slow EMAs on 5-minute close prices and rejects signals
that go against the prevailing trend structure.
"""

import logging
from typing import Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_trend_bias(
    close_prices: np.ndarray,
    fast_period: int = 50,
    slow_period: int = 200,
) -> dict:
    """Compute EMA trend structure from close prices.

    Args:
        close_prices: Array of close prices (oldest first).
        fast_period: Fast EMA period (default 50 = ~4 hours on 5-min bars).
        slow_period: Slow EMA period (default 200 = ~16 hours on 5-min bars).

    Returns:
        dict with bias, EMA values, and price-vs-EMA distances.
    """
    series = pd.Series(close_prices)
    fast_ema = series.ewm(span=fast_period, adjust=False).mean().iloc[-1]
    slow_ema = series.ewm(span=slow_period, adjust=False).mean().iloc[-1]
    current_price = close_prices[-1]

    price_vs_fast = (current_price - fast_ema) / fast_ema * 100
    price_vs_slow = (current_price - slow_ema) / slow_ema * 100

    if current_price > fast_ema and current_price > slow_ema:
        bias = "bullish"
    elif current_price < fast_ema and current_price < slow_ema:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "fast_ema": float(fast_ema),
        "slow_ema": float(slow_ema),
        "price_vs_fast": float(price_vs_fast),
        "price_vs_slow": float(price_vs_slow),
    }


def check_trend_alignment(
    direction: str, trend_bias: dict, mode: str = "gate"
) -> Tuple[bool, str]:
    """Check if signal direction aligns with EMA trend.

    Args:
        direction: 'long' or 'short'.
        trend_bias: Output from compute_trend_bias().
        mode: 'gate' = hard block counter-trend, 'soft' = allow with penalty flag.

    Returns:
        (allowed, reason) — allowed=True if trade is permitted.
        In soft mode, counter-trend signals are allowed but reason includes
        'SOFT_PENALTY' marker for the caller to apply a confidence multiplier.
    """
    bias = trend_bias["bias"]

    if bias == "bearish" and direction == "long":
        detail = f"long vs bearish EMA (price {trend_bias['price_vs_fast']:+.2f}% vs fast, {trend_bias['price_vs_slow']:+.2f}% vs slow)"
        if mode == "soft":
            return True, f"SOFT_PENALTY: {detail}"
        return False, f"long blocked by bearish EMA (price {trend_bias['price_vs_fast']:+.2f}% vs fast, {trend_bias['price_vs_slow']:+.2f}% vs slow)"

    if bias == "bullish" and direction == "short":
        detail = f"short vs bullish EMA (price {trend_bias['price_vs_fast']:+.2f}% vs fast, {trend_bias['price_vs_slow']:+.2f}% vs slow)"
        if mode == "soft":
            return True, f"SOFT_PENALTY: {detail}"
        return False, f"short blocked by bullish EMA (price {trend_bias['price_vs_fast']:+.2f}% vs fast, {trend_bias['price_vs_slow']:+.2f}% vs slow)"

    return True, f"aligned with {bias} trend"
