"""
Data normalization following LaT-PFN conventions.

Value normalization: (V - mean) / (2 * std + eps)
Time normalization:  Normalized to abstract time axis (T / 365 as in training config)
Denormalization:     V * (2 * std + eps) + mean
"""

import numpy as np
from dataclasses import dataclass


EPS = 1e-8


@dataclass
class NormStats:
    """Stores normalization statistics for denormalization."""
    mean: float
    std: float


def normalize_values(values: np.ndarray) -> tuple[np.ndarray, NormStats]:
    """
    Normalize values using LaT-PFN convention: (V - mean) / (2*std + eps).

    Args:
        values: 1D array of values (e.g. close prices).

    Returns:
        (normalized_values, NormStats for denormalization)
    """
    mean = float(np.mean(values))
    std = float(np.std(values))
    normalized = (values - mean) / (2.0 * std + EPS)
    return normalized, NormStats(mean=mean, std=std)


def denormalize_values(normalized: np.ndarray, stats: NormStats) -> np.ndarray:
    """Reverse the normalization back to original price space."""
    return normalized * (2.0 * stats.std + EPS) + stats.mean


def normalize_time(n_points: int) -> np.ndarray:
    """
    Create normalized abstract time axis.

    The LaT-PFN training config uses T_mapping = lambda x: x / 365,
    mapping time indices to fractions of a year. For inference we use
    a simple linear ramp that matches the scale the model saw during
    training (roughly 0 to ~0.66 for 240 steps).
    """
    return np.linspace(0, n_points / 365.0, n_points, dtype=np.float32)
