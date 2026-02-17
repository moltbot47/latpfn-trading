"""
Calculate stop-loss and take-profit levels from forecast and uncertainty.
"""

import numpy as np


def calculate_exits(
    entry_price: float,
    direction: str,
    forecast: np.ndarray,
    uncertainty: np.ndarray,
    risk_config: dict,
    target_multiplier: float = 1.0,
    stop_multiplier: float = 1.0,
    min_rr_override: float | None = None,
) -> tuple[float, float]:
    """
    Determine stop-loss and take-profit prices.

    Strategy:
        Stop  = entry ± (near-term uncertainty × ATR multiplier × stop_multiplier)
        Target = forecast endpoint × target_multiplier, adjusted for uncertainty.
        Enforces minimum reward:risk ratio (tier override or global fallback).

    Args:
        entry_price:       Expected entry price.
        direction:         'long' or 'short'.
        forecast:          Predicted prices (n_prompt,).
        uncertainty:       Uncertainty band (n_prompt,).
        risk_config:       config['risk'] section.
        target_multiplier: Shot-tier multiplier for target distance (default 1.0).
        stop_multiplier:   Shot-tier multiplier for stop distance (default 1.0).
        min_rr_override:   If set, overrides risk_config min_reward_risk_ratio.

    Returns:
        (stop_loss, take_profit)
    """
    atr_mult = risk_config["stop_loss_atr_multiplier"]
    min_rr = min_rr_override if min_rr_override is not None else risk_config["min_reward_risk_ratio"]

    # Stop distance based on near-term uncertainty (first 10 steps)
    near_unc = float(np.mean(uncertainty[:10]))
    stop_distance = near_unc * atr_mult * stop_multiplier

    # Minimum stop distance: 0.1% of price (avoid absurdly tight stops)
    stop_distance = max(stop_distance, entry_price * 0.001)

    # Target from forecast: use conservative side of forecast endpoint
    far_unc = float(np.mean(uncertainty[-10:]))
    forecast_end = float(np.mean(forecast[-10:]))

    if direction == "long":
        stop_loss = entry_price - stop_distance
        # Conservative target: forecast end minus uncertainty, scaled by tier
        raw_target = forecast_end - far_unc * 0.5
        raw_distance = raw_target - entry_price
        # Ensure positive target distance (forecast may be below entry)
        target_distance = max(raw_distance, stop_distance * 0.5) * target_multiplier
        take_profit = entry_price + target_distance
    else:
        stop_loss = entry_price + stop_distance
        raw_target = forecast_end + far_unc * 0.5
        raw_distance = entry_price - raw_target
        target_distance = max(raw_distance, stop_distance * 0.5) * target_multiplier
        take_profit = entry_price - target_distance

    # Enforce minimum reward:risk
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    if risk > 0 and reward / risk < min_rr:
        if direction == "long":
            take_profit = entry_price + risk * min_rr
        else:
            take_profit = entry_price - risk * min_rr

    return stop_loss, take_profit


def calculate_scalp_exits(
    entry_price: float,
    direction: str,
    forecast: np.ndarray,
    uncertainty: np.ndarray,
    risk_config: dict,
    scalp_config: dict,
    target_multiplier: float = 1.0,
    stop_multiplier: float = 1.0,
    min_rr_override: float | None = None,
) -> tuple[float, float]:
    """
    Scalp exit calculation using near-term forecast (bars 3-12).

    Instead of anchoring profit targets to the far end of the forecast
    window (bars 50-60), uses the near-term window where the model's
    signal-to-noise ratio is ~3x higher.  Produces tighter targets
    that are achievable within 15-60 minutes for consistent small wins.

    Args:
        entry_price:       Expected entry price.
        direction:         'long' or 'short'.
        forecast:          Predicted prices (n_prompt,).
        uncertainty:       Uncertainty band (n_prompt,).
        risk_config:       config['risk'] section.
        scalp_config:      config['strategy']['scalp'] section.
        target_multiplier: Scalp-tier multiplier for target distance.
        stop_multiplier:   Scalp-tier multiplier for stop distance.
        min_rr_override:   If set, overrides global scalp min R:R.

    Returns:
        (stop_loss, take_profit)
    """
    atr_mult = risk_config["stop_loss_atr_multiplier"]
    min_rr = (
        min_rr_override
        if min_rr_override is not None
        else risk_config.get("scalp_min_reward_risk_ratio", 0.3)
    )

    # ── Stop distance (same as standard — near-term uncertainty) ──
    near_unc = float(np.mean(uncertainty[:10]))
    stop_distance = near_unc * atr_mult * stop_multiplier
    stop_distance = max(stop_distance, entry_price * 0.001)

    # ── Target from NEAR-TERM forecast (bars 3-12 by default) ─────
    bar_start = scalp_config.get("forecast_bar_start", 3)
    bar_end = scalp_config.get("forecast_bar_end", 12)
    unc_deduction = scalp_config.get("uncertainty_deduction", 0.3)
    min_target_ratio = scalp_config.get("min_target_stop_ratio", 0.3)

    if bar_end > len(forecast) or bar_start >= bar_end:
        # Fall back to whatever is available
        bar_start = min(bar_start, len(forecast) - 1)
        bar_end = len(forecast)

    scalp_unc = float(np.mean(uncertainty[bar_start:bar_end]))
    scalp_forecast = float(np.mean(forecast[bar_start:bar_end]))

    if direction == "long":
        stop_loss = entry_price - stop_distance
        raw_target = scalp_forecast - scalp_unc * unc_deduction
        raw_distance = raw_target - entry_price
        target_distance = max(raw_distance, stop_distance * min_target_ratio) * target_multiplier
        take_profit = entry_price + target_distance
    else:
        stop_loss = entry_price + stop_distance
        raw_target = scalp_forecast + scalp_unc * unc_deduction
        raw_distance = entry_price - raw_target
        target_distance = max(raw_distance, stop_distance * min_target_ratio) * target_multiplier
        take_profit = entry_price - target_distance

    # ── Enforce minimum R:R (much lower for scalp) ────────────────
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    if risk > 0 and reward / risk < min_rr:
        if direction == "long":
            take_profit = entry_price + risk * min_rr
        else:
            take_profit = entry_price - risk * min_rr

    return stop_loss, take_profit
