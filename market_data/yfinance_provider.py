"""
Historical OHLCV data provider using Yahoo Finance (free).
"""

import logging
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Map our internal instrument names to yfinance tickers
TICKER_MAP = {
    "YM": "YM=F",
    "NQ": "NQ=F",
    "GC": "GC=F",
}


def fetch_ohlcv(
    symbol: str,
    bars: int = 300,
    interval: str = "5m",
) -> pd.DataFrame:
    """
    Fetch historical OHLCV data from Yahoo Finance.

    Args:
        symbol: Ticker symbol (e.g. 'NQ', 'SPY', 'GLD', '^VIX').
        bars:   Minimum number of bars to return.
        interval: Candle interval ('1m','5m','15m','1h','1d').

    Returns:
        DataFrame with columns [Open, High, Low, Close, Volume],
        indexed by datetime, sorted ascending.
    """
    ticker = TICKER_MAP.get(symbol, symbol)

    # yfinance limits intraday history; estimate how many calendar days we need
    period_days = _estimate_period_days(bars, interval)

    logger.info("Fetching %s (%s) — %dd of %s bars", symbol, ticker, period_days, interval)

    df = yf.download(
        ticker,
        period=f"{period_days}d",
        interval=interval,
        progress=False,
        auto_adjust=True,
    )

    if df.empty:
        raise ValueError(f"No data returned for {ticker} ({interval})")

    # Flatten multi-level columns if present (yfinance sometimes returns them)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(level=1, axis=1)
        # Remove any duplicate columns that result from flattening
        df = df.loc[:, ~df.columns.duplicated()]

    # Keep only OHLCV
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df.sort_index()

    # Return last N bars
    return df.tail(bars)


def _estimate_period_days(bars: int, interval: str) -> int:
    """Estimate how many calendar days to request for *bars* candles."""
    minutes_per_bar = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
    mpb = minutes_per_bar.get(interval, 5)
    trading_minutes_per_day = 390  # ~6.5 h for US equities
    days = (bars * mpb / trading_minutes_per_day) * 1.8  # buffer for weekends/holidays
    return max(int(days) + 1, 7)
