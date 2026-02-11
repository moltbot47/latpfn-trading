#!/usr/bin/env python3
"""
Prediction Accuracy Analyzer
=============================
The most important script in the system.  It answers a single question:
does this trading model actually predict direction better than a coin flip?

Reads the SQLite trade-log database, pairs each prediction with the next
observation for the same instrument, and produces a detailed accuracy
report including directional hit-rate, confidence calibration, forecast
error, and trade P&L.

Usage:
    python scripts/analyze_predictions.py
    python scripts/analyze_predictions.py --db ./data/trade_log.db
"""

import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root on sys.path so sibling imports work if needed later
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIDENCE_BINS = [
    (0.00, 0.25, "0.00 - 0.25"),
    (0.25, 0.35, "0.25 - 0.35"),
    (0.35, 0.45, "0.35 - 0.45"),
    (0.45, 0.55, "0.45 - 0.55"),
    (0.55, 0.65, "0.55 - 0.65"),
    (0.65, 1.01, "0.65+"),
]

VERDICT_THRESHOLD_GO = 0.55
VERDICT_THRESHOLD_CAUTION = 0.50
VERDICT_CONFIDENCE_FLOOR = 0.45

LINE = "-" * 72
DOUBLE_LINE = "=" * 72


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(numerator: int, denominator: int) -> float:
    """Safe percentage."""
    if denominator == 0:
        return 0.0
    return numerator / denominator * 100.0


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if b == 0:
        return default
    return a / b


def _bin_label(confidence: float) -> str:
    """Return the label for the confidence bin a value falls into."""
    for lo, hi, label in CONFIDENCE_BINS:
        if lo <= confidence < hi:
            return label
    return CONFIDENCE_BINS[-1][2]


def _direction_correct(direction: str, price_now: float, price_next: float) -> bool | None:
    """
    Was the directional call correct?

    Returns True/False, or None for neutral predictions or zero price change.
    """
    if direction == "neutral":
        return None
    delta = price_next - price_now
    if delta == 0:
        return None
    if direction == "long":
        return delta > 0
    if direction == "short":
        return delta < 0
    return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _query_to_dicts(conn: sqlite3.Connection, sql: str) -> list[dict]:
    """Execute a query and return results as a list of dicts."""
    try:
        cur = conn.execute(sql)
    except sqlite3.OperationalError:
        return []
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_predictions(conn: sqlite3.Connection) -> list[dict]:
    """Load all predictions ordered by instrument then time."""
    return _query_to_dicts(conn, """
        SELECT *
        FROM predictions
        ORDER BY instrument, timestamp, id
    """)


def load_trades(conn: sqlite3.Connection) -> list[dict]:
    """Load all trades."""
    return _query_to_dicts(conn, """
        SELECT *
        FROM trades
        ORDER BY timestamp, id
    """)


# ---------------------------------------------------------------------------
# Pairing: each prediction with the next observation for the same instrument
# ---------------------------------------------------------------------------

def pair_predictions(predictions: list[dict]) -> list[dict]:
    """
    For each prediction, look up the next prediction row for the same
    instrument and attach its current_price as 'actual_next_price'.

    Returns a new list of dicts (original fields + actual_next_price +
    direction_correct boolean).
    """
    # Group by instrument preserving order
    by_instrument: dict[str, list[dict]] = defaultdict(list)
    for p in predictions:
        by_instrument[p["instrument"]].append(p)

    paired = []
    for instrument, preds in by_instrument.items():
        for i, pred in enumerate(preds):
            if i + 1 < len(preds):
                next_price = preds[i + 1]["current_price"]
            else:
                # Last prediction for this instrument: no follow-up observation
                next_price = None

            row = dict(pred)
            row["actual_next_price"] = next_price
            if next_price is not None and pred["current_price"] is not None:
                row["direction_correct"] = _direction_correct(
                    pred["direction"], pred["current_price"], next_price
                )
            else:
                row["direction_correct"] = None
            paired.append(row)

    return paired


# ---------------------------------------------------------------------------
# Section 1 - Overall Directional Accuracy
# ---------------------------------------------------------------------------

def section_directional_accuracy(paired: list[dict]) -> dict:
    """Compute overall directional accuracy (excluding neutrals and unpaired)."""
    evaluated = [p for p in paired if p["direction_correct"] is not None]
    correct = [p for p in evaluated if p["direction_correct"]]

    total = len(evaluated)
    n_correct = len(correct)
    accuracy = _pct(n_correct, total)

    # Breakdown by direction
    by_dir: dict[str, dict] = {}
    for direction in ("long", "short"):
        subset = [p for p in evaluated if p["direction"] == direction]
        sub_correct = [p for p in subset if p["direction_correct"]]
        by_dir[direction] = {
            "total": len(subset),
            "correct": len(sub_correct),
            "accuracy": _pct(len(sub_correct), len(subset)),
        }

    neutrals = [p for p in paired if p["direction"] == "neutral"]
    unpaired = [p for p in paired if p["actual_next_price"] is None]

    return {
        "total_evaluated": total,
        "correct": n_correct,
        "accuracy": accuracy,
        "by_direction": by_dir,
        "neutrals": len(neutrals),
        "unpaired": len(unpaired),
        "total_predictions": len(paired),
    }


# ---------------------------------------------------------------------------
# Section 2 - Accuracy by Confidence Bin
# ---------------------------------------------------------------------------

def section_confidence_bins(paired: list[dict]) -> list[dict]:
    """Group by composite_confidence bin.  For each bin: count, accuracy,
    avg absolute forecast error."""
    bins: dict[str, list[dict]] = defaultdict(list)
    for p in paired:
        conf = p.get("composite_confidence")
        if conf is None:
            continue
        label = _bin_label(conf)
        bins[label].append(p)

    results = []
    for lo, hi, label in CONFIDENCE_BINS:
        preds = bins.get(label, [])
        evaluated = [p for p in preds if p["direction_correct"] is not None]
        correct = [p for p in evaluated if p["direction_correct"]]

        # Forecast error: |forecast_end_price - actual_next_price|
        errors = []
        for p in preds:
            if (
                p["actual_next_price"] is not None
                and p["forecast_end_price"] is not None
            ):
                errors.append(abs(p["forecast_end_price"] - p["actual_next_price"]))

        results.append({
            "label": label,
            "count": len(preds),
            "evaluated": len(evaluated),
            "correct": len(correct),
            "accuracy": _pct(len(correct), len(evaluated)),
            "avg_forecast_error": sum(errors) / len(errors) if errors else None,
        })

    return results


# ---------------------------------------------------------------------------
# Section 3 - Accuracy by Instrument
# ---------------------------------------------------------------------------

def section_by_instrument(paired: list[dict]) -> list[dict]:
    by_inst: dict[str, list[dict]] = defaultdict(list)
    for p in paired:
        by_inst[p["instrument"]].append(p)

    results = []
    for instrument in sorted(by_inst):
        preds = by_inst[instrument]
        evaluated = [p for p in preds if p["direction_correct"] is not None]
        correct = [p for p in evaluated if p["direction_correct"]]
        results.append({
            "instrument": instrument,
            "total": len(preds),
            "evaluated": len(evaluated),
            "correct": len(correct),
            "accuracy": _pct(len(correct), len(evaluated)),
        })

    return results


# ---------------------------------------------------------------------------
# Section 4 - Accuracy by Regime
# ---------------------------------------------------------------------------

def section_by_regime(paired: list[dict]) -> list[dict]:
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for p in paired:
        regime = p.get("regime") or "unknown"
        by_regime[regime].append(p)

    results = []
    for regime in sorted(by_regime):
        preds = by_regime[regime]
        evaluated = [p for p in preds if p["direction_correct"] is not None]
        correct = [p for p in evaluated if p["direction_correct"]]
        results.append({
            "regime": regime,
            "total": len(preds),
            "evaluated": len(evaluated),
            "correct": len(correct),
            "accuracy": _pct(len(correct), len(evaluated)),
        })

    return results


# ---------------------------------------------------------------------------
# Section 5 - Forecast Error Metrics
# ---------------------------------------------------------------------------

def section_forecast_errors(paired: list[dict]) -> dict:
    """RMSE and MAE of forecast_end_price vs. actual next price."""
    errors = []
    for p in paired:
        if (
            p["actual_next_price"] is not None
            and p["forecast_end_price"] is not None
            and p["current_price"] is not None
        ):
            err = p["forecast_end_price"] - p["actual_next_price"]
            abs_err = abs(err)
            # Percentage error relative to current price
            pct_err = abs_err / p["current_price"] * 100 if p["current_price"] else 0
            errors.append({
                "error": err,
                "abs_error": abs_err,
                "pct_error": pct_err,
                "instrument": p["instrument"],
            })

    if not errors:
        return {"rmse": None, "mae": None, "count": 0, "by_instrument": {}}

    mae = sum(e["abs_error"] for e in errors) / len(errors)
    rmse = math.sqrt(sum(e["error"] ** 2 for e in errors) / len(errors))
    mean_pct = sum(e["pct_error"] for e in errors) / len(errors)

    # Per instrument
    by_inst: dict[str, list] = defaultdict(list)
    for e in errors:
        by_inst[e["instrument"]].append(e)

    inst_metrics = {}
    for inst in sorted(by_inst):
        errs = by_inst[inst]
        inst_mae = sum(e["abs_error"] for e in errs) / len(errs)
        inst_rmse = math.sqrt(sum(e["error"] ** 2 for e in errs) / len(errs))
        inst_pct = sum(e["pct_error"] for e in errs) / len(errs)
        inst_metrics[inst] = {
            "mae": inst_mae,
            "rmse": inst_rmse,
            "mean_pct_error": inst_pct,
            "count": len(errs),
        }

    return {
        "rmse": rmse,
        "mae": mae,
        "mean_pct_error": mean_pct,
        "count": len(errors),
        "by_instrument": inst_metrics,
    }


# ---------------------------------------------------------------------------
# Section 6 - Trade Outcome Summary
# ---------------------------------------------------------------------------

def section_trade_outcomes(trades: list[dict]) -> dict:
    """Win/loss/win_rate for trades with realized P&L."""
    closed = [t for t in trades if t["pnl_dollars"] is not None]
    if not closed:
        return {"count": 0, "wins": 0, "losses": 0, "breakeven": 0,
                "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0,
                "avg_winner": 0.0, "avg_loser": 0.0, "profit_factor": 0.0,
                "by_status": {}}

    wins = [t for t in closed if t["pnl_dollars"] > 0]
    losses = [t for t in closed if t["pnl_dollars"] < 0]
    breakeven = [t for t in closed if t["pnl_dollars"] == 0]

    total_pnl = sum(t["pnl_dollars"] for t in closed)
    gross_profit = sum(t["pnl_dollars"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_dollars"] for t in losses)) if losses else 0

    avg_winner = gross_profit / len(wins) if wins else 0
    avg_loser = -gross_loss / len(losses) if losses else 0

    # Breakdown by execution status
    by_status: dict[str, dict] = {}
    statuses = set(t["execution_status"] for t in trades)
    for status in sorted(statuses):
        subset = [t for t in trades if t["execution_status"] == status]
        with_pnl = [t for t in subset if t["pnl_dollars"] is not None]
        sub_wins = [t for t in with_pnl if t["pnl_dollars"] > 0]
        by_status[status] = {
            "total": len(subset),
            "with_pnl": len(with_pnl),
            "wins": len(sub_wins),
            "win_rate": _pct(len(sub_wins), len(with_pnl)),
            "pnl": sum(t["pnl_dollars"] for t in with_pnl) if with_pnl else 0,
        }

    return {
        "count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": _pct(len(wins), len(closed)),
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(closed),
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "profit_factor": _safe_div(gross_profit, gross_loss, default=float("inf")),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "by_status": by_status,
    }


# ---------------------------------------------------------------------------
# Section 7 - Tier Performance
# ---------------------------------------------------------------------------

def section_tier_performance(trades: list[dict]) -> list[dict]:
    """Per shot-tier: count, win_rate, total P&L, avg P&L, profit factor."""
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        tier = t.get("shot_tier") or "unknown"
        by_tier[tier].append(t)

    results = []
    for tier in sorted(by_tier):
        subset = by_tier[tier]
        closed = [t for t in subset if t["pnl_dollars"] is not None]
        wins = [t for t in closed if t["pnl_dollars"] > 0]
        losses = [t for t in closed if t["pnl_dollars"] < 0]

        total_pnl = sum(t["pnl_dollars"] for t in closed) if closed else 0
        avg_pnl = total_pnl / len(closed) if closed else 0
        gross_profit = sum(t["pnl_dollars"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl_dollars"] for t in losses)) if losses else 0
        pf = _safe_div(gross_profit, gross_loss, default=float("inf"))

        avg_time = None
        timed = [t for t in closed if t["time_in_trade_minutes"] is not None]
        if timed:
            avg_time = sum(t["time_in_trade_minutes"] for t in timed) / len(timed)

        results.append({
            "tier": tier,
            "total_trades": len(subset),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": _pct(len(wins), len(closed)),
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "profit_factor": pf,
            "avg_time_minutes": avg_time,
        })

    return results


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def compute_verdict(paired: list[dict]) -> dict:
    """
    GO / CAUTION / NO-GO based on directional accuracy at confidence > 0.45.
    """
    high_conf = [
        p for p in paired
        if (p.get("composite_confidence") or 0) > VERDICT_CONFIDENCE_FLOOR
        and p["direction_correct"] is not None
    ]

    if not high_conf:
        return {
            "verdict": "INSUFFICIENT DATA",
            "detail": (
                f"No evaluated predictions with confidence > {VERDICT_CONFIDENCE_FLOOR}. "
                "Need more data before making a determination."
            ),
            "accuracy": None,
            "sample_size": 0,
        }

    correct = [p for p in high_conf if p["direction_correct"]]
    accuracy = len(correct) / len(high_conf)
    n = len(high_conf)

    if accuracy > VERDICT_THRESHOLD_GO:
        verdict = "GO"
        detail = (
            f"Directional accuracy {accuracy:.1%} (n={n}) at confidence > {VERDICT_CONFIDENCE_FLOOR} "
            f"exceeds {VERDICT_THRESHOLD_GO:.0%} threshold. Model shows predictive edge."
        )
    elif accuracy >= VERDICT_THRESHOLD_CAUTION:
        verdict = "CAUTION"
        detail = (
            f"Directional accuracy {accuracy:.1%} (n={n}) at confidence > {VERDICT_CONFIDENCE_FLOOR} "
            f"is between {VERDICT_THRESHOLD_CAUTION:.0%} and {VERDICT_THRESHOLD_GO:.0%}. "
            "Edge is marginal -- increase sample size or tighten filters before going live."
        )
    else:
        verdict = "NO-GO"
        detail = (
            f"Directional accuracy {accuracy:.1%} (n={n}) at confidence > {VERDICT_CONFIDENCE_FLOOR} "
            f"is below {VERDICT_THRESHOLD_CAUTION:.0%}. Model does not demonstrate predictive edge. "
            "Do NOT trade live."
        )

    # Statistical significance note
    if n < 30:
        detail += (
            f"\n         NOTE: Sample size ({n}) is below 30. "
            "Results are not statistically reliable. Collect more data."
        )

    return {
        "verdict": verdict,
        "detail": detail,
        "accuracy": accuracy,
        "sample_size": n,
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(
    directional: dict,
    conf_bins: list[dict],
    by_instrument: list[dict],
    by_regime: list[dict],
    forecast_errors: dict,
    trade_outcomes: dict,
    tier_perf: list[dict],
    verdict: dict,
):
    print()
    print(DOUBLE_LINE)
    print("  PREDICTION ACCURACY ANALYSIS")
    print(DOUBLE_LINE)

    # ── Section 1: Directional Accuracy ──────────────────────────────
    print()
    print("  1. DIRECTIONAL ACCURACY")
    print(LINE)
    print(f"  Total predictions:        {directional['total_predictions']}")
    print(f"  Neutral (excluded):       {directional['neutrals']}")
    print(f"  Unpaired / last (excluded): {directional['unpaired']}")
    print(f"  Evaluated:                {directional['total_evaluated']}")
    print(f"  Correct:                  {directional['correct']}")
    print(f"  Accuracy:                 {directional['accuracy']:.1f}%")
    print()
    print(f"  {'Direction':<12} {'Evaluated':>10} {'Correct':>10} {'Accuracy':>10}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
    for direction in ("long", "short"):
        d = directional["by_direction"].get(direction, {})
        print(
            f"  {direction:<12} {d.get('total', 0):>10} "
            f"{d.get('correct', 0):>10} "
            f"{d.get('accuracy', 0):>9.1f}%"
        )

    # ── Section 2: Confidence Bins ───────────────────────────────────
    print()
    print()
    print("  2. ACCURACY BY CONFIDENCE BIN")
    print(LINE)
    header = f"  {'Bin':<14} {'Count':>7} {'Eval':>7} {'Correct':>8} {'Acc%':>7} {'Avg Fcst Err':>13}"
    print(header)
    print(f"  {'-'*14} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*13}")
    for b in conf_bins:
        err_str = f"{b['avg_forecast_error']:>13.2f}" if b["avg_forecast_error"] is not None else f"{'n/a':>13}"
        acc_str = f"{b['accuracy']:>6.1f}%" if b["evaluated"] > 0 else f"{'n/a':>7}"
        print(
            f"  {b['label']:<14} {b['count']:>7} {b['evaluated']:>7} "
            f"{b['correct']:>8} {acc_str} {err_str}"
        )

    # ── Section 3: By Instrument ─────────────────────────────────────
    print()
    print()
    print("  3. ACCURACY BY INSTRUMENT")
    print(LINE)
    print(f"  {'Instrument':<12} {'Total':>8} {'Evaluated':>10} {'Correct':>8} {'Accuracy':>10}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*8} {'-'*10}")
    for row in by_instrument:
        acc_str = f"{row['accuracy']:>9.1f}%" if row["evaluated"] > 0 else f"{'n/a':>10}"
        print(
            f"  {row['instrument']:<12} {row['total']:>8} {row['evaluated']:>10} "
            f"{row['correct']:>8} {acc_str}"
        )

    # ── Section 4: By Regime ─────────────────────────────────────────
    print()
    print()
    print("  4. ACCURACY BY REGIME")
    print(LINE)
    print(f"  {'Regime':<12} {'Total':>8} {'Evaluated':>10} {'Correct':>8} {'Accuracy':>10}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*8} {'-'*10}")
    for row in by_regime:
        acc_str = f"{row['accuracy']:>9.1f}%" if row["evaluated"] > 0 else f"{'n/a':>10}"
        print(
            f"  {row['regime']:<12} {row['total']:>8} {row['evaluated']:>10} "
            f"{row['correct']:>8} {acc_str}"
        )

    # ── Section 5: Forecast Error ────────────────────────────────────
    print()
    print()
    print("  5. FORECAST ERROR METRICS")
    print(LINE)
    if forecast_errors["count"] == 0:
        print("  No forecast/actual pairs available.")
    else:
        print(f"  Observations:     {forecast_errors['count']}")
        print(f"  MAE  (points):    {forecast_errors['mae']:.4f}")
        print(f"  RMSE (points):    {forecast_errors['rmse']:.4f}")
        print(f"  Mean % Error:     {forecast_errors['mean_pct_error']:.4f}%")
        print()
        print(f"  {'Instrument':<12} {'Count':>7} {'MAE':>12} {'RMSE':>12} {'Mean%Err':>10}")
        print(f"  {'-'*12} {'-'*7} {'-'*12} {'-'*12} {'-'*10}")
        for inst, m in forecast_errors["by_instrument"].items():
            print(
                f"  {inst:<12} {m['count']:>7} {m['mae']:>12.4f} "
                f"{m['rmse']:>12.4f} {m['mean_pct_error']:>9.4f}%"
            )

    # ── Section 6: Trade Outcome Summary ─────────────────────────────
    print()
    print()
    print("  6. TRADE OUTCOME SUMMARY")
    print(LINE)
    to = trade_outcomes
    if to["count"] == 0:
        print("  No closed trades with P&L data.")
    else:
        print(f"  Closed trades:    {to['count']}")
        print(f"  Wins:             {to['wins']}")
        print(f"  Losses:           {to['losses']}")
        print(f"  Breakeven:        {to['breakeven']}")
        print(f"  Win rate:         {to['win_rate']:.1f}%")
        print()
        print(f"  Total P&L:        ${to['total_pnl']:>+,.2f}")
        print(f"  Avg P&L/trade:    ${to['avg_pnl']:>+,.2f}")
        print(f"  Avg winner:       ${to['avg_winner']:>+,.2f}")
        print(f"  Avg loser:        ${to['avg_loser']:>+,.2f}")
        print(f"  Gross profit:     ${to['gross_profit']:>+,.2f}")
        print(f"  Gross loss:       ${to['gross_loss']:>,.2f}")
        pf = to["profit_factor"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf (no losses)"
        print(f"  Profit factor:    {pf_str}")

        if to["by_status"]:
            print()
            print(f"  {'Status':<14} {'Total':>7} {'W/PnL':>7} {'Wins':>6} {'WR%':>7} {'P&L':>12}")
            print(f"  {'-'*14} {'-'*7} {'-'*7} {'-'*6} {'-'*7} {'-'*12}")
            for status, s in to["by_status"].items():
                print(
                    f"  {status:<14} {s['total']:>7} {s['with_pnl']:>7} "
                    f"{s['wins']:>6} {s['win_rate']:>6.1f}% ${s['pnl']:>+10,.2f}"
                )

    # ── Section 7: Tier Performance ──────────────────────────────────
    print()
    print()
    print("  7. SHOT TIER PERFORMANCE")
    print(LINE)
    if not tier_perf:
        print("  No trade data by tier.")
    else:
        print(
            f"  {'Tier':<16} {'Trades':>7} {'Closed':>7} {'W':>4} {'L':>4} "
            f"{'WR%':>7} {'Total P&L':>12} {'Avg P&L':>10} {'PF':>7} {'Avg Min':>8}"
        )
        print(
            f"  {'-'*16} {'-'*7} {'-'*7} {'-'*4} {'-'*4} "
            f"{'-'*7} {'-'*12} {'-'*10} {'-'*7} {'-'*8}"
        )
        for t in tier_perf:
            pf = t["profit_factor"]
            pf_str = f"{pf:>7.2f}" if pf != float("inf") else f"{'inf':>7}"
            time_str = f"{t['avg_time_minutes']:>7.1f}" if t["avg_time_minutes"] is not None else f"{'n/a':>8}"
            print(
                f"  {t['tier']:<16} {t['total_trades']:>7} {t['closed']:>7} "
                f"{t['wins']:>4} {t['losses']:>4} "
                f"{t['win_rate']:>6.1f}% ${t['total_pnl']:>+10,.2f} "
                f"${t['avg_pnl']:>+8,.2f} {pf_str} {time_str}"
            )

    # ── Verdict ──────────────────────────────────────────────────────
    print()
    print()
    print(DOUBLE_LINE)
    v = verdict["verdict"]
    if v == "GO":
        tag = "[  GO  ]"
    elif v == "CAUTION":
        tag = "[CAUTION]"
    elif v == "NO-GO":
        tag = "[ NO-GO ]"
    else:
        tag = "[ ??? ]"

    print(f"  VERDICT:  {tag}  {v}")
    print(LINE)
    print(f"  {verdict['detail']}")
    if verdict["accuracy"] is not None:
        print()
        print(f"  High-confidence accuracy: {verdict['accuracy']:.1%}  (n={verdict['sample_size']})")
        print(f"  Threshold GO > {VERDICT_THRESHOLD_GO:.0%}  |  CAUTION {VERDICT_THRESHOLD_CAUTION:.0%}-{VERDICT_THRESHOLD_GO:.0%}  |  NO-GO < {VERDICT_THRESHOLD_CAUTION:.0%}")
    print(DOUBLE_LINE)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze prediction accuracy from the trade log database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/analyze_predictions.py\n"
            "  python scripts/analyze_predictions.py --db ./data/trade_log.db\n"
        ),
    )
    parser.add_argument(
        "--db",
        type=str,
        default="./data/trade_log.db",
        help="Path to the SQLite trade log database (default: ./data/trade_log.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path.resolve()}")
        print("Run the trading system first to generate prediction data.")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = None  # We handle dict conversion ourselves

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    predictions = load_predictions(conn)
    trades = load_trades(conn)
    conn.close()

    if not predictions:
        print()
        print(DOUBLE_LINE)
        print("  PREDICTION ACCURACY ANALYSIS")
        print(DOUBLE_LINE)
        print()
        print("  Database is empty -- no predictions recorded yet.")
        print("  Run the trading system to generate data, then re-run this script.")
        print()
        print(DOUBLE_LINE)
        print()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Pair predictions with next-observation prices
    # ------------------------------------------------------------------
    paired = pair_predictions(predictions)

    # ------------------------------------------------------------------
    # Compute all sections
    # ------------------------------------------------------------------
    directional = section_directional_accuracy(paired)
    conf_bins = section_confidence_bins(paired)
    by_instrument = section_by_instrument(paired)
    by_regime = section_by_regime(paired)
    forecast_errors = section_forecast_errors(paired)
    trade_outcomes = section_trade_outcomes(trades)
    tier_perf = section_tier_performance(trades)
    verdict = compute_verdict(paired)

    # ------------------------------------------------------------------
    # Print the report
    # ------------------------------------------------------------------
    print_report(
        directional=directional,
        conf_bins=conf_bins,
        by_instrument=by_instrument,
        by_regime=by_regime,
        forecast_errors=forecast_errors,
        trade_outcomes=trade_outcomes,
        tier_perf=tier_perf,
        verdict=verdict,
    )


if __name__ == "__main__":
    main()
