"""
Data pipeline for Hyperliquid mode.

Uses Hyperliquid's native candle API for crypto OHLCV data (no yfinance delay).
Context assets (VIX) still come from yfinance but are fetched once and cached.
"""

import logging
import time
from typing import Dict, Optional

import pandas as pd

from market_data.hyperliquid_data import HyperliquidData
from market_data.yfinance_provider import fetch_ohlcv
from market_data.pair_scanner import PairScanner

logger = logging.getLogger(__name__)

# Cache TTL for context assets from yfinance (VIX, SPY — fetch once per cycle)
_CONTEXT_CACHE_TTL = 270  # 4.5 minutes


class HyperliquidPipeline:
    """Data pipeline using Hyperliquid native API for crypto instruments."""

    def __init__(self, config: dict, pair_scanner: PairScanner):
        self.config = config
        self._hl_data = HyperliquidData(
            network=config.get("hyperliquid", {}).get("network", "mainnet")
        )
        self._pair_scanner = pair_scanner

        # Context asset cache (VIX, SPY from yfinance — shared across instruments)
        self._context_cache: Dict[str, tuple] = {}  # asset → (df, timestamp)

    def get_prediction_data(
        self,
        instrument: str,
        interval: str = "5m",
    ) -> dict:
        """
        Fetch data for a single instrument prediction.

        Uses Hyperliquid API for the instrument's candles (fast, real-time).
        Uses yfinance for context assets like VIX (cached, fetched once per cycle).

        Returns dict with keys:
            heldout_df:   DataFrame of target instrument OHLCV
            context_dfs:  dict[str, DataFrame] of context asset OHLCV
            n_history:    int
            n_prompt:     int
            funding_rate: float (current funding rate for this instrument)
            open_interest: float (current OI in USD)
        """
        mcfg = self.config["model"]
        n_history = mcfg["n_history"]
        n_prompt = mcfg["n_prompt"]
        total_bars = n_history + n_prompt

        inst_cfg = self.config["instruments"].get(instrument, {})

        # Fetch target instrument candles from Hyperliquid (real-time, no delay)
        heldout_df = self._hl_data.get_candles(
            symbol=instrument,
            interval=interval,
            limit=total_bars,
        )

        if heldout_df is None or len(heldout_df) < total_bars:
            # Fallback to yfinance ticker if Hyperliquid fails
            yf_ticker = inst_cfg.get("yfinance_ticker", f"{instrument}-USD")
            logger.warning(
                "%s: Hyperliquid candles insufficient (%d/%d), falling back to yfinance (%s)",
                instrument,
                len(heldout_df) if heldout_df is not None else 0,
                total_bars,
                yf_ticker,
            )
            heldout_df = fetch_ohlcv(yf_ticker, bars=total_bars, interval=interval)

        # Fetch context assets (VIX, etc.) from yfinance with caching
        context_dfs = {}
        for asset in inst_cfg.get("context_assets", ["^VIX"]):
            try:
                df = self._fetch_context_cached(asset, total_bars, interval)
                if df is not None and len(df) >= total_bars:
                    context_dfs[asset] = df.tail(total_bars)
                else:
                    logger.warning(
                        "Context asset %s returned only %d bars (need %d), skipping",
                        asset,
                        len(df) if df is not None else 0,
                        total_bars,
                    )
            except Exception as e:
                logger.warning("Failed to fetch context asset %s: %s", asset, e)

        # Get funding rate and OI from pair scanner cache
        funding_rate = self._pair_scanner.get_funding_rate(instrument)
        open_interest = self._pair_scanner.get_open_interest(instrument)

        return {
            "heldout_df": heldout_df.tail(total_bars),
            "context_dfs": context_dfs,
            "n_history": n_history,
            "n_prompt": n_prompt,
            "funding_rate": funding_rate,
            "open_interest": open_interest,
        }

    def _fetch_context_cached(
        self, asset: str, bars: int, interval: str
    ) -> Optional[pd.DataFrame]:
        """Fetch context asset from yfinance with TTL cache."""
        key = f"{asset}_{interval}"
        now = time.monotonic()

        if key in self._context_cache:
            cached_df, cached_at = self._context_cache[key]
            if (now - cached_at) < _CONTEXT_CACHE_TTL and len(cached_df) >= bars:
                return cached_df

        try:
            df = fetch_ohlcv(asset, bars=bars, interval=interval)
            self._context_cache[key] = (df, now)
            return df
        except Exception as e:
            logger.warning("yfinance fetch for %s failed: %s", asset, e)
            # Return stale cache if available
            if key in self._context_cache:
                return self._context_cache[key][0]
            return None

    def clear_cache(self):
        self._context_cache.clear()
