"""
Trade confirmation via Discord reactions.

When confirmation_mode is enabled (required for PA/Live accounts),
signals are posted to Discord and require a human reaction to execute.
The trader has a configurable timeout to approve or reject.
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord

from discord_bot.embeds import signal_embed

logger = logging.getLogger(__name__)

# Reaction emojis
APPROVE_EMOJI = "\u2705"  # green checkmark
REJECT_EMOJI = "\u274C"   # red X


async def request_confirmation(
    channel: discord.TextChannel,
    instrument: str,
    signal,
    prediction: dict,
    timeout_seconds: int = 60,
    alert_role_id: str = None,
) -> bool:
    """
    Post a signal to Discord and wait for human approval.

    Args:
        channel:         Discord channel to post in.
        instrument:      Instrument name (e.g. 'MNQ').
        signal:          TradingSignal object.
        prediction:      Prediction dict from model.
        timeout_seconds: How long to wait for reaction (default 60s).
        alert_role_id:   Optional Discord role ID for @mention.

    Returns:
        True if approved, False if rejected or timed out.
    """
    mention = f"<@&{alert_role_id}>" if alert_role_id else "@here"
    dir_emoji = "\U0001F7E2" if signal.direction == "long" else "\U0001F534"
    tier_label = signal.shot_type.replace("_", " ").title()

    content = (
        f"{mention} {dir_emoji} **TRADE CONFIRMATION NEEDED** \u2014 "
        f"{instrument} {signal.direction.upper()} ({tier_label})\n"
        f"React {APPROVE_EMOJI} to **EXECUTE** or {REJECT_EMOJI} to **REJECT** "
        f"(auto-rejects in {timeout_seconds}s)"
    )

    embed = signal_embed(instrument, signal, prediction)
    embed.set_footer(text=f"Awaiting confirmation \u2014 {timeout_seconds}s timeout")

    msg = await channel.send(content=content, embed=embed)

    # Add reaction options
    await msg.add_reaction(APPROVE_EMOJI)
    await msg.add_reaction(REJECT_EMOJI)

    def check(reaction, user):
        return (
            reaction.message.id == msg.id
            and not user.bot
            and str(reaction.emoji) in (APPROVE_EMOJI, REJECT_EMOJI)
        )

    try:
        reaction, user = await channel.guild._state._get_client().wait_for(
            "reaction_add", timeout=timeout_seconds, check=check
        )

        if str(reaction.emoji) == APPROVE_EMOJI:
            # Update embed to show approved
            embed.set_footer(text=f"APPROVED by {user.display_name}")
            embed.color = 0x00CC00
            await msg.edit(embed=embed)
            logger.info("Trade %s %s APPROVED by %s", instrument, signal.direction, user.display_name)
            return True
        else:
            embed.set_footer(text=f"REJECTED by {user.display_name}")
            embed.color = 0xCC0000
            await msg.edit(embed=embed)
            logger.info("Trade %s %s REJECTED by %s", instrument, signal.direction, user.display_name)
            return False

    except asyncio.TimeoutError:
        embed.set_footer(text="EXPIRED \u2014 no confirmation received")
        embed.color = 0x808080
        await msg.edit(embed=embed)
        logger.info("Trade %s %s EXPIRED (no confirmation in %ds)", instrument, signal.direction, timeout_seconds)
        return False
