#!/usr/bin/env python3
"""
KJ Strategy Visual Backtest Tool

Scans historical price data for Fibonacci retracement + price action confirmation
setups, generates interactive charts with markup, and produces teaching narration scripts.

Usage:
    python scripts/kj_backtest.py --instrument MNQ
    python scripts/kj_backtest.py --instrument MNQ --chart --narrate
    python scripts/kj_backtest.py --instrument MNQ --textbook-only --chart --open-chart
    python scripts/kj_backtest.py --stats
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import webbrowser

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from market_data.yfinance_provider import fetch_ohlcv
from kj_strategy.scanner import scan_kj_setups
from kj_strategy.classifier import classify_setup
from kj_strategy.chart import generate_chart
from kj_strategy.narration import generate_narration, save_narration
from kj_strategy.database import save_setup, get_stats, load_setups

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("kj_backtest")


def main():
    parser = argparse.ArgumentParser(
        description="KJ Strategy Visual Backtest Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --instrument MNQ                     Scan MNQ for setups
  %(prog)s --instrument MNQ --chart --narrate   Generate charts + narrations
  %(prog)s --instrument MNQ --textbook-only     Show only textbook setups
  %(prog)s --stats                              Show aggregate statistics
  %(prog)s --stats --instrument MNQ             Show stats for MNQ only
        """,
    )

    parser.add_argument(
        "--instrument", "-i",
        type=str,
        help="Instrument to scan (e.g. MNQ, MYM, MES, MBT)",
    )
    parser.add_argument(
        "--bars", "-b",
        type=int,
        default=500,
        help="Number of 5-min bars to fetch (default: 500)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="5m",
        help="Candle interval (default: 5m)",
    )
    parser.add_argument(
        "--min-rr",
        type=float,
        default=1.5,
        help="Minimum reward:risk ratio (default: 1.5)",
    )
    parser.add_argument(
        "--textbook-only",
        action="store_true",
        help="Only show textbook setups (score >= 75)",
    )
    parser.add_argument(
        "--chart",
        action="store_true",
        help="Generate interactive Plotly charts",
    )
    parser.add_argument(
        "--narrate",
        action="store_true",
        help="Generate teaching narration scripts",
    )
    parser.add_argument(
        "--open-chart",
        action="store_true",
        help="Open the best chart in browser after generation",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save setups to SQLite database",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show aggregate statistics from saved setups",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List saved setups from database",
    )

    args = parser.parse_args()

    # Stats mode
    if args.stats:
        _show_stats(args.instrument)
        return

    # List mode
    if args.list:
        _list_setups(args.instrument, args.textbook_only)
        return

    # Scan mode requires instrument
    if not args.instrument:
        parser.error("--instrument is required for scanning (use --stats for aggregate view)")

    instrument = args.instrument.upper()
    logger.info("=== KJ Strategy Backtest: %s ===", instrument)

    # Fetch data
    logger.info("Fetching %d bars of %s data...", args.bars, args.interval)
    df = fetch_ohlcv(instrument, bars=args.bars, interval=args.interval)
    logger.info("Got %d bars from %s to %s", len(df), df.index[0], df.index[-1])

    # Scan for setups
    setups = scan_kj_setups(
        instrument=instrument,
        df=df,
        min_rr=args.min_rr,
    )

    if not setups:
        logger.info("No KJ setups found for %s", instrument)
        print(f"\nNo KJ strategy setups found for {instrument} in the last {args.bars} bars.")
        return

    # Classify all setups
    for setup in setups:
        classify_setup(setup, df)

    # Filter if textbook-only
    if args.textbook_only:
        setups = [s for s in setups if s.classification == "textbook"]
        if not setups:
            print(f"\nNo textbook setups found for {instrument}. Try without --textbook-only.")
            return

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"  KJ STRATEGY SETUPS: {instrument}")
    print(f"  Data: {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')} ({len(df)} bars)")
    print(f"{'=' * 70}\n")

    textbook_count = sum(1 for s in setups if s.classification == "textbook")
    regular_count = len(setups) - textbook_count
    wins = sum(1 for s in setups if s.outcome == "win")
    losses = sum(1 for s in setups if s.outcome == "loss")
    timeouts = sum(1 for s in setups if s.outcome == "timeout")

    print(f"  Found: {len(setups)} setups ({textbook_count} textbook, {regular_count} regular)")
    print(f"  Outcomes: {wins}W / {losses}L / {timeouts}T", end="")
    decided = wins + losses
    if decided > 0:
        print(f"  ({wins/decided*100:.0f}% win rate)")
    else:
        print()
    print()

    best_chart_path = None

    for idx, setup in enumerate(setups, 1):
        ts = setup.entry_timestamp.strftime("%m/%d %H:%M") if setup.entry_timestamp else "N/A"
        pattern_str = setup.patterns[0].pattern_type.replace("_", " ").title() if setup.patterns else "—"
        outcome_str = {
            "win": f"WIN  +{setup.actual_rr:.1f}R",
            "loss": f"LOSS -1.0R",
            "timeout": f"T/O  {setup.actual_rr:+.1f}R" if setup.actual_rr else "T/O",
        }.get(setup.outcome, "—")

        class_badge = "★" if setup.classification == "textbook" else "○"

        print(
            f"  {class_badge} #{idx}  {ts}  "
            f"{setup.trend_direction.upper()[:4]}  "
            f"Fib {setup.active_fib_level}%  "
            f"{pattern_str:<20s}  "
            f"R:R {setup.reward_risk_ratio:.1f}:1  "
            f"Score {setup.textbook_score:.0f}/100  "
            f"{outcome_str}"
        )

        # Generate chart
        if args.chart:
            chart_path = generate_chart(setup, df)
            logger.info("Chart saved: %s", chart_path)
            if best_chart_path is None or setup.textbook_score > setups[0].textbook_score:
                best_chart_path = chart_path

        # Generate narration
        if args.narrate:
            generate_narration(setup, df)
            narr_path = save_narration(setup)
            logger.info("Narration saved: %s", narr_path)

        # Save to database
        if args.save:
            narr_path = None
            if setup.narration:
                narr_path = save_narration(setup)
            save_setup(setup, narration_path=narr_path)

    print()

    # Summary stats
    if decided > 0:
        avg_win = sum(s.actual_rr for s in setups if s.outcome == "win") / wins if wins else 0
        avg_loss = sum(s.actual_rr for s in setups if s.outcome == "loss") / losses if losses else 0
        expectancy = (wins / decided * avg_win) + (losses / decided * avg_loss)
        print(f"  Avg Win: +{avg_win:.1f}R | Avg Loss: {avg_loss:.1f}R | Expectancy: {expectancy:+.2f}R")

        if textbook_count > 0:
            tb_wins = sum(1 for s in setups if s.classification == "textbook" and s.outcome == "win")
            tb_decided = sum(1 for s in setups if s.classification == "textbook" and s.outcome in ("win", "loss"))
            if tb_decided > 0:
                print(f"  Textbook WR: {tb_wins/tb_decided*100:.0f}% ({tb_wins}/{tb_decided})")

    if args.chart:
        print(f"\n  Charts saved to: reports/kj_charts/")
    if args.narrate:
        print(f"  Narrations saved to: reports/kj_narrations/")
    if args.save:
        print(f"  Setups saved to database: data/kj_setups.db")

    # Open best chart
    if args.open_chart and best_chart_path:
        abs_path = os.path.abspath(best_chart_path)
        print(f"\n  Opening chart: {abs_path}")
        webbrowser.open(f"file://{abs_path}")

    print()


def _show_stats(instrument: str | None = None):
    """Display aggregate statistics from the database."""
    stats = get_stats(instrument)

    if stats["total"] == 0:
        print("\nNo setups in database. Run a scan with --save first.")
        return

    label = instrument or "All Instruments"
    print(f"\n{'=' * 50}")
    print(f"  KJ STRATEGY STATS: {label}")
    print(f"{'=' * 50}\n")

    print(f"  Total setups:      {stats['total']}")
    print(f"  Textbook:          {stats.get('textbook', 0)} ({stats.get('textbook', 0)/stats['total']*100:.0f}%)")
    print(f"  Regular:           {stats.get('regular', 0)} ({stats.get('regular', 0)/stats['total']*100:.0f}%)")
    print()
    print(f"  Wins:              {stats.get('win', 0)}")
    print(f"  Losses:            {stats.get('loss', 0)}")
    print(f"  Timeouts:          {stats.get('timeout', 0)}")
    print(f"  Win Rate:          {stats.get('win_rate', 0):.1f}%")
    print(f"  Textbook WR:       {stats.get('textbook_win_rate', 0):.1f}%")
    print()
    print(f"  Avg R:R (actual):  {stats.get('avg_rr', 0):+.2f}R")
    print(f"  Avg Score:         {stats.get('avg_score', 0):.0f}/100")
    print()


def _list_setups(instrument: str | None = None, textbook_only: bool = False):
    """List saved setups from the database."""
    classification = "textbook" if textbook_only else None
    rows = load_setups(instrument=instrument, classification=classification)

    if not rows:
        print("\nNo setups found. Run a scan with --save first.")
        return

    label = instrument or "All"
    print(f"\n{'=' * 80}")
    print(f"  SAVED SETUPS: {label} {'(textbook only)' if textbook_only else ''}")
    print(f"{'=' * 80}\n")

    for r in rows:
        ts = r["entry_timestamp"][:16] if r["entry_timestamp"] else "N/A"
        cls_badge = "★" if r["classification"] == "textbook" else "○"
        outcome_str = {
            "win": f"WIN  +{r['actual_rr']:.1f}R" if r["actual_rr"] else "WIN",
            "loss": "LOSS -1.0R",
            "timeout": f"T/O  {r['actual_rr']:+.1f}R" if r["actual_rr"] else "T/O",
        }.get(r["outcome"] or "", "—")

        print(
            f"  {cls_badge} {r['instrument']:<5s}  {ts}  "
            f"{r['trend_direction'][:4].upper()}  "
            f"Fib {r['active_fib_level']}%  "
            f"R:R {r['reward_risk_ratio']:.1f}:1  "
            f"Score {r['textbook_score']:.0f}  "
            f"{outcome_str}"
        )

    print(f"\n  Total: {len(rows)} setups\n")


if __name__ == "__main__":
    main()
