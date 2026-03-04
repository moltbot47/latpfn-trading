"""KJSetup dataclass — represents a single Fibonacci retracement + confirmation setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SwingPoint:
    """A significant swing high or low in price data."""

    index: int  # bar index in DataFrame
    timestamp: datetime
    price: float
    swing_type: str  # "high" | "low"
    strength: int  # how many bars it dominated on each side


@dataclass
class FibLevels:
    """Fibonacci retracement levels derived from a swing pair."""

    swing_high: float
    swing_low: float
    direction: str  # "bullish" (retracement of uptrend) | "bearish"
    levels: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        rng = self.swing_high - self.swing_low
        if self.direction == "bullish":
            # Uptrend pullback: 0% = high (start), 100% = low (full retrace)
            self.levels = {
                "0.0": self.swing_high,
                "23.6": self.swing_high - 0.236 * rng,
                "38.2": self.swing_high - 0.382 * rng,
                "50.0": self.swing_high - 0.500 * rng,
                "61.8": self.swing_high - 0.618 * rng,
                "78.6": self.swing_high - 0.786 * rng,
                "100.0": self.swing_low,
            }
        else:
            # Downtrend pullback: 0% = low (start), 100% = high (full retrace)
            self.levels = {
                "0.0": self.swing_low,
                "23.6": self.swing_low + 0.236 * rng,
                "38.2": self.swing_low + 0.382 * rng,
                "50.0": self.swing_low + 0.500 * rng,
                "61.8": self.swing_low + 0.618 * rng,
                "78.6": self.swing_low + 0.786 * rng,
                "100.0": self.swing_high,
            }

    def zone(self, level: str, tolerance_pct: float = 0.5) -> tuple[float, float]:
        """Return (low, high) price band around a Fib level."""
        price = self.levels[level]
        rng = abs(self.swing_high - self.swing_low)
        margin = rng * tolerance_pct / 100
        return (price - margin, price + margin)


@dataclass
class CandlePattern:
    """A detected candlestick/price action pattern."""

    pattern_type: str  # hammer, bullish_engulfing, bearish_engulfing,
    # wick_rejection, double_bottom, double_top, doji
    bar_index: int
    timestamp: datetime
    confidence: float  # 0.0–1.0
    description: str
    metadata: dict = field(default_factory=dict)  # extra info (prior_bar_index, prior_price, etc.)


@dataclass
class KJSetup:
    """A complete KJ strategy setup with entry, exits, classification, and outcome."""

    # Identity
    instrument: str
    setup_id: str

    # Swing structure
    swing_high: SwingPoint
    swing_low: SwingPoint
    trend_direction: str  # "bullish" | "bearish"

    # Fibonacci
    fib_levels: FibLevels
    active_fib_level: str  # "38.2" | "50.0" | "61.8"

    # Confirmation
    patterns: list[CandlePattern] = field(default_factory=list)

    # Trade parameters
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_points: float = 0.0
    reward_points: float = 0.0
    reward_risk_ratio: float = 0.0

    # Classification
    classification: str = "regular"  # "textbook" | "regular"
    textbook_score: float = 0.0

    # Outcome (populated by trade simulation)
    outcome: Optional[str] = None  # "win" | "loss" | "timeout"
    actual_rr: Optional[float] = None
    exit_price: Optional[float] = None
    max_favorable: Optional[float] = None
    max_adverse: Optional[float] = None
    bars_to_exit: Optional[int] = None

    # Timing
    entry_bar_index: int = 0
    entry_timestamp: Optional[datetime] = None

    # Generated outputs
    chart_path: Optional[str] = None
    narration: Optional[str] = None
