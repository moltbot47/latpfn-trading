"""
Composite confidence scorer for trading signals.

Score = (w1 * model_confidence + w2 * trend_clarity + w3 * uncertainty_inv)
        × regime_multiplier

Weights and multipliers are loaded from config['signal'].
"""

import numpy as np


def score_confidence(
    model_confidence: float,
    forecast: np.ndarray,
    uncertainty: np.ndarray,
    current_price: float,
    regime: str,
    signal_config: dict,
) -> float:
    """
    Compute composite confidence score in [0, 1].

    Args:
        model_confidence: Raw confidence from model wrapper (0..1).
        forecast:         Predicted prices (n_prompt,).
        uncertainty:      Uncertainty band (n_prompt,).
        current_price:    Current market price.
        regime:           'trending', 'ranging', or 'volatile'.
        signal_config:    config['signal'] section.

    Returns:
        Composite confidence score.
    """
    weights = signal_config["weights"]

    # 1. Model confidence (passed through directly)
    w_model = weights["model_confidence"]

    # 2. Trend clarity — how strongly directional is the forecast?
    x = np.arange(len(forecast), dtype=np.float64)
    slope = np.polyfit(x, forecast, 1)[0]
    # Normalize: slope per step as % of price, scaled so 0.1% per step → 1.0
    trend_clarity = min(abs(slope) / (current_price * 0.001 + 1e-8), 1.0)
    w_trend = weights["trend_clarity"]

    # 3. Uncertainty inverse — tighter predictions → higher confidence
    avg_unc_pct = float(np.mean(uncertainty)) / (current_price + 1e-8)
    uncertainty_inv = 1.0 / (1.0 + avg_unc_pct * 100)  # scale so 1% unc → ~0.5
    w_unc = weights["uncertainty_inverse"]

    # Weighted combination
    raw_score = (
        w_model * model_confidence
        + w_trend * trend_clarity
        + w_unc * uncertainty_inv
    )

    # Regime multiplier
    multipliers = signal_config["regime_multipliers"]
    regime_mult = multipliers.get(regime, 1.0)

    return float(max(0.0, min(raw_score * regime_mult, 1.0)))
