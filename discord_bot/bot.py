"""
Discord bot for the LaT-PFN Trading System.

Runs alongside the trading loop — posts signals to the configured channel
and responds to slash commands for status, forecasts, and trade management.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.embeds import (
    signal_embed,
    execution_embed,
    risk_rejected_embed,
    cycle_summary_embed,
    status_embed,
    forecast_embed,
    radar_embed,
    trade_alert_content,
    execution_alert_content,
    sniper_plan_embed,
    sniper_result_embed,
    go_result_embed,
)

logger = logging.getLogger(__name__)


class TradingBot(commands.Bot):
    """Discord bot integrated with the LaT-PFN trading system."""

    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="LaT-PFN Automated Futures Trading Bot",
        )

        self.config = config
        self.signal_channel_id = int(
            config.get("discord", {}).get("channel_id", 0)
        )
        self.poly_channel_id = int(
            os.environ.get("POLYMARKET_DISCORD_CHANNEL_ID", 0)
        )
        self.hl_channel_id = int(
            os.environ.get("HYPERLIQUID_DISCORD_CHANNEL_ID", 0)
        )
        self.alert_role_id = config.get("discord", {}).get("alert_role_id", "")
        self._signal_channel: Optional[discord.TextChannel] = None
        self._poly_channel: Optional[discord.TextChannel] = None
        self._hl_channel: Optional[discord.TextChannel] = None
        self._trading_system = None  # set via set_trading_system()

    def set_trading_system(self, system):
        """Attach the trading system so commands can query it."""
        self._trading_system = system

    async def setup_hook(self):
        """Called when the bot is ready — sync slash commands."""
        self.tree.add_command(status_cmd)
        self.tree.add_command(positions_cmd)
        self.tree.add_command(forecast_cmd)
        self.tree.add_command(risk_cmd)
        self.tree.add_command(tiers_cmd)
        self.tree.add_command(close_cmd)
        self.tree.add_command(closeall_cmd)
        self.tree.add_command(performance_cmd)
        self.tree.add_command(daily_cmd)
        self.tree.add_command(stale_cmd)
        self.tree.add_command(sniper_cmd)
        self.tree.add_command(go_cmd)
        # Polymarket commands
        self.tree.add_command(poly_scan_cmd)
        self.tree.add_command(poly_go_cmd)
        self.tree.add_command(poly_positions_cmd)
        self.tree.add_command(poly_status_cmd)
        self.tree.add_command(poly_scalper_cmd)
        self.tree.add_command(poly_close_cmd)
        self.tree.add_command(poly_mc_status_cmd)
        self.tree.add_command(poly_turbo_cmd)
        await self.tree.sync()
        logger.info("Slash commands synced")

    async def on_ready(self):
        """Called when the bot has connected to Discord."""
        logger.info("Discord bot ready: %s (id=%s)", self.user.name, self.user.id)

        # Resolve signal channel
        if self.signal_channel_id:
            ch = self.get_channel(self.signal_channel_id)
            if ch is None:
                ch = await self.fetch_channel(self.signal_channel_id)
            self._signal_channel = ch
            logger.info("Signal channel: #%s (id=%d)", ch.name, ch.id)
        else:
            logger.warning("No discord.channel_id configured — signals won't be posted")

        # Resolve Polymarket channel
        if self.poly_channel_id:
            ch = self.get_channel(self.poly_channel_id)
            if ch is None:
                ch = await self.fetch_channel(self.poly_channel_id)
            self._poly_channel = ch
            logger.info("Polymarket channel: #%s (id=%d)", ch.name, ch.id)

        # Resolve Hyperliquid channel
        if self.hl_channel_id:
            ch = self.get_channel(self.hl_channel_id)
            if ch is None:
                ch = await self.fetch_channel(self.hl_channel_id)
            self._hl_channel = ch
            logger.info("Hyperliquid channel: #%s (id=%d)", ch.name, ch.id)

        # Post startup message
        if self._signal_channel:
            embed = discord.Embed(
                title="Trading Bot Online",
                description=(
                    f"Instruments: {', '.join(self._trading_system.instruments) if self._trading_system else 'N/A'}\n"
                    f"Mode: {self.config.get('execution', {}).get('mode', 'unknown')}"
                ),
                color=0x00CC00,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="LaT-PFN Trading System")
            await self._signal_channel.send(embed=embed)

        # Post Polymarket startup message
        if self._poly_channel:
            poly_cfg = self.config.get("polymarket", {})
            embed = discord.Embed(
                title="Polymarket Bot Online",
                description=(
                    f"Budget: ${poly_cfg.get('budget_usdc', 15.0):.2f}\n"
                    f"Strategies: Resolution Sniping + LLM Superforecaster\n"
                    f"Cycle: every {poly_cfg.get('cycle_minutes', 10)} min"
                ),
                color=0x7B3FE4,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Polymarket Trading System")
            await self._poly_channel.send(embed=embed)

    # ── Polymarket notifications ─────────────────────────────────

    async def post_poly_trade(self, trade: dict):
        """Post a Polymarket trade execution to the poly channel."""
        if not self._poly_channel:
            return
        embed = discord.Embed(
            title=f"POLY TRADE: {trade.get('direction', '?')} @ ${trade.get('entry_price', 0):.4f}",
            description=f"**{trade.get('question', '?')[:80]}**",
            color=0x00CC00,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Size", value=f"${trade.get('size_usdc', 0):.2f}", inline=True)
        embed.add_field(name="Edge", value=f"{trade.get('edge_pct', 0):.1f}%", inline=True)
        embed.add_field(name="Hours Left", value=f"{trade.get('hours_to_resolution', 0):.0f}h", inline=True)
        embed.set_footer(text="Polymarket Resolution Sniper")
        await self._poly_channel.send(embed=embed)

    async def post_poly_scan_summary(self, result: dict):
        """Post a scan cycle summary to the poly channel."""
        if not self._poly_channel:
            return
        snipes = result.get("snipe_candidates", [])
        executed = result.get("executed", [])
        exits = result.get("exits", [])

        desc_parts = [f"Markets: {result.get('markets_scanned', 0)}"]
        desc_parts.append(f"Snipe candidates: {len(snipes)}")
        desc_parts.append(f"Trades executed: {len(executed)}")
        if exits:
            desc_parts.append(f"Positions exited: {len(exits)}")

        embed = discord.Embed(
            title=f"Polymarket Cycle #{result.get('cycle', '?')}",
            description="\n".join(desc_parts),
            color=0x7B3FE4,
            timestamp=datetime.now(timezone.utc),
        )

        if snipes:
            top = snipes[0]
            embed.add_field(
                name="Top Candidate",
                value=f"YES ${top['yes_price']:.2f} | edge {top['edge_pct']:.1f}% | {top['hours_to_resolution']:.0f}h\n`{top['question'][:55]}`",
                inline=False,
            )

        embed.set_footer(text="Polymarket Trading System")
        await self._poly_channel.send(embed=embed)

    async def post_poly_exit(self, exit_info: dict):
        """Post a position exit notification."""
        if not self._poly_channel:
            return
        pnl = exit_info.get("pnl", 0)
        color = 0x00CC00 if pnl >= 0 else 0xFF4444
        embed = discord.Embed(
            title=f"POLY EXIT: P&L ${pnl:+.4f}",
            description=f"Exit @ ${exit_info.get('exit_price', 0):.4f}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Polymarket Trading System")
        await self._poly_channel.send(embed=embed)

    async def post_poly_claim(self, claim: dict):
        """Post auto-claim notification when resolved positions are redeemed."""
        if not self._poly_channel:
            return
        usdc = claim.get("usdc_received", 0)
        embed = discord.Embed(
            title=f"AUTO-CLAIM: +${usdc:.2f} USDC",
            description=(
                f"**{claim.get('question', 'Unknown')[:80]}**\n"
                f"Positions resolved: {claim.get('positions_resolved', 0)}\n"
                f"TX: `{claim.get('tx_hash', '?')[:16]}...`"
            ),
            color=0x00AAFF,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Polymarket Auto-Claim")
        await self._poly_channel.send(embed=embed)

    # ── Signal broadcasting ────────────────────────────────────────

    def _contract_size(self, instrument: str) -> float:
        """Get contract size for an instrument from config."""
        return self.config.get("instruments", {}).get(instrument, {}).get("contract_size", 1)

    async def post_signal(self, instrument: str, signal, prediction: dict):
        """Post a trading signal to the channel with @mention alert."""
        if not self._signal_channel:
            return
        # @mention alert text (triggers push notifications)
        content = trade_alert_content(instrument, signal, self.alert_role_id or None)
        embed = signal_embed(instrument, signal, prediction, self._contract_size(instrument))
        await self._signal_channel.send(content=content, embed=embed)

    async def post_execution(self, instrument: str, result: dict, signal):
        """Post order execution result with @mention alert."""
        if not self._signal_channel:
            return
        content = execution_alert_content(instrument, result, self.alert_role_id or None)
        embed = execution_embed(instrument, result, signal, self._contract_size(instrument))
        await self._signal_channel.send(content=content, embed=embed)

    async def post_risk_rejection(self, instrument: str, reason: str):
        """Post risk rejection notice — suppressed to reduce channel noise."""
        logger.debug("Risk rejection suppressed from Discord: %s — %s", instrument, reason)
        return

    async def post_radar(self, radar_items: list):
        """Post pre-trade radar — suppressed to reduce channel noise."""
        return

    async def post_cycle_summary(
        self,
        cycle: int,
        predictions: dict,
        positions: dict,
        account_equity: float,
        daily_pnl: float,
        drawdown_status: dict | None = None,
    ):
        """Post cycle summary — only posts on drawdown warnings now."""
        if not self._signal_channel:
            return
        # Only post if cushion is dangerously low (<20%)
        if drawdown_status and drawdown_status["at_risk"]:
            mention = f"<@&{self.alert_role_id}>" if self.alert_role_id else "@here"
            content = (
                f"{mention} **DRAWDOWN WARNING** — "
                f"Cushion: ${drawdown_status['cushion']:,.2f} "
                f"({drawdown_status['cushion_pct']:.0f}%) "
                f"Floor: ${drawdown_status['drawdown_floor']:,.2f}"
            )
            embed = cycle_summary_embed(
                cycle, predictions, positions, account_equity, daily_pnl, drawdown_status
            )
            await self._signal_channel.send(content=content, embed=embed)


# ── Global bot instance (set by run_bot) ──────────────────────────

_bot_instance: Optional[TradingBot] = None


def get_bot() -> Optional[TradingBot]:
    return _bot_instance


# ── Slash Commands ────────────────────────────────────────────────


@app_commands.command(name="status", description="Show trading system status")
async def status_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    embed = status_embed(
        is_running=ts.is_running,
        cycle=ts.cycle,
        instruments=ts.instruments,
        account_equity=ts.account_equity,
        positions=ts.order_mgr.open_positions,
        daily_pnl=ts.order_mgr.realized_pnl_today,
        exec_mode=ts.config.get("execution", {}).get("mode", "unknown"),
    )
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="positions", description="Show open positions")
async def positions_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    positions = ts.order_mgr.open_positions

    if not positions:
        await interaction.response.send_message("No open positions.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Open Positions",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc),
    )

    for inst, pos in positions.items():
        dir_emoji = "\U0001F7E2" if pos.direction == "long" else "\U0001F534"
        embed.add_field(
            name=f"{dir_emoji} {inst}",
            value=(
                f"**{pos.direction.upper()}** {pos.size} contracts\n"
                f"Entry: ${pos.entry_price:,.2f}\n"
                f"SL: ${pos.stop_loss:,.2f}  TP: ${pos.take_profit:,.2f}"
            ),
            inline=True,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="forecast", description="Run on-demand forecast for an instrument")
@app_commands.describe(instrument="Instrument to forecast (MYM, MNQ, MGC)")
@app_commands.choices(instrument=[
    app_commands.Choice(name="MYM (Micro Dow)", value="MYM"),
    app_commands.Choice(name="MNQ (Micro Nasdaq)", value="MNQ"),
    app_commands.Choice(name="MGC (Micro Gold)", value="MGC"),
])
async def forecast_cmd(interaction: discord.Interaction, instrument: str):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    if instrument not in ts.instruments:
        await interaction.response.send_message(
            f"Unknown instrument: {instrument}. Available: {', '.join(ts.instruments)}",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        # Fetch data and predict
        data = ts.data_pipeline.get_prediction_data(instrument)
        prediction = ts.model.predict(
            heldout_df=data["heldout_df"],
            context_dfs=data["context_dfs"],
        )

        embed = forecast_embed(instrument, prediction)

        # Also run signal generation to show what tier it would be
        signal = ts.signal_gen.generate(instrument, prediction)
        if signal:
            tier_label = signal.shot_type.replace("_", " ").title()
            embed.add_field(
                name="Signal",
                value=f"**{tier_label}** — {signal.direction.upper()} @ ${signal.entry_price:,.2f}",
                inline=False,
            )
            embed.add_field(name="SL", value=f"${signal.stop_loss:,.2f}", inline=True)
            embed.add_field(name="TP", value=f"${signal.take_profit:,.2f}", inline=True)
        else:
            embed.add_field(name="Signal", value="No trade (below threshold)", inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error("Forecast command error: %s", e, exc_info=True)
        await interaction.followup.send(f"Forecast failed: {e}")


@app_commands.command(name="risk", description="Show risk manager state")
async def risk_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    rm = ts.risk_mgr
    rc = ts.config["risk"]

    embed = discord.Embed(
        title="Risk Manager Status",
        color=0xFF8C00,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Account Equity", value=f"${rm.current_equity:,.2f}", inline=True)
    embed.add_field(name="Starting Equity", value=f"${rm.starting_equity:,.2f}", inline=True)
    embed.add_field(name="Realized P&L Today", value=f"${rm.realized_pnl_today:+,.2f}", inline=True)

    embed.add_field(name="Max Risk/Trade", value=f"{rc['max_risk_per_trade_pct']}%", inline=True)
    embed.add_field(name="Max Daily Loss", value=f"{rc['max_daily_loss_pct']}%", inline=True)
    embed.add_field(name="Max Drawdown", value=f"{rc['max_drawdown_pct']}%", inline=True)

    embed.add_field(name="Max Contracts", value=str(rc['max_position_size_contracts']), inline=True)
    embed.add_field(name="Max Concurrent", value=str(rc['max_concurrent_positions']), inline=True)
    embed.add_field(
        name="Open Positions",
        value=str(ts.order_mgr.open_count),
        inline=True,
    )

    # Prop firm limits
    pf = rc.get("prop_firm", {})
    if pf:
        embed.add_field(
            name="Prop Firm Limits",
            value=(
                f"Daily Loss: ${pf.get('max_daily_loss_usd', 'N/A'):,}\n"
                f"Total Drawdown: ${pf.get('max_total_drawdown_usd', 'N/A'):,}"
            ),
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Risk Manager")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="tiers", description="Show NBA shot-tier configuration")
async def tiers_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    tiers = bot._trading_system.config.get("shot_tiers", {})

    embed = discord.Embed(
        title="NBA Shot-Tier Classification",
        description="Trade sizing based on confidence level",
        color=0x9B59B6,
        timestamp=datetime.now(timezone.utc),
    )

    for tier_name, params in tiers.items():
        enabled = params.get("enabled", False)
        status = "" if enabled else " (disabled)"
        label = params.get("label", tier_name)

        embed.add_field(
            name=f"{label}{status}",
            value=(
                f"Min Confidence: {params['confidence_min']:.0%}\n"
                f"Target: {params['target_multiplier']}x | Stop: {params['stop_multiplier']}x\n"
                f"Size: {params['size_multiplier']}x | Min R:R: {params['min_reward_risk']}:1"
            ),
            inline=True,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="close", description="Close a specific position via webhook")
@app_commands.describe(symbol="Symbol to close (e.g. MNQ, MYM, MGC)")
@app_commands.choices(symbol=[
    app_commands.Choice(name="MNQ (Micro Nasdaq)", value="MNQ"),
    app_commands.Choice(name="MYM (Micro Dow)", value="MYM"),
    app_commands.Choice(name="MGC (Micro Gold)", value="MGC"),
])
async def close_cmd(interaction: discord.Interaction, symbol: str):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    if not ts.executor:
        await interaction.response.send_message("No executor connected (dry_run mode).", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    try:
        result = await ts.executor.close_position(symbol)
        if result:
            ts.order_mgr.remove_position(symbol)
            embed = discord.Embed(
                title=f"Position Closed: {symbol}",
                description="Close webhook sent to PickMyTrade",
                color=0x00CC00,
                timestamp=datetime.now(timezone.utc),
            )
        else:
            embed = discord.Embed(
                title=f"Close Failed: {symbol}",
                description="Webhook did not return success",
                color=0xCC0000,
                timestamp=datetime.now(timezone.utc),
            )
        embed.set_footer(text="LaT-PFN Trading System")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Close failed: {e}")


@app_commands.command(name="poly_scalper", description="Crypto scalper status — 5-min binary markets")
async def poly_scalper_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    status = poly_orch.scalper.get_status()
    lines = [
        "**Crypto Scalper Status**",
        f"Assets: {', '.join(a.upper() for a in status['enabled_assets'])}  |  "
        f"Threshold: {status['threshold']:.0%}  |  "
        f"Shares/trade: {status['shares_per_trade']}",
        f"Trades today: {status['trades_today']}  |  P&L today: ${status['pnl_today']:+.2f}",
    ]

    windows = status.get("active_windows", {})
    if windows:
        lines.append("\n**Active Windows:**")
        for asset, w in windows.items():
            lines.append(
                f"> **{asset.upper()}**  Up={w['up']:.2f} Down={w['down']:.2f}  "
                f"{w['seconds_left']}s left  {'(traded)' if w['traded'] else ''}"
            )
    else:
        lines.append("No active windows.")

    await interaction.response.send_message("\n".join(lines))


@app_commands.command(name="closeall", description="Close ALL open positions immediately")
async def closeall_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    if not ts.executor:
        await interaction.response.send_message("No executor connected (dry_run mode).", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    try:
        await ts.executor.flatten_position()
        ts.order_mgr.close_all()
        embed = discord.Embed(
            title="All Positions Closed",
            description="Flatten webhook sent for all symbols",
            color=0x00CC00,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="LaT-PFN Trading System")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Flatten failed: {e}")


@app_commands.command(name="performance", description="Show per-tier performance stats (last 30 days)")
async def performance_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    tier_stats = ts.trade_logger.get_tier_stats(days=30)

    if not tier_stats:
        await interaction.response.send_message("No trade data available for the last 30 days.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Tier Performance (30 Days)",
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc),
    )

    for tier_name, stats in tier_stats.items():
        label = tier_name.replace("_", " ").title()
        pf_display = (
            f"{stats['profit_factor']:.2f}"
            if stats["profit_factor"] != float("inf")
            else "Inf"
        )
        embed.add_field(
            name=label,
            value=(
                f"Trades: {stats['count']}  |  "
                f"Win Rate: {stats['win_rate']:.0%}\n"
                f"Total P&L: ${stats['total_pnl']:+,.2f}  |  "
                f"Avg P&L: ${stats['avg_pnl']:+,.2f}\n"
                f"Profit Factor: {pf_display}  |  "
                f"Expectancy: ${stats['expectancy']:+,.2f}"
            ),
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="daily", description="Show today's trading summary")
async def daily_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    summary = ts.trade_logger.get_daily_summary()

    if not summary:
        await interaction.response.send_message("No trade data available for today.", ephemeral=True)
        return

    pnl_color = 0x2ECC71 if summary["total_pnl"] >= 0 else 0xE74C3C

    embed = discord.Embed(
        title=f"Daily Summary — {summary['date']}",
        color=pnl_color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Trades", value=str(summary["trade_count"]), inline=True)
    embed.add_field(name="Executed", value=str(summary["executed_count"]), inline=True)
    embed.add_field(name="Win Rate", value=f"{summary['win_rate']:.0%}", inline=True)

    embed.add_field(name="Wins", value=str(summary["win_count"]), inline=True)
    embed.add_field(name="Losses", value=str(summary["loss_count"]), inline=True)
    embed.add_field(name="Total P&L", value=f"${summary['total_pnl']:+,.2f}", inline=True)

    embed.add_field(name="Best Trade", value=f"${summary['best_trade']:+,.2f}", inline=True)
    embed.add_field(name="Worst Trade", value=f"${summary['worst_trade']:+,.2f}", inline=True)
    embed.add_field(name="Avg R:R", value=f"{summary['avg_rr']:.2f}", inline=True)

    # Per-tier breakdown
    by_tier = summary.get("by_tier", {})
    if by_tier:
        tier_lines = []
        for tier_name, tier_data in by_tier.items():
            label = tier_name.replace("_", " ").title()
            wr = f"{tier_data.get('win_rate', 0):.0%}"
            tier_lines.append(
                f"**{label}**: {tier_data['count']} trades, "
                f"{wr} win rate, ${tier_data['pnl']:+,.2f}"
            )
        embed.add_field(
            name="By Tier",
            value="\n".join(tier_lines) if tier_lines else "N/A",
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="stale", description="List positions open longer than 24 hours")
async def stale_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system
    positions = ts.order_mgr.open_positions

    if not positions:
        await interaction.response.send_message("No open positions.", ephemeral=True)
        return

    now = datetime.now()
    stale_threshold_hours = 24
    stale_entries = []

    for inst, pos in positions.items():
        entry_time = getattr(pos, "entry_time", None)
        if entry_time is None:
            continue
        age_hours = (now - entry_time).total_seconds() / 3600.0
        if age_hours > stale_threshold_hours:
            stale_entries.append((inst, pos, age_hours))

    if not stale_entries:
        await interaction.response.send_message(
            "No stale positions (all open < 24 hours).", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Stale Positions (> 24 hours)",
        color=0xFF4500,
        timestamp=datetime.now(timezone.utc),
    )

    for inst, pos, age_hours in stale_entries:
        dir_emoji = "\U0001F7E2" if pos.direction == "long" else "\U0001F534"
        embed.add_field(
            name=f"{dir_emoji} {inst}",
            value=(
                f"**{pos.direction.upper()}** {pos.size} contracts\n"
                f"Entry: ${pos.entry_price:,.2f}\n"
                f"Opened: {pos.entry_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"Age: **{age_hours:.1f} hours**"
            ),
            inline=True,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    await interaction.response.send_message(embed=embed)


@app_commands.command(name="sniper", description="Sniper Mode — scan top pairs and enter positions aggressively")
async def sniper_cmd(interaction: discord.Interaction):
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message("Trading system not connected.", ephemeral=True)
        return

    ts = bot._trading_system

    if not ts.is_hyperliquid:
        await interaction.response.send_message(
            "Sniper mode is only available in Hyperliquid mode.", ephemeral=True
        )
        return

    if not ts.executor:
        await interaction.response.send_message(
            "No executor connected (dry_run mode). Sniper requires live execution.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        from signals.sniper import scan_sniper_candidates, SNIPER_MAX_POSITIONS

        # Check how many sniper slots are available
        open_count = ts.order_mgr.open_count
        max_pos = ts.config["risk"].get("max_concurrent_positions", 6)
        available = min(SNIPER_MAX_POSITIONS, max_pos - open_count)

        if available <= 0:
            await interaction.followup.send(
                f"No position slots available ({open_count}/{max_pos} open). "
                f"Close a position first with /close or /closeall."
            )
            return

        # Fetch current balance
        balance = await ts.executor.get_cash_balance()
        if balance <= 0:
            balance = ts.account_equity

        # Scan for candidates
        candidates = await scan_sniper_candidates(ts)

        if not candidates:
            await interaction.followup.send(
                "No sniper candidates found. All pairs below minimum confidence (15%) "
                "or already have open positions."
            )
            return

        # Show the plan embed
        embed = sniper_plan_embed(candidates, balance)
        msg = await interaction.followup.send(embed=embed, wait=True)

        # Add reaction buttons
        await msg.add_reaction("\u2705")  # checkmark
        await msg.add_reaction("\u274C")  # X

        # Wait for user reaction (15s timeout)
        def check(reaction, user):
            return (
                user == interaction.user
                and str(reaction.emoji) in ("\u2705", "\u274C")
                and reaction.message.id == msg.id
            )

        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=15.0, check=check)
        except asyncio.TimeoutError:
            await msg.edit(
                embed=discord.Embed(
                    title="\U0001F3AF Sniper Mode \u2014 Timed Out",
                    description="No response in 15 seconds. Sniper cancelled.",
                    color=0x808080,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            return

        if str(reaction.emoji) == "\u274C":
            await msg.edit(
                embed=discord.Embed(
                    title="\U0001F3AF Sniper Mode \u2014 Cancelled",
                    description="User cancelled sniper execution.",
                    color=0x808080,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            return

        # Execute top N candidates
        to_execute = candidates[:available]
        results = []

        for candidate in to_execute:
            try:
                order_result = await ts.executor.place_bracket_order(
                    symbol=candidate.instrument,
                    direction=candidate.direction,
                    quantity=candidate.position_size,
                    entry_price=candidate.entry_price,
                    stop_price=candidate.stop_loss,
                    target_price=candidate.take_profit,
                )

                if order_result and "orderId" in order_result:
                    # Track position locally
                    from execution.order_manager import Position
                    ts.order_mgr.add_position(Position(
                        instrument=candidate.instrument,
                        direction=candidate.direction,
                        size=candidate.position_size,
                        entry_price=candidate.entry_price,
                        stop_loss=candidate.stop_loss,
                        take_profit=candidate.take_profit,
                        order_id=order_result.get("orderId"),
                    ))

                results.append({
                    "candidate": candidate,
                    "order_result": order_result,
                })
            except Exception as e:
                logger.error("Sniper execution failed for %s: %s", candidate.instrument, e)
                results.append({
                    "candidate": candidate,
                    "order_result": None,
                    "error": str(e),
                })

        # Refresh balance after execution
        try:
            new_balance = await ts.executor.get_cash_balance()
            if new_balance > 0:
                ts.account_equity = new_balance
                balance = new_balance
        except Exception:
            pass

        # Post result embed
        result_embed = sniper_result_embed(results, balance)
        await msg.edit(embed=result_embed)

    except Exception as e:
        logger.error("Sniper command error: %s", e, exc_info=True)
        await interaction.followup.send(f"Sniper failed: {e}")


@app_commands.command(
    name="go",
    description="HOT ENTRY — scan all pairs and immediately execute best signals",
)
@app_commands.describe(
    max_trades="Max trades to execute (default 2)",
)
async def go_cmd(interaction: discord.Interaction, max_trades: int = 2):
    """
    Immediate market entry based on current momentum and directional trend.

    Runs the full microstructure pipeline (model + orderbook + sentiment +
    regime + calibration + trend filter) on all instruments, ranks the
    results, and IMMEDIATELY EXECUTES the top signals. No confirmation
    needed — this is the hot button.
    """
    bot = get_bot()
    if not bot or not bot._trading_system:
        await interaction.response.send_message(
            "Trading system not connected.", ephemeral=True
        )
        return

    ts = bot._trading_system

    if not ts.is_hyperliquid:
        await interaction.response.send_message(
            "/go is only available in Hyperliquid mode.", ephemeral=True
        )
        return

    if not ts.executor:
        await interaction.response.send_message(
            "No executor connected (dry_run mode). /go requires live execution.",
            ephemeral=True,
        )
        return

    max_trades = max(1, min(max_trades, 4))  # clamp to 1-4

    # Check available slots
    max_pos = ts.config["risk"].get("max_concurrent_positions", 6)
    available = max_pos - ts.order_mgr.open_count
    if available <= 0:
        await interaction.response.send_message(
            f"No position slots available ({ts.order_mgr.open_count}/{max_pos} open). "
            f"Close a position first with /close or /closeall.",
            ephemeral=True,
        )
        return

    # Defer — this takes 15-30s to scan all pairs
    await interaction.response.defer(thinking=True)

    try:
        # Run the full scan + execute pipeline
        result = await ts.force_scan_and_execute(max_trades=max_trades)

        # Build and send the result embed
        embed = go_result_embed(result)

        # If we executed trades, @mention for notification
        content = None
        if result["executed"]:
            mention = (
                f"<@&{bot.alert_role_id}>" if bot.alert_role_id else "@here"
            )
            n = len(result["executed"])
            coins = ", ".join(e["instrument"] for e in result["executed"])
            content = f"{mention} **HOT ENTRY** — {n} trade{'s' if n > 1 else ''} executed: {coins}"

        await interaction.followup.send(content=content, embed=embed)

    except Exception as e:
        logger.error("GO command error: %s", e, exc_info=True)
        await interaction.followup.send(f"/go failed: {e}")


# ── Polymarket commands ──────────────────────────────────────────────

def _get_poly_orch(bot):
    """Get the Polymarket orchestrator, or None if not available/connected."""
    if not bot:
        return None
    orch = getattr(bot, "_polymarket_orchestrator", None)
    if not orch:
        return None
    # Check that the CLOB client is connected (Bug 9 fix)
    if not orch.client._client:
        return None
    return orch


@app_commands.command(name="poly_scan", description="Scan Polymarket for snipe + divergence candidates")
async def poly_scan_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message(
            "Polymarket not connected. Wait for it to initialize or check credentials.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        result = await poly_orch.force_scan()

        lines = [f"**Polymarket Scan** (cycle #{result.get('cycle', '?')})"]
        lines.append(f"Markets scanned: {result.get('markets_scanned', 0)}")
        lines.append("")

        snipes = result.get("snipe_candidates", [])
        if snipes:
            lines.append(f"**Resolution Snipe Candidates ({len(snipes)})**")
            for s in snipes[:5]:
                lines.append(
                    f"> YES=${s['yes_price']:.2f}  edge={s['edge_pct']:.1f}%  "
                    f"hrs={s['hours_to_resolution']:.0f}  `{s['question'][:55]}`"
                )
        else:
            lines.append("No snipe candidates found.")

        divs = result.get("divergence_candidates", [])
        if divs:
            lines.append(f"\n**LLM Divergence Candidates ({len(divs)})**")
            for d in divs[:5]:
                lines.append(
                    f"> {d['direction']} LLM={d['llm_probability']:.2f} vs "
                    f"mkt={d['market_yes_price']:.2f}  "
                    f"div={d['divergence']:+.2f}  `{d['question'][:50]}`"
                )
        else:
            lines.append("\nNo divergence candidates found.")

        executed = result.get("executed", [])
        if executed:
            lines.append(f"\n**Executed: {len(executed)} trades**")
            for t in executed:
                lines.append(
                    f"> {t.get('direction', '?')} `{t.get('question', '?')[:45]}`  "
                    f"${t.get('size_usdc', 0):.2f}"
                )

        await interaction.followup.send("\n".join(lines))
    except Exception as e:
        logger.error("poly_scan error: %s", e, exc_info=True)
        await interaction.followup.send(f"Scan failed: {e}")


@app_commands.command(name="poly_go", description="Execute best Polymarket candidates now")
async def poly_go_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message(
            "Polymarket not connected. Wait for it to initialize or check credentials.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        result = await poly_orch.force_execute()

        executed = result.get("executed", [])
        if executed:
            lines = [f"**Polymarket /go — {len(executed)} trades executed**"]
            for t in executed:
                lines.append(
                    f"> {t.get('direction', '?')} @ ${t.get('entry_price', 0):.4f}  "
                    f"${t.get('size_usdc', 0):.2f}  `{t.get('question', '')[:50]}`"
                )
            await interaction.followup.send("\n".join(lines))
        else:
            errors = result.get("errors", [])
            blocked = result.get("blocked_reason", "")
            msg = "No trades executed."
            if blocked:
                msg += f"\nBlocked: {blocked}"
            if errors:
                msg += f"\nErrors: {'; '.join(str(e) for e in errors)}"
            await interaction.followup.send(msg)
    except Exception as e:
        logger.error("poly_go error: %s", e, exc_info=True)
        await interaction.followup.send(f"/poly_go failed: {e}")


@app_commands.command(name="poly_positions", description="Show open Polymarket positions")
async def poly_positions_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    positions = poly_orch.positions.get_open_positions()
    if not positions:
        await interaction.response.send_message("No open Polymarket positions.", ephemeral=True)
        return

    lines = [f"**Polymarket Positions ({len(positions)} open)**"]
    for key, pos in positions.items():
        lines.append(
            f"> [{pos.strategy}] **{pos.direction}** @ ${pos.entry_price:.4f}  "
            f"${pos.size_usdc:.2f} ({pos.shares:.1f} shares)\n"
            f">   `{pos.question[:55]}`"
        )

    deployed = poly_orch.positions.total_deployed()
    realized = poly_orch.positions.total_realized_pnl()
    lines.append(f"\nDeployed: ${deployed:.2f}  |  Realized P&L: ${realized:+.2f}")

    await interaction.response.send_message("\n".join(lines))


@app_commands.command(name="poly_status", description="Polymarket bot status and risk summary")
async def poly_status_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    status = poly_orch.get_status()
    lines = [
        "**Polymarket Status**",
        f"Running: {'Yes' if status['running'] else 'No'}  |  Cycle: {status['cycle']}  |  Last scan: {status['last_scan_age']}",
        f"Budget: ${status['budget']:.2f}  |  Deployed: ${status['deployed']:.2f}  |  Available: ${status['available']:.2f}",
        f"Exposure: {status['exposure_pct']:.0f}%  |  Positions: {status['open_positions']}/{status['max_positions']}",
        f"Daily P&L: ${status['daily_pnl']:+.2f}  |  Total Realized: ${status['total_realized_pnl']:+.2f}",
    ]

    fc = status.get("forecast_stats", {})
    if fc:
        brier = fc.get("brier_score")
        lines.append(
            f"Forecasts: {fc.get('total_forecasts', 0)} total, "
            f"{fc.get('resolved', 0)} resolved"
            + (f"  |  Brier: {brier:.4f}" if brier is not None else "")
        )

    await interaction.response.send_message("\n".join(lines))


@app_commands.command(name="poly_close", description="Close a Polymarket position by market ID prefix")
@app_commands.describe(market_prefix="First few characters of the market ID or question")
async def poly_close_cmd(interaction: discord.Interaction, market_prefix: str):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    # Find matching position
    open_pos = poly_orch.positions.get_open_positions()
    match_key = None
    for key, pos in open_pos.items():
        if (market_prefix.lower() in pos.market_id.lower() or
            market_prefix.lower() in pos.question.lower()):
            match_key = key
            break

    if not match_key:
        await interaction.followup.send(f"No open position matching '{market_prefix}'")
        return

    pos = poly_orch.positions.positions[match_key]
    try:
        mid = poly_orch.client.get_midpoint(pos.token_id)
        if mid <= 0:
            mid = pos.entry_price

        result = poly_orch.client.sell_market(pos.token_id, pos.shares)
        realized_pnl = (mid - pos.entry_price) * pos.shares
        poly_orch.positions.close_position(match_key, mid, realized_pnl)
        poly_orch.risk.record_pnl(realized_pnl)

        await interaction.followup.send(
            f"Closed: **{pos.direction}** `{pos.question[:50]}`\n"
            f"Entry: ${pos.entry_price:.4f} → Exit: ${mid:.4f}  |  "
            f"P&L: ${realized_pnl:+.4f}"
        )
    except Exception as e:
        await interaction.followup.send(f"Close failed: {e}")


@app_commands.command(name="poly_mc_status", description="Max Concurrent strategy status")
async def poly_mc_status_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    mc = poly_orch.max_concurrent_strategy
    mc_positions = poly_orch.positions.get_positions_by_strategy("max_concurrent")

    mc_deployed = sum(p.size_usdc for p in mc_positions.values())
    mc_pnl = sum(
        p.realized_pnl for p in poly_orch.positions.positions.values()
        if p.strategy == "max_concurrent" and p.status in ("closed", "resolved")
    )

    lines = [
        "**Max Concurrent Strategy**",
        f"Positions: {len(mc_positions)}/{mc.max_positions}  |  Budget: ${mc.budget:.2f}",
        f"Deployed: ${mc_deployed:.2f}  |  Realized P&L: ${mc_pnl:+.2f}",
        f"Settings: ${mc.bet_size}/bet  |  {mc.min_divergence:.0%} min div  |  {mc.exit_hours}h exit",
    ]

    # Top 5 open positions by divergence
    if mc_positions:
        sorted_pos = sorted(
            mc_positions.items(),
            key=lambda kv: abs(kv[1].llm_probability - kv[1].market_probability),
            reverse=True,
        )[:5]
        lines.append("\n**Top positions:**")
        for key, pos in sorted_pos:
            div = pos.llm_probability - pos.market_probability
            lines.append(
                f"  {pos.direction} `{pos.question[:45]}` @ {pos.entry_price:.2f} "
                f"(div {div:+.2f})"
            )

    await interaction.response.send_message("\n".join(lines))


@app_commands.command(name="poly_turbo", description="Turbo LLM strategy status")
async def poly_turbo_cmd(interaction: discord.Interaction):
    bot = get_bot()
    poly_orch = _get_poly_orch(bot)
    if not poly_orch:
        await interaction.response.send_message("Polymarket not connected.", ephemeral=True)
        return

    ts = poly_orch.turbo.get_status()
    turbo_positions = poly_orch.positions.get_positions_by_strategy("turbo")

    turbo_pnl = sum(
        p.realized_pnl for p in poly_orch.positions.positions.values()
        if p.strategy == "turbo" and p.status in ("closed", "resolved")
    )

    lines = [
        f"**Turbo LLM Strategy** {'ON' if ts['running'] else 'OFF'}",
        f"Cycle: {ts['cycle']}  |  Positions: {ts['positions']}/{ts['max_positions']}",
        f"Deployed: ${ts['deployed']}  |  Session P&L: ${ts['session_pnl']:+.4f}",
        f"Total Realized P&L: ${turbo_pnl:+.2f}",
        f"Trades: {ts['session_trades']}  |  Exits: {ts['session_exits']}",
        f"Settings: ${ts['bet_size']}/bet  |  {ts['exit_minutes']}min exit  |  {ts['cycle_seconds']}s cycle",
    ]

    if turbo_positions:
        sorted_pos = sorted(
            turbo_positions.items(),
            key=lambda kv: abs(kv[1].llm_probability - kv[1].market_probability),
            reverse=True,
        )[:5]
        lines.append("\n**Top positions:**")
        for key, pos in sorted_pos:
            div = pos.llm_probability - pos.market_probability
            lines.append(
                f"  {pos.direction} `{pos.question[:45]}` @ {pos.entry_price:.2f} "
                f"(div {div:+.2f})"
            )

    await interaction.response.send_message("\n".join(lines))
