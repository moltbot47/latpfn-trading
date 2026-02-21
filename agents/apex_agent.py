"""
Apex CME futures agent — wraps TradingSystem (pickmytrade/traderspost mode)
with soul-driven personality, inter-agent communication, and self-optimization.

Does NOT replace TradingSystem.  Instead:
1. Hooks into post-cycle events to publish market intel
2. Listens for intel from HL and Poly agents for crypto instrument correlation
3. Posts personality-driven self-assessments to Discord
4. Tracks consistency rule progress
"""

import logging
import time
from typing import Any, Dict, Optional

from agents.base import TradingAgent
from agents.message_bus import AgentMessage, MessageBus, MessageType

logger = logging.getLogger(__name__)


class ApexAgent(TradingAgent):
    """Autonomous agent wrapping the Apex/CME TradingSystem."""

    def __init__(self, trading_system, bus: MessageBus, bot, config: dict):
        super().__init__(
            name="apex_trader",
            bus=bus,
            bot=bot,
            config=config,
            subscribe_to=[
                MessageType.MARKET_INTEL,
                MessageType.RISK_ALERT,
                MessageType.TRADE_SIGNAL,
                MessageType.PERFORMANCE_REPORT,
            ],
        )
        self.system = trading_system

        # Cross-agent intel state
        self._hl_crypto_bias: Optional[str] = None
        self._poly_crypto_bias: Optional[str] = None
        self._last_regime_data: Dict[str, dict] = {}

        # Consistency tracking
        self._biggest_day_profit = 1660.25  # from eval history
        self._total_profit_target = 5534.17  # $1,660.25 / 0.30

        # Self-learning
        self._consecutive_losses = 0

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

    def _on_market_intel(self, payload: dict):
        """Handle market intel from other agents."""
        source = payload.get("source", "")
        self._intel_cache[f"{source}_intel"] = payload

        if source == "hyperliquid":
            # Note crypto regime for MBT/MET correlation
            regime = payload.get("regime_data", {})
            if regime:
                for inst in ("BTC", "ETH", "SOL"):
                    if inst in regime:
                        self._last_regime_data[f"hl_{inst}"] = regime[inst]

        elif source == "polymarket":
            llm = payload.get("llm_crypto_forecasts", {})
            if llm:
                self._poly_crypto_bias = llm.get("overall_bias")

    def _on_risk_alert(self, payload: dict):
        """Handle risk alerts (informational only — separate accounts)."""
        logger.info(
            "Apex agent: %s risk alert — %s",
            payload.get("sender", "?"), payload.get("alert_type", "unknown"),
        )

    def _on_trade_signal(self, payload: dict):
        """Handle trade signals from other agents — note directional bias."""
        inst = payload.get("instrument", "").upper()
        direction = payload.get("direction", "")

        # HL crypto trades inform MBT/MET bias
        crypto_map = {"BTC": "MBT", "ETH": "MET"}
        if inst in crypto_map and direction:
            bias = "bullish" if direction == "long" else "bearish"
            self._hl_crypto_bias = bias
            logger.info(
                "Apex agent: HL %s %s → %s bias for %s",
                direction, inst, bias, crypto_map[inst],
            )

    def _on_performance_report(self, payload: dict):
        """Handle performance reports from other agents."""
        pass

    # ── Intel Publishing ──────────────────────────────────────────

    def get_intel_snapshot(self) -> Dict[str, Any]:
        """Extract market intelligence to share with other agents."""
        snapshot = {
            "source": "apex",
            "cycle": getattr(self.system, 'cycle', 0),
            "equity": getattr(self.system, 'account_equity', 0),
            "open_positions": self.system.order_mgr.open_count,
            "daily_pnl": getattr(self.system.order_mgr, 'realized_pnl_today', 0),
        }

        # Regime data from last cycle
        if self._last_regime_data:
            snapshot["regime_data"] = self._last_regime_data

        # Drawdown status
        try:
            dd = self.system.apex.get_drawdown_status(self.system.account_equity)
            snapshot["drawdown"] = {
                "cushion": dd.get("cushion", 0),
                "cushion_pct": dd.get("cushion_pct", 100),
                "at_risk": dd.get("cushion_pct", 100) < 30,
            }
        except Exception:
            pass

        # Time window info
        try:
            from signals.time_boost import get_active_window
            window = get_active_window(self.config)
            if window:
                snapshot["time_window"] = window
        except Exception:
            pass

        return snapshot

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
            "consecutive_losses": self._consecutive_losses,
            "win_rate": self.get_win_rate(),
            "hl_crypto_bias": self._hl_crypto_bias,
            "poly_crypto_bias": self._poly_crypto_bias,
        }

    # ── Post-Cycle Hook (called from main_loop.py) ───────────────

    async def post_cycle_hook(self, cycle: int, regime_data: dict = None):
        """Called after each TradingSystem cycle completes."""
        if regime_data:
            self._last_regime_data = regime_data

        await self.publish_intel()

        # Risk alert if drawdown is concerning
        try:
            dd = self.system.apex.get_drawdown_status(self.system.account_equity)
            if dd.get("cushion_pct", 100) < 30:
                await self.publish_risk_alert({
                    "alert_type": "drawdown_warning",
                    "detail": f"Apex cushion: ${dd['cushion']:.2f} ({dd['cushion_pct']:.0f}%)",
                    "cushion": dd["cushion"],
                    "cushion_pct": dd["cushion_pct"],
                })
        except Exception:
            pass

        if cycle % 5 == 0:
            await self.publish_status()

        # Self-assessment to Discord
        channel = getattr(self.bot, '_signal_channel', None)
        await self.maybe_self_assess(channel)

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

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    # ── Cross-Agent Confidence Adjustment ─────────────────────────

    def get_cross_agent_confidence_boost(
        self, instrument: str, direction: str
    ) -> float:
        """Calculate confidence adjustment from cross-agent intel.

        Returns additive boost: -0.02 to +0.02.
        Conservative: prop firm account, minimal cross-pollination.
        """
        boost = 0.0

        # Only apply to crypto instruments
        is_crypto = instrument.upper() in ("MBT", "MET")
        if not is_crypto:
            return 0.0

        # HL crypto directional bias
        if self._hl_crypto_bias:
            if direction == "long" and self._hl_crypto_bias == "bullish":
                boost += 0.01
            elif direction == "short" and self._hl_crypto_bias == "bearish":
                boost += 0.01

        # Poly LLM crypto bias
        if self._poly_crypto_bias:
            if direction == "long" and self._poly_crypto_bias == "bullish":
                boost += 0.01
            elif direction == "short" and self._poly_crypto_bias == "bearish":
                boost += 0.01

        return max(-0.02, min(boost, 0.02))

    # ── Discord Personality ───────────────────────────────────────

    def _format_self_assessment(self, status: dict) -> str:
        """Format TRADING LOG in Apex's professional prop firm style."""
        equity = status.get("equity", 0)
        positions = status.get("positions", 0)
        daily_pnl = status.get("daily_pnl", 0)
        win_rate = status.get("win_rate")
        uptime = status.get("agent_uptime_min", 0)

        lines = [
            f"**Equity:** ${equity:,.2f}",
            f"**Positions:** {positions} active",
            f"**Daily P&L:** ${daily_pnl:+.2f}",
        ]

        if win_rate is not None:
            lines.append(f"**Win Rate:** {win_rate:.0%} (last 50)")

        # Drawdown status
        try:
            dd = self.system.apex.get_drawdown_status(equity)
            lines.append(
                f"**Drawdown Cushion:** ${dd['cushion']:.2f} ({dd['cushion_pct']:.0f}%)"
            )
        except Exception:
            pass

        # Time window
        try:
            from signals.time_boost import get_active_window
            window = get_active_window(self.config)
            if window:
                lines.append(f"**Time Window:** {window.replace('_', ' ').title()}")
        except Exception:
            pass

        # Cross-agent intel
        if self._hl_crypto_bias:
            lines.append(f"**HL Crypto Bias:** {self._hl_crypto_bias}")
        if self._poly_crypto_bias:
            lines.append(f"**Poly Crypto Bias:** {self._poly_crypto_bias}")

        # Bus stats
        msgs_in = status.get("messages_in", 0)
        msgs_out = status.get("messages_out", 0)
        lines.append(f"**Comms:** {msgs_in} in / {msgs_out} out")
        lines.append(f"**Uptime:** {uptime:.0f} min")

        return "\n".join(lines)

    def _get_assess_interval(self) -> int:
        return 10  # Every 10 cycles (~50 min at 5-min cycles)
