"""
Converts raw LaT-PFN model output (binned logits) into
point forecasts and uncertainty estimates in original price space.
"""

import numpy as np
import torch

from market_data.normalizer import NormStats, denormalize_values

# Default bin configuration (must match model training)
N_BINS = 100
RANGE_MIN = -3.5
RANGE_MAX = 3.5


def _bin_centroids(n_bins: int = N_BINS) -> np.ndarray:
    """Return the centroid of each output bin."""
    bin_area = (RANGE_MAX - RANGE_MIN) / n_bins
    offset = bin_area / 2
    return np.linspace(RANGE_MIN + offset, RANGE_MAX - offset, n_bins)


def logits_to_mean_std(logits: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert binned logits to expected value and standard deviation
    in **normalized** space.

    Args:
        logits: shape (..., n_bins)

    Returns:
        (mean, std) both shaped (...)
    """
    probs = torch.nn.functional.softmax(logits, dim=-1).cpu().numpy()
    centroids = _bin_centroids(logits.shape[-1])

    mean = (probs * centroids).sum(axis=-1)
    variance = (probs * (centroids - mean[..., np.newaxis]) ** 2).sum(axis=-1)
    std = np.sqrt(variance)
    return mean, std


def process_forecast(
    model_output: dict,
    stats: NormStats,
    heldout_idx: int = 3,
) -> dict:
    """
    Process the full output of ``create_forecast``.

    Args:
        model_output: dict from model.create_forecast() with keys
                      'forecast', 'latent_forecast', 'backcast'.
        stats:        NormStats of the Close column (heldout_idx=3).
        heldout_idx:  Which heldout series corresponds to Close (default 3 = OHLC[3]).

    Returns:
        dict with:
            forecast_prices : np.ndarray  — predicted Close prices (n_prompt,)
            uncertainty     : np.ndarray  — std in price space    (n_prompt,)
            forecast_norm   : np.ndarray  — predicted values in normalized space
            backcast_prices : np.ndarray  — reconstructed history prices (n_history,)
    """
    # Forecast logits: [batch=1, n_heldout, n_prompt, n_bins]
    forecast_logits = model_output["forecast"][0, heldout_idx]  # (n_prompt, n_bins)
    mean_norm, std_norm = logits_to_mean_std(forecast_logits)

    # Denormalize to price space
    forecast_prices = denormalize_values(mean_norm, stats)
    uncertainty = std_norm * (2.0 * stats.std + 1e-8)  # scale std same way

    result = {
        "forecast_prices": forecast_prices,
        "uncertainty": uncertainty,
        "forecast_norm": mean_norm,
    }

    # Backcast (reconstructed history)
    if "backcast" in model_output:
        bc_logits = model_output["backcast"][0, heldout_idx]
        bc_mean, _ = logits_to_mean_std(bc_logits)
        result["backcast_prices"] = denormalize_values(bc_mean, stats)

    return result
