"""
Discord embed builders for trading signals, status, and forecasts.
"""

import discord
from datetime import datetime, timezone


# Shot tier colors (Discord embed hex)
TIER_COLORS = {
    "layup": 0x00FF00,        # bright green
    "short_range": 0x7CFC00,  # lawn green
    "free_throw": 0xFFD700,   # gold
    "three_pointer": 0xFF8C00, # dark orange
    "half_court": 0xFF4500,   # orange red
    "hail_mary": 0xFF0000,    # red
    "no_trade": 0x808080,     # gray
}

DIRECTION_COLORS = {
    "long": 0x00CC00,
    "short": 0xCC0000,
    "neutral": 0x808080,
}


def signal_embed(instrument: str, signal, prediction: dict) -> discord.Embed:
    """Build a rich embed for a trading signal."""
    dir_emoji = "\U0001F7E2" if signal.direction == "long" else "\U0001F534"
    tier_label = signal.shot_type.replace("_", " ").title()
    color = TIER_COLORS.get(signal.shot_type, 0x808080)

    embed = discord.Embed(
        title=f"{dir_emoji} {instrument} {signal.direction.upper()} Signal",
        description=f"**{tier_label}** — Confidence: {signal.confidence:.1%}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
    embed.add_field(name="Stop Loss", value=f"${signal.stop_loss:,.2f}", inline=True)
    embed.add_field(name="Take Profit", value=f"${signal.take_profit:,.2f}", inline=True)
    embed.add_field(name="Contracts", value=str(signal.position_size), inline=True)
    embed.add_field(name="Regime", value=signal.regime.title(), inline=True)

    # Risk/reward
    risk_pts = abs(signal.entry_price - signal.stop_loss)
    reward_pts = abs(signal.take_profit - signal.entry_price)
    rr = reward_pts / risk_pts if risk_pts > 0 else 0
    embed.add_field(name="R:R", value=f"{rr:.1f}:1", inline=True)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def execution_embed(instrument: str, result: dict, signal) -> discord.Embed:
    """Build embed for order execution result."""
    if result and "orderId" in result:
        embed = discord.Embed(
            title=f"Order Placed: {instrument}",
            description=f"{signal.direction.upper()} {signal.position_size} contracts via PickMyTrade",
            color=0x00CC00,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Order ID", value=str(result["orderId"]), inline=True)
        embed.add_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
        embed.add_field(name="SL / TP", value=f"${signal.stop_loss:,.2f} / ${signal.take_profit:,.2f}", inline=True)
    else:
        embed = discord.Embed(
            title=f"Order Failed: {instrument}",
            description="Webhook did not return a valid order ID",
            color=0xCC0000,
            timestamp=datetime.now(timezone.utc),
        )
    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def risk_rejected_embed(instrument: str, reason: str) -> discord.Embed:
    """Build embed for a risk-rejected signal."""
    embed = discord.Embed(
        title=f"Signal Rejected: {instrument}",
        description=reason,
        color=0xFF8C00,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Risk Manager")
    return embed


def cycle_summary_embed(
    cycle: int,
    predictions: dict,
    positions: dict,
    account_equity: float,
    daily_pnl: float,
) -> discord.Embed:
    """Build embed for end-of-cycle summary."""
    pnl_emoji = "\U0001F7E2" if daily_pnl >= 0 else "\U0001F534"
    embed = discord.Embed(
        title=f"Cycle {cycle} Summary",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc),
    )

    # Predictions summary
    lines = []
    for inst, pred in predictions.items():
        if pred is None:
            lines.append(f"**{inst}**: no data")
            continue
        direction = pred["direction"].upper()
        conf = pred["confidence"]
        shot = pred.get("shot_type", "")
        if shot:
            shot = f" [{shot.replace('_', ' ').title()}]"
        emoji = {"LONG": "\U0001F7E2", "SHORT": "\U0001F534"}.get(direction, "\u26AA")
        lines.append(f"{emoji} **{inst}**: {direction} ({conf:.1%}){shot}")

    embed.add_field(
        name="Predictions",
        value="\n".join(lines) if lines else "No predictions",
        inline=False,
    )

    # Account
    embed.add_field(name="Equity", value=f"${account_equity:,.2f}", inline=True)
    embed.add_field(name="Daily P&L", value=f"{pnl_emoji} ${daily_pnl:+,.2f}", inline=True)
    embed.add_field(name="Open Positions", value=str(len(positions)), inline=True)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def status_embed(
    is_running: bool,
    cycle: int,
    instruments: list,
    account_equity: float,
    positions: dict,
    daily_pnl: float,
    exec_mode: str,
) -> discord.Embed:
    """Build embed for /status command."""
    status_text = "\U0001F7E2 Running" if is_running else "\U0001F534 Stopped"
    embed = discord.Embed(
        title="Trading System Status",
        description=status_text,
        color=0x00CC00 if is_running else 0xCC0000,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Cycle", value=str(cycle), inline=True)
    embed.add_field(name="Execution", value=exec_mode, inline=True)
    embed.add_field(name="Instruments", value=", ".join(instruments), inline=True)
    embed.add_field(name="Equity", value=f"${account_equity:,.2f}", inline=True)
    embed.add_field(name="Daily P&L", value=f"${daily_pnl:+,.2f}", inline=True)
    embed.add_field(name="Positions", value=str(len(positions)), inline=True)

    # List open positions if any
    if positions:
        pos_lines = []
        for inst, pos in positions.items():
            pos_lines.append(
                f"**{inst}** {pos.direction.upper()} {pos.size} @ ${pos.entry_price:,.2f}"
            )
        embed.add_field(name="Open Positions", value="\n".join(pos_lines), inline=False)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def forecast_embed(instrument: str, prediction: dict) -> discord.Embed:
    """Build embed for on-demand forecast."""
    direction = prediction["direction"]
    dir_emoji = {
        "long": "\U0001F7E2",
        "short": "\U0001F534",
        "neutral": "\u26AA",
    }.get(direction, "\u26AA")
    color = DIRECTION_COLORS.get(direction, 0x808080)

    embed = discord.Embed(
        title=f"{dir_emoji} {instrument} Forecast",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Direction", value=direction.upper(), inline=True)
    embed.add_field(name="Confidence", value=f"{prediction['confidence']:.1%}", inline=True)
    embed.add_field(name="Regime", value=prediction["regime"].title(), inline=True)
    embed.add_field(
        name="Current Price",
        value=f"${prediction['current_price']:,.2f}",
        inline=True,
    )

    forecast = prediction["forecast_prices"]
    if len(forecast) > 0:
        embed.add_field(name="Forecast End", value=f"${forecast[-1]:,.2f}", inline=True)
        move_pct = (forecast[-1] - prediction["current_price"]) / prediction["current_price"] * 100
        embed.add_field(name="Expected Move", value=f"{move_pct:+.2f}%", inline=True)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


# ── Pre-Trade Radar ─────────────────────────────────────────────


def radar_embed(radar_items: list) -> discord.Embed:
    """
    Build embed for pre-trade radar — scenarios building toward a trigger.

    Each item dict: instrument, direction, confidence, nearest_tier,
    tier_threshold, regime, current_price, forecast_end
    """
    embed = discord.Embed(
        title="\U0001F4E1 Trade Radar — Scenarios Building",
        description="These instruments are approaching trade thresholds",
        color=0xF1C40F,  # yellow/amber
        timestamp=datetime.now(timezone.utc),
    )

    for item in radar_items:
        inst = item["instrument"]
        direction = item["direction"]
        conf = item["confidence"]
        tier = item["nearest_tier"].replace("_", " ").title()
        threshold = item["tier_threshold"]
        gap = threshold - conf
        regime = item["regime"].title()

        # Progress bar toward threshold
        progress = conf / threshold if threshold > 0 else 0
        bar_len = 10
        filled = min(int(progress * bar_len), bar_len)
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

        dir_emoji = {
            "long": "\U0001F7E2",
            "short": "\U0001F534",
        }.get(direction, "\u26AA")

        embed.add_field(
            name=f"{dir_emoji} {inst} — {direction.upper()}",
            value=(
                f"Confidence: **{conf:.1%}** \u2192 needs **{threshold:.0%}** for {tier}\n"
                f"`{bar}` {progress:.0%} ready\n"
                f"Gap: {gap:.1%} | Regime: {regime}\n"
                f"Price: ${item['current_price']:,.2f} \u2192 ${item['forecast_end']:,.2f}"
            ),
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Radar \u2014 updated every cycle")
    return embed


# ── Alert-level embeds with @mentions ────────────────────────────


def trade_alert_content(instrument: str, signal, alert_role_id: str = None) -> str:
    """Build the text content (outside embed) for trade alerts with @mentions."""
    dir_emoji = "\U0001F7E2" if signal.direction == "long" else "\U0001F534"
    tier_label = signal.shot_type.replace("_", " ").title()
    mention = f"<@&{alert_role_id}>" if alert_role_id else "@here"
    return (
        f"{mention} {dir_emoji} **TRADE ALERT** \u2014 "
        f"{instrument} {signal.direction.upper()} ({tier_label})"
    )


def execution_alert_content(instrument: str, result: dict, alert_role_id: str = None) -> str:
    """Build text content for order execution alerts."""
    if result and "orderId" in result:
        mention = f"<@&{alert_role_id}>" if alert_role_id else "@here"
        return f"{mention} \u2705 **ORDER PLACED** \u2014 {instrument} (ID: {result['orderId']})"
    return f"\u274C **ORDER FAILED** \u2014 {instrument}"
