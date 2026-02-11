"""
Order lifecycle management: tracks active orders/positions and P&L.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """An active position."""
    instrument: str
    direction: str
    size: int
    entry_price: float
    stop_loss: float
    take_profit: float
    order_id: Optional[int] = None
    entry_time: datetime = field(default_factory=datetime.now)
    current_price: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "instrument": self.instrument,
            "direction": self.direction,
            "size": self.size,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "order_id": self.order_id,
            "entry_time": self.entry_time.isoformat(),
            "current_price": self.current_price,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        """Deserialize from a dictionary."""
        return cls(
            instrument=data["instrument"],
            direction=data["direction"],
            size=data["size"],
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            order_id=data.get("order_id"),
            entry_time=datetime.fromisoformat(data["entry_time"])
            if "entry_time" in data
            else datetime.now(),
            current_price=data.get("current_price", 0.0),
        )

    @property
    def unrealized_pnl_points(self) -> float:
        if self.current_price == 0:
            return 0.0
        diff = self.current_price - self.entry_price
        return diff if self.direction == "long" else -diff


class OrderManager:
    """Tracks positions and realized P&L."""

    def __init__(self, state_file: str = "./data/positions.json"):
        self.open_positions: Dict[str, Position] = {}  # keyed by instrument
        self.closed_positions: List[Position] = []
        self.realized_pnl_today: float = 0.0
        self.state_file: str = state_file

    def add_position(self, position: Position):
        self.open_positions[position.instrument] = position
        logger.info(
            "Position opened: %s %s %d @ %.2f",
            position.instrument, position.direction,
            position.size, position.entry_price,
        )
        self._save_state()

    def close_position(
        self,
        instrument: str,
        exit_price: float,
        contract_size: float,
    ) -> float:
        """
        Close a position and record P&L.

        Returns realized P&L in dollars.
        """
        pos = self.open_positions.pop(instrument, None)
        if pos is None:
            logger.warning("No open position for %s to close", instrument)
            return 0.0

        pnl_points = exit_price - pos.entry_price
        if pos.direction == "short":
            pnl_points = -pnl_points

        pnl_dollars = pnl_points * contract_size * pos.size

        self.realized_pnl_today += pnl_dollars
        self.closed_positions.append(pos)

        logger.info(
            "Position closed: %s  exit=%.2f  pnl=%.2f pts ($%.2f)",
            instrument, exit_price, pnl_points, pnl_dollars,
        )

        self._save_state()
        return pnl_dollars

    def update_prices(self, prices: Dict[str, float]):
        """Update current prices for open positions."""
        for instrument, price in prices.items():
            if instrument in self.open_positions:
                self.open_positions[instrument].current_price = price

    def has_position(self, instrument: str) -> bool:
        return instrument in self.open_positions

    def remove_position(self, instrument: str):
        """Remove a position from tracking (used when closed externally)."""
        pos = self.open_positions.pop(instrument, None)
        if pos:
            self.closed_positions.append(pos)
            logger.info("Position removed from tracking: %s", instrument)
            self._save_state()

    def close_all(self):
        """Remove all open positions from tracking."""
        for instrument in list(self.open_positions.keys()):
            self.remove_position(instrument)

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    # ---- Persistence ---------------------------------------------------

    def _save_state(self):
        """Write all open positions to the JSON state file."""
        try:
            dir_name = os.path.dirname(self.state_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            payload = [pos.to_dict() for pos in self.open_positions.values()]
            tmp_path = self.state_file + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.state_file)
            logger.debug("Saved %d position(s) to %s", len(payload), self.state_file)
        except Exception as e:
            logger.error("Failed to save position state: %s", e)

    def load_state(self):
        """Load open positions from the JSON state file (call on startup)."""
        if not os.path.exists(self.state_file):
            logger.info("No position state file found at %s — starting fresh", self.state_file)
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            for item in data:
                pos = Position.from_dict(item)
                self.open_positions[pos.instrument] = pos
            logger.info(
                "Restored %d position(s) from %s", len(data), self.state_file
            )
        except Exception as e:
            logger.error("Failed to load position state from %s: %s", self.state_file, e)

    # ---- Helpers -------------------------------------------------------

    def reset_daily_pnl(self):
        self.realized_pnl_today = 0.0
