"""
Market-data-based regime detection.

Classifies the current market state using observed price data and
volatility indicators rather than forecast shape. This provides
a more accurate regime signal that can modulate position sizing
and stop distances.

Methods:
  1. Realized volatility percentile (20-day vol vs. 1-year distribution)
  2. ADX (Average Directional Index) for trend strength
  3. VIX level (if available in context data)

The regime is used to scale position sizing, NOT signal confidence,
per quant best practice.
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def detect_regime(
    price_df: pd.DataFrame,
    vix_df: pd.DataFrame | None = None,
) -> dict:
    """
    Detect market regime from observed price data.

    Args:
        price_df: OHLCV DataFrame for the target instrument (needs 60+ rows).
        vix_df:   Optional VIX OHLCV DataFrame for volatility context.

    Returns:
        {
            "regime": str,           # "trending" | "ranging" | "volatile"
            "adx": float,            # 0-100, trend strength
            "realized_vol_pctile": float,  # 0-100, where current vol sits historically
            "vix_level": float | None,     # current VIX if available
            "vix_percentile": float | None, # VIX vs. recent history
            "size_multiplier": float,       # 0.5-1.0, regime-based sizing adjustment
        }
    """
    close = price_df["Close"].values
    high = price_df["High"].values
    low = price_df["Low"].values

    # 1. ADX (Average Directional Index)
    adx = _compute_adx(high, low, close, period=14)

    # 2. Realized volatility percentile
    vol_pctile = _realized_vol_percentile(close, short_window=20, long_window=252)

    # 3. VIX level and percentile
    vix_level = None
    vix_pctile = None
    if vix_df is not None and len(vix_df) >= 60:
        vix_close = vix_df["Close"].values
        vix_level = float(vix_close[-1])
        # Percentile over last ~1 year of VIX data
        if len(vix_close) >= 60:
            vix_pctile = float(
                np.sum(vix_close[-252:] <= vix_level) / min(len(vix_close), 252) * 100
            )

    # Classify regime
    regime, size_mult = _classify(adx, vol_pctile, vix_pctile)

    return {
        "regime": regime,
        "adx": round(adx, 1),
        "realized_vol_pctile": round(vol_pctile, 1),
        "vix_level": round(vix_level, 2) if vix_level is not None else None,
        "vix_percentile": round(vix_pctile, 1) if vix_pctile is not None else None,
        "size_multiplier": size_mult,
    }


def _classify(
    adx: float,
    vol_pctile: float,
    vix_pctile: float | None,
) -> tuple[str, float]:
    """
    Regime classification logic.

    Returns (regime_name, size_multiplier).

    Size multiplier scales position size:
      - trending: 1.0 (full size — trends are where money is made)
      - ranging: 0.75 (reduced — mean-reversion prone, smaller moves)
      - volatile: 0.5 (half size — wider stops needed, protect capital)
    """
    # Volatile: high realized vol OR high VIX
    is_volatile = vol_pctile > 80
    if vix_pctile is not None:
        is_volatile = is_volatile or vix_pctile > 80

    # Trending: strong ADX
    is_trending = adx > 25

    if is_volatile:
        return "volatile", 0.5
    elif is_trending:
        return "trending", 1.0
    else:
        return "ranging", 0.75


def _realized_vol_percentile(
    close: np.ndarray,
    short_window: int = 20,
    long_window: int = 252,
) -> float:
    """
    Where current 20-day realized volatility sits in its 1-year distribution.

    Returns percentile (0-100).
    """
    if len(close) < short_window + 2:
        return 50.0  # default to median if insufficient data

    # Log returns
    returns = np.diff(np.log(close + 1e-10))

    # Rolling volatility (annualized)
    if len(returns) < long_window:
        long_window = len(returns)

    current_vol = np.std(returns[-short_window:]) * np.sqrt(252)

    # Historical rolling vols
    vols = []
    for i in range(short_window, min(len(returns), long_window)):
        v = np.std(returns[i - short_window : i]) * np.sqrt(252)
        vols.append(v)

    if not vols:
        return 50.0

    percentile = np.sum(np.array(vols) <= current_vol) / len(vols) * 100
    return float(percentile)


def _compute_adx(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> float:
    """
    Compute the Average Directional Index (ADX).

    ADX > 25 = trending, ADX < 20 = ranging.
    Returns the latest ADX value (0-100).
    """
    n = len(close)
    if n < period + 2:
        return 20.0  # default neutral

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Smoothed averages (Wilder's smoothing)
    atr = _wilder_smooth(tr[1:], period)
    smooth_plus = _wilder_smooth(plus_dm[1:], period)
    smooth_minus = _wilder_smooth(minus_dm[1:], period)

    if len(atr) == 0 or atr[-1] < 1e-10:
        return 20.0

    # Directional Indicators
    plus_di = 100 * smooth_plus[-1] / (atr[-1] + 1e-10)
    minus_di = 100 * smooth_minus[-1] / (atr[-1] + 1e-10)

    # DX
    di_sum = plus_di + minus_di
    if di_sum < 1e-10:
        return 20.0
    dx_series = np.abs(plus_di - minus_di) / di_sum * 100

    return float(dx_series)


def _wilder_smooth(data: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing method (used in ADX calculation)."""
    if len(data) < period:
        return np.array([np.mean(data)]) if len(data) > 0 else np.array([0.0])

    result = np.zeros(len(data))
    result[period - 1] = np.sum(data[:period])
    for i in range(period, len(data)):
        result[i] = result[i - 1] - result[i - 1] / period + data[i]
    return result[period - 1 :]
