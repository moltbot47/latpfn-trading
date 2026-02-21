"""
Data pipeline: fetches target instrument + context assets,
normalizes, and formats data for the LaT-PFN model.
"""

import logging
import threading
import time
from typing import Dict

import numpy as np
import pandas as pd

from market_data.yfinance_provider import fetch_ohlcv
from market_data.normalizer import normalize_values, normalize_time, NormStats

logger = logging.getLogger(__name__)

# Cache entries older than this (seconds) are refetched
_CACHE_TTL_SECONDS = 270  # 4.5 minutes (just under 5-min prediction cycle)


# ── Global yfinance rate limiter (token bucket: max 2 calls/sec) ───────

class _YFinanceRateLimiter:
    """Token-bucket rate limiter with circuit breaker for yfinance calls.

    - Max 2 calls per second (token bucket).
    - Circuit breaker: after 5 consecutive failures, pause 30 seconds.
    """

    def __init__(self, max_calls_per_second: float = 2.0, failure_threshold: int = 5,
                 circuit_pause_seconds: float = 30.0):
        self._min_interval = 1.0 / max_calls_per_second
        self._last_call_time = 0.0
        self._lock = threading.Lock()

        # Circuit breaker state
        self._consecutive_failures = 0
        self._failure_threshold = failure_threshold
        self._circuit_pause_seconds = circuit_pause_seconds
        self._circuit_open_until = 0.0

    def wait(self):
        """Block until a call is allowed by the rate limiter and circuit breaker."""
        with self._lock:
            now = time.monotonic()

            # Circuit breaker: if open, wait until it closes
            if now < self._circuit_open_until:
                wait_time = self._circuit_open_until - now
                logger.warning(
                    "yfinance circuit breaker open — waiting %.1fs before retry",
                    wait_time,
                )
                time.sleep(wait_time)
                now = time.monotonic()

            # Token bucket: enforce minimum interval between calls
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

            self._last_call_time = time.monotonic()

    def record_success(self):
        """Record a successful yfinance call — reset failure counter."""
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self):
        """Record a failed yfinance call — trip circuit breaker if threshold reached."""
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = time.monotonic() + self._circuit_pause_seconds
                logger.error(
                    "yfinance circuit breaker TRIPPED after %d consecutive failures — "
                    "pausing for %.0fs",
                    self._consecutive_failures, self._circuit_pause_seconds,
                )
                self._consecutive_failures = 0  # reset after tripping


# Module-level singleton
_rate_limiter = _YFinanceRateLimiter()


def _rate_limited_fetch(symbol: str, bars: int, interval: str) -> pd.DataFrame:
    """Fetch OHLCV data with rate limiting and circuit breaker protection."""
    _rate_limiter.wait()
    try:
        df = fetch_ohlcv(symbol, bars=bars, interval=interval)
        _rate_limiter.record_success()
        return df
    except Exception:
        _rate_limiter.record_failure()
        raise


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

        # Fetch target instrument (rate-limited)
        # Use yfinance_ticker if configured (e.g. "BTC-USD" for Hyperliquid "BTC")
        ticker = inst_cfg.get("yfinance_ticker", instrument)
        heldout_df = _rate_limited_fetch(ticker, bars=total_bars, interval=interval)

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

        df = _rate_limited_fetch(symbol, bars=bars, interval=interval)
        self._cache[key] = (df, now)
        return df

    def clear_cache(self):
        self._cache.clear()
