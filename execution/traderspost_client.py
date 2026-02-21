"""
TradersPost webhook client for order execution via Apex/Tradovate.

Sends HTTP POST requests to the TradersPost webhook endpoint,
which bridges signals to Tradovate on prop firm accounts where
direct API access is unavailable.

Replaces PickMyTrade (trial expired). Same interface as WebhookClient.

TradersPost docs: https://docs.traderspost.io/docs/core-concepts/signals/webhooks
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict

import aiohttp

logger = logging.getLogger(__name__)


class TradersPostClient:
    """Async webhook client for TradersPost order execution."""

    def __init__(self, config: dict):
        tp = config["traderspost"]
        self.webhook_url = tp["webhook_url"]  # Full URL with embedded auth
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self):
        """Initialize HTTP session and validate webhook URL."""
        self._session = aiohttp.ClientSession()

        if not self.webhook_url or "traderspost.io" not in self.webhook_url:
            raise ConnectionError(
                "TRADERSPOST_WEBHOOK_URL not configured. "
                "Add your TradersPost webhook URL to config/settings.yaml "
                "or set TRADERSPOST_WEBHOOK_URL in .env"
            )

        logger.info(
            "TradersPost webhook client ready — endpoint: %s...%s",
            self.webhook_url[:60], self.webhook_url[-8:],
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
        Send a bracket order via TradersPost webhook.

        Args:
            symbol:       Instrument symbol (e.g. 'MNQ', 'MES', 'MBT').
            direction:    'long' or 'short'.
            quantity:     Number of contracts.
            entry_price:  Current market price (signal price for reference).
            stop_price:   Stop loss price.
            target_price: Take profit price.

        Returns:
            Dict with 'orderId' on success, None on failure.
        """
        payload = {
            "ticker": symbol,
            "action": "buy" if direction == "long" else "sell",
            "orderType": "market",
            "quantity": int(quantity),
            "signalPrice": round(entry_price, 2),
            "takeProfit": {
                "limitPrice": round(target_price, 2),
            },
            "stopLoss": {
                "type": "stop",
                "stopPrice": round(stop_price, 2),
            },
        }

        result = await self._send_webhook(payload)

        if result is not None and result.get("success"):
            order_id = result.get("id", str(int(time.time() * 1000)))
            logger.info(
                "TradersPost order sent: %s %s %d @ %.2f  SL=%.2f TP=%.2f  id=%s",
                direction.upper(), symbol, quantity, entry_price,
                stop_price, target_price, order_id,
            )
            return {"orderId": order_id}

        return None

    async def close_position(self, symbol: str) -> Optional[Dict]:
        """Send an exit signal for a specific symbol."""
        payload = {
            "ticker": symbol,
            "action": "exit",
        }

        result = await self._send_webhook(payload)
        if result is not None and result.get("success"):
            logger.info("TradersPost exit sent for %s", symbol)
            return {"status": "closed"}
        return None

    async def flatten_position(self, account_id: int = None) -> Optional[Dict]:
        """Close all positions by sending exit webhooks for all known symbols in parallel."""
        symbols = [
            "MNQ", "MYM", "MES", "M2K", "MGC", "MCL",
            "M6E", "M6B", "M6A", "M6J",
            "MBT", "MET", "10Y",
            "NQ", "YM", "ES", "RTY", "GC", "CL",
        ]
        results = await asyncio.gather(
            *[self.close_position(sym) for sym in symbols],
            return_exceptions=True,
        )
        failed = [
            sym for sym, r in zip(symbols, results)
            if r is None or isinstance(r, Exception)
        ]
        if failed:
            logger.error(
                "FLATTEN WARNING: exit webhook failed for %s — verify positions manually!",
                failed,
            )
        return {"status": "flattened", "failed": failed}

    # ── Account info (stub — TradersPost has no balance query) ────────

    async def get_cash_balance(self) -> float:
        """Return 0 — balance must be checked on Tradovate directly."""
        logger.info("Cash balance not available via webhook — check Tradovate")
        return 0.0

    async def find_contract(self, symbol_root: str) -> Optional[str]:
        """TradersPost handles contract resolution — return root symbol."""
        return symbol_root

    # ── HTTP helper ───────────────────────────────────────────────────

    async def _send_webhook(
        self, payload: dict, max_retries: int = 3
    ) -> Optional[dict]:
        """POST JSON payload to TradersPost webhook endpoint with retry logic.

        Retries up to max_retries times with exponential backoff (1s, 2s, 4s)
        on aiohttp.ClientError and timeout errors.

        Returns:
            Parsed JSON response dict on success, None on failure.
            Expected response: {"success": true, "id": "...", "logId": "...", "payload": {...}}
        """
        if self._session is None:
            logger.error("Webhook client not connected (call connect() first)")
            return None

        last_exception = None
        for attempt in range(1, max_retries + 1):
            try:
                async with self._session.post(
                    self.webhook_url,
                    json=payload,  # application/json (not text/plain like PMT)
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    text = await resp.text()
                    logger.info(
                        "TradersPost response [attempt %d/%d] status=%d body=%s",
                        attempt, max_retries, resp.status, text[:500],
                    )

                    if resp.status == 200:
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            logger.warning(
                                "TradersPost returned non-JSON 200: %s", text[:200]
                            )
                            return {"success": True, "raw": text}

                    elif resp.status == 429:
                        # Rate limited (60/min, 500/hour)
                        backoff = 2 ** attempt
                        logger.warning(
                            "TradersPost rate limited (429) — waiting %ds",
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    else:
                        logger.error(
                            "TradersPost webhook failed %d: %s  payload=%s",
                            resp.status, text[:200], json.dumps(payload),
                        )
                        return None

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt < max_retries:
                    backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    logger.warning(
                        "TradersPost attempt %d/%d failed (%s: %s) — retrying in %ds",
                        attempt, max_retries, type(e).__name__, e, backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "TradersPost FAILED after %d attempts. Last error: %s: %s  payload=%s",
                        max_retries, type(e).__name__, e, json.dumps(payload),
                    )
            except Exception as e:
                logger.error("TradersPost unexpected error: %s", e)
                return None

        return None
