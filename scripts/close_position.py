#!/usr/bin/env python3
"""
Quick CLI to close a position via PickMyTrade webhook.

Usage:
    python scripts/close_position.py MNQ        # close MNQ position
    python scripts/close_position.py MYM MGC    # close multiple
    python scripts/close_position.py --all      # close all positions
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from execution.webhook_client import WebhookClient

ALL_SYMBOLS = ["MNQ", "MYM", "MGC", "NQ", "YM", "GC"]


async def close(symbols: list[str]):
    config = load_config()
    client = WebhookClient(config)
    await client.connect()

    for symbol in symbols:
        print(f"Sending close webhook for {symbol}...")
        result = await client.close_position(symbol)
        if result:
            print(f"  {symbol}: close sent successfully")
        else:
            print(f"  {symbol}: close failed")

    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Close positions via PickMyTrade webhook")
    parser.add_argument("symbols", nargs="*", help="Symbols to close (e.g. MNQ MYM MGC)")
    parser.add_argument("--all", action="store_true", help="Close all symbols")
    args = parser.parse_args()

    if args.all:
        symbols = ALL_SYMBOLS
    elif args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        parser.print_help()
        sys.exit(1)

    asyncio.run(close(symbols))


if __name__ == "__main__":
    main()
