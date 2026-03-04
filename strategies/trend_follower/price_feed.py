"""Lightweight price feed for 5-second trailing stop polling.

Uses yfinance batch download for efficiency. Two modes:
- full_bars(): 5-day OHLCV for indicator computation (call every 5 min)
- snapshot(): Latest 1-min bar for trail management (call every 5 sec)
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Map internal symbols to yfinance tickers
TICKER_MAP = {
    "MYM": "YM=F",
    "MNQ": "NQ=F",
    "MES": "ES=F",
    "MBT": "BTC-USD",
    "MET": "ETH-USD",
    "M2K": "RTY=F",
}


@dataclass
class PriceSnapshot:
    """Current price data for an instrument."""

    symbol: str
    price: float
    high: float
    low: float
    volume: int
    timestamp: float


class PriceFeed:
    """Batch price polling for multiple futures instruments."""

    def __init__(self, instruments: list[str]):
        self.instruments = instruments
        self.yf_tickers = [TICKER_MAP.get(i, i) for i in instruments]
        self._ticker_to_inst = {TICKER_MAP.get(i, i): i for i in instruments}
        self._last_snapshots: dict[str, PriceSnapshot] = {}
        self._bars_cache: Optional[dict[str, pd.DataFrame]] = None
        self._bars_cache_time: float = 0
        self._snapshot_cache_time: float = 0

    def full_bars(self, days: int = 5, interval: str = "5m") -> dict[str, pd.DataFrame]:
        """Fetch full OHLCV bars for indicator computation.

        Call every 5 minutes. Returns dict of instrument -> DataFrame.
        """
        try:
            if len(self.yf_tickers) == 1:
                data = yf.download(
                    self.yf_tickers[0],
                    period=f"{days}d",
                    interval=interval,
                    progress=False,
                )
                result = {}
                inst = self._ticker_to_inst[self.yf_tickers[0]]
                if data is not None and not data.empty:
                    # Flatten multi-level columns if present
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    result[inst] = data.dropna()
            else:
                data = yf.download(
                    self.yf_tickers,
                    period=f"{days}d",
                    interval=interval,
                    progress=False,
                    group_by="ticker",
                )
                result = {}
                for yf_tick, inst in self._ticker_to_inst.items():
                    try:
                        df = data[yf_tick].copy()
                        if df is not None and not df.empty:
                            result[inst] = df.dropna()
                    except (KeyError, TypeError):
                        logger.debug("No data for %s (%s)", inst, yf_tick)

            self._bars_cache = result
            self._bars_cache_time = time.time()
            logger.info("Fetched bars for %d instruments", len(result))
            return result
        except Exception as e:
            logger.error("Full bars fetch failed: %s", e)
            return self._bars_cache or {}

    def snapshot(self) -> dict[str, PriceSnapshot]:
        """Fetch latest prices for all instruments.

        Uses 1-min bars (1 day) and extracts the last row.
        Returns cached snapshots on failure.
        """
        # Rate limit: min 2 seconds between snapshot calls
        now = time.time()
        if now - self._snapshot_cache_time < 2.0:
            return dict(self._last_snapshots)

        try:
            if len(self.yf_tickers) == 1:
                data = yf.download(
                    self.yf_tickers[0],
                    period="1d",
                    interval="1m",
                    progress=False,
                )
                if data is not None and not data.empty:
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    last = data.iloc[-1]
                    inst = self._ticker_to_inst[self.yf_tickers[0]]
                    self._last_snapshots[inst] = PriceSnapshot(
                        symbol=inst,
                        price=float(last["Close"]),
                        high=float(last["High"]),
                        low=float(last["Low"]),
                        volume=int(last.get("Volume", 0)),
                        timestamp=now,
                    )
            else:
                data = yf.download(
                    self.yf_tickers,
                    period="1d",
                    interval="1m",
                    progress=False,
                    group_by="ticker",
                )
                for yf_tick, inst in self._ticker_to_inst.items():
                    try:
                        df = data[yf_tick]
                        if df is not None and not df.empty:
                            last = df.iloc[-1]
                            self._last_snapshots[inst] = PriceSnapshot(
                                symbol=inst,
                                price=float(last["Close"]),
                                high=float(last["High"]),
                                low=float(last["Low"]),
                                volume=int(last.get("Volume", 0)),
                                timestamp=now,
                            )
                    except (KeyError, TypeError):
                        pass

            self._snapshot_cache_time = now
            return dict(self._last_snapshots)
        except Exception as e:
            logger.warning("Snapshot fetch failed: %s", e)
            return dict(self._last_snapshots)
