"""
Risk manager: pre-trade validation gate between signal generation and execution.

Supports drawdown-aware dynamic position sizing: when a ``drawdown_cushion``
and ``max_drawdown`` are supplied via ``set_account_state()``, position sizes
are scaled proportionally to remaining cushion.  Falls back to static sizing
when drawdown data is not available.
"""

import logging
from typing import Dict, Optional

from signals.generator import TradingSignal
from risk.position_sizer import calculate_position_size, calculate_drawdown_aware_size
from risk.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Maximum aggregate portfolio risk as a fraction of remaining drawdown cushion.
# If total dollar risk of all open positions exceeds this ratio of the cushion,
# new trades are blocked.
MAX_PORTFOLIO_RISK_RATIO: float = 2.0  # 200% of cushion (relaxed for small accounts)


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

        # Drawdown-aware sizing state (None = not available, use static sizing)
        self.drawdown_cushion: Optional[float] = None
        self.max_drawdown: Optional[float] = None

        # Kelly criterion per-tier risk overrides (set by orchestrator)
        # Maps tier name → risk percentage as decimal (e.g. 0.015 for 1.5%)
        self.tier_risk_overrides: Dict[str, float] = {}

    def set_account_state(
        self,
        starting_equity: float,
        current_equity: float,
        realized_pnl_today: float,
        drawdown_cushion: Optional[float] = None,
        max_drawdown: Optional[float] = None,
    ):
        """
        Update account state (call periodically or on fills).

        Args:
            starting_equity:   Account equity at start of session.
            current_equity:    Current account equity (including unrealized P&L).
            realized_pnl_today: Realized P&L for today.
            drawdown_cushion:  Dollars remaining before trailing drawdown floor
                               is hit.  Pass ``None`` to fall back to static sizing.
            max_drawdown:      Maximum trailing drawdown amount (e.g. 2500 for
                               a $50k Apex eval).  Pass ``None`` to fall back
                               to static sizing.
        """
        self.starting_equity = starting_equity
        self.current_equity = current_equity
        self.realized_pnl_today = realized_pnl_today
        self.drawdown_cushion = drawdown_cushion
        self.max_drawdown = max_drawdown

    def validate(
        self,
        signal: TradingSignal,
        open_positions: int,
        open_positions_dict: Optional[Dict] = None,
    ) -> tuple[bool, Optional[TradingSignal], str]:
        """
        Validate and adjust a trading signal.

        Args:
            signal:               The trading signal to validate.
            open_positions:       Number of currently open positions.
            open_positions_dict:  Dict of instrument -> Position objects, used
                                  for aggregate portfolio risk calculation.
                                  Pass ``None`` to skip portfolio risk cap.

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

        # ── Position sizing: drawdown-aware or static ─────────────
        inst_cfg = self.config["instruments"][signal.instrument]
        base_risk_pct = self.risk_cfg["max_risk_per_trade_pct"] / 100.0
        # Crypto perps use fractional sizes (0.001 BTC); futures use integer contracts
        is_crypto = self.config.get("execution", {}).get("mode") == "hyperliquid"

        # Apply Kelly criterion override if available for this tier
        if self.tier_risk_overrides and signal.shot_type in self.tier_risk_overrides:
            kelly_pct = self.tier_risk_overrides[signal.shot_type]
            if kelly_pct > 0:
                logger.info(
                    "%s: Kelly override for %s: %.2f%% (was %.2f%%)",
                    signal.instrument, signal.shot_type,
                    kelly_pct * 100, base_risk_pct * 100,
                )
                base_risk_pct = kelly_pct

        effective_risk_pct = base_risk_pct  # default for logging

        if self.drawdown_cushion is not None and self.max_drawdown is not None:
            # Scale min_cushion_to_trade proportionally (30% of max_drawdown)
            # $750 default is 30% of $2500 Apex drawdown — same ratio for any account
            min_cushion = self.max_drawdown * 0.30
            # Drawdown-aware dynamic sizing
            contracts, effective_risk_pct = calculate_drawdown_aware_size(
                account_equity=self.current_equity,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                contract_size=inst_cfg["contract_size"],
                base_risk_pct=base_risk_pct,
                max_contracts=self.risk_cfg["max_position_size_contracts"],
                drawdown_cushion=self.drawdown_cushion,
                max_drawdown=self.max_drawdown,
                min_cushion_to_trade=min_cushion,
                fractional=is_crypto,
            )
        else:
            # Fallback: static sizing (no drawdown data available)
            contracts = calculate_position_size(
                account_equity=self.current_equity,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                contract_size=inst_cfg["contract_size"],
                max_risk_pct=base_risk_pct,
                max_contracts=self.risk_cfg["max_position_size_contracts"],
                fractional=is_crypto,
            )

        # Apply shot-tier size multiplier AFTER drawdown scaling
        # (Layup=1.0, Half Court=0.25, etc.)
        size_mult = getattr(signal, "size_multiplier", 1.0)
        # Apply market-regime size multiplier (trending=1.0, ranging=0.75, volatile=0.5)
        regime_mult = getattr(signal, "regime_size_mult", 1.0)
        combined_mult = size_mult * regime_mult

        if combined_mult < 1.0:
            if is_crypto:
                contracts = contracts * combined_mult
            else:
                scaled = int(contracts * combined_mult)
                # Floor to at least 1 if base contracts > 0, else 0
                contracts = max(scaled, 1) if contracts > 0 and combined_mult > 0 else scaled
            logger.info(
                "%s [%s]: tier_mult=%.2f × regime_mult=%.2f = %.2f → %s",
                signal.instrument, signal.shot_type, size_mult, regime_mult,
                combined_mult, f"{contracts:.6f}" if is_crypto else str(int(contracts)),
            )

        if contracts == 0 or (is_crypto and contracts < 1e-8):
            cushion_info = ""
            if self.drawdown_cushion is not None:
                cushion_info = f", cushion=${self.drawdown_cushion:.2f}"
            return (
                False,
                None,
                f"Position size zero after {signal.shot_type} sizing "
                f"(tier={size_mult:.2f} × regime={regime_mult:.2f}, "
                f"eff_risk={effective_risk_pct:.4f}{cushion_info})",
            )

        # ── Aggregate portfolio risk cap ──────────────────────────
        if (
            self.drawdown_cushion is not None
            and self.drawdown_cushion > 0
            and open_positions_dict is not None
        ):
            existing_risk = self.get_portfolio_risk(open_positions_dict)
            new_trade_risk = (
                abs(signal.entry_price - signal.stop_loss)
                * inst_cfg["contract_size"]
                * contracts
            )
            total_risk = existing_risk + new_trade_risk
            risk_cap = self.drawdown_cushion * MAX_PORTFOLIO_RISK_RATIO

            if total_risk > risk_cap:
                logger.warning(
                    "PORTFOLIO RISK CAP: total risk $%.2f (existing $%.2f + new $%.2f) "
                    "> %.0f%% of cushion $%.2f (cap $%.2f)",
                    total_risk, existing_risk, new_trade_risk,
                    MAX_PORTFOLIO_RISK_RATIO * 100, self.drawdown_cushion, risk_cap,
                )
                return (
                    False,
                    None,
                    f"Aggregate portfolio risk ${total_risk:.2f} exceeds "
                    f"{MAX_PORTFOLIO_RISK_RATIO:.0%} of cushion ${self.drawdown_cushion:.2f} "
                    f"(cap ${risk_cap:.2f})",
                )

            logger.info(
                "Portfolio risk check OK: total $%.2f / cap $%.2f (%.0f%% used)",
                total_risk, risk_cap, (total_risk / risk_cap * 100) if risk_cap > 0 else 0,
            )

        # Update signal with validated size
        signal.position_size = contracts

        # Compute dollar risk for this trade
        trade_risk_dollars = (
            abs(signal.entry_price - signal.stop_loss)
            * inst_cfg["contract_size"]
            * contracts
        )

        logger.info(
            "RISK APPROVED [%s]: %s %s %d contracts  risk=$%.2f  "
            "eff_risk_pct=%.4f  cushion=%s",
            signal.shot_type,
            signal.instrument,
            signal.direction,
            contracts,
            trade_risk_dollars,
            effective_risk_pct,
            f"${self.drawdown_cushion:.2f}" if self.drawdown_cushion is not None else "N/A",
        )

        return True, signal, f"Approved ({signal.shot_type})"

    def get_portfolio_risk(self, open_positions_dict: Dict) -> float:
        """
        Sum the dollar risk of all open positions.

        Dollar risk per position = |entry_price - stop_loss| * contract_size * size.

        Args:
            open_positions_dict: Dict of instrument -> Position objects.

        Returns:
            Total dollar risk across all open positions.
        """
        total_risk = 0.0
        for instrument, pos in open_positions_dict.items():
            inst_cfg = self.config["instruments"].get(instrument)
            if inst_cfg is None:
                logger.warning("Unknown instrument %s in open positions, skipping risk calc", instrument)
                continue
            contract_size = inst_cfg["contract_size"]
            pos_risk = abs(pos.entry_price - pos.stop_loss) * contract_size * pos.size
            total_risk += pos_risk
        return total_risk
