#!/usr/bin/env python3
"""
LaT-PFN Automated Futures Trading System
─────────────────────────────────────────
Predicts price movements on US30 (YM), NQ, and Gold (GC) futures
using the LaT-PFN zero-shot time-series forecasting model, and
executes trades via the Tradovate API.

Usage:
    python main.py                  # Run with default config
    python main.py --config path    # Custom config file
    python main.py --dry-run        # Predictions only, no execution
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from orchestrator.main_loop import TradingSystem


def main():
    parser = argparse.ArgumentParser(
        description="LaT-PFN Automated Futures Trading System"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to settings YAML (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run predictions only — do not connect to Tradovate or place orders",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    if args.dry_run:
        config["tradovate"]["credentials"]["username"] = ""
        config["tradovate"]["credentials"]["password"] = ""

    system = TradingSystem(config)
    asyncio.run(system.start())


if __name__ == "__main__":
    main()
