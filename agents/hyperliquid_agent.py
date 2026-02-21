"""
Hyperliquid autonomous agent — wraps TradingSystem with soul-driven
personality, inter-agent communication, and self-optimization.

Does NOT replace TradingSystem.  Instead:
1. Hooks into post-cycle events to publish market intel
2. Listens for intel from other agents and adjusts behavior
3. Posts personality-driven self-assessments to Discord
4. Tracks performance for self-learning parameter adjustments
"""

import logging
import time
from typing import Any, Dict, Optional

from agents.base import TradingAgent
from agents.message_bus import AgentMessage, MessageBus, MessageType

logger = logging.getLogger(__name__)


class HyperliquidAgent(TradingAgent):
    """Autonomous agent wrapping the Hyperliquid TradingSystem."""

    def __init__(self, trading_system, bus: MessageBus, bot, config: dict):
        super().__init__(
            name="hyperliquid",
            bus=bus,
            bot=bot,
            config=config,
            subscribe_to=[
                MessageType.MARKET_INTEL,
                MessageType.RISK_ALERT,
                MessageType.TRADE_SIGNAL,
                MessageType.PERFORMANCE_REPORT,
                MessageType.PERF_FEEDBACK,
            ],
        )
        self.system = trading_system

        # Cross-agent intel state
        self._poly_crypto_bias: Optional[str] = None  # "bullish" / "bearish" / None
        self._poly_scalper_direction: Dict[str, str] = {}  # asset -> "up"/"down"
        self._poly_risk_status: str = "ok"
        self._poly_forecasts: Dict[str, dict] = {}  # asset -> forecast data

        # Self-learning state
        self._regime_accuracy: Dict[str, list] = {}  # regime -> [was_profitable]
        self._last_regime_data: Dict[str, dict] = {}
        self._consecutive_losses = 0

        # Turbo performance feedback (Layer 2 — bidirectional)
        self._turbo_asset_wr: Dict[str, float] = {}   # asset → rolling WR
        self._turbo_signal_quality: float = 0.5        # overall turbo signal reliability
        self._turbo_feedback_ts: float = 0             # last feedback timestamp
        self._confidence_penalties: Dict[str, float] = {}  # asset → penalty from bad turbo WR

        # Position manager reference (set externally)
        self._position_manager = None

    # ── Message Handling ──────────────────────────────────────────

    async def _handle_message(self, msg: AgentMessage):
        """Process incoming message from another agent."""
        if msg.msg_type == MessageType.MARKET_INTEL:
            self._on_market_intel(msg.payload)
        elif msg.msg_type == MessageType.RISK_ALERT:
            self._on_risk_alert(msg.payload)
        elif msg.msg_type == MessageType.TRADE_SIGNAL:
            self._on_trade_signal(msg.payload)
        elif msg.msg_type == MessageType.PERFORMANCE_REPORT:
            self._on_performance_report(msg.payload)
        elif msg.msg_type == MessageType.PERF_FEEDBACK:
            self._on_perf_feedback(msg.payload)

    def _on_market_intel(self, payload: dict):
        """Handle market intel from Polymarket agent."""
        self._intel_cache["poly_intel"] = payload

        # Extract crypto bias from LLM forecasts
        llm = payload.get("llm_crypto_forecasts", {})
        if llm:
            self._poly_crypto_bias = llm.get("overall_bias")
            self._poly_forecasts = llm.get("forecasts", {})
            logger.info(
                "HL agent: Poly crypto bias = %s (forecasts: %d)",
                self._poly_crypto_bias, len(self._poly_forecasts),
            )

        # Scalper directional data
        scalper = payload.get("scalper_signals", {})
        if scalper:
            self._poly_scalper_direction = scalper

    def _on_risk_alert(self, payload: dict):
        """Handle risk alert from Polymarket (informational)."""
        self._poly_risk_status = payload.get("alert_type", "unknown")
        logger.info(
            "HL agent: Poly risk alert — %s: %s",
            payload.get("alert_type"), payload.get("detail", ""),
        )

    def _on_trade_signal(self, payload: dict):
        """Handle trade signal from Polymarket — note directional bias."""
        direction = payload.get("direction", "")
        question = payload.get("question", "").lower()

        crypto_map = {
            "btc": ["btc", "bitcoin"],
            "eth": ["eth", "ethereum"],
            "sol": ["sol", "solana"],
        }
        for asset, keywords in crypto_map.items():
            if any(kw in question for kw in keywords):
                bias = "bullish" if direction.upper() in ("YES", "UP") else "bearish"
                self._poly_crypto_bias = bias
                logger.info(
                    "HL agent: Poly %s trade → %s bias", asset.upper(), bias,
                )
                break

    def _on_performance_report(self, payload: dict):
        """Handle performance report from Polymarket — note calibration."""
        brier = payload.get("brier_score")
        if brier is not None:
            logger.info("HL agent: Poly Brier score = %.3f", brier)

    def _on_perf_feedback(self, payload: dict):
        """
        Handle real-time performance feedback from Polymarket turbo.

        Payload:
            asset_wr: {asset: rolling_wr}       — per-asset win rate
            overall_wr: float                    — overall turbo WR
            signal_type_wr: {type: wr}           — contrarian vs market_lean
            streak_state: str                    — "hot:2W" / "cool:60s" / "neutral"
            last_result: {asset, direction, won}  — most recent trade
        """
        if payload.get("source") != "turbo":
            return

        # Update per-asset win rates
        asset_wr = payload.get("asset_wr", {})
        if asset_wr:
            self._turbo_asset_wr = asset_wr
            self._turbo_feedback_ts = time.time()

            # Compute confidence penalties: assets where turbo is losing
            self._confidence_penalties = {}
            for asset, wr in asset_wr.items():
                if wr < 0.25:
                    # Bad WR → penalty: -0.03 (strong negative signal)
                    self._confidence_penalties[asset] = -0.03
                elif wr < 0.35:
                    # Marginal → small penalty: -0.01
                    self._confidence_penalties[asset] = -0.01
                elif wr > 0.50:
                    # Good WR → boost: +0.02
                    self._confidence_penalties[asset] = 0.02

            logger.info(
                "HL agent: turbo feedback — WRs: %s, penalties: %s",
                {a: f"{w:.0%}" for a, w in asset_wr.items()},
                {a: f"{p:+.2f}" for a, p in self._confidence_penalties.items()},
            )

        # Forward to position manager for threshold adjustment
        if self._position_manager and asset_wr:
            self._position_manager.update_turbo_intel(asset_wr)

        # Forward to gatekeeper (HyperliquidRisk) for entry blocking
        gatekeeper = getattr(self.system, 'apex', None)
        if gatekeeper and hasattr(gatekeeper, 'update_turbo_feedback') and asset_wr:
            gatekeeper.update_turbo_feedback(asset_wr)

        # Overall turbo reliability
        overall_wr = payload.get("overall_wr")
        if overall_wr is not None:
            self._turbo_signal_quality = overall_wr

    # ── Intel Publishing ──────────────────────────────────────────

    def get_intel_snapshot(self) -> Dict[str, Any]:
        """Extract market intelligence to share with Polymarket agent."""
        snapshot = {
            "source": "hyperliquid",
            "cycle": getattr(self.system, 'cycle', 0),
            "equity": getattr(self.system, 'account_equity', 0),
            "open_positions": self.system.order_mgr.open_count,
            "daily_pnl": getattr(self.system.order_mgr, 'realized_pnl_today', 0),
        }

        # Sentiment data
        sf = getattr(self.system, '_sentiment_filter', None)
        if sf:
            try:
                fng = sf.get_fear_greed()
                if fng:
                    snapshot["fear_greed"] = fng
            except Exception:
                pass

        # Regime data from last cycle
        if self._last_regime_data:
            snapshot["regime_data"] = self._last_regime_data

        # Drawdown status
        try:
            dd = self.system.apex.get_drawdown_status(self.system.account_equity)
            cushion = dd.get("cushion", 0)
            cushion_pct = dd.get("cushion_pct", 100)
            snapshot["drawdown"] = {
                "cushion": cushion,
                "cushion_pct": cushion_pct,
                "at_risk": cushion_pct < 30,
            }
        except Exception:
            pass

        # Funding rates for core pairs (Layer 2 — enriched intel)
        pair_scanner = getattr(self.system, '_pair_scanner', None)
        if pair_scanner:
            funding_rates = {}
            for coin in ("BTC", "ETH", "SOL", "XRP"):
                rate = pair_scanner.get_funding_rate(coin)
                if rate != 0:
                    funding_rates[coin.lower()] = {
                        "rate_8h": rate,
                        "annual": rate * 3 * 365,
                        "direction": "longs_pay" if rate > 0 else "shorts_pay",
                    }
            if funding_rates:
                snapshot["funding_rates"] = funding_rates

        # Position manager status (Layer 2)
        if self._position_manager:
            pm_status = self._position_manager.get_status()
            snapshot["position_manager"] = {
                "leverage": pm_status.get("leverage", 0),
                "position_count": pm_status.get("position_count", 0),
                "total_unrealized": pm_status.get("total_unrealized", 0),
                "recent_actions": pm_status.get("recent_actions", [])[-3:],
            }

        # HL's own per-asset WR (reverse feedback for turbo)
        if self._trade_outcomes:
            hl_asset_wr = {}
            for outcome in self._trade_outcomes[-50:]:
                inst = outcome.get("instrument", "").lower()
                if inst:
                    if inst not in hl_asset_wr:
                        hl_asset_wr[inst] = {"w": 0, "l": 0}
                    if outcome.get("pnl", 0) > 0:
                        hl_asset_wr[inst]["w"] += 1
                    else:
                        hl_asset_wr[inst]["l"] += 1
            snapshot["hl_asset_wr"] = {
                a: d["w"] / (d["w"] + d["l"]) if (d["w"] + d["l"]) > 0 else 0
                for a, d in hl_asset_wr.items()
            }

        return snapshot

    async def publish_perf_feedback(self):
        """Publish HL performance feedback to turbo (reverse direction)."""
        if not self._trade_outcomes:
            return

        recent = self._trade_outcomes[-20:]
        wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
        overall_wr = wins / len(recent) if recent else 0

        # Per-asset WR
        asset_wr = {}
        for outcome in self._trade_outcomes[-50:]:
            inst = outcome.get("instrument", "").lower()
            if inst:
                if inst not in asset_wr:
                    asset_wr[inst] = {"w": 0, "l": 0}
                if outcome.get("pnl", 0) > 0:
                    asset_wr[inst]["w"] += 1
                else:
                    asset_wr[inst]["l"] += 1

        asset_wr_pct = {
            a: d["w"] / (d["w"] + d["l"]) if (d["w"] + d["l"]) > 0 else 0
            for a, d in asset_wr.items()
        }

        payload = {
            "source": "hyperliquid",
            "overall_wr": overall_wr,
            "asset_wr": asset_wr_pct,
            "consecutive_losses": self._consecutive_losses,
            "regime_accuracy": {
                r: sum(v) / len(v) if v else 0
                for r, v in self._regime_accuracy.items()
            },
        }

        self._messages_published += 1
        await self.bus.publish(AgentMessage(
            msg_type=MessageType.PERF_FEEDBACK,
            sender=self.name,
            payload=payload,
        ))

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Full status for STATUS_UPDATE messages."""
        return {
            "agent": self.name,
            "equity": getattr(self.system, 'account_equity', 0),
            "positions": self.system.order_mgr.open_count,
            "daily_pnl": getattr(self.system.order_mgr, 'realized_pnl_today', 0),
            "cycle": getattr(self.system, 'cycle', 0),
            "is_running": getattr(self.system, 'is_running', False),
            "instruments": len(getattr(self.system, 'instruments', [])),
            "poly_bias": self._poly_crypto_bias,
            "consecutive_losses": self._consecutive_losses,
            "win_rate": self.get_win_rate(),
        }

    # ── Post-Cycle Hook (called from main_loop.py) ───────────────

    async def post_cycle_hook(self, cycle: int, regime_data: dict = None):
        """
        Called after each TradingSystem cycle completes.

        Args:
            cycle: Current cycle number.
            regime_data: Dict of instrument -> regime info from this cycle.
        """
        # Cache regime data for sharing
        if regime_data:
            self._last_regime_data = regime_data

        # Publish intel to bus
        await self.publish_intel()

        # Publish risk alert if drawdown is concerning
        try:
            dd = self.system.apex.get_drawdown_status(self.system.account_equity)
            if dd.get("cushion_pct", 100) < 30:
                await self.publish_risk_alert({
                    "alert_type": "drawdown_warning",
                    "detail": f"Cushion: ${dd['cushion']:.2f} ({dd['cushion_pct']:.0f}%)",
                    "cushion": dd["cushion"],
                    "cushion_pct": dd["cushion_pct"],
                })
        except Exception:
            pass

        # Status update every 5 cycles
        if cycle % 5 == 0:
            await self.publish_status()

        # Publish performance feedback to turbo every 3 cycles (~6 min)
        if cycle % 3 == 0 and self._trade_outcomes:
            await self.publish_perf_feedback()

        # Self-assessment to Discord
        hl_channel = getattr(self.bot, '_hl_channel', None)
        if not hl_channel:
            # Fall back to signal channel
            hl_channel = getattr(self.bot, '_signal_channel', None)
        await self.maybe_self_assess(hl_channel)

    async def on_trade_executed(self, instrument: str, direction: str,
                                confidence: float, entry_price: float,
                                stop_loss: float, take_profit: float,
                                size: float, shot_type: str = ""):
        """Called when TradingSystem executes a trade."""
        await self.publish_trade_signal({
            "instrument": instrument,
            "direction": direction,
            "confidence": confidence,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "size": size,
            "shot_type": shot_type,
        })

    async def on_trade_closed(self, instrument: str, direction: str,
                              pnl: float, hold_minutes: float = 0):
        """Called when a position is closed — feeds self-learning."""
        self.record_trade_outcome({
            "instrument": instrument,
            "direction": direction,
            "pnl": pnl,
            "hold_minutes": hold_minutes,
        })

        # Track consecutive losses for circuit breaker awareness
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Track regime accuracy
        if instrument in self._last_regime_data:
            regime = self._last_regime_data[instrument].get("regime", "unknown")
            if regime not in self._regime_accuracy:
                self._regime_accuracy[regime] = []
            self._regime_accuracy[regime].append(pnl > 0)
            # Keep last 50 per regime
            if len(self._regime_accuracy[regime]) > 50:
                self._regime_accuracy[regime] = self._regime_accuracy[regime][-50:]

    # ── Cross-Agent Confidence Adjustment ─────────────────────────

    def get_cross_agent_confidence_boost(
        self, instrument: str, direction: str
    ) -> float:
        """
        Calculate confidence adjustment from cross-agent intel.

        Returns additive boost: -0.05 to +0.05 (widened from ±0.03).
        Uses turbo performance feedback for data-driven adjustments.
        """
        boost = 0.0

        # 1. Polymarket LLM crypto bias alignment (±0.02)
        if self._poly_crypto_bias:
            is_crypto = instrument.upper() in ("BTC", "ETH", "SOL", "MBT", "MET")
            if is_crypto:
                if direction == "long" and self._poly_crypto_bias == "bullish":
                    boost += 0.02
                elif direction == "short" and self._poly_crypto_bias == "bearish":
                    boost += 0.02
                elif direction == "long" and self._poly_crypto_bias == "bearish":
                    boost -= 0.01
                elif direction == "short" and self._poly_crypto_bias == "bullish":
                    boost -= 0.01

        # 2. Scalper direction alignment (±0.01)
        asset_lower = instrument.lower()
        scalper_dir = self._poly_scalper_direction.get(asset_lower)
        if scalper_dir:
            if (direction == "long" and scalper_dir == "up") or \
               (direction == "short" and scalper_dir == "down"):
                boost += 0.01

        # 3. Turbo performance-based penalty/boost (±0.03) — Layer 2 feedback
        #    Only apply if feedback is fresh (< 5 min old)
        if self._turbo_feedback_ts and (time.time() - self._turbo_feedback_ts) < 300:
            turbo_penalty = self._confidence_penalties.get(asset_lower, 0)
            boost += turbo_penalty

        return max(-0.05, min(boost, 0.05))

    # ── Discord Personality ───────────────────────────────────────

    def _format_self_assessment(self, status: dict) -> str:
        """Format SITREP in HL's terse, data-first military style."""
        equity = status.get("equity", 0)
        positions = status.get("positions", 0)
        daily_pnl = status.get("daily_pnl", 0)
        win_rate = status.get("win_rate")
        uptime = status.get("agent_uptime_min", 0)

        lines = [
            f"**Equity:** ${equity:.2f}",
            f"**Positions:** {positions} active",
            f"**Daily P&L:** ${daily_pnl:+.2f}",
        ]

        if win_rate is not None:
            lines.append(f"**Win Rate:** {win_rate:.0%} (last 50)")

        if self._poly_crypto_bias:
            lines.append(f"**Poly Intel:** {self._poly_crypto_bias} crypto bias")

        if self._last_regime_data:
            regimes = set(r.get("regime", "?") for r in self._last_regime_data.values())
            lines.append(f"**Regimes:** {', '.join(regimes)}")

        # Bus stats
        bus = status.get("bus_stats", {})
        msgs_in = status.get("messages_in", 0)
        msgs_out = status.get("messages_out", 0)
        lines.append(f"**Comms:** {msgs_in} in / {msgs_out} out")
        lines.append(f"**Uptime:** {uptime:.0f} min")

        return "\n".join(lines)

    def _get_assess_interval(self) -> int:
        return 10  # Every 10 cycles (~20 min at 2-min cycles)
