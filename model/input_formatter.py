"""
Formats OHLCV DataFrames into the 7-tensor input that LaT-PFN's
``create_forecast`` method expects.

Tensor layout
─────────────
Context (example series — correlated assets providing in-context learning):
  T_context_history : [1, n_ctx, n_history, 1]
  T_context_prompt  : [1, n_ctx, n_prompt,  1]
  V_context_history : [1, n_ctx, n_history, 1]
  V_context_prompt  : [1, n_ctx, n_prompt,  1]

Heldout (target series — what we want to forecast):
  T_heldout_history : [1, n_held, n_history, 1]
  T_heldout_prompt  : [1, n_held, n_prompt,  1]
  V_heldout_history : [1, n_held, n_history, 1]

Strategy
────────
- The 4 heldout series are the target instrument's Open, High, Low, Close.
- Context series come from correlated assets' Close prices.
- If fewer than ``n_ctx`` context assets are available, we duplicate
  existing ones (the model needs dim > 1 in every non-feature axis).
"""

from typing import Dict, List

import numpy as np
import pandas as pd
import torch

from data.normalizer import normalize_values, normalize_time, NormStats

# Columns used as the 4 heldout series for the target instrument
HELDOUT_COLS = ["Open", "High", "Low", "Close"]


def format_inputs(
    heldout_df: pd.DataFrame,
    context_dfs: Dict[str, pd.DataFrame],
    n_history: int = 180,
    n_prompt: int = 60,
    min_context: int = 2,
) -> tuple[dict, NormStats]:
    """
    Build the 7 tensors required by ``LaTPFNV4.create_forecast()``.

    Args:
        heldout_df:  Target instrument OHLCV, length >= n_history + n_prompt.
        context_dfs: {symbol: OHLCV DataFrame} for context assets.
        n_history:   History length (default 180).
        n_prompt:    Forecast horizon (default 60).
        min_context: Minimum context series (model needs dim > 1).

    Returns:
        (tensors_dict, close_stats)
        tensors_dict has keys matching create_forecast argument names.
        close_stats is the NormStats for the Close column (for denormalization).
    """
    total = n_history + n_prompt

    # ── Time axis (shared by all series) ──────────────────────────────
    T_full = normalize_time(total)  # shape (total,)
    T_hist = T_full[:n_history]
    T_prom = T_full[n_history:]

    # ── Heldout series (O, H, L, C of target instrument) ─────────────
    heldout_arrays = []
    close_stats = None
    for col in HELDOUT_COLS:
        vals = heldout_df[col].values[-total:].astype(np.float32)
        v_norm, stats = normalize_values(vals)
        heldout_arrays.append(v_norm)
        if col == "Close":
            close_stats = stats

    # Split heldout into history / prompt
    V_heldout_hist = np.stack([a[:n_history] for a in heldout_arrays])  # (4, n_history)
    # (no V_heldout_prompt — that's what the model predicts)

    T_heldout_hist = np.tile(T_hist, (len(HELDOUT_COLS), 1))  # (4, n_history)
    T_heldout_prom = np.tile(T_prom, (len(HELDOUT_COLS), 1))  # (4, n_prompt)

    # ── Context series (Close prices of correlated assets) ────────────
    ctx_history_V: List[np.ndarray] = []
    ctx_prompt_V: List[np.ndarray] = []

    for symbol, df in context_dfs.items():
        close = df["Close"].values[-total:].astype(np.float32)
        if len(close) < total:
            continue
        v_norm, _ = normalize_values(close)
        ctx_history_V.append(v_norm[:n_history])
        ctx_prompt_V.append(v_norm[n_history:])

    # Pad / duplicate to have at least min_context series
    if not ctx_history_V:
        raise ValueError(
            "No valid context series available. Need at least 1 context asset "
            f"with {total} bars. Check context_assets config and data availability."
        )
    while len(ctx_history_V) < min_context:
        ctx_history_V.append(ctx_history_V[0])
        ctx_prompt_V.append(ctx_prompt_V[0])

    n_ctx = len(ctx_history_V)

    V_ctx_hist = np.stack(ctx_history_V)  # (n_ctx, n_history)
    V_ctx_prom = np.stack(ctx_prompt_V)   # (n_ctx, n_prompt)
    T_ctx_hist = np.tile(T_hist, (n_ctx, 1))
    T_ctx_prom = np.tile(T_prom, (n_ctx, 1))

    # ── Convert to tensors [1, n_series, seq_len, 1] ─────────────────
    def to_tensor(arr: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(arr).float().unsqueeze(0).unsqueeze(-1)

    tensors = {
        "T_context_history": to_tensor(T_ctx_hist),
        "T_context_prompt":  to_tensor(T_ctx_prom),
        "V_context_history": to_tensor(V_ctx_hist),
        "V_context_prompt":  to_tensor(V_ctx_prom),
        "T_heldout_history": to_tensor(T_heldout_hist),
        "T_heldout_prompt":  to_tensor(T_heldout_prom),
        "V_heldout_history": to_tensor(V_heldout_hist),
    }

    return tensors, close_stats
