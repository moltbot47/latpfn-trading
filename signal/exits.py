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
) -> tuple[float, float]:
    """
    Determine stop-loss and take-profit prices.

    Strategy:
        Stop  = entry ± (near-term uncertainty × ATR multiplier)
        Target = forecast endpoint, adjusted for uncertainty.
        Enforces minimum reward:risk ratio.

    Args:
        entry_price: Expected entry price.
        direction:   'long' or 'short'.
        forecast:    Predicted prices (n_prompt,).
        uncertainty: Uncertainty band (n_prompt,).
        risk_config: config['risk'] section.

    Returns:
        (stop_loss, take_profit)
    """
    atr_mult = risk_config["stop_loss_atr_multiplier"]
    min_rr = risk_config["min_reward_risk_ratio"]

    # Stop distance based on near-term uncertainty (first 10 steps)
    near_unc = float(np.mean(uncertainty[:10]))
    stop_distance = near_unc * atr_mult

    # Minimum stop distance: 0.1% of price (avoid absurdly tight stops)
    stop_distance = max(stop_distance, entry_price * 0.001)

    # Target from forecast: use conservative side of forecast endpoint
    far_unc = float(np.mean(uncertainty[-10:]))
    forecast_end = float(np.mean(forecast[-10:]))

    if direction == "long":
        stop_loss = entry_price - stop_distance
        # Conservative target: forecast end minus uncertainty
        take_profit = forecast_end - far_unc * 0.5
        # Ensure target is above entry
        take_profit = max(take_profit, entry_price + stop_distance * 0.5)
    else:
        stop_loss = entry_price + stop_distance
        take_profit = forecast_end + far_unc * 0.5
        take_profit = min(take_profit, entry_price - stop_distance * 0.5)

    # Enforce minimum reward:risk
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    if risk > 0 and reward / risk < min_rr:
        if direction == "long":
            take_profit = entry_price + risk * min_rr
        else:
            take_profit = entry_price - risk * min_rr

    return stop_loss, take_profit
