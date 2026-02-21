#!/usr/bin/env python3
"""
Hyperliquid scalper — runs as a separate process alongside the Apex bot.

Scans 50 crypto perps every 60 seconds, executes via Hyperliquid DEX
with 20x leverage on a $30 account. Designed for high-frequency
micro-scalping across the entire crypto market.

Usage:
    source venv/bin/activate
    python run_hl.py              # Live trading
    python run_hl.py --dry-run    # Predictions only
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from orchestrator.main_loop import TradingSystem
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Hyperliquid Scalper")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()

    # Override execution mode to Hyperliquid
    config["execution"]["mode"] = "hyperliquid"

    # Use HL-specific cycle interval
    hl_cycle = config.get("hyperliquid", {}).get("cycle_minutes", 1)
    config["schedule"]["prediction_interval_minutes"] = hl_cycle

    # Disable EOD flatten (crypto trades 24/7)
    config["schedule"]["flatten_eod"] = False

    # Use Hyperliquid instruments instead of CME
    if "instruments_hyperliquid" in config:
        config["instruments"] = config["instruments_hyperliquid"]

    if args.dry_run:
        config["execution"]["dry_run"] = True

    setup_logging(config)
    logger.info("=" * 60)
    logger.info("  HYPERLIQUID SCALPER — %d pairs, %d-min cycles, 20x leverage",
                config.get("hyperliquid", {}).get("top_pairs", 50), hl_cycle)
    logger.info("=" * 60)

    system = TradingSystem(config)
    asyncio.run(system.start())


if __name__ == "__main__":
    main()
