"""
Base trading agent — wraps an existing orchestrator with soul-file-driven
personality, inter-agent communication, and self-optimization loops.

Subclasses implement:
  - _handle_message(): react to incoming messages
  - get_intel_snapshot(): what to publish each cycle
  - get_status_snapshot(): current agent state
  - _format_self_assessment(): personality-driven SITREP
"""

import abc
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord

from agents.message_bus import AgentMessage, MessageBus, MessageType
from agents.soul import SoulFile

logger = logging.getLogger(__name__)


class TradingAgent(abc.ABC):
    """
    Abstract base class for an autonomous trading agent.

    Wraps an existing orchestrator.  Adds:
    - Soul file loading and personality
    - Inter-agent messaging via message bus
    - Personality-driven Discord posting
    - Periodic self-assessment and performance tracking
    - Self-optimization loop
    """

    def __init__(
        self,
        name: str,
        bus: MessageBus,
        bot,
        config: dict,
        subscribe_to: Optional[List[MessageType]] = None,
    ):
        self.name = name
        self.bus = bus
        self.bot = bot
        self.config = config

        # Load soul file
        self.soul = SoulFile(name)

        # Register on message bus
        subs = subscribe_to or [
            MessageType.MARKET_INTEL,
            MessageType.RISK_ALERT,
            MessageType.TRADE_SIGNAL,
            MessageType.STATUS_UPDATE,
            MessageType.PERFORMANCE_REPORT,
        ]
        self._inbox = bus.register(name, subs)

        # Agent state
        self._cycle = 0
        self._started_at = 0.0
        self._messages_received = 0
        self._messages_published = 0
        self._intel_cache: Dict[str, Any] = {}

        # Performance tracking (self-learning)
        self._trade_outcomes: List[Dict] = []  # rolling window of outcomes
        self._optimization_log: List[Dict] = []  # parameter changes made

    async def start(self):
        """Start the agent's listener loop (run as asyncio task)."""
        self._started_at = time.time()
        logger.info(
            "Agent '%s' online | soul: %s | drive: %s",
            self.name, self.soul.agent_name, self.soul.core_drive[:60],
        )
        await self._listen()

    async def _listen(self):
        """Main loop: drain inbox and process messages."""
        while True:
            try:
                msg: AgentMessage = await asyncio.wait_for(
                    self._inbox.get(), timeout=1.0
                )
                self._messages_received += 1
                logger.info(
                    "%s received %s from %s (msg #%d)",
                    self.name, msg.msg_type.value, msg.sender, self._messages_received,
                )
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                pass  # Normal — no messages, loop again
            except Exception as e:
                logger.error("Agent '%s' handler error: %s", self.name, e)

    # ── Abstract methods ──────────────────────────────────────────

    @abc.abstractmethod
    async def _handle_message(self, msg: AgentMessage):
        """Process an incoming message from another agent."""
        ...

    @abc.abstractmethod
    def get_intel_snapshot(self) -> Dict[str, Any]:
        """Extract current market intelligence to share."""
        ...

    @abc.abstractmethod
    def get_status_snapshot(self) -> Dict[str, Any]:
        """Get current agent status for STATUS_UPDATE."""
        ...

    @abc.abstractmethod
    def _format_self_assessment(self, status: dict) -> str:
        """Format a personality-driven self-assessment string."""
        ...

    # ── Publishing helpers ────────────────────────────────────────

    async def publish_intel(self):
        """Publish current market intelligence to the bus."""
        intel = self.get_intel_snapshot()
        if intel:
            self._messages_published += 1
            await self.bus.publish(AgentMessage(
                msg_type=MessageType.MARKET_INTEL,
                sender=self.name,
                payload=intel,
            ))
            logger.info(
                "%s published MARKET_INTEL (%d keys, msg #%d)",
                self.name, len(intel), self._messages_published,
            )

    async def publish_risk_alert(self, alert_data: dict):
        """Publish a risk alert (high priority)."""
        self._messages_published += 1
        await self.bus.publish(AgentMessage(
            msg_type=MessageType.RISK_ALERT,
            sender=self.name,
            payload=alert_data,
            priority=10,
        ))

    async def publish_trade_signal(self, trade_data: dict):
        """Publish an executed trade signal."""
        self._messages_published += 1
        await self.bus.publish(AgentMessage(
            msg_type=MessageType.TRADE_SIGNAL,
            sender=self.name,
            payload=trade_data,
        ))

    async def publish_status(self):
        """Publish a status update."""
        status = self.get_status_snapshot()
        if status:
            self._messages_published += 1
            await self.bus.publish(AgentMessage(
                msg_type=MessageType.STATUS_UPDATE,
                sender=self.name,
                payload=status,
            ))

    async def publish_performance(self, perf_data: dict):
        """Publish a performance report."""
        self._messages_published += 1
        await self.bus.publish(AgentMessage(
            msg_type=MessageType.PERFORMANCE_REPORT,
            sender=self.name,
            payload=perf_data,
        ))

    # ── Personality-driven Discord posting ────────────────────────

    def make_embed(
        self,
        title: str,
        description: str = "",
        fields: Optional[List[dict]] = None,
        color: Optional[int] = None,
    ) -> discord.Embed:
        """Create a Discord embed styled by the soul file."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.soul.embed_color,
            timestamp=datetime.now(timezone.utc),
        )
        if fields:
            for f in fields:
                embed.add_field(
                    name=f["name"],
                    value=f["value"],
                    inline=f.get("inline", True),
                )
        embed.set_footer(text=self.soul.footer_text)
        return embed

    async def post_to_channel(
        self,
        channel,
        embed: discord.Embed,
        content: Optional[str] = None,
    ):
        """Post a message to the agent's Discord channel."""
        if channel is None:
            return
        try:
            await channel.send(content=content, embed=embed)
        except Exception as e:
            logger.error("Agent '%s' Discord post failed: %s", self.name, e)

    # ── Self-assessment ───────────────────────────────────────────

    async def maybe_self_assess(self, channel):
        """Post periodic self-assessment to Discord channel."""
        self._cycle += 1
        interval = self._get_assess_interval()
        if self._cycle % interval != 0:
            return

        status = self.get_status_snapshot()
        status["agent_uptime_min"] = (time.time() - self._started_at) / 60
        status["messages_in"] = self._messages_received
        status["messages_out"] = self._messages_published
        status["bus_stats"] = self.bus.stats

        description = self._format_self_assessment(status)
        embed = self.make_embed(
            title=f"{self.name.upper()} SITREP #{self._cycle}",
            description=description,
        )
        await self.post_to_channel(channel, embed)
        logger.info("Agent '%s' posted SITREP #%d", self.name, self._cycle)

    def _get_assess_interval(self) -> int:
        """Self-assessment frequency (subclasses override)."""
        return 10

    # ── Performance tracking ──────────────────────────────────────

    def record_trade_outcome(self, outcome: dict):
        """Record a trade outcome for self-learning analysis."""
        outcome["recorded_at"] = time.time()
        self._trade_outcomes.append(outcome)
        # Keep rolling window of 200 outcomes
        if len(self._trade_outcomes) > 200:
            self._trade_outcomes = self._trade_outcomes[-200:]

    def get_win_rate(self, window: int = 50) -> Optional[float]:
        """Compute win rate over last N trades."""
        recent = self._trade_outcomes[-window:]
        if len(recent) < 5:
            return None
        wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
        return wins / len(recent)

    def log_optimization(self, param: str, old_val: Any, new_val: Any, reason: str):
        """Log a self-optimization parameter change."""
        entry = {
            "timestamp": time.time(),
            "param": param,
            "old": old_val,
            "new": new_val,
            "reason": reason,
        }
        self._optimization_log.append(entry)
        logger.info(
            "Agent '%s' self-optimized: %s %s → %s (%s)",
            self.name, param, old_val, new_val, reason,
        )
