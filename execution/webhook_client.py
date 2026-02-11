"""
PickMyTrade webhook client for order execution via Apex/Tradovate.

Sends HTTP POST requests to the PickMyTrade webhook endpoint,
which bridges signals to Tradovate on prop firm accounts where
direct API access is unavailable.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict

import aiohttp

logger = logging.getLogger(__name__)


class WebhookClient:
    """Async webhook client for PickMyTrade order execution."""

    def __init__(self, config: dict):
        pm = config["pickmytrade"]
        self.webhook_url = pm["webhook_url"]
        self.token = pm["token"]
        self.account_id = pm["account_id"]
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self):
        """Initialize HTTP session and validate credentials."""
        self._session = aiohttp.ClientSession()

        if not self.token or self.token.startswith("your_"):
            raise ConnectionError(
                "PICKMYTRADE_TOKEN not configured. "
                "Add your token to ~/latpfn-trading/.env"
            )
        if not self.account_id or self.account_id.startswith("your_"):
            raise ConnectionError(
                "PICKMYTRADE_ACCOUNT_ID not configured. "
                "Add your account ID to ~/latpfn-trading/.env"
            )

        logger.info(
            "PickMyTrade webhook client ready — endpoint: %s", self.webhook_url
        )

    async def disconnect(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # ── Order execution ───────────────────────────────────────────────

    async def place_bracket_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> Optional[Dict]:
        """
        Send a bracket order via PickMyTrade webhook.

        Args:
            symbol:       Instrument symbol (e.g. 'NQ', 'YM', 'GC').
            direction:    'long' or 'short'.
            quantity:     Number of contracts.
            entry_price:  Entry price.
            stop_price:   Stop loss price.
            target_price: Take profit price.

        Returns:
            Dict with 'orderId' on success, None on failure.
        """
        payload = {
            "symbol": symbol,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": "buy" if direction == "long" else "sell",
            "quantity": quantity,
            "price": round(entry_price, 2),
            "tp": round(target_price, 2),
            "sl": round(stop_price, 2),
            "token": self.token,
            "account_id": self.account_id,
            "pyramid": False,
            "reverse_order_close": True,
        }

        result = await self._send_webhook(payload)

        if result is not None:
            order_id = int(time.time() * 1000)
            logger.info(
                "Webhook order sent: %s %s %d @ %.2f  SL=%.2f TP=%.2f  id=%d",
                direction.upper(), symbol, quantity, entry_price,
                stop_price, target_price, order_id,
            )
            return {"orderId": order_id}

        return None

    async def close_position(self, symbol: str) -> Optional[Dict]:
        """Send a close-position webhook."""
        payload = {
            "symbol": symbol,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": "close",
            "token": self.token,
            "account_id": self.account_id,
        }

        result = await self._send_webhook(payload)
        if result is not None:
            logger.info("Close webhook sent for %s", symbol)
            return {"status": "closed"}
        return None

    async def flatten_position(self, account_id: int = None) -> Optional[Dict]:
        """Close all positions by sending close webhooks for common symbols."""
        for symbol in ["MNQ", "MYM", "MES", "M2K", "MGC", "NQ", "YM", "ES", "RTY", "GC"]:
            await self.close_position(symbol)
        return {"status": "flattened"}

    # ── Account info (stub — PickMyTrade has no balance query) ────────

    async def get_cash_balance(self) -> float:
        """Return 0 — balance must be checked on Tradovate directly."""
        logger.info("Cash balance not available via webhook — check Tradovate")
        return 0.0

    async def find_contract(self, symbol_root: str) -> Optional[str]:
        """PickMyTrade handles contract resolution — return root symbol."""
        return symbol_root

    # ── HTTP helper ───────────────────────────────────────────────────

    async def _send_webhook(self, payload: dict) -> Optional[str]:
        """POST JSON payload to PickMyTrade webhook endpoint."""
        if self._session is None:
            logger.error("Webhook client not connected (call connect() first)")
            return None

        try:
            async with self._session.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "text/plain"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    logger.debug("Webhook OK: %s", text[:200])
                    return text
                else:
                    logger.error(
                        "Webhook failed %d: %s  payload=%s",
                        resp.status, text[:200], json.dumps(payload),
                    )
                    return None
        except aiohttp.ClientError as e:
            logger.error("Webhook HTTP error: %s", e)
            return None
        except Exception as e:
            logger.error("Webhook unexpected error: %s", e)
            return None
