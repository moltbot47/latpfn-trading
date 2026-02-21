"""
Hyperliquid market data provider.

Fetches candle data and available pairs directly from the Hyperliquid API
instead of yfinance. Context assets (VIX, SPY) still come from yfinance.
"""

import logging
import time
from typing import Optional, List, Dict

import pandas as pd
from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)


class HyperliquidData:
    """Fetch OHLCV candle data from Hyperliquid."""

    def __init__(self, network: str = "mainnet"):
        base_url = (
            constants.MAINNET_API_URL
            if network == "mainnet"
            else constants.TESTNET_API_URL
        )
        self._info = Info(base_url, skip_ws=True)
        self._meta_cache: Optional[dict] = None
        self._meta_cache_time: float = 0

    def get_candles(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 240,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles from Hyperliquid.

        Args:
            symbol:   Coin name (e.g. 'BTC', 'ETH', 'SOL').
            interval: Candle interval ('1m', '5m', '15m', '1h', '4h', '1d').
            limit:    Number of candles to fetch.

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
            indexed by datetime, or None on failure.
        """
        coin = symbol.upper()

        # Calculate time range
        interval_seconds = self._interval_to_seconds(interval)
        end_time = int(time.time() * 1000)
        start_time = end_time - (limit * interval_seconds * 1000)

        try:
            candles = self._info.candles_snapshot(coin, interval, start_time, end_time)

            if not candles:
                logger.warning("No candles returned for %s", coin)
                return None

            rows = []
            for c in candles:
                rows.append({
                    "datetime": pd.to_datetime(c["t"], unit="ms", utc=True),
                    "Open": float(c["o"]),
                    "High": float(c["h"]),
                    "Low": float(c["l"]),
                    "Close": float(c["c"]),
                    "Volume": float(c["v"]),
                })

            df = pd.DataFrame(rows)
            df.set_index("datetime", inplace=True)
            df.sort_index(inplace=True)

            # Trim to requested limit
            if len(df) > limit:
                df = df.iloc[-limit:]

            logger.debug("Fetched %d candles for %s (%s)", len(df), coin, interval)
            return df

        except Exception as e:
            logger.error("Failed to fetch Hyperliquid candles for %s: %s", coin, e)
            return None

    def get_available_pairs(self) -> List[Dict]:
        """
        Fetch all tradeable perpetual futures from Hyperliquid.

        Returns:
            List of dicts with coin info: name, szDecimals, maxLeverage.
        """
        try:
            meta = self._get_meta()
            pairs = []
            for asset in meta.get("universe", []):
                pairs.append({
                    "coin": asset["name"],
                    "sz_decimals": asset.get("szDecimals", 3),
                    "max_leverage": asset.get("maxLeverage", 50),
                })
            return pairs
        except Exception as e:
            logger.error("Failed to fetch Hyperliquid pairs: %s", e)
            return []

    def get_mid_prices(self) -> Dict[str, float]:
        """Fetch current mid prices for all coins."""
        try:
            mids = self._info.all_mids()
            return {k: float(v) for k, v in mids.items()}
        except Exception as e:
            logger.error("Failed to fetch mid prices: %s", e)
            return {}

    def _get_meta(self) -> dict:
        """Cached metadata fetch (refreshes every 5 minutes)."""
        now = time.time()
        if self._meta_cache is None or (now - self._meta_cache_time) > 300:
            self._meta_cache = self._info.meta()
            self._meta_cache_time = now
        return self._meta_cache

    @staticmethod
    def _interval_to_seconds(interval: str) -> int:
        """Convert interval string to seconds."""
        multipliers = {"m": 60, "h": 3600, "d": 86400}
        unit = interval[-1]
        value = int(interval[:-1])
        return value * multipliers.get(unit, 60)
