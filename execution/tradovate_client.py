"""
Tradovate REST + WebSocket client for order execution.

Supports demo and live modes. All automated orders include
``isAutomated: true`` for CME compliance.
"""

import asyncio
import json
import logging
import time
from typing import Optional, Dict, List

import aiohttp

logger = logging.getLogger(__name__)


class TradovateClient:
    """Async Tradovate API client."""

    def __init__(self, config: dict):
        tv = config["tradovate"]
        self.mode = tv["mode"]
        creds = tv["credentials"]

        if self.mode == "demo":
            self.api_url = tv["api_url"]
            self.ws_url = tv["ws_url"]
            self.md_url = tv["md_url"]
        else:
            self.api_url = tv["live_api_url"]
            self.ws_url = tv["live_ws_url"]
            self.md_url = tv["live_md_url"]

        self.username = creds["username"]
        self.password = creds["password"]
        self.secret = creds.get("secret", "")
        self.cid = creds.get("cid", 1)

        self.access_token: Optional[str] = None
        self.account_id: Optional[int] = None
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self):
        """Authenticate and discover account."""
        self._session = aiohttp.ClientSession()
        await self._authenticate()
        await self._get_account()
        logger.info(
            "Tradovate connected (%s) — account %s",
            self.mode, self.account_id,
        )

    async def disconnect(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def _authenticate(self):
        """POST /auth/accesstokenrequest to get bearer token."""
        url = f"{self.api_url}/auth/accesstokenrequest"
        payload = {
            "name": self.username,
            "password": self.password,
            "appId": "LatPFN-Trading",
            "appVersion": "1.0",
            "deviceId": "latpfn-python",
            "cid": self.cid,
            "sec": self.secret,
        }
        async with self._session.post(url, json=payload) as resp:
            data = await resp.json()
            if resp.status != 200 or "accessToken" not in data:
                raise ConnectionError(f"Tradovate auth failed: {data}")
            self.access_token = data["accessToken"]
            logger.info("Authenticated with Tradovate")

    async def _get_account(self):
        """Discover the first available trading account."""
        data = await self._get("/account/list")
        if not data:
            raise ConnectionError("No Tradovate accounts found")
        self.account_id = data[0]["id"]

    # ── Account info ──────────────────────────────────────────────────

    async def get_cash_balance(self) -> float:
        """Get current account cash balance."""
        data = await self._get(
            f"/cashBalance/getCashBalanceSnapshot",
            params={"accountId": self.account_id},
        )
        return float(data.get("cashBalance", 0) if data else 0)

    async def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        data = await self._get("/position/list")
        return [p for p in (data or []) if p.get("netPos", 0) != 0]

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
        Place a bracket order (entry + stop loss + take profit).

        Args:
            symbol:       Tradovate contract symbol (e.g. 'NQH5').
            direction:    'long' or 'short'.
            quantity:     Number of contracts.
            entry_price:  Limit entry price.
            stop_price:   Stop loss price.
            target_price: Take profit price.

        Returns:
            Order response dict or None on failure.
        """
        action = "Buy" if direction == "long" else "Sell"
        exit_action = "Sell" if direction == "long" else "Buy"
        ts = int(time.time() * 1000)

        payload = {
            "accountSpec": self.username,
            "accountId": self.account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Limit",
            "price": entry_price,
            "isAutomated": True,
            "bracket1": {
                "action": exit_action,
                "orderType": "Limit",
                "price": target_price,
            },
            "bracket2": {
                "action": exit_action,
                "orderType": "Stop",
                "stopPrice": stop_price,
            },
        }

        result = await self._post("/order/placeOSO", payload)

        if result and "orderId" in result:
            logger.info(
                "Bracket order placed: %s %s %d @ %.2f  SL=%.2f TP=%.2f  id=%s",
                action, symbol, quantity, entry_price,
                stop_price, target_price, result["orderId"],
            )
        else:
            logger.error("Failed to place bracket order: %s", result)

        return result

    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
    ) -> Optional[Dict]:
        """Place a simple market order (for flattening positions)."""
        action = "Buy" if direction == "long" else "Sell"
        payload = {
            "accountSpec": self.username,
            "accountId": self.account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Market",
            "isAutomated": True,
        }
        return await self._post("/order/placeOrder", payload)

    async def cancel_order(self, order_id: int) -> Optional[Dict]:
        """Cancel an open order."""
        return await self._post("/order/cancelorder", {"orderId": order_id})

    async def flatten_position(self, account_id: int = None) -> Optional[Dict]:
        """Close all positions on the account."""
        aid = account_id or self.account_id
        return await self._post(
            "/order/liquidatePosition",
            {"accountId": aid},
        )

    # ── Contract lookup ───────────────────────────────────────────────

    async def find_contract(self, symbol_root: str) -> Optional[str]:
        """
        Find the active front-month contract symbol for a root.
        e.g. 'NQ' → 'NQH5'
        """
        data = await self._get(
            "/contract/find",
            params={"name": symbol_root},
        )
        if data and "name" in data:
            return data["name"]
        # Fallback: try the suggest endpoint
        data = await self._get(
            "/contract/suggest",
            params={"t": symbol_root, "l": 1},
        )
        if data and len(data) > 0:
            return data[0].get("name")
        return None

    # ── HTTP helpers ──────────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None) -> Optional[dict | list]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.api_url}{path}"
        try:
            async with self._session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                text = await resp.text()
                logger.error("GET %s → %d: %s", path, resp.status, text)
                return None
        except Exception as e:
            logger.error("GET %s error: %s", path, e)
            return None

    async def _post(self, path: str, payload: dict) -> Optional[dict]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.api_url}{path}"
        try:
            async with self._session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return data
                logger.error("POST %s → %d: %s", path, resp.status, data)
                return None
        except Exception as e:
            logger.error("POST %s error: %s", path, e)
            return None
