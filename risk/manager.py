"""
Risk manager: pre-trade validation gate between signal generation and execution.
"""

import logging
from typing import Optional

from signals.generator import TradingSignal
from risk.position_sizer import calculate_position_size
from risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class RiskManager:
    """Validates signals and enforces all risk rules before execution."""

    def __init__(self, config: dict):
        self.config = config
        self.risk_cfg = config["risk"]
        self.circuit_breaker = CircuitBreaker(config)

        # Account state (updated externally)
        self.starting_equity = 0.0
        self.current_equity = 0.0
        self.realized_pnl_today = 0.0

    def set_account_state(
        self,
        starting_equity: float,
        current_equity: float,
        realized_pnl_today: float,
    ):
        """Update account state (call periodically or on fills)."""
        self.starting_equity = starting_equity
        self.current_equity = current_equity
        self.realized_pnl_today = realized_pnl_today

    def validate(
        self,
        signal: TradingSignal,
        open_positions: int,
    ) -> tuple[bool, Optional[TradingSignal], str]:
        """
        Validate and adjust a trading signal.

        Returns:
            (approved, adjusted_signal_or_None, reason_string)
        """
        # Update circuit breaker
        self.circuit_breaker.update(
            realized_pnl_today=self.realized_pnl_today,
            current_equity=self.current_equity,
            starting_equity=self.starting_equity,
            open_positions=open_positions,
        )

        # Check circuit breaker
        ok, reason = self.circuit_breaker.can_open_position(open_positions)
        if not ok:
            return False, None, reason

        # Calculate proper position size
        inst_cfg = self.config["instruments"][signal.instrument]
        contracts = calculate_position_size(
            account_equity=self.current_equity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            contract_size=inst_cfg["contract_size"],
            max_risk_pct=self.risk_cfg["max_risk_per_trade_pct"] / 100.0,
            max_contracts=self.risk_cfg["max_position_size_contracts"],
        )

        # Apply shot-tier size multiplier (Layup=1.0, Half Court=0.25, etc.)
        size_mult = getattr(signal, "size_multiplier", 1.0)
        if size_mult < 1.0:
            scaled = int(contracts * size_mult)
            # Floor to at least 1 if base contracts > 0, else 0
            contracts = max(scaled, 1) if contracts > 0 and size_mult > 0 else scaled
            logger.info(
                "%s [%s]: size_multiplier=%.2f → %d contracts",
                signal.instrument, signal.shot_type, size_mult, contracts,
            )

        if contracts == 0:
            return False, None, f"Position size zero after {signal.shot_type} sizing (size_mult={size_mult:.2f})"

        # Update signal with validated size
        signal.position_size = contracts

        logger.info(
            "RISK APPROVED [%s]: %s %s %d contracts  risk=$%.2f",
            signal.shot_type,
            signal.instrument,
            signal.direction,
            contracts,
            abs(signal.entry_price - signal.stop_loss) * inst_cfg["contract_size"] * contracts,
        )

        return True, signal, f"Approved ({signal.shot_type})"
