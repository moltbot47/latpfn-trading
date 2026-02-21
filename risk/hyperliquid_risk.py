"""
Hyperliquid-specific risk rules with smart entry gatekeeper.

Combines simplified compliance for a personal crypto perps account with
cross-platform intelligence gating. Before opening ANY new position:

  1. Check daily loss limit (percentage-based)
  2. Check max concurrent positions (realistic for account size)
  3. Check per-position notional cap (% of equity, not flat leverage)
  4. Check aggregate leverage after this trade
  5. Check funding rate favorability (avoid paying expensive funding)
  6. Check cross-platform turbo WR on this asset (don't trade turbo-cold assets)
  7. Check if position manager recently closed this coin (cooldown)

Interface-compatible with ApexCompliance so the orchestrator can use
either interchangeably.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class HyperliquidRisk:
    """Risk validator for Hyperliquid crypto perps trading."""

    def __init__(self, config: dict):
        hl_cfg = config.get("hyperliquid", {})
        risk_cfg = config.get("risk", {})
        gate_cfg = hl_cfg.get("gatekeeper", {})

        self.account_equity = hl_cfg.get("account_equity", 250)
        self.max_leverage = hl_cfg.get("default_leverage", 5)
        self.max_concurrent = hl_cfg.get("max_concurrent_positions", 5)
        self.max_risk_per_trade_pct = risk_cfg.get("max_risk_per_trade_pct", 2.0)
        self.daily_loss_limit_pct = hl_cfg.get("daily_loss_limit_pct", 5.0)

        # Smart gatekeeper thresholds (Layer 3)
        self.max_position_pct = gate_cfg.get("max_position_pct", 0.30)    # max 30% of equity per position
        self.max_aggregate_leverage = gate_cfg.get("max_aggregate_leverage", 5.0)
        self.min_turbo_wr = gate_cfg.get("min_turbo_wr", 0.25)            # block if turbo WR < 25%
        self.funding_penalty_threshold = gate_cfg.get("funding_penalty_threshold", 0.005)  # 0.5%/8h
        self.close_cooldown_seconds = gate_cfg.get("close_cooldown_seconds", 300)  # 5 min after PM close

        # ApexCompliance-compatible attribute
        self.trailing_drawdown_amount = self.account_equity * (self.daily_loss_limit_pct / 100)

        # State
        self._daily_pnl = 0.0
        self._current_date = None

        # Cross-platform intelligence (set externally by feedback bus)
        self._turbo_asset_wr: Dict[str, float] = {}
        self._turbo_feedback_ts: float = 0
        self._pm_close_times: Dict[str, float] = {}   # coin → last PM close timestamp
        self._current_aggregate_leverage: float = 0
        self._funding_rates: Dict[str, float] = {}     # coin → current 8h funding rate
        self._gate_block_reasons: list = []             # recent block reasons for TUI

    def check_all(
        self,
        signal,
        open_count: int = 0,
        realized_pnl_today: float = 0.0,
    ) -> tuple:
        """
        Run all Hyperliquid risk checks including smart gatekeeper.

        Returns:
            (passed: bool, reason: str)
        """
        today = datetime.now().date()
        if self._current_date != today:
            self._daily_pnl = 0.0
            self._current_date = today

        self._daily_pnl = realized_pnl_today

        # Check 1: Daily loss limit
        daily_limit = self.account_equity * (self.daily_loss_limit_pct / 100)
        if self._daily_pnl < -daily_limit:
            reason = f"Daily loss limit hit: ${self._daily_pnl:.2f} exceeds -${daily_limit:.2f}"
            self._gate_block_reasons.append(("daily_loss", reason))
            return (False, reason)

        # Check 2: Max concurrent positions
        if open_count >= self.max_concurrent:
            reason = f"Max concurrent positions reached: {open_count}/{self.max_concurrent}"
            self._gate_block_reasons.append(("max_pos", reason))
            return (False, reason)

        # Check 3: Per-position notional cap (% of equity)
        entry = getattr(signal, "entry_price", 0)
        size = getattr(signal, "position_size", 0)
        notional = entry * size if entry and size else 0
        max_per_position = self.account_equity * self.max_position_pct
        if notional > max_per_position:
            reason = (
                f"Position notional ${notional:.0f} exceeds "
                f"{self.max_position_pct:.0%} of equity (${max_per_position:.0f})"
            )
            self._gate_block_reasons.append(("notional_cap", reason))
            return (False, reason)

        # Check 4: Aggregate leverage cap
        if self._current_aggregate_leverage > 0:
            new_leverage = (self._current_aggregate_leverage * self.account_equity + notional) / max(self.account_equity, 1)
            if new_leverage > self.max_aggregate_leverage:
                reason = (
                    f"Aggregate leverage {new_leverage:.1f}x would exceed "
                    f"{self.max_aggregate_leverage:.0f}x cap"
                )
                self._gate_block_reasons.append(("agg_leverage", reason))
                return (False, reason)

        # Check 5: Cross-platform turbo WR gate
        instrument = getattr(signal, "instrument", "") or ""
        coin_lower = instrument.lower()
        if self._turbo_asset_wr and (time.time() - self._turbo_feedback_ts) < 600:
            turbo_wr = self._turbo_asset_wr.get(coin_lower)
            if turbo_wr is not None and turbo_wr < self.min_turbo_wr:
                reason = (
                    f"Turbo WR for {coin_lower.upper()} is {turbo_wr:.0%} "
                    f"(below {self.min_turbo_wr:.0%} gate)"
                )
                self._gate_block_reasons.append(("turbo_wr", reason))
                return (False, reason)

        # Check 6: Funding rate against direction
        direction = getattr(signal, "direction", "")
        funding = self._funding_rates.get(coin_lower, 0)
        if abs(funding) > self.funding_penalty_threshold:
            is_long = direction == "long"
            funding_against = (is_long and funding > self.funding_penalty_threshold) or \
                              (not is_long and funding < -self.funding_penalty_threshold)
            if funding_against:
                annual = abs(funding) * 3 * 365 * 100
                reason = (
                    f"Funding rate {annual:.0f}%/yr against {direction} {coin_lower.upper()} "
                    f"(threshold: {self.funding_penalty_threshold*3*365*100:.0f}%/yr)"
                )
                self._gate_block_reasons.append(("funding", reason))
                return (False, reason)

        # Check 7: Position manager cooldown
        close_time = self._pm_close_times.get(coin_lower, 0)
        if close_time and (time.time() - close_time) < self.close_cooldown_seconds:
            remaining = self.close_cooldown_seconds - (time.time() - close_time)
            reason = (
                f"Position manager closed {coin_lower.upper()} {remaining:.0f}s ago "
                f"(cooldown: {self.close_cooldown_seconds}s)"
            )
            self._gate_block_reasons.append(("pm_cooldown", reason))
            return (False, reason)

        # Trim block reasons log
        if len(self._gate_block_reasons) > 100:
            self._gate_block_reasons = self._gate_block_reasons[-100:]

        return (True, "passed")

    # ── Cross-platform intelligence setters ─────────────────────

    def update_turbo_feedback(self, asset_wr: Dict[str, float]):
        """Update turbo WR data for gatekeeper checks."""
        self._turbo_asset_wr = asset_wr
        self._turbo_feedback_ts = time.time()

    def update_funding_rates(self, rates: Dict[str, float]):
        """Update current funding rates for all watched coins."""
        self._funding_rates = rates

    def update_aggregate_leverage(self, leverage: float):
        """Update current aggregate leverage from position manager."""
        self._current_aggregate_leverage = leverage

    def record_pm_close(self, coin: str):
        """Record that position manager closed a coin (triggers cooldown)."""
        self._pm_close_times[coin.lower()] = time.time()

    # ── ApexCompliance-compatible interface ──────────────────────

    def should_flatten_now(self) -> bool:
        """Crypto trades 24/7 — never auto-flatten for time."""
        return False

    def is_in_no_new_trades_window(self) -> bool:
        """Crypto trades 24/7 — always open for new trades."""
        return False

    def update_balance(self, current_balance) -> dict:
        """Update tracked account equity."""
        if isinstance(current_balance, (int, float)):
            self.account_equity = current_balance
            self.trailing_drawdown_amount = self.account_equity * (self.daily_loss_limit_pct / 100)
        return self.get_drawdown_status(self.account_equity)

    def get_drawdown_status(self, current_balance: float = None) -> dict:
        """Return drawdown status compatible with ApexCompliance format."""
        bal = current_balance if current_balance is not None else self.account_equity
        daily_limit = bal * (self.daily_loss_limit_pct / 100)
        cushion = daily_limit + self._daily_pnl
        cushion_pct = (cushion / daily_limit * 100) if daily_limit > 0 else 100

        return {
            "current_balance": bal,
            "highest_balance": bal,
            "drawdown_floor": bal - daily_limit,
            "floor_locked": False,
            "cushion": cushion,
            "cushion_pct": cushion_pct,
            "at_risk": self._daily_pnl < -(daily_limit * 0.50),
            "profit_to_target": 0,
            "profit_target_balance": 0,
            # Hyperliquid-specific extras
            "account_equity": bal,
            "daily_pnl": self._daily_pnl,
            "daily_limit": daily_limit,
            "max_leverage": self.max_leverage,
            "aggregate_leverage": self._current_aggregate_leverage,
            "turbo_asset_wr": self._turbo_asset_wr,
            "recent_blocks": self._gate_block_reasons[-5:],
        }

    def load_drawdown_state(self):
        """No persistent drawdown tracking needed for personal account."""
        pass

    def save_drawdown_state(self):
        """No persistent drawdown tracking needed for personal account."""
        pass
