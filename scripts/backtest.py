#!/usr/bin/env python3
"""
Historical backtest runner.

Replays historical data through the full pipeline:
  data → LaT-PFN prediction → signal generation → risk validation → simulated execution

Usage:
    python scripts/backtest.py --instrument NQ --days 30 --interval 5m
    python scripts/backtest.py --instrument GC --days 60 --interval 15m
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from data.yfinance_provider import fetch_ohlcv
from model.wrapper import LaTPFNPredictor
from signal.generator import SignalGenerator, TradingSignal
from signal.exits import calculate_exits
from risk.position_sizer import calculate_position_size
from scripts.sim_utils import simulate_trade


def run_backtest(
    config: dict,
    instrument: str,
    days: int,
    interval: str,
    account_equity: float,
):
    """Run a walk-forward backtest."""
    inst_cfg = config["instruments"][instrument]
    n_history = config["model"]["n_history"]
    n_prompt = config["model"]["n_prompt"]
    window = n_history + n_prompt

    print(f"\n{'='*60}")
    print(f"BACKTEST: {instrument} ({inst_cfg['name']})")
    print(f"Period: {days} days  |  Interval: {interval}")
    print(f"Window: {n_history} history + {n_prompt} forecast = {window} bars")
    print(f"Account: ${account_equity:,.2f}")
    print(f"{'='*60}\n")

    # Fetch extended history
    total_bars = window + days * 78  # ~78 5min bars per trading day
    print(f"Fetching {total_bars} bars of {instrument} data...")

    heldout_df = fetch_ohlcv(instrument, bars=total_bars, interval=interval)
    print(f"Got {len(heldout_df)} bars from {heldout_df.index[0]} to {heldout_df.index[-1]}")

    # Fetch context assets
    context_dfs = {}
    for asset in inst_cfg["context_assets"]:
        try:
            df = fetch_ohlcv(asset, bars=total_bars, interval=interval)
            if len(df) >= window:
                context_dfs[asset] = df
        except Exception as e:
            print(f"  Warning: failed to fetch {asset}: {e}")

    print(f"Context assets loaded: {len(context_dfs)}")

    # Initialize model
    print("\nLoading LaT-PFN model...")
    model = LaTPFNPredictor(config)
    signal_gen = SignalGenerator(config)

    # Walk-forward simulation
    trades = []
    n_steps = len(heldout_df) - window
    step_size = n_prompt  # non-overlapping steps

    print(f"\nRunning {n_steps // step_size} prediction cycles...\n")

    for i in range(0, n_steps, step_size):
        slice_end = i + window
        if slice_end > len(heldout_df):
            break

        # Current data window
        window_df = heldout_df.iloc[i:slice_end]

        # Slice context to same time range
        ctx_slice = {}
        for sym, df in context_dfs.items():
            if len(df) > slice_end:
                ctx_slice[sym] = df.iloc[i:slice_end]

        if len(ctx_slice) < 2:
            continue

        # Predict
        try:
            prediction = model.predict(
                heldout_df=window_df,
                context_dfs=ctx_slice,
            )
        except Exception as e:
            print(f"  Step {i}: prediction error: {e}")
            continue

        # Generate signal
        signal = signal_gen.generate(instrument, prediction)
        if signal is None:
            continue

        # Simulate trade outcome
        # Look at actual future prices (if available)
        future_start = slice_end
        future_end = min(future_start + n_prompt, len(heldout_df))
        if future_start >= len(heldout_df):
            break

        future_prices = heldout_df["Close"].iloc[future_start:future_end].values

        trade_result = simulate_trade(signal, future_prices, inst_cfg["contract_size"])
        if trade_result:
            trades.append(trade_result)
            status = "WIN" if trade_result["pnl"] > 0 else "LOSS"
            print(
                f"  {window_df.index[-1].strftime('%m/%d %H:%M')}  "
                f"{signal.direction:5s}  "
                f"entry=${signal.entry_price:.2f}  "
                f"exit=${trade_result['exit_price']:.2f}  "
                f"P&L=${trade_result['pnl']:+.2f}  [{status}]"
            )

    # Summary
    _print_summary(trades, account_equity, instrument)


def _print_summary(trades: list, account_equity: float, instrument: str):
    """Print backtest performance summary."""
    print(f"\n{'='*60}")
    print(f"BACKTEST RESULTS: {instrument}")
    print(f"{'='*60}")

    if not trades:
        print("No trades generated.")
        return

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    exit_reasons = [t["reason"] for t in trades]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
    max_dd = _max_drawdown(pnls)

    print(f"  Total trades:    {len(trades)}")
    print(f"  Win rate:        {win_rate:.1f}%")
    print(f"  Total P&L:       ${total_pnl:+,.2f}")
    print(f"  Avg win:         ${avg_win:+,.2f}")
    print(f"  Avg loss:        ${avg_loss:+,.2f}")
    print(f"  Profit factor:   {profit_factor:.2f}")
    print(f"  Max drawdown:    ${max_dd:,.2f}")
    print(f"  Return:          {total_pnl/account_equity*100:+.2f}%")
    print()
    print(f"  Exit reasons:")
    for reason in ["take_profit", "stop_loss", "timeout"]:
        count = exit_reasons.count(reason)
        print(f"    {reason:15s}: {count}")
    print(f"{'='*60}")


def _max_drawdown(pnls: list) -> float:
    """Calculate maximum drawdown from P&L sequence."""
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    return float(np.max(drawdown)) if len(drawdown) > 0 else 0.0


def main():
    parser = argparse.ArgumentParser(description="LaT-PFN Trading Backtest")
    parser.add_argument("--instrument", type=str, default="NQ", choices=["YM", "NQ", "GC"])
    parser.add_argument("--days", type=int, default=30, help="Days of history to backtest")
    parser.add_argument("--interval", type=str, default="5m", help="Candle interval")
    parser.add_argument("--equity", type=float, default=50000, help="Starting account equity")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    run_backtest(config, args.instrument, args.days, args.interval, args.equity)


if __name__ == "__main__":
    main()
