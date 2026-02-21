"""
Hyperliquid DEX client for order execution on decentralized perpetual futures.

Uses the official hyperliquid-python-sdk to place orders, manage positions,
and query account state directly on-chain. Implements the same executor
interface as WebhookClient for drop-in compatibility with the orchestrator.
"""

import asyncio
import logging
import os
import time
from typing import Optional, Dict

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.signing import OrderType

logger = logging.getLogger(__name__)


class HyperliquidClient:
    """Executor client for Hyperliquid decentralized perps exchange."""

    def __init__(self, config: dict):
        hl_cfg = config.get("hyperliquid", {})
        self.network = hl_cfg.get("network", "mainnet")
        self.default_leverage = hl_cfg.get("default_leverage", 5)
        self.order_type_pref = hl_cfg.get("order_type", "limit")
        self.slippage = hl_cfg.get("slippage_tolerance", 0.1) / 100  # pct → decimal

        # Loaded in connect()
        self._exchange: Optional[Exchange] = None
        self._info: Optional[Info] = None
        self._address: Optional[str] = None
        self._leverage_set: set = set()  # track which coins have leverage set

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self):
        """Initialize Hyperliquid SDK with wallet credentials."""
        private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
        self._address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")

        if not private_key or private_key.startswith("your_"):
            raise ConnectionError(
                "HYPERLIQUID_PRIVATE_KEY not configured. "
                "Add your wallet private key to ~/latpfn-trading/.env"
            )
        if not self._address or self._address.startswith("your_"):
            raise ConnectionError(
                "HYPERLIQUID_WALLET_ADDRESS not configured. "
                "Add your wallet address to ~/latpfn-trading/.env"
            )

        base_url = (
            constants.MAINNET_API_URL
            if self.network == "mainnet"
            else constants.TESTNET_API_URL
        )

        account = Account.from_key(private_key)
        self._info = Info(base_url, skip_ws=True)
        self._exchange = Exchange(account, base_url)

        # Validate connection by fetching user state
        try:
            state = self._info.user_state(self._address)
            equity = float(state.get("marginSummary", {}).get("accountValue", 0))
            logger.info(
                "Hyperliquid client ready — network: %s  address: %s...%s  equity: $%.2f",
                self.network,
                self._address[:6],
                self._address[-4:],
                equity,
            )
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Hyperliquid: {e}")

    async def disconnect(self):
        """Cleanup SDK resources."""
        if self._info:
            try:
                self._info.disconnect_websocket()
            except Exception:
                pass
        self._exchange = None
        self._info = None
        logger.info("Hyperliquid client disconnected")

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
        Place an order on Hyperliquid with SL/TP trigger orders.

        For Hyperliquid perps, quantity is in USD notional divided by price
        to get the coin size. The orchestrator passes contract count, but
        for crypto perps we interpret quantity as the number of position
        units from the risk manager (which already accounts for sizing).

        Args:
            symbol:       Coin name (e.g. 'BTC', 'ETH', 'SOL').
            direction:    'long' or 'short'.
            quantity:     Position size in contracts (used as coin amount).
            entry_price:  Desired entry price.
            stop_price:   Stop loss price.
            target_price: Take profit price.

        Returns:
            Dict with 'orderId' on success, None on failure.
        """
        if not self._exchange or not self._info:
            logger.error("Hyperliquid client not connected")
            return None

        is_buy = direction == "long"
        coin = symbol.upper()

        # Ensure leverage is set for this coin
        await self._ensure_leverage(coin)

        # Calculate order size in coin units
        # quantity from risk manager is in "contracts" — for crypto perps
        # we need to convert to coin size based on the position sizing
        sz = float(quantity)

        # Get appropriate decimal places for this coin
        sz_decimals = self._get_sz_decimals(coin)
        sz = round(sz, sz_decimals)

        if sz <= 0:
            logger.warning("Order size too small after rounding: %s %s", coin, sz)
            return None

        try:
            # Adaptive order type: check spread to decide market vs limit
            # Maker rebate = 0.01%, taker fee = 0.035% — limit saves ~0.045% per trade
            result = await self._adaptive_entry(coin, is_buy, sz, entry_price)

            # Parse response
            status = result.get("status", "")
            if status == "ok":
                response = result.get("response", {})
                statuses = response.get("data", {}).get("statuses", [])

                order_id = None
                for s in statuses:
                    if "resting" in s:
                        order_id = s["resting"]["oid"]
                    elif "filled" in s:
                        order_id = s["filled"]["oid"]

                if order_id is None:
                    # Check for errors in statuses
                    for s in statuses:
                        if "error" in s:
                            logger.error("Hyperliquid order error: %s", s["error"])
                            return None
                    order_id = int(time.time() * 1000)

                logger.info(
                    "Hyperliquid order placed: %s %s %.6f @ %.2f  SL=%.2f TP=%.2f  oid=%s",
                    direction.upper(), coin, sz, entry_price,
                    stop_price, target_price, order_id,
                )

                # Place SL/TP trigger orders
                await self._place_sl_tp(coin, not is_buy, sz, stop_price, target_price)

                return {"orderId": order_id}
            else:
                logger.error("Hyperliquid order failed: %s", result)
                return None

        except Exception as e:
            logger.error("Hyperliquid order exception: %s: %s", type(e).__name__, e)
            return None

    async def partial_close(
        self, symbol: str, fraction: float = 0.5
    ) -> Optional[Dict]:
        """
        Close a fraction of an open position via market order.

        Args:
            symbol:   Coin name (e.g. 'BTC', 'ETH').
            fraction: Fraction to close (0.0 to 1.0). Default 0.5 = close half.

        Returns:
            Dict with status on success, None on failure.
        """
        if not self._exchange or not self._info:
            logger.error("Hyperliquid client not connected")
            return None

        coin = symbol.upper()
        fraction = max(0.0, min(fraction, 1.0))

        try:
            state = self._info.user_state(self._address)
            positions = state.get("assetPositions", [])

            pos_info = None
            for p in positions:
                pos = p.get("position", {})
                if pos.get("coin") == coin:
                    pos_info = pos
                    break

            if pos_info is None:
                logger.warning("No open position found for %s", coin)
                return None

            full_sz = abs(float(pos_info.get("szi", 0)))
            if full_sz == 0:
                return None

            close_sz = full_sz * fraction
            sz_decimals = self._get_sz_decimals(coin)
            close_sz = round(close_sz, sz_decimals)

            if close_sz <= 0:
                logger.warning("Partial close size too small for %s (%.6f)", coin, close_sz)
                return None

            # Determine direction: if position is long (szi > 0), sell to close
            szi = float(pos_info.get("szi", 0))
            is_buy = szi < 0  # short position → buy to close

            result = self._exchange.market_open(
                coin, is_buy, close_sz, slippage=0.05, reduce_only=True
            )

            status = result.get("status", "")
            if status == "ok":
                logger.info(
                    "Partial close %s: %.0f%% (%.6f of %.6f)",
                    coin, fraction * 100, close_sz, full_sz,
                )

                # Cancel existing TP/SL and re-place for remaining size
                remaining_sz = round(full_sz - close_sz, sz_decimals)
                if remaining_sz > 0:
                    await self._cancel_coin_orders(coin)

                return {
                    "status": "partial_closed",
                    "closed_size": close_sz,
                    "remaining_size": remaining_sz,
                }
            else:
                logger.error("Partial close failed for %s: %s", coin, result)
                return None

        except Exception as e:
            logger.error("Partial close exception for %s: %s", coin, e)
            return None

    async def _cancel_coin_orders(self, coin: str):
        """Cancel all open orders for a coin (used after partial close to re-set SL/TP)."""
        try:
            open_orders = self._info.open_orders(self._address)
            for order in open_orders:
                if order.get("coin") == coin:
                    try:
                        self._exchange.cancel(coin, order["oid"])
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Failed to cancel orders for %s: %s", coin, e)

    async def close_position(self, symbol: str) -> Optional[Dict]:
        """Market close a single position."""
        if not self._exchange or not self._info:
            logger.error("Hyperliquid client not connected")
            return None

        coin = symbol.upper()

        try:
            # Get current position for this coin
            state = self._info.user_state(self._address)
            positions = state.get("assetPositions", [])

            pos_info = None
            for p in positions:
                pos = p.get("position", {})
                if pos.get("coin") == coin:
                    pos_info = pos
                    break

            if pos_info is None:
                logger.warning("No open position found for %s", coin)
                return {"status": "no_position"}

            sz = abs(float(pos_info.get("szi", 0)))
            if sz == 0:
                logger.warning("Position size is 0 for %s", coin)
                return {"status": "no_position"}

            # Cancel any open orders for this coin first
            open_orders = self._info.open_orders(self._address)
            for order in open_orders:
                if order.get("coin") == coin:
                    try:
                        self._exchange.cancel(coin, order["oid"])
                    except Exception:
                        pass

            # Market close the position
            result = self._exchange.market_close(coin, slippage=0.05)

            status = result.get("status", "")
            if status == "ok":
                logger.info("Hyperliquid position closed: %s  size=%.6f", coin, sz)
                return {"status": "closed"}
            else:
                logger.error("Hyperliquid close failed for %s: %s", coin, result)
                return None

        except Exception as e:
            logger.error("Hyperliquid close exception for %s: %s", coin, e)
            return None

    async def flatten_position(self, account_id=None) -> Optional[Dict]:
        """Close all open positions."""
        if not self._exchange or not self._info:
            logger.error("Hyperliquid client not connected")
            return None

        try:
            state = self._info.user_state(self._address)
            positions = state.get("assetPositions", [])

            open_coins = []
            for p in positions:
                pos = p.get("position", {})
                sz = float(pos.get("szi", 0))
                if sz != 0:
                    open_coins.append(pos.get("coin"))

            if not open_coins:
                logger.info("No open positions to flatten")
                return {"status": "flattened", "failed": []}

            # Close each position
            failed = []
            for coin in open_coins:
                result = await self.close_position(coin)
                if result is None:
                    failed.append(coin)

            if failed:
                logger.error("Flatten failed for: %s", failed)

            return {"status": "flattened", "failed": failed}

        except Exception as e:
            logger.error("Hyperliquid flatten exception: %s", e)
            return None

    # ── Account info ──────────────────────────────────────────────────

    async def get_cash_balance(self) -> float:
        """Fetch total equity from Hyperliquid (perps + spot USDC for unified accounts)."""
        if not self._info:
            return 0.0

        try:
            # Perps clearinghouse equity
            state = self._info.user_state(self._address)
            perps_equity = float(state.get("marginSummary", {}).get("accountValue", 0))

            # Spot USDC balance (unified accounts hold USDC in spot)
            spot_usdc = 0.0
            try:
                spot_state = self._info.spot_user_state(self._address)
                for bal in spot_state.get("balances", []):
                    if bal.get("coin") == "USDC":
                        spot_usdc = float(bal.get("total", 0))
                        break
            except Exception:
                pass

            total = perps_equity + spot_usdc
            if spot_usdc > 0 and perps_equity == 0:
                logger.debug(
                    "Unified account: $%.2f spot USDC available for perps trading",
                    spot_usdc,
                )
            return total
        except Exception as e:
            logger.error("Failed to fetch Hyperliquid balance: %s", e)
            return 0.0

    async def find_contract(self, symbol_root: str) -> Optional[str]:
        """Hyperliquid uses simple coin names — return as-is."""
        return symbol_root.upper()

    # ── Adaptive order execution ──────────────────────────────────────

    async def _adaptive_entry(
        self, coin: str, is_buy: bool, sz: float, entry_price: float
    ) -> dict:
        """
        Intelligent order type selection based on orderbook spread.

        Tight spread (<0.05%): market order for guaranteed fill.
        Wide spread (>=0.05%): limit order at best bid/ask for maker rebate.
        If limit not filled within 5s, cancel and re-place at updated best.
        Falls back to market after 2 failed limit attempts.
        """
        # Always use market if configured or for very small orders
        if self.order_type_pref == "market":
            return self._exchange.market_open(
                coin, is_buy, sz, slippage=self.slippage
            )

        # Check spread
        spread_pct = self._get_spread_pct(coin)
        tight_spread_threshold = 0.05  # 0.05% = ~5 bps

        if spread_pct is not None and spread_pct < tight_spread_threshold:
            # Tight spread — market order (fast fill, minimal slippage)
            logger.debug(
                "%s: tight spread %.3f%% — using market order", coin, spread_pct
            )
            return self._exchange.market_open(
                coin, is_buy, sz, slippage=self.slippage
            )

        # Wide spread — try limit order for maker rebate
        max_attempts = 2
        for attempt in range(max_attempts):
            best_px = self._get_best_price(coin, is_buy)
            if best_px is None:
                break

            limit_px = self._round_price(best_px, coin)
            logger.debug(
                "%s: limit order attempt %d — %s %.6f @ %.2f (spread=%.3f%%)",
                coin, attempt + 1, "BUY" if is_buy else "SELL", sz, limit_px,
                spread_pct or 0,
            )

            result = self._exchange.order(
                coin, is_buy, sz, limit_px,
                {"limit": {"tif": "Gtc"}},
            )

            status = result.get("status", "")
            if status != "ok":
                break

            # Check if immediately filled
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            for s in statuses:
                if "filled" in s:
                    logger.info("%s: limit order filled immediately (maker)", coin)
                    return result

            # Resting — wait up to 5s for fill
            order_id = None
            for s in statuses:
                if "resting" in s:
                    order_id = s["resting"]["oid"]

            if order_id is not None:
                filled = await self._wait_for_fill(coin, order_id, timeout=5.0)
                if filled:
                    logger.info("%s: limit order filled within 5s (maker)", coin)
                    return result

                # Not filled — cancel and retry
                try:
                    self._exchange.cancel(coin, order_id)
                    logger.debug("%s: cancelled unfilled limit order %s", coin, order_id)
                except Exception:
                    pass

        # Fallback to market order
        logger.info("%s: limit attempts exhausted — falling back to market order", coin)
        return self._exchange.market_open(coin, is_buy, sz, slippage=self.slippage)

    def _get_spread_pct(self, coin: str) -> float | None:
        """Get current bid-ask spread as a percentage of mid price."""
        try:
            book = self._info.l2_snapshot(coin)
            if not book or "levels" not in book or len(book["levels"]) < 2:
                return None
            bids = book["levels"][0]
            asks = book["levels"][1]
            if not bids or not asks:
                return None
            best_bid = float(bids[0].get("px", 0))
            best_ask = float(asks[0].get("px", 0))
            mid = (best_bid + best_ask) / 2
            if mid <= 0:
                return None
            return (best_ask - best_bid) / mid * 100
        except Exception:
            return None

    def _get_best_price(self, coin: str, is_buy: bool) -> float | None:
        """Get best bid (for buy) or best ask (for sell) to join the queue."""
        try:
            book = self._info.l2_snapshot(coin)
            if not book or "levels" not in book or len(book["levels"]) < 2:
                return None
            if is_buy:
                bids = book["levels"][0]
                return float(bids[0].get("px", 0)) if bids else None
            else:
                asks = book["levels"][1]
                return float(asks[0].get("px", 0)) if asks else None
        except Exception:
            return None

    async def _wait_for_fill(
        self, coin: str, order_id: int, timeout: float = 5.0
    ) -> bool:
        """Poll for order fill status within timeout."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            try:
                open_orders = self._info.open_orders(self._address)
                still_open = any(
                    o.get("oid") == order_id for o in open_orders
                )
                if not still_open:
                    return True  # Order no longer open = filled or cancelled
            except Exception:
                pass
            await asyncio.sleep(1.0)
        return False

    # ── Internal helpers ──────────────────────────────────────────────

    async def _ensure_leverage(self, coin: str):
        """Set leverage for a coin if not already set this session."""
        if coin in self._leverage_set:
            return

        try:
            self._exchange.update_leverage(
                self.default_leverage, coin, is_cross=True
            )
            self._leverage_set.add(coin)
            logger.debug("Set %dx cross leverage for %s", self.default_leverage, coin)
        except Exception as e:
            logger.warning("Failed to set leverage for %s: %s", coin, e)

    async def _place_sl_tp(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        stop_price: float,
        target_price: float,
    ):
        """Place stop-loss and take-profit trigger orders."""
        sz_decimals = self._get_sz_decimals(coin)
        sz = round(sz, sz_decimals)

        # Stop-loss (trigger order)
        try:
            sl_trigger_px = self._round_price(stop_price, coin)
            self._exchange.order(
                coin,
                is_buy,
                sz,
                sl_trigger_px,
                {"trigger": {"triggerPx": sl_trigger_px, "isMarket": True, "tpsl": "sl"}},
                reduce_only=True,
            )
            logger.debug("SL trigger placed: %s @ %.2f", coin, sl_trigger_px)
        except Exception as e:
            logger.warning("Failed to place SL for %s: %s", coin, e)

        # Take-profit (trigger order)
        try:
            tp_trigger_px = self._round_price(target_price, coin)
            self._exchange.order(
                coin,
                is_buy,
                sz,
                tp_trigger_px,
                {"trigger": {"triggerPx": tp_trigger_px, "isMarket": True, "tpsl": "tp"}},
                reduce_only=True,
            )
            logger.debug("TP trigger placed: %s @ %.2f", coin, tp_trigger_px)
        except Exception as e:
            logger.warning("Failed to place TP for %s: %s", coin, e)

    def _get_sz_decimals(self, coin: str) -> int:
        """Get size decimal places for a coin from exchange metadata."""
        try:
            meta = self._info.meta()
            for asset in meta.get("universe", []):
                if asset.get("name") == coin:
                    return asset.get("szDecimals", 3)
        except Exception:
            pass
        # Defaults by coin
        defaults = {"BTC": 5, "ETH": 4, "SOL": 2, "DOGE": 0, "XRP": 1}
        return defaults.get(coin, 3)

    def _round_price(self, price: float, coin: str) -> float:
        """Round price to appropriate tick size."""
        if price >= 10000:
            return round(price, 1)
        elif price >= 100:
            return round(price, 2)
        elif price >= 1:
            return round(price, 3)
        else:
            return round(price, 5)
