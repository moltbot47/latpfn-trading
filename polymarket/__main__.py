"""
Standalone entry point for Polymarket trading bot.

Usage:
    python -m polymarket              # Run the full orchestrator
    python -m polymarket --scan       # One-time scan, print candidates
    python -m polymarket --status     # Show current positions and P&L
    python -m polymarket --forecast   # Forecast top 10 markets

Can run independently from the Hyperliquid trading system.
"""

import argparse
import asyncio
import logging
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config import load_config


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


async def run_orchestrator(config: dict):
    """Run the full Polymarket orchestrator loop."""
    from polymarket.orchestrator import PolymarketOrchestrator

    orch = PolymarketOrchestrator(config)
    try:
        await orch.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await orch.shutdown()


async def run_scan(config: dict):
    """One-time scan: show candidates without executing."""
    from polymarket.client import PolymarketClient
    from polymarket.scanner import MarketScanner

    client = PolymarketClient(config)
    await client.connect()
    scanner = MarketScanner(client, config)

    print("Scanning Polymarket...")
    markets = scanner.scan_markets()
    print(f"Found {len(markets)} active markets\n")

    # Resolution snipe candidates
    snipes = scanner.filter_resolution_candidates(markets)
    print(f"=== Resolution Snipe Candidates ({len(snipes)}) ===")
    for s in snipes[:10]:
        print(
            f"  YES=${s['yes_price']:.2f}  edge={s['edge_pct']:.1f}%  "
            f"hours={s['hours_to_resolution']:.0f}  vol=${s['volume_24h']:.0f}  "
            f"'{s['question'][:60]}'"
        )

    # Forecastable markets
    forecastable = scanner.get_forecastable_markets(markets)
    print(f"\n=== Forecastable Markets ({len(forecastable)}) ===")
    for m in forecastable[:10]:
        print(
            f"  YES=${m['yes_price']:.2f}  vol=${m['volume']:.0f}  "
            f"hours={m['hours_left']:.0f}  '{m['question'][:60]}'"
        )

    balance = client.get_balance()
    print(f"\nBalance: ${balance:.2f}")
    await client.disconnect()


async def run_forecast(config: dict):
    """Forecast top markets with LLM."""
    from polymarket.client import PolymarketClient
    from polymarket.llm_forecaster import LLMForecaster
    from polymarket.scanner import MarketScanner

    client = PolymarketClient(config)
    await client.connect()
    scanner = MarketScanner(client, config)
    forecaster = LLMForecaster(config)

    markets = scanner.scan_markets()
    forecastable = scanner.get_forecastable_markets(markets, limit=10)

    print(f"Forecasting {len(forecastable)} markets with Claude...\n")
    forecasts = await forecaster.batch_forecast(forecastable)

    for m in forecastable:
        fc = forecasts.get(m["market_id"], {})
        if not fc:
            continue
        div = fc["probability"] - m["yes_price"]
        print(
            f"  MKT=${m['yes_price']:.2f}  LLM={fc['probability']:.2f}  "
            f"div={div:+.2f}  conf={fc['confidence']:.2f}  "
            f"'{m['question'][:55]}'"
        )
        if fc.get("reasoning"):
            print(f"    > {fc['reasoning'][:80]}")
        print()

    # Show calibration if available
    brier = forecaster.compute_brier_score()
    if brier is not None:
        print(f"Brier score (30d): {brier:.4f}")

    await client.disconnect()


async def run_status(config: dict):
    """Show current positions and P&L."""
    from polymarket.positions import PositionManager

    pm = PositionManager()
    open_pos = pm.get_open_positions()

    print(f"=== Polymarket Positions ({len(open_pos)} open) ===\n")
    for key, pos in open_pos.items():
        print(
            f"  [{pos.strategy}] {pos.direction} '{pos.question[:50]}'\n"
            f"    entry=${pos.entry_price:.4f}  size=${pos.size_usdc:.2f}  "
            f"shares={pos.shares:.1f}  target=${pos.target_exit:.2f}"
        )
        if pos.llm_probability > 0:
            print(f"    LLM={pos.llm_probability:.2f}  mkt={pos.market_probability:.2f}")
        print()

    deployed = pm.total_deployed()
    realized = pm.total_realized_pnl()
    print(f"Deployed: ${deployed:.2f}")
    print(f"Realized P&L: ${realized:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--scan", action="store_true", help="One-time scan")
    parser.add_argument("--forecast", action="store_true", help="Forecast top markets")
    parser.add_argument("--status", action="store_true", help="Show positions")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    config = load_config()

    if args.scan:
        asyncio.run(run_scan(config))
    elif args.forecast:
        asyncio.run(run_forecast(config))
    elif args.status:
        asyncio.run(run_status(config))
    else:
        asyncio.run(run_orchestrator(config))


if __name__ == "__main__":
    main()
