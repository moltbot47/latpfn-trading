"""
Polymarket CLOB API client.

Wraps py-clob-client SDK for authenticated order placement and the
Gamma API for public market discovery.  Follows the same executor
pattern as execution/hyperliquid_client.py.
"""

import json
import logging
import os
from typing import Dict, List, Optional

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    BalanceAllowanceParams,
    BookParams,
    MarketOrderArgs,
    OpenOrderParams,
    OrderArgs,
    OrderType,
)
from py_clob_client.order_builder.constants import BUY, SELL

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
DATA_URL = "https://data-api.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet


class PolymarketClient:
    """Authenticated Polymarket CLOB client for order placement and market data."""

    def __init__(self, config: dict):
        self.config = config
        pm_cfg = config.get("polymarket", {})
        self.budget = pm_cfg.get("budget_usdc", 15.0)
        self._client: Optional[ClobClient] = None
        self._address: Optional[str] = None

    # ── Connection ───────────────────────────────────────────────────

    async def connect(self):
        """Initialize ClobClient with credentials from environment."""
        private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        api_key = os.getenv("POLYMARKET_API_KEY", "")
        api_secret = os.getenv("POLYMARKET_API_SECRET", "")
        api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "")
        self._address = os.getenv("POLYMARKET_WALLET_ADDRESS", "")
        funder = os.getenv("POLYMARKET_FUNDER_ADDRESS", self._address)
        sig_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))

        if not private_key:
            raise ConnectionError(
                "POLYMARKET_PRIVATE_KEY not set. Add it to .env"
            )

        if api_key and api_secret and api_passphrase:
            creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            )
            self._client = ClobClient(
                CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                creds=creds,
                signature_type=sig_type,
                funder=funder,
            )
            logger.info("Polymarket client connected with stored credentials")
        else:
            # Derive credentials from private key
            self._client = ClobClient(
                CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                signature_type=sig_type,
                funder=funder,
            )
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
            logger.info(
                "Polymarket credentials derived. Save these to .env:\n"
                "  POLYMARKET_API_KEY=%s\n"
                "  POLYMARKET_API_SECRET=%s\n"
                "  POLYMARKET_API_PASSPHRASE=%s",
                creds.api_key,
                creds.api_secret,
                creds.api_passphrase,
            )

        # Validate connection
        try:
            self._client.get_ok()
        except Exception as e:
            raise ConnectionError(f"Polymarket CLOB health check failed: {e}")

        balance = self.get_balance()
        logger.info(
            "Polymarket ready — balance: $%.2f  budget: $%.2f",
            balance, self.budget,
        )

    async def disconnect(self):
        """Cleanup."""
        self._client = None
        logger.info("Polymarket client disconnected")

    # ── Market data (public) ─────────────────────────────────────────

    def get_gamma_markets(
        self,
        active: bool = True,
        min_volume: float = 1000,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Fetch markets from Gamma API with filters."""
        params = {
            "active": active,
            "closed": False,
            "archived": False,
            "enableOrderBook": True,
            "volume_num_min": min_volume,
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": False,
        }
        resp = requests.get(f"{GAMMA_URL}/markets", params=params, timeout=30)
        resp.raise_for_status()
        markets = resp.json()

        # Parse JSON-encoded array fields
        for m in markets:
            for field in ("clobTokenIds", "outcomePrices", "outcomes"):
                if isinstance(m.get(field), str):
                    try:
                        m[field] = json.loads(m[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return markets

    def get_all_active_markets(self, min_volume: float = 1000) -> List[Dict]:
        """Paginate through all active markets."""
        all_markets = []
        offset = 0
        limit = 100
        while True:
            batch = self.get_gamma_markets(
                min_volume=min_volume, limit=limit, offset=offset
            )
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return all_markets

    def get_market(self, condition_id: str) -> Dict:
        """Fetch single market from CLOB API."""
        return self._client.get_market(condition_id)

    def get_orderbook(self, token_id: str) -> Dict:
        """Get L2 orderbook for an outcome token."""
        return self._client.get_order_book(token_id)

    def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        result = self._client.get_midpoint(token_id)
        return float(result.get("mid", 0))

    def get_spread(self, token_id: str) -> float:
        """Get bid-ask spread for a token."""
        result = self._client.get_spread(token_id)
        return float(result.get("spread", 0))

    # ── Order placement (authenticated) ──────────────────────────────

    def buy_limit(
        self, token_id: str, price: float, size: float
    ) -> Dict:
        """Place a limit buy order (GTC)."""
        order_args = OrderArgs(
            token_id=token_id, price=price, size=size, side=BUY,
        )
        signed = self._client.create_order(order_args)
        result = self._client.post_order(signed, OrderType.GTC)
        logger.info(
            "BUY limit: token=%s..%s  price=%.4f  size=%.2f  result=%s",
            token_id[:8], token_id[-4:], price, size,
            result.get("status", result.get("orderID", "?")),
        )
        return result

    def sell_limit(
        self, token_id: str, price: float, size: float
    ) -> Dict:
        """Place a limit sell order (GTC)."""
        order_args = OrderArgs(
            token_id=token_id, price=price, size=size, side=SELL,
        )
        signed = self._client.create_order(order_args)
        result = self._client.post_order(signed, OrderType.GTC)
        logger.info(
            "SELL limit: token=%s..%s  price=%.4f  size=%.2f  result=%s",
            token_id[:8], token_id[-4:], price, size,
            result.get("status", result.get("orderID", "?")),
        )
        return result

    def buy_market(self, token_id: str, amount_usdc: float) -> Dict:
        """Place a market buy (FOK). amount_usdc = dollars to spend."""
        order_args = MarketOrderArgs(
            token_id=token_id, amount=amount_usdc, side=BUY,
        )
        signed = self._client.create_market_order(order_args)
        result = self._client.post_order(signed, OrderType.FOK)
        logger.info(
            "BUY market: token=%s..%s  $%.2f  result=%s",
            token_id[:8], token_id[-4:], amount_usdc,
            result.get("status", result.get("orderID", "?")),
        )
        return result

    def sell_market(self, token_id: str, shares: float) -> Dict:
        """Place a market sell (FOK). shares = number of shares to sell."""
        order_args = MarketOrderArgs(
            token_id=token_id, amount=shares, side=SELL,
        )
        signed = self._client.create_market_order(order_args)
        result = self._client.post_order(signed, OrderType.FOK)
        logger.info(
            "SELL market: token=%s..%s  shares=%.2f  result=%s",
            token_id[:8], token_id[-4:], shares,
            result.get("status", result.get("orderID", "?")),
        )
        return result

    # ── Order management ─────────────────────────────────────────────

    def get_open_orders(self, market: Optional[str] = None) -> List[Dict]:
        """Get open orders, optionally filtered by market condition_id."""
        params = OpenOrderParams(market=market) if market else OpenOrderParams()
        return self._client.get_orders(params)

    def cancel_order(self, order_id: str):
        """Cancel a single order."""
        self._client.cancel(order_id)
        logger.info("Cancelled order %s", order_id)

    def cancel_all(self):
        """Cancel all open orders."""
        self._client.cancel_all()
        logger.info("Cancelled all Polymarket orders")

    # ── Balance and positions ────────────────────────────────────────

    def get_balance(self) -> float:
        """Get USDC collateral balance (converted from raw 6-decimal units)."""
        try:
            result = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type="COLLATERAL")
            )
            raw = float(result.get("balance", 0))
            # USDC has 6 decimals on Polygon — raw value is in micro-USDC
            return raw / 1e6 if raw > 1000 else raw
        except Exception as e:
            logger.error("Failed to fetch Polymarket balance: %s", e)
            return 0.0

    def get_token_balance(self, token_id: str) -> float:
        """Get conditional token balance (shares held)."""
        try:
            result = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type="CONDITIONAL", token_id=token_id)
            )
            raw = float(result.get("balance", 0))
            return raw / 1e6 if raw > 1000 else raw
        except Exception as e:
            logger.error("Failed to fetch token balance: %s", e)
            return 0.0

    def get_positions_from_api(self) -> List[Dict]:
        """Fetch positions from Polymarket Data API."""
        if not self._address:
            return []
        try:
            resp = requests.get(
                f"{DATA_URL}/positions",
                params={
                    "user": self._address,
                    "sizeThreshold": 0.01,
                    "limit": 500,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            return []

    def get_portfolio_value(self) -> float:
        """Get total portfolio value from Data API."""
        if not self._address:
            return 0.0
        try:
            resp = requests.get(
                f"{DATA_URL}/value",
                params={"user": self._address},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                return float(data[0].get("value", 0))
            return 0.0
        except Exception as e:
            logger.error("Failed to fetch portfolio value: %s", e)
            return 0.0
