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
import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from market_data.yfinance_provider import fetch_ohlcv
from forecaster.wrapper import LaTPFNPredictor
from signals.generator import SignalGenerator, TradingSignal
from signals.exits import calculate_exits
from risk.position_sizer import calculate_position_size
from scripts.sim_utils import simulate_trade


def run_backtest(
    config: dict,
    instrument: str,
    days: int,
    interval: str,
    account_equity: float,
    slippage: float = 0,
    save_results: bool = False,
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

        # Apply slippage: widen entry cost and narrow exit targets
        if slippage > 0:
            if signal.direction == "long":
                signal.entry_price += slippage
                signal.take_profit -= slippage
                signal.stop_loss -= slippage
            else:
                signal.entry_price -= slippage
                signal.take_profit += slippage
                signal.stop_loss += slippage

        trade_result = simulate_trade(signal, future_prices, inst_cfg["contract_size"])
        if trade_result:
            trade_result["shot_type"] = getattr(signal, "shot_type", "unknown")
            trade_result["direction"] = signal.direction
            trade_result["entry_price"] = signal.entry_price
            trade_result["confidence"] = getattr(signal, "confidence", 0)
            trades.append(trade_result)
            status = "WIN" if trade_result["pnl"] > 0 else "LOSS"
            print(
                f"  {window_df.index[-1].strftime('%m/%d %H:%M')}  "
                f"{signal.direction:5s}  "
                f"[{signal.shot_type}]  "
                f"entry=${signal.entry_price:.2f}  "
                f"exit=${trade_result['exit_price']:.2f}  "
                f"P&L=${trade_result['pnl']:+.2f}  [{status}]"
            )

    # Summary
    _print_summary(trades, account_equity, instrument)

    # Save results to reports/ if requested
    if save_results and trades:
        _save_results(trades, account_equity, instrument, days, slippage)


def _per_tier_metrics(trades: list) -> dict:
    """Calculate per shot-tier metrics breakdown."""
    from collections import defaultdict
    tiers = defaultdict(list)
    for t in trades:
        tier = t.get("shot_type", "unknown")
        tiers[tier].append(t["pnl"])

    breakdown = {}
    for tier, pnls in tiers.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        breakdown[tier] = {
            "count": len(pnls),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(np.mean(pnls), 2) if pnls else 0,
            "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) != 0 else 99.0,
        }
    return breakdown


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

    # Per-tier breakdown
    tier_metrics = _per_tier_metrics(trades)
    if tier_metrics:
        print(f"\n  Per-tier breakdown:")
        print(f"    {'Tier':15s} {'Trades':>6s} {'WR%':>6s} {'P&L':>12s} {'Avg':>10s} {'PF':>6s}")
        print(f"    {'-'*55}")
        for tier in ["layup", "short_range", "free_throw", "three_pointer", "half_court", "hail_mary"]:
            if tier in tier_metrics:
                m = tier_metrics[tier]
                print(
                    f"    {tier:15s} {m['count']:6d} {m['win_rate']:5.1f}% "
                    f"${m['total_pnl']:+10.2f} ${m['avg_pnl']:+8.2f} {m['profit_factor']:5.2f}"
                )
        # Show unknown tiers
        for tier, m in tier_metrics.items():
            if tier not in ["layup", "short_range", "free_throw", "three_pointer", "half_court", "hail_mary"]:
                print(
                    f"    {tier:15s} {m['count']:6d} {m['win_rate']:5.1f}% "
                    f"${m['total_pnl']:+10.2f} ${m['avg_pnl']:+8.2f} {m['profit_factor']:5.2f}"
                )

    print(f"{'='*60}")


def _max_drawdown(pnls: list) -> float:
    """Calculate maximum drawdown from P&L sequence."""
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    return float(np.max(drawdown)) if len(drawdown) > 0 else 0.0


def _save_results(trades: list, account_equity: float, instrument: str, days: int, slippage: float):
    """Save backtest results to reports/ directory as JSON."""
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backtest_{instrument}_{date_str}.json"

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    equity_curve = list(np.cumsum(pnls).round(2))

    report = {
        "instrument": instrument,
        "days": days,
        "slippage": slippage,
        "account_equity": account_equity,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(float(np.mean(wins)), 2) if wins else 0,
            "avg_loss": round(float(np.mean(losses)), 2) if losses else 0,
            "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) != 0 else 99.0,
            "max_drawdown": round(_max_drawdown(pnls), 2),
            "return_pct": round(total_pnl / account_equity * 100, 2),
        },
        "per_tier": _per_tier_metrics(trades),
        "equity_curve": equity_curve,
        "trades": trades,
    }

    out_path = reports_dir / filename
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nResults saved to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="LaT-PFN Trading Backtest")
    parser.add_argument("--instrument", type=str, default="MNQ",
                        help="Instrument symbol (e.g. MNQ, MYM, MES, M2K, MCL, M6E, M6B, M6A, M6J)")
    parser.add_argument("--days", type=int, default=60, help="Days of history to backtest (max ~60 for 5m data)")
    parser.add_argument("--interval", type=str, default="5m", help="Candle interval")
    parser.add_argument("--equity", type=float, default=50000, help="Starting account equity")
    parser.add_argument("--slippage", type=float, default=0, help="Slippage points added to entries/exits")
    parser.add_argument("--save-results", action="store_true", help="Save results to reports/ directory")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)

    # Validate instrument exists in config
    if args.instrument not in config["instruments"]:
        valid = ", ".join(config["instruments"].keys())
        print(f"Error: '{args.instrument}' not in config. Valid instruments: {valid}")
        sys.exit(1)

    run_backtest(config, args.instrument, args.days, args.interval, args.equity,
                 slippage=args.slippage, save_results=args.save_results)


if __name__ == "__main__":
    main()
