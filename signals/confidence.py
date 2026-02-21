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
    funding_rate: float = 0.0,
    open_interest: float = 0.0,
    direction: str = "",
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
        funding_rate:     Current funding rate (positive = longs pay shorts).
        open_interest:    Current open interest in USD.
        direction:        Predicted direction ('long' or 'short').

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

    score = raw_score * regime_mult

    # 4. Funding rate edge (Hyperliquid-specific)
    # If funding is positive (longs pay shorts) and we're going short → boost
    # If funding is negative (shorts pay longs) and we're going long → boost
    # Opposite = penalty. This captures "being paid to hold" edge.
    if funding_rate != 0.0 and direction:
        # Annualized funding impact: rate * 3 * 365 (funding every 8h)
        # Typical rates: 0.0001 = 0.01% per 8h = 10.95% annual
        funding_annual = abs(funding_rate) * 3 * 365
        funding_boost = min(funding_annual * 0.5, 0.10)  # cap at +/- 10% score

        funding_favors_direction = (
            (funding_rate > 0 and direction == "short") or
            (funding_rate < 0 and direction == "long")
        )
        if funding_favors_direction:
            score *= (1.0 + funding_boost)
        else:
            score *= (1.0 - funding_boost * 0.5)  # smaller penalty for unfavorable

    return float(max(0.0, min(score, 1.0)))
