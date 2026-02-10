"""
Runner that starts the Discord bot and trading system concurrently.

The trading loop and Discord bot share the same asyncio event loop,
allowing the orchestrator to post signals to Discord in real time.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from discord_bot.bot import TradingBot, _bot_instance
import discord_bot.bot as bot_module
from orchestrator.main_loop import TradingSystem
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


async def run(config_path: str = None, dry_run: bool = False):
    """Start the Discord bot and trading system together."""
    config = load_config(config_path)

    if dry_run:
        config.setdefault("execution", {})["mode"] = "dry_run"

    setup_logging(config)

    # Validate Discord token
    token = config.get("discord", {}).get("bot_token", "")
    if not token or token.startswith("your_"):
        logger.error(
            "DISCORD_BOT_TOKEN not configured. "
            "Add your bot token to ~/latpfn-trading/.env"
        )
        sys.exit(1)

    # Create bot and trading system
    bot = TradingBot(config)
    bot_module._bot_instance = bot

    system = TradingSystem(config)
    system.discord_bot = bot
    bot.set_trading_system(system)

    async def start_trading():
        """Wait for bot to be ready, then start the trading loop."""
        await bot.wait_until_ready()
        logger.info("Bot ready — starting trading loop")
        await system.start()

    async with bot:
        bot.loop.create_task(start_trading())
        await bot.start(token)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="LaT-PFN Trading System with Discord Bot"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to settings YAML",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Predictions only, no orders",
    )
    args = parser.parse_args()

    asyncio.run(run(args.config, args.dry_run))


if __name__ == "__main__":
    main()
