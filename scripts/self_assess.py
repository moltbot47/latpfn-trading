#!/usr/bin/env python3
"""
Self-assessment: loads the latest optimization report and produces a
go/no-go recommendation with plain-language reasoning.

Usage:
    python scripts/self_assess.py
    python scripts/self_assess.py --report reports/optimization_NQ_20260207.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def assess(report_path: str = None, account_equity: float = 50000.0):
    """Load optimization results and produce a trading readiness assessment.

    Args:
        report_path: Path to optimization JSON. If None, uses latest.
        account_equity: Account equity for drawdown % calculation.
    """
    # Find latest report
    reports_dir = Path("./reports")
    if report_path:
        path = Path(report_path)
    else:
        json_files = sorted(reports_dir.glob("optimization_*.json"), reverse=True)
        if not json_files:
            print("No optimization reports found. Run auto_optimize.py first.")
            return
        path = json_files[0]

    print(f"Analyzing: {path}\n")

    with open(path) as f:
        results = json.load(f)

    # Extract instrument from filename
    instrument = path.stem.split("_")[1] if "_" in path.stem else "Unknown"

    # ── Analysis ──────────────────────────────────────────────────

    total = len(results)
    profitable = [r for r in results if r["metrics"]["total_pnl"] > 0 and r["metrics"]["total_trades"] >= 3]
    best = max(results, key=lambda r: r["metrics"]["score"])
    bm = best["metrics"]
    bp = best["params"]

    pct_profitable = len(profitable) / total * 100 if total > 0 else 0
    avg_sharpe = sum(r["metrics"]["sharpe"] for r in profitable) / len(profitable) if profitable else 0
    avg_pf = sum(r["metrics"]["profit_factor"] for r in profitable) / len(profitable) if profitable else 0

    # ── Scoring criteria ──────────────────────────────────────────

    checks = []

    # 1. Enough trades?
    if bm["total_trades"] >= 20:
        checks.append(("Sufficient sample size", True, f"{bm['total_trades']} trades"))
    elif bm["total_trades"] >= 10:
        checks.append(("Marginal sample size", True, f"{bm['total_trades']} trades — borderline"))
    else:
        checks.append(("Insufficient sample size", False, f"Only {bm['total_trades']} trades — need 20+"))

    # 2. Positive Sharpe?
    if bm["sharpe"] >= 1.5:
        checks.append(("Strong Sharpe ratio", True, f"{bm['sharpe']}"))
    elif bm["sharpe"] >= 0.5:
        checks.append(("Acceptable Sharpe ratio", True, f"{bm['sharpe']}"))
    elif bm["sharpe"] > 0:
        checks.append(("Weak Sharpe ratio", False, f"{bm['sharpe']} — below 0.5"))
    else:
        checks.append(("Negative Sharpe ratio", False, f"{bm['sharpe']} — losing strategy"))

    # 3. Profit factor > 1?
    if bm["profit_factor"] >= 1.5:
        checks.append(("Healthy profit factor", True, f"{bm['profit_factor']}"))
    elif bm["profit_factor"] >= 1.1:
        checks.append(("Marginal profit factor", True, f"{bm['profit_factor']}"))
    else:
        checks.append(("Poor profit factor", False, f"{bm['profit_factor']}"))

    # 4. Win rate reasonable?
    if 40 <= bm["win_rate"] <= 75:
        checks.append(("Healthy win rate", True, f"{bm['win_rate']}%"))
    elif bm["win_rate"] > 75:
        checks.append(("Suspiciously high win rate", False, f"{bm['win_rate']}% — may be overfitted"))
    else:
        checks.append(("Low win rate", False, f"{bm['win_rate']}%"))

    # 5. Max drawdown acceptable?
    dd_pct = bm["max_drawdown"] / account_equity * 100
    if dd_pct < 5:
        checks.append(("Low drawdown", True, f"${bm['max_drawdown']:,.2f} ({dd_pct:.1f}%)"))
    elif dd_pct < 10:
        checks.append(("Moderate drawdown", True, f"${bm['max_drawdown']:,.2f} ({dd_pct:.1f}%)"))
    else:
        checks.append(("Excessive drawdown", False, f"${bm['max_drawdown']:,.2f} ({dd_pct:.1f}%)"))

    # 6. Robustness: are multiple param sets profitable?
    if pct_profitable >= 50:
        checks.append(("Robust across parameters", True, f"{pct_profitable:.0f}% configs profitable"))
    elif pct_profitable >= 25:
        checks.append(("Somewhat robust", True, f"{pct_profitable:.0f}% configs profitable"))
    else:
        checks.append(("Not robust", False, f"Only {pct_profitable:.0f}% configs profitable"))

    # ── Verdict ───────────────────────────────────────────────────

    passed = sum(1 for _, ok, _ in checks if ok)
    total_checks = len(checks)
    pass_pct = passed / total_checks * 100

    if pass_pct >= 80:
        verdict = "GO — Ready for paper trading"
        verdict_detail = "Strategy shows consistent edge. Proceed with paper trading using the recommended parameters. Monitor for at least 1-2 weeks before considering live."
    elif pass_pct >= 50:
        verdict = "CAUTION — Paper trade with close monitoring"
        verdict_detail = "Strategy shows some promise but has weaknesses. Paper trade and watch for the flagged issues. Do NOT go live until all checks pass."
    else:
        verdict = "NO-GO — Do not trade"
        verdict_detail = "Strategy does not meet minimum viability criteria. Try different timeframes, more context assets, or a longer backtest period."

    # ── Output ────────────────────────────────────────────────────

    print("=" * 60)
    print(f"  SELF-ASSESSMENT: {instrument}")
    print("=" * 60)
    print()

    for name, passed_check, detail in checks:
        icon = "[PASS]" if passed_check else "[FAIL]"
        print(f"  {icon}  {name}: {detail}")

    print()
    print("─" * 60)
    print(f"  Score: {passed}/{total_checks} checks passed ({pass_pct:.0f}%)")
    print()
    print(f"  VERDICT:  {verdict}")
    print()
    print(f"  {verdict_detail}")
    print()

    if bm["total_pnl"] > 0:
        print(f"  Best configuration:")
        print(f"    min_confidence:          {bp['min_confidence']}")
        print(f"    stop_loss_atr_mult:      {bp['stop_loss_atr_mult']}")
        print(f"    min_reward_risk:         {bp['min_reward_risk']}")
        print(f"    Expected: {bm['win_rate']}% win rate, "
              f"${bm['total_pnl']:+,.2f} P&L, "
              f"{bm['sharpe']} Sharpe")

    # ── Per-tier assessment ────────────────────────────────────
    per_tier = bm.get("per_tier", {})
    if per_tier:
        print()
        print("─" * 60)
        print("  SHOT-TIER ASSESSMENT")
        print("─" * 60)
        print()
        for tier, tm in sorted(per_tier.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True):
            ev_positive = tm.get("total_pnl", 0) > 0
            has_trades = tm.get("count", 0) >= 3
            tier_label = tier.replace("_", " ").title()

            if ev_positive and has_trades:
                tier_verdict = "GO"
                icon = "[PASS]"
            elif not has_trades:
                tier_verdict = "INSUFFICIENT DATA"
                icon = "[SKIP]"
            else:
                tier_verdict = "NO-GO (EV-negative)"
                icon = "[FAIL]"

            print(
                f"  {icon}  {tier_label:<16}  {tier_verdict}"
                f"  —  {tm.get('count', 0)} trades, "
                f"${tm.get('total_pnl', 0):+,.2f} P&L, "
                f"{tm.get('win_rate', 0):.1f}% win, "
                f"PF={tm.get('profit_factor', 0):.2f}"
            )

        ev_negative_tiers = [t for t, m in per_tier.items() if m.get("total_pnl", 0) <= 0 and m.get("count", 0) >= 3]
        if ev_negative_tiers:
            print()
            print(f"  RECOMMENDATION: Disable these tiers in config/settings.yaml:")
            for t in ev_negative_tiers:
                print(f"    shot_tiers.{t}.enabled: false")

    print("=" * 60)

    # Return structured result
    return {
        "instrument": instrument,
        "verdict": verdict,
        "checks_passed": passed,
        "checks_total": total_checks,
        "best_params": bp,
        "best_metrics": bm,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-assess trading strategy viability")
    parser.add_argument("--report", type=str, default=None, help="Path to optimization JSON")
    parser.add_argument("--equity", type=float, default=50000, help="Account equity for drawdown %")
    args = parser.parse_args()
    assess(args.report, account_equity=args.equity)
