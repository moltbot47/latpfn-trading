"""
Hyperliquid Position Manager — active position lifecycle management.

Runs every 30 seconds alongside the main trading loop. Queries real
exchange state and enforces:
  1. Hard stop: cut losers beyond ROE threshold
  2. Trailing profit lock: move stop to breakeven once in profit
  3. Dust cleanup: close positions too small to matter
  4. Leverage cap: reduce exposure when aggregate leverage is too high
  5. Funding drain: close positions bleeding funding with no upside
  6. Max position count: close worst performers when over limit
  7. Cross-platform intelligence: tighten/loosen thresholds based on
     Polymarket turbo feedback

Reads real positions from Hyperliquid API. Executes closes via
HyperliquidClient. Publishes actions to MessageBus for TUI + feedback.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Default thresholds ───────────────────────────────────────────

DEFAULT_CUT_LOSS_ROE = -0.10       # -10% ROE → hard close
DEFAULT_PROFIT_LOCK_ROE = 0.05     # +5% ROE → set trailing stop at +2%
DEFAULT_TRAILING_STOP_ROE = 0.02   # trailing stop distance (2% below peak)
DEFAULT_DUST_VALUE_USD = 3.0       # positions below $3 notional → close
DEFAULT_MAX_POSITIONS = 5          # max simultaneous positions
DEFAULT_MAX_LEVERAGE = 5.0         # max aggregate account leverage
DEFAULT_MAX_POSITION_PCT = 0.30    # max 30% of equity in one position
DEFAULT_FUNDING_DRAIN_RATE = 0.01  # 1% per 8h funding = close if losing
DEFAULT_MAX_AGE_HOURS = 48         # close positions older than 48h
DEFAULT_SCAN_INTERVAL = 30         # seconds between scans


@dataclass
class ManagedPosition:
    """Enriched position state tracked by the manager."""
    coin: str
    size: float                     # signed: positive=long, negative=short
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    roe_pct: float                  # return on equity %
    margin_used: float
    notional_value: float
    leverage: int
    funding_rate: float             # current 8h funding rate
    funding_pnl: float             # cumulative funding paid/received
    liq_price: float
    age_hours: float
    # Manager state
    trailing_stop_price: float = 0.0
    peak_roe: float = 0.0
    action_taken: str = ""


@dataclass
class ManagerAction:
    """Record of an action taken by the position manager."""
    coin: str
    action: str                     # close_loss, close_profit, close_dust, close_leverage, close_funding
    reason: str
    roe_at_action: float
    pnl_at_action: float
    timestamp: float = field(default_factory=time.time)


class HLPositionManager:
    """Active position lifecycle manager for Hyperliquid."""

    def __init__(self, client, config: dict, bus=None):
        """
        Args:
            client: HyperliquidClient instance (may not be connected yet).
            config: Full config dict (reads hyperliquid section).
            bus: Optional MessageBus for publishing actions.
        """
        self._client = client
        self._bus = bus

        hl_cfg = config.get("hyperliquid", {})
        pm_cfg = hl_cfg.get("position_manager", {})

        # Thresholds (configurable via settings.yaml)
        self.cut_loss_roe = pm_cfg.get("cut_loss_roe", DEFAULT_CUT_LOSS_ROE)
        self.profit_lock_roe = pm_cfg.get("profit_lock_roe", DEFAULT_PROFIT_LOCK_ROE)
        self.trailing_stop_roe = pm_cfg.get("trailing_stop_roe", DEFAULT_TRAILING_STOP_ROE)
        self.dust_value_usd = pm_cfg.get("dust_value_usd", DEFAULT_DUST_VALUE_USD)
        self.max_positions = pm_cfg.get("max_positions", DEFAULT_MAX_POSITIONS)
        self.max_leverage = pm_cfg.get("max_leverage", DEFAULT_MAX_LEVERAGE)
        self.max_position_pct = pm_cfg.get("max_position_pct", DEFAULT_MAX_POSITION_PCT)
        self.funding_drain_rate = pm_cfg.get("funding_drain_rate", DEFAULT_FUNDING_DRAIN_RATE)
        self.max_age_hours = pm_cfg.get("max_age_hours", DEFAULT_MAX_AGE_HOURS)
        self.scan_interval = pm_cfg.get("scan_interval", DEFAULT_SCAN_INTERVAL)

        # State
        self._positions: Dict[str, ManagedPosition] = {}
        self._trailing_stops: Dict[str, float] = {}   # coin → trailing stop price
        self._peak_roes: Dict[str, float] = {}         # coin → highest ROE seen
        self._first_seen: Dict[str, float] = {}        # coin → first observed timestamp
        self._action_log: List[ManagerAction] = []
        self._last_scan: float = 0
        self._account_equity: float = 0
        self._total_notional: float = 0
        self._total_margin: float = 0
        self._aggregate_leverage: float = 0
        self._running = False

        # External references (set by runner.py)
        self._pair_scanner = None   # for funding rate enrichment

        # Cross-platform intelligence (set externally by feedback bus)
        self._turbo_asset_wr: Dict[str, float] = {}    # asset → rolling WR from turbo
        self._turbo_hot_assets: set = set()             # assets turbo is winning on
        self._turbo_cold_assets: set = set()            # assets turbo is losing on

    # ── Main loop ────────────────────────────────────────────────

    async def start(self):
        """Start the position management loop (run as asyncio task)."""
        self._running = True
        logger.info(
            "HL Position Manager started — scan every %ds, "
            "cut_loss=%.0f%%, profit_lock=%.0f%%, max_pos=%d, max_lev=%.0fx",
            self.scan_interval,
            self.cut_loss_roe * 100,
            self.profit_lock_roe * 100,
            self.max_positions,
            self.max_leverage,
        )
        while self._running:
            try:
                await self.scan_and_manage()
            except Exception as e:
                logger.error("Position manager scan error: %s", e)
            await asyncio.sleep(self.scan_interval)

    def stop(self):
        """Stop the management loop."""
        self._running = False

    # ── Core scan ────────────────────────────────────────────────

    async def scan_and_manage(self) -> List[ManagerAction]:
        """
        Full scan cycle:
        1. Fetch real positions from exchange
        2. Compute enriched metrics for each
        3. Apply rules in priority order
        4. Execute closes
        5. Return list of actions taken
        """
        actions = []

        # Fetch real exchange state
        positions = await self._fetch_positions()
        if positions is None:
            return actions

        self._positions = {p.coin: p for p in positions}
        self._last_scan = time.time()

        # Enrich funding rates from pair scanner BEFORE rules run
        if self._pair_scanner:
            self.enrich_funding_rates(self._pair_scanner)

        if not positions:
            return actions

        # Log summary
        total_pnl = sum(p.unrealized_pnl for p in positions)
        logger.info(
            "Position scan: %d positions, equity=$%.2f, leverage=%.1fx, "
            "unrealized=$%.2f",
            len(positions), self._account_equity,
            self._aggregate_leverage, total_pnl,
        )

        # Apply rules in priority order (most urgent first)
        # Track coins already closed this scan to prevent double-close
        closed_this_scan: set = set()

        # Rule 1: Hard loss cut (highest priority)
        actions.extend(await self._rule_cut_losses(positions, closed_this_scan))

        # Rule 2: Dust cleanup (free up margin for nothing)
        actions.extend(await self._rule_close_dust(positions, closed_this_scan))

        # Rule 3: Leverage reduction (systemic risk)
        actions.extend(await self._rule_reduce_leverage(positions, closed_this_scan))

        # Rule 4: Max position count (close worst performers)
        actions.extend(await self._rule_max_positions(positions, closed_this_scan))

        # Rule 5: Funding drain (bleeding money on losing side)
        actions.extend(await self._rule_funding_drain(positions, closed_this_scan))

        # Rule 6: Age limit
        actions.extend(await self._rule_max_age(positions, closed_this_scan))

        # Rule 7: Trailing profit lock (set/update trailing stops)
        actions.extend(await self._rule_trailing_profit(positions, closed_this_scan))

        # Log actions
        self._action_log.extend(actions)
        # Keep rolling window
        if len(self._action_log) > 500:
            self._action_log = self._action_log[-500:]

        if actions:
            for a in actions:
                logger.info(
                    "POSITION MANAGER: %s %s — %s (ROE=%.1f%%, PnL=$%.2f)",
                    a.action, a.coin, a.reason,
                    a.roe_at_action * 100, a.pnl_at_action,
                )

            # Publish to message bus if available
            if self._bus:
                await self._publish_actions(actions)

        return actions

    # ── Rules ────────────────────────────────────────────────────

    async def _rule_cut_losses(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Close positions exceeding loss threshold."""
        actions = []
        for p in positions:
            if p.coin in closed:
                continue
            # Dynamic threshold: tighten for turbo-cold assets
            threshold = self.cut_loss_roe
            asset_key = p.coin.lower()
            if asset_key in self._turbo_cold_assets:
                threshold = threshold * 0.5  # -5% instead of -10%

            if p.roe_pct <= threshold:
                result = await self._close_position(p.coin)
                if result:
                    closed.add(p.coin)
                    actions.append(ManagerAction(
                        coin=p.coin,
                        action="close_loss",
                        reason=f"ROE {p.roe_pct:.1%} breached {threshold:.0%} threshold"
                              + (" (turbo-cold tightened)" if asset_key in self._turbo_cold_assets else ""),
                        roe_at_action=p.roe_pct,
                        pnl_at_action=p.unrealized_pnl,
                    ))
        return actions

    async def _rule_close_dust(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Close positions with negligible notional value."""
        actions = []
        for p in positions:
            if p.coin in closed:
                continue
            if abs(p.notional_value) < self.dust_value_usd:
                result = await self._close_position(p.coin)
                if result:
                    closed.add(p.coin)
                    actions.append(ManagerAction(
                        coin=p.coin,
                        action="close_dust",
                        reason=f"Notional ${abs(p.notional_value):.2f} below ${self.dust_value_usd:.0f} dust threshold",
                        roe_at_action=p.roe_pct,
                        pnl_at_action=p.unrealized_pnl,
                    ))
        return actions

    async def _rule_reduce_leverage(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Reduce leverage by closing worst positions when aggregate leverage is too high."""
        actions = []
        if self._aggregate_leverage <= self.max_leverage:
            return actions

        # Sort by unrealized PnL ascending (worst first)
        sorted_positions = sorted(positions, key=lambda p: p.unrealized_pnl)

        for p in sorted_positions:
            if p.coin in closed:
                continue
            if self._aggregate_leverage <= self.max_leverage:
                break

            pre_close_leverage = self._aggregate_leverage
            result = await self._close_position(p.coin)
            if result:
                closed.add(p.coin)
                # Recalculate leverage after close
                self._total_notional -= abs(p.notional_value)
                if self._account_equity > 0:
                    self._aggregate_leverage = self._total_notional / self._account_equity

                actions.append(ManagerAction(
                    coin=p.coin,
                    action="close_leverage",
                    reason=f"Aggregate leverage {pre_close_leverage:.1f}x "
                           f"exceeded {self.max_leverage:.0f}x cap",
                    roe_at_action=p.roe_pct,
                    pnl_at_action=p.unrealized_pnl,
                ))

        return actions

    async def _rule_max_positions(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Close worst performers when over max position count."""
        actions = []

        active = [p for p in positions if p.coin not in closed]
        if len(active) <= self.max_positions:
            return actions

        # Sort by unrealized PnL ascending (worst first)
        sorted_positions = sorted(active, key=lambda p: p.unrealized_pnl)
        excess = len(active) - self.max_positions

        for p in sorted_positions[:excess]:
            result = await self._close_position(p.coin)
            if result:
                closed.add(p.coin)
                actions.append(ManagerAction(
                    coin=p.coin,
                    action="close_max_positions",
                    reason=f"{len(active)} positions exceeded {self.max_positions} max "
                           f"(worst performer: PnL ${p.unrealized_pnl:.2f})",
                    roe_at_action=p.roe_pct,
                    pnl_at_action=p.unrealized_pnl,
                ))

        return actions

    async def _rule_funding_drain(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Close positions that are losing AND paying expensive funding."""
        actions = []
        for p in positions:
            if p.coin in closed:
                continue

            # Only close if: position is losing AND funding rate is against us
            is_long = p.size > 0
            funding_against = (is_long and p.funding_rate > self.funding_drain_rate) or \
                              (not is_long and p.funding_rate < -self.funding_drain_rate)

            if funding_against and p.unrealized_pnl < 0:
                annual_rate = abs(p.funding_rate) * 3 * 365 * 100
                result = await self._close_position(p.coin)
                if result:
                    closed.add(p.coin)
                    actions.append(ManagerAction(
                        coin=p.coin,
                        action="close_funding",
                        reason=f"Losing ${abs(p.unrealized_pnl):.2f} + funding "
                               f"{annual_rate:.0f}%/yr against position",
                        roe_at_action=p.roe_pct,
                        pnl_at_action=p.unrealized_pnl,
                    ))

        return actions

    async def _rule_max_age(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Close positions exceeding max age."""
        actions = []
        for p in positions:
            if p.coin in closed:
                continue
            if p.age_hours > self.max_age_hours and p.unrealized_pnl <= 0:
                result = await self._close_position(p.coin)
                if result:
                    closed.add(p.coin)
                    actions.append(ManagerAction(
                        coin=p.coin,
                        action="close_age",
                        reason=f"Open {p.age_hours:.0f}h (max {self.max_age_hours}h) with negative PnL",
                        roe_at_action=p.roe_pct,
                        pnl_at_action=p.unrealized_pnl,
                    ))
        return actions

    async def _rule_trailing_profit(self, positions: List[ManagedPosition], closed: set) -> List[ManagerAction]:
        """Manage trailing stops for profitable positions."""
        actions = []
        for p in positions:
            if p.coin in closed:
                continue

            # Track peak ROE
            prev_peak = self._peak_roes.get(p.coin, 0)
            if p.roe_pct > prev_peak:
                self._peak_roes[p.coin] = p.roe_pct

            current_peak = self._peak_roes.get(p.coin, 0)

            # Only set trailing stop if we've reached profit lock threshold
            if current_peak < self.profit_lock_roe:
                continue

            # Dynamic trailing distance: tighter for turbo-hot assets (let winners run less)
            trail_distance = self.trailing_stop_roe
            asset_key = p.coin.lower()
            if asset_key in self._turbo_hot_assets:
                trail_distance = self.trailing_stop_roe * 0.5  # tighter trail

            # Calculate trailing stop level
            is_long = p.size > 0
            if is_long:
                trail_price = p.mark_price * (1 - trail_distance)
                prev_trail = self._trailing_stops.get(p.coin, 0)
                # Only ratchet up
                trail_price = max(trail_price, prev_trail)
                self._trailing_stops[p.coin] = trail_price

                # Check if trailing stop was hit
                if p.mark_price <= trail_price and trail_price > 0 and prev_trail > 0:
                    result = await self._close_position(p.coin)
                    if result:
                        closed.add(p.coin)
                        actions.append(ManagerAction(
                            coin=p.coin,
                            action="close_trailing",
                            reason=f"Trailing stop hit at ${trail_price:.2f} "
                                   f"(peak ROE {current_peak:.1%}, locked profit)",
                            roe_at_action=p.roe_pct,
                            pnl_at_action=p.unrealized_pnl,
                        ))
            else:
                trail_price = p.mark_price * (1 + trail_distance)
                prev_trail = self._trailing_stops.get(p.coin, float('inf'))
                trail_price = min(trail_price, prev_trail)
                self._trailing_stops[p.coin] = trail_price

                if p.mark_price >= trail_price and trail_price < float('inf') and prev_trail < float('inf'):
                    result = await self._close_position(p.coin)
                    if result:
                        closed.add(p.coin)
                        actions.append(ManagerAction(
                            coin=p.coin,
                            action="close_trailing",
                            reason=f"Trailing stop hit at ${trail_price:.2f} "
                                   f"(peak ROE {current_peak:.1%}, locked profit)",
                            roe_at_action=p.roe_pct,
                            pnl_at_action=p.unrealized_pnl,
                        ))

        return actions

    # ── Exchange interaction ─────────────────────────────────────

    async def _fetch_positions(self) -> Optional[List[ManagedPosition]]:
        """Fetch all open positions from Hyperliquid with enriched metrics."""
        try:
            if not self._client._info or not self._client._address:
                logger.debug("Position manager: client not connected yet, skipping scan")
                return None
            # SDK call is synchronous HTTP — run in thread to avoid blocking event loop
            state = await asyncio.to_thread(
                self._client._info.user_state, self._client._address
            )
            margin_summary = state.get("marginSummary", {})
            self._account_equity = float(margin_summary.get("accountValue", 0))
            self._total_margin = float(margin_summary.get("totalMarginUsed", 0))
            self._total_notional = float(margin_summary.get("totalNtlPos", 0))

            if self._account_equity > 0:
                self._aggregate_leverage = self._total_notional / self._account_equity
            else:
                self._aggregate_leverage = 0

            positions = []
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                sz = float(pos.get("szi", 0))
                if sz == 0:
                    continue

                entry_px = float(pos.get("entryPx", 0))
                mark_px = float(pos.get("positionValue", 0))
                # positionValue is total notional — derive mark price
                if abs(sz) > 0:
                    mark_px_derived = abs(float(pos.get("positionValue", 0))) / abs(sz)
                else:
                    mark_px_derived = entry_px

                unrealized = float(pos.get("unrealizedPnl", 0))
                margin = float(pos.get("marginUsed", 0))
                notional = abs(float(pos.get("positionValue", 0)))
                leverage_val = int(pos.get("leverage", {}).get("value", 5)) if isinstance(pos.get("leverage"), dict) else 5
                funding = float(pos.get("cumFunding", {}).get("sinceChange", 0)) if isinstance(pos.get("cumFunding"), dict) else 0
                liq_px = float(pos.get("liquidationPx", 0) or 0)

                # ROE = unrealizedPnl / marginUsed
                roe = unrealized / margin if margin > 0 else 0

                # Funding rate from returnOnEquity field isn't ideal;
                # we'll get it from pair scanner context if available
                funding_rate = 0.0  # will be enriched externally

                coin_name = pos.get("coin", "???")

                # Track first-seen time locally for age calculation
                now = time.time()
                if coin_name not in self._first_seen:
                    self._first_seen[coin_name] = now
                age_hours = (now - self._first_seen[coin_name]) / 3600.0

                positions.append(ManagedPosition(
                    coin=coin_name,
                    size=sz,
                    entry_price=entry_px,
                    mark_price=mark_px_derived,
                    unrealized_pnl=unrealized,
                    roe_pct=roe,
                    margin_used=margin,
                    notional_value=notional,
                    leverage=leverage_val,
                    funding_rate=funding_rate,
                    funding_pnl=funding,
                    liq_price=liq_px,
                    age_hours=age_hours,
                ))

            # Clean up first_seen for positions that no longer exist
            active_coins = {p.coin for p in positions}
            stale = [c for c in self._first_seen if c not in active_coins]
            for c in stale:
                del self._first_seen[c]

            return positions

        except Exception as e:
            logger.error("Failed to fetch HL positions: %s", e)
            return None

    async def _close_position(self, coin: str) -> bool:
        """Close a position via the HyperliquidClient."""
        try:
            result = await self._client.close_position(coin)
            if result and result.get("status") in ("closed", "no_position"):
                # Clean up tracking state
                self._trailing_stops.pop(coin, None)
                self._peak_roes.pop(coin, None)
                self._first_seen.pop(coin, None)
                return True
            logger.warning("Position close returned unexpected: %s %s", coin, result)
            return False
        except Exception as e:
            logger.error("Failed to close position %s: %s", coin, e)
            return False

    # ── Cross-platform intelligence ──────────────────────────────

    def update_turbo_intel(self, asset_wr: Dict[str, float]):
        """
        Update thresholds based on Polymarket turbo performance feedback.

        Args:
            asset_wr: Dict of asset → rolling win rate from turbo (e.g. {"btc": 0.30})
        """
        self._turbo_asset_wr = asset_wr
        self._turbo_hot_assets = {a for a, wr in asset_wr.items() if wr >= 0.40}
        self._turbo_cold_assets = {a for a, wr in asset_wr.items() if wr < 0.25}

        if self._turbo_cold_assets:
            logger.info(
                "Position manager: turbo-cold assets (tighter stops): %s",
                ", ".join(self._turbo_cold_assets),
            )
        if self._turbo_hot_assets:
            logger.info(
                "Position manager: turbo-hot assets (wider trailing): %s",
                ", ".join(self._turbo_hot_assets),
            )

    def enrich_funding_rates(self, pair_scanner):
        """Pull current funding rates from pair scanner into managed positions."""
        for coin, pos in self._positions.items():
            rate = pair_scanner.get_funding_rate(coin)
            pos.funding_rate = rate

    # ── Getters for TUI / monitoring ─────────────────────────────

    @property
    def positions(self) -> Dict[str, ManagedPosition]:
        return self._positions

    @property
    def account_equity(self) -> float:
        return self._account_equity

    @property
    def aggregate_leverage(self) -> float:
        return self._aggregate_leverage

    @property
    def recent_actions(self) -> List[ManagerAction]:
        """Last 20 actions for display."""
        return self._action_log[-20:]

    def get_status(self) -> dict:
        """Status snapshot for TUI / bus publishing."""
        positions_summary = {}
        for coin, p in self._positions.items():
            positions_summary[coin] = {
                "size": p.size,
                "entry": p.entry_price,
                "mark": p.mark_price,
                "roe": p.roe_pct,
                "pnl": p.unrealized_pnl,
                "notional": p.notional_value,
                "trailing_stop": self._trailing_stops.get(coin, 0),
                "peak_roe": self._peak_roes.get(coin, 0),
            }

        return {
            "equity": self._account_equity,
            "leverage": self._aggregate_leverage,
            "total_notional": self._total_notional,
            "total_margin": self._total_margin,
            "position_count": len(self._positions),
            "total_unrealized": sum(p.unrealized_pnl for p in self._positions.values()),
            "positions": positions_summary,
            "recent_actions": [
                {"coin": a.coin, "action": a.action, "reason": a.reason,
                 "roe": a.roe_at_action, "pnl": a.pnl_at_action}
                for a in self._action_log[-10:]
            ],
            "turbo_hot": list(self._turbo_hot_assets),
            "turbo_cold": list(self._turbo_cold_assets),
            "thresholds": {
                "cut_loss": self.cut_loss_roe,
                "profit_lock": self.profit_lock_roe,
                "max_positions": self.max_positions,
                "max_leverage": self.max_leverage,
            },
        }

    # ── Bus publishing ───────────────────────────────────────────

    async def _publish_actions(self, actions: List[ManagerAction]):
        """Publish position manager actions to message bus."""
        if not self._bus:
            return
        try:
            from agents.message_bus import AgentMessage, MessageType
            payload = {
                "source": "hl_position_manager",
                "actions": [
                    {
                        "coin": a.coin,
                        "action": a.action,
                        "reason": a.reason,
                        "roe": a.roe_at_action,
                        "pnl": a.pnl_at_action,
                        "timestamp": a.timestamp,
                    }
                    for a in actions
                ],
                "status": self.get_status(),
            }
            await self._bus.publish(AgentMessage(
                msg_type=MessageType.RISK_ALERT,
                sender="hl_position_manager",
                payload=payload,
                priority=5,
            ))
        except Exception as e:
            logger.debug("Failed to publish position manager actions: %s", e)
