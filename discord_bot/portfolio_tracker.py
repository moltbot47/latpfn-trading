"""
Live portfolio tracker — posts periodic balance/P&L updates to Discord.

Updates both #polymarket-trading and #hyperliquid-portfolio channels
with accurate live data every N minutes. Uses pinned messages that
get edited in-place to avoid channel spam.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import discord
import requests

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Posts live portfolio updates to dedicated Discord channels."""

    def __init__(self, bot, config: dict):
        self.bot = bot
        self.config = config
        self.update_interval = 300  # 5 minutes

        # Channel IDs from env
        self.poly_channel_id = int(os.environ.get("POLYMARKET_DISCORD_CHANNEL_ID", 0))
        self.hl_channel_id = int(os.environ.get("HYPERLIQUID_DISCORD_CHANNEL_ID", 0))

        # Pinned message IDs (edit in place instead of spamming)
        self._poly_msg_id: Optional[int] = None
        self._hl_msg_id: Optional[int] = None

        # Polymarket addresses
        self._proxy = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")

    async def start(self):
        """Start the portfolio tracking loop."""
        await self.bot.wait_until_ready()
        logger.info("Portfolio tracker started (interval=%ds)", self.update_interval)

        # Initial post (wait for other systems to initialize)
        await asyncio.sleep(15)
        try:
            await self._update_all()
            logger.info("Portfolio tracker: initial update posted")
        except Exception as e:
            logger.error("Portfolio tracker initial update failed: %s", e, exc_info=True)

        while True:
            await asyncio.sleep(self.update_interval)
            try:
                await self._update_all()
            except Exception as e:
                logger.error("Portfolio tracker error: %s", e, exc_info=True)

    async def _update_all(self):
        """Update both portfolio channels."""
        try:
            await self._update_polymarket()
        except Exception as e:
            logger.error("Polymarket update failed: %s", e)
        try:
            await self._update_hyperliquid()
        except Exception as e:
            logger.error("Hyperliquid update failed: %s", e)

    # ── Polymarket Portfolio ───────────────────────────────────────

    async def _update_polymarket(self):
        """Fetch Polymarket data and post/update embed."""
        if not self.poly_channel_id:
            return

        channel = self.bot.get_channel(self.poly_channel_id)
        if not channel:
            return

        # Fetch portfolio data
        poly_orch = getattr(self.bot, "_polymarket_orchestrator", None)

        # CLOB balance
        usdc_balance = 0.0
        if poly_orch:
            try:
                if hasattr(poly_orch, 'client') and hasattr(poly_orch.client, '_client') and poly_orch.client._client:
                    usdc_balance = poly_orch.client.get_balance()
            except Exception as e:
                logger.debug("CLOB balance fetch failed: %s", e)

        # Data API portfolio value (run in thread to avoid blocking event loop)
        portfolio_value = 0.0
        positions_data = []
        if self._proxy:
            try:
                portfolio_value, positions_data = await asyncio.to_thread(
                    self._fetch_poly_data_api
                )
            except Exception as e:
                logger.debug("Poly data API error: %s", e)

        # Local tracker data
        local_deployed = 0.0
        local_realized = 0.0
        scalper_stats = {}
        if poly_orch:
            try:
                local_deployed = poly_orch.positions.total_deployed()
                local_realized = poly_orch.positions.total_realized_pnl()
                if hasattr(poly_orch, 'scalper'):
                    scalper_stats = poly_orch.scalper.get_status()
            except Exception as e:
                logger.debug("Local tracker data fetch failed: %s", e)

        total_value = portfolio_value + usdc_balance

        # Build embed
        embed = discord.Embed(
            title="Polymarket Portfolio",
            color=0x7B3FE4,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Balance",
            value=f"Cash: **${usdc_balance:.2f}**\nPortfolio: **${portfolio_value:.2f}**\nTotal: **${total_value:.2f}**",
            inline=True,
        )
        embed.add_field(
            name="P&L",
            value=f"Deployed: ${local_deployed:.2f}\nRealized: ${local_realized:+.2f}",
            inline=True,
        )

        if scalper_stats:
            embed.add_field(
                name="Scalper",
                value=f"Trades: {scalper_stats.get('trades_today', 0)}\nP&L: ${scalper_stats.get('pnl_today', 0):+.2f}",
                inline=True,
            )

        # Positions
        if positions_data:
            pos_lines = []
            for p in positions_data[:8]:
                title = p.get("title", p.get("question", "?"))[:40]
                outcome = p.get("outcome", "?")
                size = float(p.get("size", 0))
                cur = float(p.get("curPrice", 0))
                avg = float(p.get("avgPrice", 0))
                unrealized = (cur - avg) * size
                emoji = "+" if unrealized >= 0 else ""
                pos_lines.append(
                    f"`{outcome}` {title}\n"
                    f"  {size:.0f} sh @ ${avg:.2f} → ${cur:.2f} ({emoji}{unrealized:.2f})"
                )
            embed.add_field(
                name=f"Positions ({len(positions_data)})",
                value="\n".join(pos_lines) or "None",
                inline=False,
            )

        embed.set_footer(text="Updates every 5 min • Polymarket Trading System")

        await self._send_or_edit(channel, embed, "poly")

    def _fetch_poly_data_api(self):
        """Synchronous Polymarket Data API fetch (run in thread)."""
        portfolio_value = 0.0
        positions_data = []
        try:
            resp = requests.get(
                "https://data-api.polymarket.com/value",
                params={"user": self._proxy}, timeout=10,
            )
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                portfolio_value = float(data[0].get("value", 0))
        except Exception:
            pass
        try:
            resp = requests.get(
                "https://data-api.polymarket.com/positions",
                params={"user": self._proxy, "sizeThreshold": 0.01, "limit": 20},
                timeout=10,
            )
            positions_data = resp.json() or []
        except Exception:
            pass
        return portfolio_value, positions_data

    def _fetch_hl_data(self, hl_wallet: str):
        """Synchronous Hyperliquid API fetch (run in thread)."""
        hl_balance = 0.0
        hl_pnl = 0.0
        hl_positions = []
        try:
            resp = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "clearinghouseState", "user": hl_wallet},
                timeout=10,
            )
            data = resp.json()
            if "marginSummary" in data:
                hl_balance = float(data["marginSummary"].get("accountValue", 0))
                hl_pnl = float(data["marginSummary"].get("totalUnrealizedPnl", 0))
            if "assetPositions" in data:
                for ap in data["assetPositions"]:
                    pos = ap.get("position", {})
                    if float(pos.get("szi", 0)) != 0:
                        hl_positions.append({
                            "instrument": pos.get("coin", "?"),
                            "direction": "long" if float(pos.get("szi", 0)) > 0 else "short",
                            "entry_price": float(pos.get("entryPx", 0)),
                            "size": abs(float(pos.get("szi", 0))),
                            "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                        })
        except Exception as e:
            logger.debug("HL API error: %s", e)
        return hl_balance, hl_pnl, hl_positions

    # ── Hyperliquid Portfolio ──────────────────────────────────────

    async def _update_hyperliquid(self):
        """Fetch Hyperliquid data and post/update embed."""
        if not self.hl_channel_id:
            return

        channel = self.bot.get_channel(self.hl_channel_id)
        if not channel:
            return

        # Get Hyperliquid positions and balance from API
        hl_balance = 0.0
        hl_positions = []
        hl_pnl = 0.0

        hl_wallet = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")
        if hl_wallet:
            try:
                hl_balance, hl_pnl, hl_positions = await asyncio.to_thread(
                    self._fetch_hl_data, hl_wallet
                )
            except Exception as e:
                logger.debug("HL data fetch error: %s", e)

        embed = discord.Embed(
            title="Hyperliquid Portfolio",
            color=0x00BFFF,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Account",
            value=f"Balance: **${hl_balance:.2f}**\nUnrealized P&L: ${hl_pnl:+.2f}",
            inline=True,
        )

        # Open positions
        if hl_positions:
            pos_lines = []
            for p in hl_positions[:6]:
                inst = p.get("instrument", "?")
                direction = p.get("direction", "?")
                entry = p.get("entry_price", 0)
                upnl = p.get("unrealized_pnl", 0)
                size = p.get("size", 0)
                pos_lines.append(
                    f"**{inst}** {direction} {size}\n"
                    f"  Entry: ${entry:,.2f} | uPnL: ${upnl:+.2f}"
                )
            embed.add_field(
                name=f"Positions ({len(hl_positions)})",
                value="\n".join(pos_lines),
                inline=False,
            )
        else:
            embed.add_field(name="Positions", value="No open positions", inline=False)

        embed.set_footer(text="Updates every 5 min • Hyperliquid Trading System")

        await self._send_or_edit(channel, embed, "hl")

    # ── Message Management ─────────────────────────────────────────

    async def _send_or_edit(self, channel, embed, tracker_type: str):
        """Send a new message or edit the existing pinned one."""
        msg_id = self._poly_msg_id if tracker_type == "poly" else self._hl_msg_id

        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass  # Message was deleted, send new one

        # Send new message
        msg = await channel.send(embed=embed)

        if tracker_type == "poly":
            self._poly_msg_id = msg.id
        else:
            self._hl_msg_id = msg.id

        # Pin it so it stays at the top
        try:
            await msg.pin()
        except Exception:
            pass  # May not have pin permissions
