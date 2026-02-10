"""
Data pipeline: fetches target instrument + context assets,
normalizes, and formats data for the LaT-PFN model.
"""

import logging
import time
from typing import Dict

import numpy as np
import pandas as pd

from market_data.yfinance_provider import fetch_ohlcv
from market_data.normalizer import normalize_values, normalize_time, NormStats

logger = logging.getLogger(__name__)

# Cache entries older than this (seconds) are refetched
_CACHE_TTL_SECONDS = 270  # 4.5 minutes (just under 5-min prediction cycle)


class DataPipeline:
    """Orchestrates data fetching and preparation for LaT-PFN."""

    def __init__(self, config: dict):
        self.config = config
        self._cache: Dict[str, tuple[pd.DataFrame, float]] = {}  # (data, timestamp)

    def get_prediction_data(
        self,
        instrument: str,
        interval: str = "5m",
    ) -> dict:
        """
        Fetch and prepare all data needed for a single prediction.

        Returns dict with keys:
            heldout_df:   DataFrame of target instrument OHLCV (>= n_history + n_prompt rows)
            context_dfs:  dict[str, DataFrame] of context asset OHLCV
            n_history:    int
            n_prompt:     int
        """
        mcfg = self.config["model"]
        n_history = mcfg["n_history"]
        n_prompt = mcfg["n_prompt"]
        total_bars = n_history + n_prompt

        inst_cfg = self.config["instruments"][instrument]

        # Fetch target instrument
        heldout_df = fetch_ohlcv(instrument, bars=total_bars, interval=interval)

        # Fetch context assets
        context_dfs = {}
        for asset in inst_cfg["context_assets"]:
            try:
                df = self._fetch_cached(asset, total_bars, interval)
                if len(df) >= total_bars:
                    context_dfs[asset] = df.tail(total_bars)
                else:
                    logger.warning(
                        "Context asset %s returned only %d bars (need %d), skipping",
                        asset, len(df), total_bars,
                    )
            except Exception as e:
                logger.warning("Failed to fetch context asset %s: %s", asset, e)

        return {
            "heldout_df": heldout_df.tail(total_bars),
            "context_dfs": context_dfs,
            "n_history": n_history,
            "n_prompt": n_prompt,
        }

    def _fetch_cached(
        self, symbol: str, bars: int, interval: str
    ) -> pd.DataFrame:
        """Fetch with TTL-based in-memory cache."""
        key = f"{symbol}_{interval}"
        now = time.monotonic()

        if key in self._cache:
            cached_df, cached_at = self._cache[key]
            age = now - cached_at
            if age < _CACHE_TTL_SECONDS and len(cached_df) >= bars:
                return cached_df

        df = fetch_ohlcv(symbol, bars=bars, interval=interval)
        self._cache[key] = (df, now)
        return df

    def clear_cache(self):
        self._cache.clear()
