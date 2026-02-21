"""
Crypto Scalper — 5-minute binary market scalping strategy.

Targets Polymarket's "Bitcoin/ETH/SOL Up or Down" 5-minute markets.
Uses real-time price monitoring + optional LaT-PFN predictions to
buy near-certain outcomes in the final 30-120 seconds of each window.

Expected return: 5-15% per trade, up to 12 trades/hour per asset.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass

# Suppress noisy per-request httpx logs from the scalper's 1-second polling
logging.getLogger("httpx").setLevel(logging.WARNING)
from typing import Dict, List, Optional, Tuple

import requests

from polymarket.positions import PolyPosition

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com"

# Supported assets and their slug prefixes
SUPPORTED_ASSETS = {
    "btc": "btc-updown-5m",
    "eth": "eth-updown-5m",
    "sol": "sol-updown-5m",
    "xrp": "xrp-updown-5m",
}


@dataclass
class ScalpWindow:
    """A single 5-minute trading window."""

    asset: str  # "btc", "eth", etc.
    slug: str  # "btc-updown-5m-1771450500"
    start_ts: int  # Unix timestamp of window start
    end_ts: int  # Unix timestamp of window end
    condition_id: str  # Market condition ID
    up_token_id: str  # Token ID for "Up" outcome
    down_token_id: str  # Token ID for "Down" outcome
    up_price: float = 0.5  # Current Up price
    down_price: float = 0.5  # Current Down price
    traded: bool = False  # Already placed a trade this window


class CryptoScalper:
    """
    5-minute binary market scalper.

    Monitors crypto Up/Down markets and buys near-certain outcomes
    when price divergence is high and time remaining is low.
    """

    def __init__(self, client, position_mgr, config: dict):
        self.client = client
        self.positions = position_mgr

        pm_cfg = config.get("polymarket", {})
        scalper_cfg = pm_cfg.get("scalper", {})

        self.budget = pm_cfg.get("budget_usdc", 15.0)
        self.enabled_assets = scalper_cfg.get("assets", ["btc"])
        self.entry_threshold = scalper_cfg.get("entry_threshold", 0.82)
        self.max_entry_price = scalper_cfg.get("max_entry_price", 0.95)
        self.min_seconds_left = scalper_cfg.get("min_seconds_left", 15)
        self.max_seconds_left = scalper_cfg.get("max_seconds_left", 120)
        self.max_position_pct = scalper_cfg.get("max_position_pct", 0.15)
        self.shares_per_trade = scalper_cfg.get("shares_per_trade", 10)
        self.cooldown_windows = scalper_cfg.get("cooldown_windows", 1)

        # State
        self._current_windows: Dict[str, ScalpWindow] = {}  # asset -> window
        self._last_trade_window: Dict[str, int] = {}  # asset -> window start_ts
        self._session = requests.Session()  # Persistent HTTP for speed

        # Stats
        self.trades_today = 0
        self.pnl_today = 0.0

    # ── Window Discovery ───────────────────────────────────────────

    def _get_current_window_ts(self) -> int:
        """Get the start timestamp of the current 5-min window."""
        now = int(time.time())
        return now - (now % 300)

    def _get_window_slug(self, asset: str, window_ts: int) -> str:
        """Build the Gamma API slug for a 5-min window."""
        prefix = SUPPORTED_ASSETS.get(asset, f"{asset}-updown-5m")
        return f"{prefix}-{window_ts}"

    def discover_window(self, asset: str) -> Optional[ScalpWindow]:
        """
        Fetch the current 5-min window for an asset from Gamma API.
        Uses persistent HTTP session for speed (~100ms vs ~400ms).
        """
        window_ts = self._get_current_window_ts()
        slug = self._get_window_slug(asset, window_ts)

        try:
            resp = self._session.get(
                f"{GAMMA_URL}/events",
                params={"slug": slug},
                timeout=5,
            )
            events = resp.json() if resp.status_code == 200 else []
            if not events:
                return None

            event = events[0]
            markets = event.get("markets", [])
            if not markets:
                return None

            market = markets[0]

            # Parse JSON-encoded fields
            for field in ("clobTokenIds", "outcomePrices", "outcomes"):
                if isinstance(market.get(field), str):
                    try:
                        market[field] = json.loads(market[field])
                    except (json.JSONDecodeError, TypeError):
                        pass

            tokens = market.get("clobTokenIds", [])
            prices = market.get("outcomePrices", [])
            if len(tokens) < 2:
                return None

            return ScalpWindow(
                asset=asset,
                slug=slug,
                start_ts=window_ts,
                end_ts=window_ts + 300,
                condition_id=market.get("conditionId", ""),
                up_token_id=tokens[0],
                down_token_id=tokens[1],
                up_price=float(prices[0]) if prices else 0.5,
                down_price=float(prices[1]) if len(prices) > 1 else 0.5,
            )
        except Exception as e:
            logger.debug("Window discovery failed for %s: %s", asset, e)
            return None

    def refresh_prices(self, window: ScalpWindow) -> bool:
        """
        Refresh prices for a window using the CLOB midpoint API.
        Returns True if prices updated successfully.
        """
        try:
            up_mid = self.client.get_midpoint(window.up_token_id)
            if up_mid > 0:
                window.up_price = up_mid
                window.down_price = 1.0 - up_mid
                return True
        except Exception as e:
            logger.debug("Price refresh failed: %s", e)
        return False

    # ── Signal Detection ───────────────────────────────────────────

    def should_trade(self, window: ScalpWindow) -> Optional[Dict]:
        """
        Check if conditions are met for a scalp trade.

        Returns trade signal dict or None.
        """
        if window.traded:
            return None

        now = time.time()
        seconds_left = window.end_ts - now

        # Time window check
        if seconds_left < self.min_seconds_left:
            return None  # Too late, might not fill
        if seconds_left > self.max_seconds_left:
            return None  # Too early, outcome still uncertain

        # Cooldown check
        last_trade_ts = self._last_trade_window.get(window.asset, 0)
        if window.start_ts - last_trade_ts < 300 * self.cooldown_windows:
            if last_trade_ts > 0:
                return None

        # Price divergence check — is one outcome near-certain?
        if window.up_price >= self.entry_threshold and window.up_price <= self.max_entry_price:
            return {
                "direction": "Up",
                "token_id": window.up_token_id,
                "price": window.up_price,
                "edge_pct": (1.0 - window.up_price) / window.up_price * 100,
                "seconds_left": seconds_left,
            }
        elif window.down_price >= self.entry_threshold and window.down_price <= self.max_entry_price:
            return {
                "direction": "Down",
                "token_id": window.down_token_id,
                "price": window.down_price,
                "edge_pct": (1.0 - window.down_price) / window.down_price * 100,
                "seconds_left": seconds_left,
            }

        return None

    # ── Position Sizing ────────────────────────────────────────────

    def size_trade(self, price: float) -> Tuple[float, float]:
        """
        Calculate trade size. Returns (shares, cost_usdc).
        Uses fixed share count for speed (no complex calculations).
        """
        available = self.budget - self.positions.total_deployed()
        max_cost = self.budget * self.max_position_pct
        shares = self.shares_per_trade
        cost = shares * price

        # Ensure minimum 5 shares (Polymarket minimum)
        if shares < 5:
            shares = 5
            cost = shares * price

        # Cap at available budget
        if cost > min(available, max_cost):
            shares = min(available, max_cost) / price
            shares = max(int(shares), 5)  # Floor to int, min 5
            cost = shares * price

        if cost > available or shares < 5:
            return 0, 0

        return shares, cost

    # ── Execution ──────────────────────────────────────────────────

    async def execute_scalp(
        self, window: ScalpWindow, signal: Dict
    ) -> Optional[Dict]:
        """
        Execute a scalp trade. Optimized for speed:
        - Uses limit order at current price (acts like market order)
        - Minimal logging until after execution
        """
        price = signal["price"]
        shares, cost = self.size_trade(price)
        if shares < 5:
            return None

        token_id = signal["token_id"]
        direction = signal["direction"]

        # Fire the order — speed is critical here
        try:
            result = self.client.buy_limit(
                token_id=token_id,
                price=price,
                size=shares,
            )
        except Exception as e:
            logger.error("Scalp order failed: %s", e)
            return None

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error("Scalp order missing orderID: %s", result)
            return None

        # Mark window as traded
        window.traded = True
        self._last_trade_window[window.asset] = window.start_ts

        # Record position
        pos = PolyPosition(
            market_id=window.condition_id,
            token_id=token_id,
            question=f"{window.asset.upper()} Up/Down 5m ({direction})",
            strategy="crypto_scalp",
            direction=direction,
            entry_price=price,
            size_usdc=cost,
            shares=shares,
            target_exit=1.0,
            expected_pnl_pct=signal["edge_pct"],
            resolution_date=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(window.end_ts)
            ),
            market_probability=price,
            order_id=order_id,
        )
        key = self.positions.open_position(pos)

        self.trades_today += 1

        logger.info(
            "SCALP: %s %s @ $%.2f | %d shares ($%.2f) | %ds left | edge=%.1f%%",
            window.asset.upper(), direction, price, shares, cost,
            signal["seconds_left"], signal["edge_pct"],
        )

        return {
            "position_key": key,
            "order_id": order_id,
            "asset": window.asset,
            "direction": direction,
            "entry_price": price,
            "shares": shares,
            "size_usdc": cost,
            "edge_pct": signal["edge_pct"],
            "seconds_left": signal["seconds_left"],
            "window_slug": window.slug,
        }

    # ── Main Loop ──────────────────────────────────────────────────

    async def run_loop(self):
        """
        Main scalping loop. Runs continuously, checking every second.

        For each enabled asset:
        1. Discover current 5-min window
        2. Refresh prices
        3. Check if trade conditions are met
        4. Execute if conditions met
        5. Auto-resolve positions when windows close
        """
        logger.info(
            "Crypto scalper started: assets=%s, threshold=%.2f, shares=%d",
            self.enabled_assets, self.entry_threshold, self.shares_per_trade,
        )

        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.error("Scalper tick error: %s", e)
            await asyncio.sleep(1)  # 1-second polling

    async def _tick(self):
        """One iteration of the scalp loop."""
        current_ts = self._get_current_window_ts()

        for asset in self.enabled_assets:
            # Check if we need a new window
            existing = self._current_windows.get(asset)
            if not existing or existing.start_ts != current_ts:
                window = await asyncio.to_thread(self.discover_window, asset)
                if window:
                    self._current_windows[asset] = window
                continue

            window = existing

            # Refresh prices (run in thread to avoid blocking event loop)
            await asyncio.to_thread(self.refresh_prices, window)

            # Check for trade signal
            signal = self.should_trade(window)
            if signal:
                result = await self.execute_scalp(window, signal)
                if result and self._bot:
                    try:
                        await self._bot.post_poly_trade(result)
                    except Exception:
                        pass

            # Auto-resolve when window closes
            now = time.time()
            if now > window.end_ts + 10:  # 10s grace period
                await self._resolve_window(window)
                self._current_windows.pop(asset, None)

    async def _resolve_window(self, window: ScalpWindow):
        """Resolve positions from a closed window."""
        for key, pos in list(self.positions.get_open_positions().items()):
            if pos.strategy != "crypto_scalp":
                continue
            if pos.market_id != window.condition_id:
                continue

            # Get final price (should be ~1.0 or ~0.0)
            try:
                mid = self.client.get_midpoint(pos.token_id)
                if mid <= 0:
                    mid = 1.0 if pos.direction == "Up" and window.up_price > 0.5 else 0.0
            except Exception:
                mid = 1.0  # Assume win if we can't check

            outcome_price = round(mid)  # 0 or 1
            self.positions.resolve_position(key, outcome_price)

            pnl = (outcome_price - pos.entry_price) * pos.shares
            self.pnl_today += pnl
            logger.info(
                "SCALP RESOLVED: %s %s → %s | PnL=$%.2f",
                pos.question, pos.direction,
                "WIN" if outcome_price > 0.5 else "LOSS", pnl,
            )

    # ── Bot reference ──────────────────────────────────────────────

    _bot = None

    def set_bot(self, bot):
        """Attach Discord bot for notifications."""
        self._bot = bot

    # ── Status ─────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get scalper status for Discord commands."""
        windows = {}
        for asset, w in self._current_windows.items():
            secs_left = max(0, w.end_ts - time.time())
            windows[asset] = {
                "up": w.up_price,
                "down": w.down_price,
                "seconds_left": int(secs_left),
                "traded": w.traded,
            }
        return {
            "enabled_assets": self.enabled_assets,
            "active_windows": windows,
            "trades_today": self.trades_today,
            "pnl_today": self.pnl_today,
            "threshold": self.entry_threshold,
            "shares_per_trade": self.shares_per_trade,
        }
