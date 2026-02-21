"""
Inter-agent message bus — asyncio Queue-based pub/sub.

All agents share the same asyncio event loop.  Messages are structured
dicts published to topics.  Each agent subscribes to message types it
cares about and receives them in a personal inbox queue.

Zero external dependencies — just asyncio queues.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Standard message types for inter-agent communication."""
    MARKET_INTEL = "market_intel"
    RISK_ALERT = "risk_alert"
    CAPITAL_REQUEST = "capital_request"
    STATUS_UPDATE = "status_update"
    TRADE_SIGNAL = "trade_signal"
    PERFORMANCE_REPORT = "performance_report"
    # Bidirectional feedback (Layer 2)
    PERF_FEEDBACK = "perf_feedback"        # per-trade WR feedback (turbo → HL, HL → turbo)
    POSITION_ACTION = "position_action"    # position manager actions (closes, trailing stops)


@dataclass
class AgentMessage:
    """A single inter-agent message."""
    msg_type: MessageType
    sender: str                       # agent name ("hyperliquid", "polymarket")
    payload: Dict[str, Any]           # arbitrary structured data
    timestamp: float = field(default_factory=time.time)
    priority: int = 0                 # higher = more urgent (risk alerts = 10)

    def to_dict(self) -> dict:
        return {
            "msg_type": self.msg_type.value,
            "sender": self.sender,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "priority": self.priority,
        }


class MessageBus:
    """
    Lightweight asyncio pub/sub message bus.

    Each agent gets a personal asyncio.Queue (inbox).  When a message is
    published, it fans out to every subscribed agent's inbox (except the
    sender).  Non-blocking — if an inbox is full, the message is dropped.
    """

    def __init__(self, max_queue_size: int = 200):
        self._inboxes: Dict[str, asyncio.Queue] = {}
        self._subscriptions: Dict[str, Set[MessageType]] = {}
        self._max_queue_size = max_queue_size
        self._message_count = 0
        self._drop_count = 0

    def register(
        self,
        agent_name: str,
        subscribe_to: List[MessageType],
    ) -> asyncio.Queue:
        """
        Register an agent and return its inbox queue.

        Args:
            agent_name: Unique agent identifier.
            subscribe_to: Message types this agent wants to receive.

        Returns:
            asyncio.Queue — drain this in the agent's listen loop.
        """
        inbox = asyncio.Queue(maxsize=self._max_queue_size)
        self._inboxes[agent_name] = inbox
        self._subscriptions[agent_name] = set(subscribe_to)
        logger.info(
            "Bus: '%s' registered (subscriptions: %s)",
            agent_name, [mt.value for mt in subscribe_to],
        )
        return inbox

    async def publish(self, message: AgentMessage):
        """
        Publish a message to all subscribed agents (except sender).

        Non-blocking: drops with warning if inbox is full.
        """
        self._message_count += 1
        delivered = 0

        for agent_name, inbox in self._inboxes.items():
            if agent_name == message.sender:
                continue
            if message.msg_type not in self._subscriptions.get(agent_name, set()):
                continue
            try:
                inbox.put_nowait(message)
                delivered += 1
            except asyncio.QueueFull:
                self._drop_count += 1
                logger.warning(
                    "Bus: inbox full for '%s', dropped %s from '%s'",
                    agent_name, message.msg_type.value, message.sender,
                )

        if delivered > 0:
            logger.debug(
                "Bus: %s from '%s' → %d agents",
                message.msg_type.value, message.sender, delivered,
            )

    @property
    def stats(self) -> dict:
        """Bus statistics for monitoring."""
        return {
            "total_messages": self._message_count,
            "total_drops": self._drop_count,
            "agents": list(self._inboxes.keys()),
            "queue_sizes": {
                name: q.qsize() for name, q in self._inboxes.items()
            },
        }
