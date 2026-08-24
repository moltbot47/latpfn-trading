"""
Pika Agent — Pokemon TCG investment scout and price monitor.

Monitors card prices, alerts on deals, and provides market intel
to the Discord channel. Shares pokemon_cards.db with the dashboard.
"""

import logging
from typing import Any, Dict, List, Optional

import discord

from agents.base import TradingAgent
from agents.message_bus import AgentMessage, MessageBus, MessageType

logger = logging.getLogger(__name__)

PIKA_EMBED_COLOR = 0xFFD700  # Gold


class PikaAgent(TradingAgent):
    """Pokemon card investment agent."""

    def __init__(self, bus: MessageBus, bot, config: dict):
        super().__init__(
            name="pika",
            bus=bus,
            bot=bot,
            config=config,
            subscribe_to=[MessageType.STATUS_UPDATE],
        )
        self._channel_id = config.get("pika", {}).get(
            "discord_channel_id", 0
        )

    async def _handle_message(self, msg: AgentMessage):
        """React to incoming bus messages."""
        pass

    def get_intel_snapshot(self) -> Dict[str, Any]:
        """Return card market intel for other agents."""
        return {
            "agent": "pika",
            "type": "card_market_intel",
            "status": "active",
        }

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Current agent state."""
        return {
            "agent": "pika",
            "cycle": self._cycle,
            "messages_received": self._messages_received,
            "messages_published": self._messages_published,
        }

    def _format_self_assessment(self) -> str:
        """Personality-driven status report."""
        return (
            f"Pika | Cycle {self._cycle} | "
            f"Msgs in: {self._messages_received} | "
            f"Msgs out: {self._messages_published}"
        )

    async def post_price_alert(self, card_name: str, price: float,
                                change_pct: float, alert_type: str):
        """Post a price alert to the Discord channel."""
        if not self._channel_id or not self.bot:
            return

        channel = self.bot.get_channel(self._channel_id)
        if not channel:
            return

        if alert_type == "drop":
            title = f"BUYING OPP: {card_name}"
            color = 0x3FB950  # green
            desc = f"Dropped **{abs(change_pct):.1f}%** to **${price:.2f}**"
        elif alert_type == "spike":
            title = f"SPIKE: {card_name}"
            color = 0xF85149  # red
            desc = f"Up **{change_pct:.1f}%** to **${price:.2f}**. Consider taking profit."
        else:
            title = f"ALERT: {card_name}"
            color = PIKA_EMBED_COLOR
            desc = f"Now at **${price:.2f}** ({change_pct:+.1f}%)"

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text="Pika | TCG Market Intel")

        await channel.send(embed=embed)

        # Publish to bus
        self.bus.publish(AgentMessage(
            msg_type=MessageType.CARD_MARKET_INTEL,
            sender="pika",
            payload={
                "card": card_name,
                "price": price,
                "change_pct": change_pct,
                "alert_type": alert_type,
            },
        ))
        self._messages_published += 1
