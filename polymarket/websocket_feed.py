"""
Real-time WebSocket price feed for Polymarket CLOB.

Subscribes to orderbook updates for specific tokens, providing
tick-by-tick price data for the crypto scalper strategy.
Uses persistent connection with auto-reconnect.
"""

import asyncio
import json
import logging
import time
from typing import Callable, Dict, List, Optional

import websockets

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PriceUpdate:
    """A single price tick from the WebSocket feed."""

    __slots__ = ("token_id", "best_bid", "best_ask", "mid", "timestamp")

    def __init__(self, token_id: str, best_bid: float, best_ask: float):
        self.token_id = token_id
        self.best_bid = best_bid
        self.best_ask = best_ask
        self.mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        self.timestamp = time.time()


class WebSocketFeed:
    """Real-time price feed from Polymarket CLOB WebSocket."""

    def __init__(self):
        self._ws = None
        self._running = False
        self._subscriptions: Dict[str, str] = {}  # token_id -> asset_id
        self._prices: Dict[str, PriceUpdate] = {}  # token_id -> latest price
        self._callbacks: List[Callable] = []
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0

    def get_price(self, token_id: str) -> Optional[PriceUpdate]:
        """Get the latest price for a token (non-blocking)."""
        return self._prices.get(token_id)

    def get_mid(self, token_id: str) -> float:
        """Get the midpoint price for a token."""
        p = self._prices.get(token_id)
        return p.mid if p else 0.0

    def on_price(self, callback: Callable):
        """Register a callback for price updates: callback(PriceUpdate)."""
        self._callbacks.append(callback)

    async def subscribe(self, token_id: str, asset_id: str = ""):
        """Subscribe to price updates for a token."""
        self._subscriptions[token_id] = asset_id
        if self._ws:
            await self._send_subscribe([token_id])

    async def unsubscribe(self, token_id: str):
        """Unsubscribe from a token's price updates."""
        self._subscriptions.pop(token_id, None)
        self._prices.pop(token_id, None)

    async def start(self):
        """Start the WebSocket connection with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                if not self._running:
                    break
                logger.warning(
                    "WebSocket disconnected: %s. Reconnecting in %.0fs...",
                    e, self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

    async def stop(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _connect_and_listen(self):
        """Connect to WebSocket and process messages."""
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._reconnect_delay = 1.0  # Reset on successful connect
            logger.info("WebSocket connected to %s", WS_URL)

            # Re-subscribe to all tokens
            if self._subscriptions:
                await self._send_subscribe(list(self._subscriptions.keys()))

            async for message in ws:
                try:
                    self._process_message(message)
                except Exception as e:
                    logger.debug("WS message parse error: %s", e)

    async def _send_subscribe(self, token_ids: List[str]):
        """Send subscription messages for tokens."""
        if not self._ws:
            return
        for token_id in token_ids:
            msg = json.dumps({
                "type": "market",
                "assets_id": token_id,
            })
            await self._ws.send(msg)
            logger.debug("Subscribed to token %s...%s", token_id[:8], token_id[-4:])

    def _process_message(self, raw: str):
        """Parse a WebSocket message and update prices."""
        data = json.loads(raw)

        # Handle different message types
        msg_type = data.get("event_type", data.get("type", ""))

        if msg_type in ("book", "price_change"):
            token_id = data.get("asset_id", "")
            if not token_id:
                return

            # Extract best bid/ask from orderbook update
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0

            update = PriceUpdate(token_id, best_bid, best_ask)
            self._prices[token_id] = update

            for cb in self._callbacks:
                try:
                    cb(update)
                except Exception as e:
                    logger.debug("Price callback error: %s", e)

        elif msg_type == "last_trade_price":
            token_id = data.get("asset_id", "")
            price = float(data.get("price", 0))
            if token_id and price > 0:
                existing = self._prices.get(token_id)
                if existing:
                    existing.mid = price
                    existing.timestamp = time.time()
                else:
                    self._prices[token_id] = PriceUpdate(token_id, price, price)
