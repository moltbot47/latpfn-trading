"""
Discord bot for the LaT-PFN Trading System.

Runs alongside the trading loop — posts signals to the configured channel
and responds to slash commands for status, forecasts, and trade management.
"""

import asyncio
import logging
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
        self._signal_channel: Optional[discord.TextChannel] = None
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

    # ── Signal broadcasting ────────────────────────────────────────

    async def post_signal(self, instrument: str, signal, prediction: dict):
        """Post a trading signal to the channel."""
        if not self._signal_channel:
            return
        embed = signal_embed(instrument, signal, prediction)
        await self._signal_channel.send(embed=embed)

    async def post_execution(self, instrument: str, result: dict, signal):
        """Post order execution result."""
        if not self._signal_channel:
            return
        embed = execution_embed(instrument, result, signal)
        await self._signal_channel.send(embed=embed)

    async def post_risk_rejection(self, instrument: str, reason: str):
        """Post risk rejection notice."""
        if not self._signal_channel:
            return
        embed = risk_rejected_embed(instrument, reason)
        await self._signal_channel.send(embed=embed)

    async def post_cycle_summary(
        self,
        cycle: int,
        predictions: dict,
        positions: dict,
        account_equity: float,
        daily_pnl: float,
    ):
        """Post end-of-cycle summary."""
        if not self._signal_channel:
            return
        embed = cycle_summary_embed(cycle, predictions, positions, account_equity, daily_pnl)
        await self._signal_channel.send(embed=embed)


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
