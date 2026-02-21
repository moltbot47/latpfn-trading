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

    # Optionally create Polymarket orchestrator
    poly_orch = None
    if config.get("polymarket", {}).get("enabled", False):
        try:
            from polymarket.orchestrator import PolymarketOrchestrator
            poly_orch = PolymarketOrchestrator(config)
            poly_orch.set_bot(bot)
            bot._polymarket_orchestrator = poly_orch
            logger.info("Polymarket orchestrator created")
        except ImportError as e:
            logger.warning("Polymarket module not available: %s", e)
        except Exception as e:
            logger.error("Polymarket init error: %s", e)

    # Check if main trading system should run
    hl_cfg = config.get("hyperliquid", {})
    main_trading_enabled = hl_cfg.get("enabled", True)

    async def start_trading():
        """Wait for bot to be ready, then start the trading loop."""
        await bot.wait_until_ready()
        if not main_trading_enabled:
            logger.info("Main trading system disabled (hyperliquid.enabled=false)")
            return
        logger.info("Bot ready — starting trading loop")
        await system.start()

    async def start_polymarket():
        """Wait for bot to be ready, then start the Polymarket loop."""
        await bot.wait_until_ready()
        if poly_orch:
            logger.info("Starting Polymarket orchestrator...")
            try:
                await poly_orch.start()
            except Exception as e:
                logger.error("Polymarket orchestrator error: %s", e, exc_info=True)

    # Portfolio tracker — live balance updates to both channels
    from discord_bot.portfolio_tracker import PortfolioTracker
    tracker = PortfolioTracker(bot, config)

    # ── Autonomous Agents with inter-agent communication ──────────
    hl_agent = None
    poly_agent = None
    apex_agent = None
    hl_position_manager = None
    try:
        from agents.message_bus import MessageBus
        from agents.hyperliquid_agent import HyperliquidAgent
        from agents.polymarket_agent import PolymarketAgent
        from agents.apex_agent import ApexAgent

        bus = MessageBus(max_queue_size=200)

        # Apex agent (CME futures via TradersPost/PickMyTrade)
        exec_mode = config.get("execution", {}).get("mode", "dry_run")
        if exec_mode in ("traderspost", "pickmytrade", "tradovate"):
            apex_agent = ApexAgent(
                trading_system=system, bus=bus, bot=bot, config=config,
            )
            system._agent = apex_agent
            logger.info("Apex agent created — soul loaded")

        # HL agent (Hyperliquid DEX)
        hl_agent = HyperliquidAgent(
            trading_system=system, bus=bus, bot=bot, config=config,
        )
        if exec_mode == "hyperliquid":
            system._agent = hl_agent
        logger.info("HL agent created — soul loaded")

        if poly_orch:
            poly_agent = PolymarketAgent(
                orchestrator=poly_orch, bus=bus, bot=bot, config=config,
            )
            poly_orch._agent = poly_agent
            logger.info("Poly agent created — soul loaded")

            # Wire turbo strategy ↔ message bus for 2-way feedback
            poly_orch.turbo._message_bus = bus
            logger.info("Turbo strategy ↔ message bus connected")

        # HL Position Manager (Layer 1: active position lifecycle management)
        if exec_mode == "hyperliquid" and system.executor:
            try:
                from execution.hl_position_manager import HLPositionManager
                hl_position_manager = HLPositionManager(
                    client=system.executor,
                    config=config,
                    bus=bus,
                )
                # Wire position manager ↔ HL agent (bidirectional reference)
                hl_agent._position_manager = hl_position_manager
                # Give PM access to pair scanner for funding rate enrichment
                if hasattr(system, '_pair_scanner') and system._pair_scanner:
                    hl_position_manager._pair_scanner = system._pair_scanner
                # Store on trading system for access from main loop
                system._position_manager = hl_position_manager
                logger.info("HL Position Manager created — 7 rules active")
            except Exception as e:
                logger.warning("HL Position Manager init failed: %s", e)

        logger.info("Agent-to-agent bus online — %d agents registered", len(bus.stats["agents"]))
    except Exception as e:
        logger.warning("Agent system init failed (non-fatal): %s", e)

    async with bot:
        bot.loop.create_task(start_trading())
        if poly_orch:
            bot.loop.create_task(start_polymarket())
        bot.loop.create_task(tracker.start())
        if apex_agent and main_trading_enabled:
            bot.loop.create_task(apex_agent.start())
        if hl_agent:  # Always start — bus listener for intel (doesn't trade)
            bot.loop.create_task(hl_agent.start())
        if poly_agent:
            bot.loop.create_task(poly_agent.start())
        if hl_position_manager:
            bot.loop.create_task(hl_position_manager.start())
            logger.info("HL Position Manager loop started (scan every %ds)", hl_position_manager.scan_interval)
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
