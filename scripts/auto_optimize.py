#!/usr/bin/env python3
"""
Auto-optimizer: runs backtests across parameter combinations,
analyzes results, and reports the best configuration.

This script:
  1. Defines a grid of tweakable parameters
  2. Runs walk-forward backtests for each combination
  3. Scores each run on multiple metrics (Sharpe, win rate, profit factor, drawdown)
  4. Ranks configurations and exports results
  5. Generates a plain-text analysis report

Usage:
    python scripts/auto_optimize.py --instrument NQ --days 30
    python scripts/auto_optimize.py --instrument GC --days 60 --interval 15m
    python scripts/auto_optimize.py --all --days 30
"""

import argparse
import csv
import itertools
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_config
from data.yfinance_provider import fetch_ohlcv
from model.wrapper import LaTPFNPredictor
from signal.generator import SignalGenerator, TradingSignal
from signal.confidence import score_confidence
from signal.exits import calculate_exits
from signal.shot_classifier import classify as classify_shot

# ── Parameter grid ────────────────────────────────────────────────────

PARAM_GRID = {
    "min_confidence":        [0.40, 0.50, 0.60, 0.70],
    "stop_loss_atr_mult":    [1.0, 1.5, 2.0, 2.5],
    "min_reward_risk":       [1.0, 1.5, 2.0, 2.5],
}


def generate_param_combos() -> list[dict]:
    """Generate all combinations from the grid."""
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = []
    for combo in itertools.product(*values):
        combos.append(dict(zip(keys, combo)))
    return combos


# ── Backtest engine ───────────────────────────────────────────────────

def run_single_backtest(
    model: LaTPFNPredictor,
    heldout_df,
    context_dfs: dict,
    config: dict,
    instrument: str,
    params: dict,
    account_equity: float = 50000.0,
) -> dict:
    """
    Run a walk-forward backtest with specific parameters.

    Returns dict of performance metrics.
    """
    n_history = config["model"]["n_history"]
    n_prompt = config["model"]["n_prompt"]
    window = n_history + n_prompt
    inst_cfg = config["instruments"][instrument]

    # Override config with test params
    test_config = deepcopy(config)
    test_config["signal"]["min_confidence"] = params["min_confidence"]
    test_config["risk"]["stop_loss_atr_multiplier"] = params["stop_loss_atr_mult"]
    test_config["risk"]["min_reward_risk_ratio"] = params["min_reward_risk"]

    signal_gen = SignalGenerator(test_config)

    trades = []
    n_steps = len(heldout_df) - window
    step_size = n_prompt

    for i in range(0, n_steps, step_size):
        slice_end = i + window
        if slice_end > len(heldout_df):
            break

        window_df = heldout_df.iloc[i:slice_end]
        ctx_slice = {}
        for sym, df in context_dfs.items():
            if len(df) > slice_end:
                ctx_slice[sym] = df.iloc[i:slice_end]

        if len(ctx_slice) < 2:
            continue

        try:
            prediction = model.predict(heldout_df=window_df, context_dfs=ctx_slice)
        except Exception:
            continue

        signal = signal_gen.generate(instrument, prediction)
        if signal is None:
            continue

        # Simulate trade
        future_start = slice_end
        future_end = min(future_start + n_prompt, len(heldout_df))
        if future_start >= len(heldout_df):
            break

        future_prices = heldout_df["Close"].iloc[future_start:future_end].values
        result = _simulate_trade(signal, future_prices, inst_cfg["contract_size"])
        if result:
            result["shot_type"] = getattr(signal, "shot_type", "unknown")
            trades.append(result)

    return _calculate_metrics(trades, account_equity)


def _simulate_trade(
    signal: TradingSignal,
    future_prices: np.ndarray,
    contract_size: float,
) -> dict | None:
    if len(future_prices) == 0:
        return None

    entry = signal.entry_price
    sl = signal.stop_loss
    tp = signal.take_profit
    is_long = signal.direction == "long"

    for price in future_prices:
        if is_long and price <= sl:
            return {"pnl": (sl - entry) * contract_size, "reason": "stop_loss"}
        if not is_long and price >= sl:
            return {"pnl": (entry - sl) * contract_size, "reason": "stop_loss"}
        if is_long and price >= tp:
            return {"pnl": (tp - entry) * contract_size, "reason": "take_profit"}
        if not is_long and price <= tp:
            return {"pnl": (entry - tp) * contract_size, "reason": "take_profit"}

    last = future_prices[-1]
    pnl = (last - entry) * contract_size if is_long else (entry - last) * contract_size
    return {"pnl": pnl, "reason": "timeout"}


# ── Metrics ───────────────────────────────────────────────────────────

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


def _calculate_metrics(trades: list, account_equity: float) -> dict:
    """Calculate comprehensive performance metrics."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0, "total_pnl": 0,
            "sharpe": 0, "sortino": 0, "profit_factor": 0,
            "max_drawdown": 0, "avg_win": 0, "avg_loss": 0,
            "return_pct": 0, "score": 0,
            "tp_count": 0, "sl_count": 0, "timeout_count": 0,
            "per_tier": {},
        }

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 99.0

    # Sharpe ratio (annualized, assuming ~252 trading days)
    pnl_arr = np.array(pnls)
    mean_ret = np.mean(pnl_arr)
    std_ret = np.std(pnl_arr)
    sharpe = (mean_ret / (std_ret + 1e-8)) * np.sqrt(252) if std_ret > 0 else 0

    # Sortino (only downside deviation)
    downside = pnl_arr[pnl_arr < 0]
    downside_std = np.std(downside) if len(downside) > 0 else 1e-8
    sortino = (mean_ret / (downside_std + 1e-8)) * np.sqrt(252)

    # Max drawdown
    equity_curve = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    drawdown = peak - equity_curve
    max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0

    return_pct = total_pnl / account_equity * 100

    # Composite score (weighted ranking metric)
    # Prioritizes: Sharpe > profit factor > win rate > low drawdown
    score = (
        sharpe * 30
        + min(profit_factor, 5) * 15
        + win_rate * 0.3
        + max(0, 100 - max_dd / account_equity * 1000) * 0.2
        + (return_pct if return_pct > 0 else return_pct * 2) * 0.5
    )

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "profit_factor": round(min(profit_factor, 99), 2),
        "max_drawdown": round(max_dd, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "return_pct": round(return_pct, 2),
        "score": round(score, 2),
        "tp_count": sum(1 for t in trades if t["reason"] == "take_profit"),
        "sl_count": sum(1 for t in trades if t["reason"] == "stop_loss"),
        "timeout_count": sum(1 for t in trades if t["reason"] == "timeout"),
        "per_tier": _per_tier_metrics(trades),
    }


# ── Report generation ─────────────────────────────────────────────────

def generate_report(
    results: list[dict],
    instrument: str,
    output_dir: Path,
):
    """Generate analysis report and CSV export."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Sort by score
    results.sort(key=lambda x: x["metrics"]["score"], reverse=True)

    # ── CSV export ────────────────────────────────────────────────
    csv_path = output_dir / f"optimization_{instrument}_{timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = list(results[0]["params"].keys()) + list(results[0]["metrics"].keys())
        writer.writerow(header)
        for r in results:
            row = list(r["params"].values()) + list(r["metrics"].values())
            writer.writerow(row)

    # ── JSON export ───────────────────────────────────────────────
    json_path = output_dir / f"optimization_{instrument}_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    # ── Text report ───────────────────────────────────────────────
    report_path = output_dir / f"report_{instrument}_{timestamp}.txt"
    best = results[0]
    worst = results[-1]

    viable = [r for r in results if r["metrics"]["total_pnl"] > 0 and r["metrics"]["total_trades"] >= 5]

    lines = []
    lines.append("=" * 70)
    lines.append(f"  LaT-PFN AUTO-OPTIMIZATION REPORT — {instrument}")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Total configurations tested:  {len(results)}")
    lines.append(f"  Profitable configurations:    {len(viable)}")
    lines.append(f"  Unprofitable configurations:  {len(results) - len(viable)}")
    lines.append("")

    lines.append("─" * 70)
    lines.append("  TOP 5 CONFIGURATIONS")
    lines.append("─" * 70)
    for i, r in enumerate(results[:5]):
        p = r["params"]
        m = r["metrics"]
        lines.append(f"")
        lines.append(f"  #{i+1}  Score: {m['score']:.1f}")
        lines.append(f"      Params:  conf≥{p['min_confidence']}  SL×{p['stop_loss_atr_mult']}  R:R≥{p['min_reward_risk']}")
        lines.append(f"      Trades:  {m['total_trades']}  |  Win rate: {m['win_rate']}%  |  PF: {m['profit_factor']}")
        lines.append(f"      P&L:     ${m['total_pnl']:+,.2f}  ({m['return_pct']:+.2f}%)")
        lines.append(f"      Sharpe:  {m['sharpe']}  |  Sortino: {m['sortino']}  |  Max DD: ${m['max_drawdown']:,.2f}")
        lines.append(f"      Exits:   TP={m['tp_count']}  SL={m['sl_count']}  Timeout={m['timeout_count']}")

    # ── Per-tier breakdown for the best config ──────────────────
    best_tiers = best["metrics"].get("per_tier", {})
    if best_tiers:
        lines.append("")
        lines.append("─" * 70)
        lines.append("  SHOT-TIER BREAKDOWN (Best Config)")
        lines.append("─" * 70)
        lines.append(f"  {'Tier':<16} {'Count':>6} {'Win%':>7} {'P&L':>12} {'Avg P&L':>10} {'PF':>6}")
        lines.append("  " + "─" * 58)
        for tier, tm in sorted(best_tiers.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            ev_tag = " EV+" if tm["total_pnl"] > 0 else " EV-"
            lines.append(
                f"  {tier:<16} {tm['count']:>6} {tm['win_rate']:>6.1f}% "
                f"${tm['total_pnl']:>+10,.2f} ${tm['avg_pnl']:>+8,.2f} "
                f"{tm['profit_factor']:>5.2f}{ev_tag}"
            )

    lines.append("")
    lines.append("─" * 70)
    lines.append("  ANALYSIS")
    lines.append("─" * 70)
    lines.append("")

    if len(viable) == 0:
        lines.append("  WARNING: No profitable configuration found.")
        lines.append("  This suggests LaT-PFN predictions may not have edge on this")
        lines.append("  instrument/timeframe. Consider:")
        lines.append("    - Trying a different timeframe (15m, 1h, 1d)")
        lines.append("    - Adding more or different context assets")
        lines.append("    - Longer backtest period for more data")
        lines.append("    - This instrument may not suit zero-shot forecasting")
    elif len(viable) < len(results) * 0.2:
        lines.append("  CAUTION: Only {:.0f}% of configs are profitable.".format(
            len(viable) / len(results) * 100
        ))
        lines.append("  The edge is fragile and parameter-sensitive.")
        lines.append("  Use the top config but monitor closely on paper.")
    else:
        lines.append("  POSITIVE: {:.0f}% of configs are profitable.".format(
            len(viable) / len(results) * 100
        ))
        lines.append("  The model shows a consistent edge across parameter ranges.")

    if viable:
        lines.append("")
        lines.append(f"  RECOMMENDED CONFIG for {instrument}:")
        bp = viable[0]["params"]
        lines.append(f"    signal.min_confidence:          {bp['min_confidence']}")
        lines.append(f"    risk.stop_loss_atr_multiplier:  {bp['stop_loss_atr_mult']}")
        lines.append(f"    risk.min_reward_risk_ratio:     {bp['min_reward_risk']}")
        bm = viable[0]["metrics"]
        lines.append(f"")
        lines.append(f"  Expected performance (backtest):")
        lines.append(f"    Win rate:      {bm['win_rate']}%")
        lines.append(f"    Profit factor: {bm['profit_factor']}")
        lines.append(f"    Sharpe ratio:  {bm['sharpe']}")
        lines.append(f"    Max drawdown:  ${bm['max_drawdown']:,.2f}")

    lines.append("")
    lines.append("─" * 70)
    lines.append(f"  Full results: {csv_path}")
    lines.append(f"  JSON data:    {json_path}")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    with open(report_path, "w") as f:
        f.write(report_text)

    # Print to terminal
    print(report_text)

    return {
        "report_path": str(report_path),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "best_params": viable[0]["params"] if viable else None,
        "best_metrics": viable[0]["metrics"] if viable else None,
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LaT-PFN Auto-Optimizer")
    parser.add_argument("--instrument", type=str, default="NQ", choices=["YM", "NQ", "GC"])
    parser.add_argument("--all", action="store_true", help="Run for all instruments")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--interval", type=str, default="5m")
    parser.add_argument("--equity", type=float, default=50000)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    instruments = list(config["instruments"].keys()) if args.all else [args.instrument]

    # Load model once (shared across all backtests)
    print("Loading LaT-PFN model...")
    model = LaTPFNPredictor(config)

    for instrument in instruments:
        inst_cfg = config["instruments"][instrument]
        n_total = config["model"]["n_history"] + config["model"]["n_prompt"]
        total_bars = n_total + args.days * 78

        print(f"\n{'='*60}")
        print(f"OPTIMIZING: {instrument}")
        print(f"{'='*60}")

        # Fetch data once
        print(f"Fetching {instrument} data...")
        heldout_df = fetch_ohlcv(instrument, bars=total_bars, interval=args.interval)
        print(f"  Got {len(heldout_df)} bars")

        context_dfs = {}
        for asset in inst_cfg["context_assets"]:
            try:
                df = fetch_ohlcv(asset, bars=total_bars, interval=args.interval)
                if len(df) >= n_total:
                    context_dfs[asset] = df
            except Exception as e:
                print(f"  Warning: {asset}: {e}")

        print(f"  Context assets: {len(context_dfs)}")

        # Run all parameter combos
        combos = generate_param_combos()
        print(f"  Testing {len(combos)} parameter combinations...\n")

        results = []
        for i, params in enumerate(combos):
            metrics = run_single_backtest(
                model=model,
                heldout_df=heldout_df,
                context_dfs=context_dfs,
                config=config,
                instrument=instrument,
                params=params,
                account_equity=args.equity,
            )
            results.append({"params": params, "metrics": metrics})

            # Progress
            pnl = metrics["total_pnl"]
            trades = metrics["total_trades"]
            marker = "+" if pnl > 0 else "-"
            print(
                f"  [{i+1:3d}/{len(combos)}] "
                f"conf≥{params['min_confidence']:.2f}  "
                f"SL×{params['stop_loss_atr_mult']:.1f}  "
                f"R:R≥{params['min_reward_risk']:.1f}  →  "
                f"{trades:3d} trades  ${pnl:+10,.2f}  {marker}"
            )

        # Generate report
        output_dir = Path("./reports")
        summary = generate_report(results, instrument, output_dir)

        # Auto-apply best config suggestion
        if summary["best_params"]:
            print(f"\n  To apply the best config, update config/settings.yaml:")
            bp = summary["best_params"]
            print(f"    signal.min_confidence: {bp['min_confidence']}")
            print(f"    risk.stop_loss_atr_multiplier: {bp['stop_loss_atr_mult']}")
            print(f"    risk.min_reward_risk_ratio: {bp['min_reward_risk']}")


if __name__ == "__main__":
    main()
