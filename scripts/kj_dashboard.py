#!/usr/bin/env python3
"""
KJ Strategy Dashboard — public web UI for sharing KJ setups.

Scans all active instruments, generates interactive Plotly charts,
and serves a clean dashboard at http://localhost:5055.

Usage:
    python scripts/kj_dashboard.py
    python scripts/kj_dashboard.py --port 8080
"""

import argparse
import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, send_file, abort

# Project root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from market_data.yfinance_provider import fetch_ohlcv
from kj_strategy.scanner import scan_kj_setups
from kj_strategy.chart import generate_chart

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=str(ROOT / "templates"))

INSTRUMENTS = ["MNQ", "MYM", "MES", "MBT"]
CHART_DIR = ROOT / "reports" / "kj_charts"

# In-memory cache of latest scan results
_cache = {
    "setups": [],        # list of dicts for template rendering
    "last_scan": None,   # ISO timestamp
    "scanning": False,
}


def _setup_to_dict(s) -> dict:
    """Convert a KJSetup to a JSON-serializable dict for the template."""
    pat = s.patterns[0] if s.patterns else None
    return {
        "setup_id": s.setup_id,
        "instrument": s.instrument,
        "direction": s.trend_direction,
        "fib_level": s.active_fib_level,
        "pattern": pat.pattern_type.replace("_", " ").title() if pat else "—",
        "pattern_confidence": f"{pat.confidence:.0%}" if pat else "—",
        "entry_price": f"{s.entry_price:,.2f}",
        "stop_loss": f"{s.stop_loss:,.2f}",
        "take_profit": f"{s.take_profit:,.2f}",
        "rr": f"{s.reward_risk_ratio:.1f}",
        "score": int(s.textbook_score),
        "classification": s.classification,
        "outcome": s.outcome or "pending",
        "actual_rr": f"{s.actual_rr:+.1f}R" if s.actual_rr is not None else "—",
        "entry_time": s.entry_timestamp.strftime("%m/%d %H:%M") if s.entry_timestamp else "—",
        "chart_path": s.chart_path,
    }


def run_scan():
    """Scan all instruments and cache results."""
    if _cache["scanning"]:
        return
    _cache["scanning"] = True
    logger.info("Starting KJ scan across %s", INSTRUMENTS)

    all_setups = []
    for instrument in INSTRUMENTS:
        try:
            bars = fetch_ohlcv(instrument, bars=500, interval="5m")
            setups = scan_kj_setups(instrument, bars)
            for s in setups:
                generate_chart(s, bars, output_dir=str(CHART_DIR))
                all_setups.append(s)
            logger.info("%s: %d setups found", instrument, len(setups))
        except Exception as e:
            logger.error("Scan failed for %s: %s", instrument, e)

    # Sort by score descending
    all_setups.sort(key=lambda s: s.textbook_score, reverse=True)

    _cache["setups"] = [_setup_to_dict(s) for s in all_setups]
    _cache["last_scan"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _cache["scanning"] = False
    logger.info("Scan complete: %d total setups", len(all_setups))


# ── Routes ──────────────────────────────────────────────────────────


@app.route("/")
def index():
    """Landing page with all setups."""
    # Separate textbook vs regular
    textbook = [s for s in _cache["setups"] if s["classification"] == "textbook"]
    regular = [s for s in _cache["setups"] if s["classification"] == "regular"]

    # Stats
    total = len(_cache["setups"])
    wins = sum(1 for s in _cache["setups"] if s["outcome"] == "win")
    losses = sum(1 for s in _cache["setups"] if s["outcome"] == "loss")
    win_rate = f"{wins / (wins + losses) * 100:.0f}%" if (wins + losses) > 0 else "—"

    return render_template(
        "kj_dashboard.html",
        textbook=textbook,
        regular=regular,
        total=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        last_scan=_cache["last_scan"] or "Never",
        scanning=_cache["scanning"],
        instruments=INSTRUMENTS,
    )


@app.route("/chart/<setup_id>")
def view_chart(setup_id):
    """Serve an individual chart HTML file."""
    # Find the chart file
    matches = list(CHART_DIR.glob(f"*_{setup_id}_*.html"))
    if not matches:
        abort(404, f"Chart not found for setup {setup_id}")
    return send_file(matches[0])


@app.route("/api/setups")
def api_setups():
    """JSON API for all cached setups."""
    return jsonify({
        "setups": _cache["setups"],
        "last_scan": _cache["last_scan"],
        "scanning": _cache["scanning"],
    })


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    """Trigger a fresh scan in the background."""
    if _cache["scanning"]:
        return jsonify({"status": "already_scanning"})
    threading.Thread(target=run_scan, daemon=True).start()
    return jsonify({"status": "started"})


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KJ Strategy Dashboard")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-scan", action="store_true", help="Skip initial scan")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.no_scan:
        print("Running initial scan (this takes ~30s)...")
        run_scan()
        print(f"Scan complete: {len(_cache['setups'])} setups found")

    print(f"\n  KJ Dashboard running at http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)
