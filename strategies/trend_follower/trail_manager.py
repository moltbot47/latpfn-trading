"""Trailing stop management for trend-following exits.

Implements chandelier exit (ATR-based trailing) with optional scale-out.
Updated every 5 seconds via price polling.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TrailState:
    """Trailing stop state for a single position."""

    instrument: str
    direction: str  # "long" or "short"
    entry_price: float
    initial_stop: float
    current_stop: float
    atr: float
    best_price: float  # highest for long, lowest for short
    trail_multiplier: float = 3.0
    scale_out_done: bool = False
    original_size: int = 1
    current_size: int = 1

    @property
    def risk_per_unit(self) -> float:
        """Initial risk distance (entry to initial stop)."""
        return abs(self.entry_price - self.initial_stop)

    @property
    def scale_out_target(self) -> float:
        """Price target for first partial exit (1.5x risk)."""
        r = self.risk_per_unit
        if self.direction == "long":
            return self.entry_price + 1.5 * r
        return self.entry_price - 1.5 * r

    @property
    def unrealized_r(self) -> float:
        """Current P&L expressed as multiples of initial risk (R)."""
        r = self.risk_per_unit
        if r <= 0:
            return 0.0
        if self.direction == "long":
            return (self.best_price - self.entry_price) / r
        return (self.entry_price - self.best_price) / r

    def update(self, price: float, high: float, low: float) -> Optional[str]:
        """Update trailing stop with new price data.

        Returns:
            None if no action needed.
            "stop_hit" if trailing stop was hit.
            "scale_out" if scale-out target reached (first time only).
        """
        if self.direction == "long":
            # Check stop hit
            if price <= self.current_stop:
                return "stop_hit"

            # Update best price and trail
            if high > self.best_price:
                self.best_price = high
                new_stop = self.best_price - self.trail_multiplier * self.atr
                if new_stop > self.current_stop:
                    self.current_stop = new_stop

            # Check scale-out
            if not self.scale_out_done and self.current_size > 1:
                if price >= self.scale_out_target:
                    self.scale_out_done = True
                    return "scale_out"

        else:  # short
            if price >= self.current_stop:
                return "stop_hit"

            if low < self.best_price:
                self.best_price = low
                new_stop = self.best_price + self.trail_multiplier * self.atr
                if new_stop < self.current_stop:
                    self.current_stop = new_stop

            if not self.scale_out_done and self.current_size > 1:
                if price <= self.scale_out_target:
                    self.scale_out_done = True
                    return "scale_out"

        return None

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "initial_stop": self.initial_stop,
            "current_stop": self.current_stop,
            "atr": self.atr,
            "best_price": self.best_price,
            "trail_multiplier": self.trail_multiplier,
            "scale_out_done": self.scale_out_done,
            "original_size": self.original_size,
            "current_size": self.current_size,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrailState":
        return cls(
            instrument=d["instrument"],
            direction=d["direction"],
            entry_price=d["entry_price"],
            initial_stop=d["initial_stop"],
            current_stop=d["current_stop"],
            atr=d["atr"],
            best_price=d["best_price"],
            trail_multiplier=d.get("trail_multiplier", 3.0),
            scale_out_done=d.get("scale_out_done", False),
            original_size=d.get("original_size", 1),
            current_size=d.get("current_size", 1),
        )


class TrailManager:
    """Manages trailing stops for all open positions."""

    def __init__(self, trail_multiplier: float = 3.0):
        self.trail_multiplier = trail_multiplier
        self.trails: dict[str, TrailState] = {}

    def add_trail(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        atr: float,
        position_size: int,
        stop_multiplier: float = 2.0,
    ) -> TrailState:
        """Create trailing stop for a new position."""
        if direction == "long":
            initial_stop = entry_price - stop_multiplier * atr
            best_price = entry_price
        else:
            initial_stop = entry_price + stop_multiplier * atr
            best_price = entry_price

        trail = TrailState(
            instrument=instrument,
            direction=direction,
            entry_price=entry_price,
            initial_stop=initial_stop,
            current_stop=initial_stop,
            atr=atr,
            best_price=best_price,
            trail_multiplier=self.trail_multiplier,
            original_size=position_size,
            current_size=position_size,
        )
        self.trails[instrument] = trail
        logger.info(
            "Trail added: %s %s @ %.2f  stop=%.2f  ATR=%.2f  trail=%.1fx",
            direction.upper(),
            instrument,
            entry_price,
            initial_stop,
            atr,
            self.trail_multiplier,
        )
        return trail

    def update_all(self, snapshots: dict) -> list[tuple[str, str]]:
        """Update all trails with latest prices.

        Args:
            snapshots: dict of instrument -> PriceSnapshot (or any object with .price, .high, .low)

        Returns:
            List of (instrument, action) for triggered events.
        """
        actions = []
        for inst, trail in list(self.trails.items()):
            snap = snapshots.get(inst)
            if not snap:
                continue
            action = trail.update(snap.price, snap.high, snap.low)
            if action:
                actions.append((inst, action))
        return actions

    def remove(self, instrument: str):
        self.trails.pop(instrument, None)

    def get_state(self, instrument: str) -> Optional[TrailState]:
        return self.trails.get(instrument)
