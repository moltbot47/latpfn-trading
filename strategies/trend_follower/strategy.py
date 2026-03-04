"""Trend-following strategy: Donchian breakout entries with ATR stops.

Entry logic:
  1. Price breaks above/below 20-period Donchian channel
  2. ADX > 25 (trending regime required)
  3. EMA alignment (price above both 50/200 EMA for longs, below for shorts)

Exit logic handled by TrailManager (chandelier trailing stop).
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index."""
    high, low, close = df["High"], df["Low"], df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-10))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.rolling(period).mean()


@dataclass
class TrendSignal:
    """Entry signal from the trend-following strategy."""

    instrument: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_price: float
    atr: float
    adx: float
    confidence: float  # 0-1 based on breakout strength + ADX
    position_size: int = 1


class TrendStrategy:
    """Donchian breakout trend-following with ATR stops.

    Configurable via the 'trend_follower' section of settings.yaml.
    """

    def __init__(self, config: dict):
        tf_cfg = config.get("trend_follower", {})
        self.donchian_period = tf_cfg.get("donchian_period", 20)
        self.atr_period = tf_cfg.get("atr_period", 14)
        self.adx_threshold = tf_cfg.get("adx_threshold", 25)
        self.ema_fast = tf_cfg.get("ema_fast", 50)
        self.ema_slow = tf_cfg.get("ema_slow", 200)
        self.stop_atr_mult = tf_cfg.get("stop_atr_multiplier", 2.0)
        self.min_atr_dollars = tf_cfg.get("min_atr_dollars", 5.0)

        # Risk
        self.risk_per_trade_pct = tf_cfg.get("risk_per_trade_pct", 0.02)
        risk_cfg = config.get("risk", {})
        self.max_contracts = risk_cfg.get("max_position_size_contracts", 10)

        # Instrument config
        self.instruments_cfg = config.get("instruments", {})

    def scan(self, instrument: str, bars: pd.DataFrame) -> Optional[TrendSignal]:
        """Scan for Donchian breakout entry on a single instrument.

        Args:
            instrument: Symbol (e.g., "MNQ")
            bars: OHLCV DataFrame (5-min bars, need >= 200 rows for EMA-200)

        Returns:
            TrendSignal if breakout detected and filters pass, else None.
        """
        min_rows = max(self.donchian_period, self.ema_slow, self.atr_period) + 5
        if len(bars) < min_rows:
            return None

        # Compute indicators
        atr = compute_atr(bars, self.atr_period)
        adx = compute_adx(bars, self.atr_period)
        ema_f = bars["Close"].ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = bars["Close"].ewm(span=self.ema_slow, adjust=False).mean()
        upper = bars["High"].rolling(self.donchian_period).max()
        lower = bars["Low"].rolling(self.donchian_period).min()

        price = float(bars["Close"].iloc[-1])
        prev_close = float(bars["Close"].iloc[-2])
        current_atr = float(atr.iloc[-1])
        current_adx = float(adx.iloc[-1])
        current_ema_f = float(ema_f.iloc[-1])
        current_ema_s = float(ema_s.iloc[-1])
        current_upper = float(upper.iloc[-1])
        current_lower = float(lower.iloc[-1])
        prev_upper = float(upper.iloc[-2])
        prev_lower = float(lower.iloc[-2])

        # ATR dollar filter (skip flat/illiquid instruments)
        inst_cfg = self.instruments_cfg.get(instrument, {})
        contract_size = inst_cfg.get("contract_size", 1.0)
        if current_atr * contract_size < self.min_atr_dollars:
            return None

        # ADX filter: trending regime required
        if np.isnan(current_adx) or current_adx < self.adx_threshold:
            return None

        direction = None

        # Long breakout: close crosses above Donchian upper
        if price >= current_upper and prev_close < prev_upper:
            if price > current_ema_f and price > current_ema_s:
                direction = "long"

        # Short breakout: close crosses below Donchian lower
        elif price <= current_lower and prev_close > prev_lower:
            if price < current_ema_f and price < current_ema_s:
                direction = "short"

        if direction is None:
            return None

        # Stop price
        if direction == "long":
            stop_price = price - self.stop_atr_mult * current_atr
        else:
            stop_price = price + self.stop_atr_mult * current_atr

        # Confidence score: ADX strength + breakout magnitude
        adx_score = min(current_adx / 75.0, 1.0)
        if direction == "long":
            breakout_pct = (price - current_upper) / (current_atr + 1e-10)
        else:
            breakout_pct = (current_lower - price) / (current_atr + 1e-10)
        breakout_score = min(max(breakout_pct, 0) + 0.5, 1.0)
        confidence = 0.5 * adx_score + 0.5 * breakout_score

        return TrendSignal(
            instrument=instrument,
            direction=direction,
            entry_price=price,
            stop_price=round(stop_price, 2),
            atr=current_atr,
            adx=current_adx,
            confidence=confidence,
        )

    def size_position(
        self, signal: TrendSignal, equity: float, contract_size: float
    ) -> int:
        """Risk-based position sizing: (equity * risk%) / (stop_dist * contract_size)."""
        stop_distance = abs(signal.entry_price - signal.stop_price)
        if stop_distance <= 0:
            return 1
        risk_dollars = equity * self.risk_per_trade_pct
        contracts = int(risk_dollars / (stop_distance * contract_size))
        return max(1, min(contracts, self.max_contracts))
