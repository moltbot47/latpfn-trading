"""
Polymarket autonomous agent — wraps PolymarketOrchestrator with
soul-driven personality, inter-agent communication, and self-optimization.

Does NOT replace PolymarketOrchestrator.  Instead:
1. Hooks into post-cycle events to publish LLM forecasts and trade signals
2. Listens for HL regime data to adjust scalper aggressiveness
3. Posts personality-driven self-assessments to Discord
4. Tracks Brier score and per-strategy P&L for self-learning
"""

import logging
import time
from typing import Any, Dict, List, Optional

from agents.base import TradingAgent
from agents.message_bus import AgentMessage, MessageBus, MessageType

logger = logging.getLogger(__name__)


class PolymarketAgent(TradingAgent):
    """Autonomous agent wrapping the Polymarket Orchestrator."""

    def __init__(self, orchestrator, bus: MessageBus, bot, config: dict):
        super().__init__(
            name="polymarket",
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
        self.orch = orchestrator

        # Cross-agent intel from HL
        self._hl_regime_data: Dict[str, dict] = {}
        self._hl_fear_greed: Optional[dict] = None
        self._hl_drawdown: Optional[dict] = None
        self._hl_trade_bias: Dict[str, str] = {}  # "btc" -> "long"/"short"

        # Self-learning state
        self._strategy_pnl: Dict[str, float] = {
            "resolution_snipe": 0.0,
            "superforecaster": 0.0,
            "max_concurrent": 0.0,
            "crypto_scalp": 0.0,
            "turbo": 0.0,
        }
        self._scalper_asset_wins: Dict[str, List[bool]] = {}  # asset -> [win, loss, ...]

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
        """Handle market intel from HL agent — regime data, sentiment."""
        self._intel_cache["hl_intel"] = payload

        regime = payload.get("regime_data", {})
        if regime:
            self._hl_regime_data = regime

        fng = payload.get("fear_greed")
        if fng:
            self._hl_fear_greed = fng

        dd = payload.get("drawdown")
        if dd:
            self._hl_drawdown = dd

        logger.info(
            "Poly agent: HL intel — %d regimes, equity=$%.2f",
            len(regime), payload.get("equity", 0),
        )
        self._push_turbo_intel()

    def _on_risk_alert(self, payload: dict):
        """Handle HL risk alerts (informational only)."""
        alert = payload.get("alert_type", "unknown")
        logger.info(
            "Poly agent: HL risk alert — %s: %s",
            alert, payload.get("detail", ""),
        )
        if alert == "drawdown_warning":
            self._hl_drawdown = payload
        self._push_turbo_intel()

    def _on_trade_signal(self, payload: dict):
        """Handle HL trade execution — note directional bias for scalper."""
        inst = payload.get("instrument", "").upper()
        direction = payload.get("direction", "")

        # Map futures instruments to crypto assets
        inst_map = {"MBT": "btc", "BTC": "btc", "MET": "eth", "ETH": "eth"}
        asset = inst_map.get(inst)
        if asset and direction:
            self._hl_trade_bias[asset] = direction
            logger.info(
                "Poly agent: HL %s %s → noted for scalper", direction, inst,
            )
        self._push_turbo_intel()

    def _on_perf_feedback(self, payload: dict):
        """Handle HL performance feedback — forward asset WRs to turbo."""
        if payload.get("source") != "hyperliquid":
            return

        asset_wr = payload.get("asset_wr", {})
        if not asset_wr:
            return

        logger.info(
            "Poly agent: HL perf feedback — WRs: %s",
            {a: f"{w:.0%}" for a, w in asset_wr.items()},
        )

        # Forward to turbo strategy as intel
        if hasattr(self.orch, 'turbo') and self.orch.turbo:
            try:
                self.orch.turbo.update_intel({
                    "hl_asset_wr": asset_wr,
                    "hl_consecutive_losses": payload.get("consecutive_losses", 0),
                })
            except Exception as e:
                logger.debug("Turbo HL feedback push error: %s", e)

    def _on_performance_report(self, payload: dict):
        """Handle HL performance report."""
        logger.info(
            "Poly agent: HL performance — equity=$%.2f, win_rate=%s",
            payload.get("equity", 0), payload.get("win_rate", "?"),
        )

    # ── Intel Publishing ──────────────────────────────────────────

    def get_intel_snapshot(self) -> Dict[str, Any]:
        """Extract Polymarket intelligence to share with HL agent."""
        snapshot = {
            "source": "polymarket",
            "cycle": self.orch.cycle,
            "budget": self.orch.risk.budget,
            "deployed": self.orch.positions.total_deployed(),
            "open_positions": self.orch.positions.position_count(),
            "daily_pnl": self.orch.risk.daily_realized_pnl,
        }

        # LLM crypto forecasts from last scan
        last_scan = self.orch.last_scan or {}
        div_candidates = last_scan.get("divergence_candidates", [])
        crypto_forecasts = {}

        for c in div_candidates:
            q = c.get("question", "").lower()
            for asset, keywords in [
                ("btc", ["btc", "bitcoin"]),
                ("eth", ["eth", "ethereum"]),
                ("sol", ["sol", "solana"]),
            ]:
                if any(kw in q for kw in keywords):
                    crypto_forecasts[asset] = {
                        "llm_prob": c.get("llm_probability", 0.5),
                        "market_prob": c.get("market_yes_price", 0.5),
                        "divergence": c.get("divergence", 0),
                        "direction": c.get("direction", ""),
                    }

        if crypto_forecasts:
            bullish = sum(1 for f in crypto_forecasts.values()
                          if f["direction"] == "YES")
            bearish = sum(1 for f in crypto_forecasts.values()
                          if f["direction"] == "NO")
            bias = "bullish" if bullish > bearish else (
                "bearish" if bearish > bullish else "neutral"
            )
            snapshot["llm_crypto_forecasts"] = {
                "overall_bias": bias,
                "forecasts": crypto_forecasts,
            }

        # Scalper status
        if hasattr(self.orch, 'scalper'):
            try:
                scalper_status = self.orch.scalper.get_status()
                snapshot["scalper_stats"] = {
                    "trades_today": scalper_status.get("trades_today", 0),
                    "pnl_today": scalper_status.get("pnl_today", 0),
                }
            except Exception:
                pass

        return snapshot

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Full status for STATUS_UPDATE messages."""
        brier = None
        try:
            brier = self.orch.forecaster.compute_brier_score()
        except Exception:
            pass

        return {
            "agent": self.name,
            "budget": self.orch.risk.budget,
            "deployed": self.orch.positions.total_deployed(),
            "positions": self.orch.positions.position_count(),
            "daily_pnl": self.orch.risk.daily_realized_pnl,
            "cycle": self.orch.cycle,
            "is_running": self.orch.is_running,
            "brier_score": brier,
            "strategy_pnl": dict(self._strategy_pnl),
            "hl_bias": dict(self._hl_trade_bias),
            "win_rate": self.get_win_rate(),
        }

    # ── Post-Cycle Hook (called from orchestrator.py) ─────────────

    async def post_cycle_hook(self, result: dict):
        """
        Called after each PolymarketOrchestrator scan cycle.

        Args:
            result: The cycle result dict from _scan_cycle().
        """
        # Publish intel to bus
        await self.publish_intel()

        # Publish trade signals for executed trades
        for trade in result.get("executed", []):
            await self.publish_trade_signal({
                "strategy": trade.get("strategy", "unknown"),
                "direction": trade.get("direction", ""),
                "question": trade.get("question", ""),
                "entry_price": trade.get("entry_price", 0),
                "size_usdc": trade.get("size_usdc", 0),
                "edge_pct": trade.get("edge_pct", 0),
            })

        # Record exits for self-learning
        for exit_info in result.get("exits", []):
            strategy = exit_info.get("strategy", "unknown")
            pnl = exit_info.get("pnl", 0)
            if strategy in self._strategy_pnl:
                self._strategy_pnl[strategy] += pnl
            self.record_trade_outcome({
                "strategy": strategy,
                "pnl": pnl,
                "question": exit_info.get("question", ""),
            })

        # Risk alert if trading is blocked
        can_trade, reason = self.orch.risk.can_trade()
        if not can_trade:
            await self.publish_risk_alert({
                "alert_type": "trading_blocked",
                "detail": reason,
                "budget": self.orch.risk.budget,
                "daily_pnl": self.orch.risk.daily_realized_pnl,
            })

        # Status update every 3 cycles
        if self.orch.cycle % 3 == 0:
            await self.publish_status()

        # Performance report every 30 cycles
        if self.orch.cycle % 30 == 0:
            brier = None
            try:
                brier = self.orch.forecaster.compute_brier_score()
            except Exception:
                pass
            await self.publish_performance({
                "brier_score": brier,
                "strategy_pnl": dict(self._strategy_pnl),
                "win_rate": self.get_win_rate(),
                "total_trades": len(self._trade_outcomes),
            })

        # Self-assessment to Discord
        channel = getattr(self.bot, '_poly_channel', None)
        await self.maybe_self_assess(channel)

    # ── Turbo Intel Push ────────────────────────────────────────

    def _push_turbo_intel(self):
        """Push digested HL intel to turbo strategy (smart filtered)."""
        if not hasattr(self.orch, 'turbo') or not self.orch.turbo:
            return
        try:
            intel = {}
            if self._hl_fear_greed:
                intel["fear_greed"] = self._hl_fear_greed
            if self._hl_regime_data:
                asset_map = {"MBT": "btc", "BTC": "btc", "MET": "eth", "ETH": "eth"}
                regime = {}
                for inst, data in self._hl_regime_data.items():
                    asset = asset_map.get(inst, inst.lower())
                    regime[asset] = data
                intel["regime"] = regime
            if self._hl_trade_bias:
                intel["hl_bias"] = dict(self._hl_trade_bias)
            if self._hl_drawdown and self._hl_drawdown.get("at_risk"):
                intel["risk_alert"] = True
            if intel:
                self.orch.turbo.update_intel(intel)
        except Exception as e:
            logger.debug("Turbo intel push error: %s", e)

    # ── Scalper Adjustment from HL Intel ──────────────────────────

    def get_scalper_threshold_adjustment(self, asset: str) -> float:
        """
        Adjust scalper entry threshold based on HL regime data.

        Returns additive adjustment to entry_threshold.
        Negative = more aggressive, positive = more cautious.
        Soul file rules:
        - trending + ADX>30: -0.03
        - volatile/funding_squeeze: +0.05
        """
        adjustment = 0.0

        # HL regime for this asset's corresponding futures
        asset_to_futures = {"btc": "MBT", "eth": "MET", "sol": "SOL"}
        futures_key = asset_to_futures.get(asset, asset.upper())

        regime_info = self._hl_regime_data.get(futures_key, {})
        if regime_info:
            regime = regime_info.get("regime", "")
            adx = regime_info.get("adx", 20)

            if regime == "trending" and adx > 30:
                adjustment -= 0.03  # More aggressive in trending
            elif regime in ("volatile", "funding_squeeze"):
                adjustment += 0.05  # More cautious in volatile

        # HL trade direction alignment — small boost
        hl_dir = self._hl_trade_bias.get(asset)
        if hl_dir:
            adjustment -= 0.01  # Slight aggression when HL has a position

        return max(-0.05, min(adjustment, 0.05))

    def get_scalper_bias(self, asset: str) -> Optional[str]:
        """
        Get directional bias for scalper from HL intel.

        Returns "up", "down", or None.
        """
        hl_dir = self._hl_trade_bias.get(asset)
        if hl_dir == "long":
            return "up"
        elif hl_dir == "short":
            return "down"
        return None

    # ── Discord Personality ───────────────────────────────────────

    def _format_self_assessment(self, status: dict) -> str:
        """Format Market Pulse in Poly's analytical pundit style."""
        budget = status.get("budget", 0)
        deployed = status.get("deployed", 0)
        positions = status.get("positions", 0)
        daily_pnl = status.get("daily_pnl", 0)
        brier = status.get("brier_score")
        win_rate = status.get("win_rate")
        uptime = status.get("agent_uptime_min", 0)

        lines = [
            f"**Budget:** ${budget:.2f} | **Deployed:** ${deployed:.2f}",
            f"**Positions:** {positions} open | **Daily P&L:** ${daily_pnl:+.2f}",
        ]

        # Strategy breakdown
        spnl = status.get("strategy_pnl", {})
        if any(v != 0 for v in spnl.values()):
            strat_parts = []
            for s, v in spnl.items():
                short_name = s.replace("resolution_", "").replace("crypto_", "")
                strat_parts.append(f"{short_name}: ${v:+.2f}")
            lines.append(f"**By Strategy:** {' | '.join(strat_parts)}")

        if brier is not None:
            quality = "excellent" if brier < 0.15 else "good" if brier < 0.20 else "fair" if brier < 0.25 else "needs work"
            lines.append(f"**Brier Score:** {brier:.3f} ({quality})")

        if win_rate is not None:
            lines.append(f"**Win Rate:** {win_rate:.0%} (last 50)")

        # Cross-agent intel
        if self._hl_regime_data:
            regimes = set(r.get("regime", "?") for r in self._hl_regime_data.values())
            lines.append(f"**HL Regimes:** {', '.join(regimes)}")

        if self._hl_trade_bias:
            bias_parts = [f"{a.upper()}: {d}" for a, d in self._hl_trade_bias.items()]
            lines.append(f"**HL Bias:** {', '.join(bias_parts)}")

        # Bus comms
        msgs_in = status.get("messages_in", 0)
        msgs_out = status.get("messages_out", 0)
        lines.append(f"**Comms:** {msgs_in} in / {msgs_out} out | **Uptime:** {uptime:.0f} min")

        return "\n".join(lines)

    def _get_assess_interval(self) -> int:
        return 5  # Every 5 cycles (~50 min at 10-min cycles)
