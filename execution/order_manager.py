"""
Order lifecycle management: tracks active orders/positions and P&L.
"""

import logging
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

    @property
    def unrealized_pnl_points(self) -> float:
        if self.current_price == 0:
            return 0.0
        diff = self.current_price - self.entry_price
        return diff if self.direction == "long" else -diff


class OrderManager:
    """Tracks positions and realized P&L."""

    def __init__(self):
        self.open_positions: Dict[str, Position] = {}  # keyed by instrument
        self.closed_positions: List[Position] = []
        self.realized_pnl_today: float = 0.0

    def add_position(self, position: Position):
        self.open_positions[position.instrument] = position
        logger.info(
            "Position opened: %s %s %d @ %.2f",
            position.instrument, position.direction,
            position.size, position.entry_price,
        )

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

    def close_all(self):
        """Remove all open positions from tracking."""
        for instrument in list(self.open_positions.keys()):
            self.remove_position(instrument)

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    def reset_daily_pnl(self):
        self.realized_pnl_today = 0.0
