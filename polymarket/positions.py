"""
Polymarket position tracking with JSON persistence.

Same pattern as execution/order_manager.py — positions are saved to
data/polymarket_positions.json and reloaded on restart.
"""

import dataclasses
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

POSITIONS_FILE = Path(__file__).parent.parent / "data" / "polymarket_positions.json"


@dataclass
class PolyPosition:
    """A single Polymarket position."""

    market_id: str  # conditionId
    token_id: str  # YES or NO outcome token
    question: str
    strategy: str  # "resolution_snipe" | "superforecaster"
    direction: str  # "YES" | "NO"
    entry_price: float  # 0.85 = $0.85
    size_usdc: float  # USDC spent
    shares: float  # shares owned (size / price)
    target_exit: float  # expected exit price
    expected_pnl_pct: float
    resolution_date: str  # ISO timestamp
    llm_probability: float = 0.0
    market_probability: float = 0.0
    opened_at: str = ""
    status: str = "open"  # open | closed | resolved
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    closed_at: str = ""
    order_id: str = ""
    metadata: Dict = field(default_factory=dict)


class PositionManager:
    """Manages Polymarket positions with JSON persistence."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or POSITIONS_FILE
        self.positions: Dict[str, PolyPosition] = {}
        self._load()

    def _load(self):
        """Load positions from disk."""
        if not self.path.exists():
            self.positions = {}
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            valid_fields = {f.name for f in dataclasses.fields(PolyPosition)}
            self.positions = {}
            for key, val in data.items():
                filtered = {k: v for k, v in val.items() if k in valid_fields}
                self.positions[key] = PolyPosition(**filtered)
            logger.info("Loaded %d Polymarket positions", len(self.positions))
        except Exception as e:
            logger.error("Failed to load Polymarket positions: %s", e)
            self.positions = {}

    def _save(self):
        """Persist positions to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {k: asdict(v) for k, v in self.positions.items()}
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save Polymarket positions: %s", e)

    def open_position(self, pos: PolyPosition) -> str:
        """Record a new position. Returns the position key."""
        if not pos.opened_at:
            pos.opened_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        key = f"{pos.market_id}_{pos.direction}_{int(time.time())}"
        self.positions[key] = pos
        self._save()
        logger.info(
            "Opened %s position: %s %s @ %.4f ($%.2f, %.1f shares)",
            pos.strategy, pos.direction, pos.question[:50],
            pos.entry_price, pos.size_usdc, pos.shares,
        )
        return key

    def close_position(
        self, key: str, exit_price: float, realized_pnl: float
    ):
        """Mark position as closed with exit details."""
        if key not in self.positions:
            logger.warning("Position key %s not found", key)
            return
        pos = self.positions[key]
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.realized_pnl = realized_pnl
        pos.closed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()
        logger.info(
            "Closed position %s: %s @ %.4f → %.4f  PnL=$%.4f",
            key, pos.question[:40], pos.entry_price, exit_price, realized_pnl,
        )

    def resolve_position(self, key: str, outcome_price: float):
        """Mark position as resolved (market ended)."""
        if key not in self.positions:
            return
        pos = self.positions[key]
        pnl = (outcome_price - pos.entry_price) * pos.shares
        pos.status = "resolved"
        pos.exit_price = outcome_price
        pos.realized_pnl = pnl
        pos.closed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()
        logger.info(
            "Resolved %s: outcome=%.2f  PnL=$%.4f", pos.question[:40],
            outcome_price, pnl,
        )

    def get_open_positions(self) -> Dict[str, PolyPosition]:
        """Return only open positions."""
        return {k: v for k, v in self.positions.items() if v.status == "open"}

    def get_positions_by_strategy(self, strategy: str) -> Dict[str, PolyPosition]:
        """Return open positions for a specific strategy."""
        return {
            k: v for k, v in self.positions.items()
            if v.status == "open" and v.strategy == strategy
        }

    def total_deployed(self) -> float:
        """Total USDC currently deployed in open positions."""
        return sum(p.size_usdc for p in self.positions.values() if p.status == "open")

    def total_realized_pnl(self) -> float:
        """Total realized P&L across all closed/resolved positions."""
        return sum(
            p.realized_pnl for p in self.positions.values()
            if p.status in ("closed", "resolved")
        )

    def position_count(self) -> int:
        """Number of open positions."""
        return sum(1 for p in self.positions.values() if p.status == "open")

    def has_position_for_market(self, market_id: str) -> bool:
        """Check if we already have an open position on this market."""
        return any(
            p.market_id == market_id and p.status == "open"
            for p in self.positions.values()
        )
