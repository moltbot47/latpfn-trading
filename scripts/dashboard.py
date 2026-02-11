#!/usr/bin/env python3
"""
Live trading dashboard — Flask web UI.

Reads from existing data files (trade_log.db, positions.json, heartbeat.json,
drawdown_state.json) and serves a real-time dashboard at http://localhost:5050.

Features:
  - Live account overview with progress-to-target
  - Open positions with TP progress bars
  - Performance stats, tier breakdown, equity curve
  - Prediction accuracy by instrument and confidence
  - Tradovate report upload for reconciliation
  - Daily P&L history chart

Usage:
    python scripts/dashboard.py
    python scripts/dashboard.py --port 8080
"""

import argparse
import csv
import io
import json
import sqlite3
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Project root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import load_config

app = Flask(__name__, template_folder=str(ROOT / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "trade_log.db"
REPORT_DB_PATH = DATA_DIR / "broker_reports.db"
POSITIONS_PATH = DATA_DIR / "positions.json"
HEARTBEAT_PATH = DATA_DIR / "heartbeat.json"
DRAWDOWN_PATH = DATA_DIR / "drawdown_state.json"


# ── Helpers ────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_report_db():
    conn = sqlite3.connect(str(REPORT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_report_db():
    """Create broker report tables if they don't exist."""
    conn = _get_report_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS broker_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            actual_balance      REAL,
            actual_pnl_today    REAL,
            actual_total_pnl    REAL,
            actual_trades_today INTEGER,
            commissions         REAL DEFAULT 0,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(report_date)
        );

        CREATE TABLE IF NOT EXISTS broker_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date     TEXT NOT NULL,
            timestamp       TEXT,
            instrument      TEXT,
            direction       TEXT,
            quantity        INTEGER,
            entry_price     REAL,
            exit_price      REAL,
            pnl             REAL,
            commission      REAL DEFAULT 0,
            order_id        TEXT,
            raw_symbol      TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()
    conn.close()


# Initialize on import
_init_report_db()


# ── API: System Status ─────────────────────────────────────────────────


@app.route("/api/status")
def api_status():
    heartbeat = _read_json(HEARTBEAT_PATH)
    if heartbeat:
        try:
            ts = datetime.fromisoformat(heartbeat["timestamp"])
            age_sec = (datetime.now() - ts).total_seconds()
            heartbeat["age_seconds"] = round(age_sec, 1)
            heartbeat["alive"] = age_sec < 600  # 10 min threshold
        except Exception:
            heartbeat["alive"] = False
            heartbeat["age_seconds"] = -1
    else:
        heartbeat = {"alive": False, "age_seconds": -1, "cycle": 0}

    return jsonify(heartbeat)


# ── API: Account / Drawdown ────────────────────────────────────────────


@app.route("/api/account")
def api_account():
    drawdown = _read_json(DRAWDOWN_PATH) or {}
    config = load_config()
    prop = config.get("risk", {}).get("prop_firm", {})

    starting = prop.get("starting_balance", 50000)
    highest = drawdown.get("highest_balance", starting)
    floor = drawdown.get("drawdown_floor", starting - prop.get("max_total_drawdown_usd", 2500))
    locked = drawdown.get("floor_locked", False)

    # Daily P&L from today's trades
    daily_pnl = 0.0
    conn = _get_db()
    if conn:
        try:
            today = date.today().isoformat()
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) as pnl FROM trades "
                "WHERE timestamp LIKE ? || '%' AND execution_status='executed' AND pnl_dollars IS NOT NULL",
                (today,),
            ).fetchone()
            daily_pnl = row["pnl"] if row else 0.0
        except Exception:
            pass
        finally:
            conn.close()

    # Estimate current equity from positions
    positions = _read_json(POSITIONS_PATH) or []
    unrealized = 0.0
    for p in positions:
        cp = p.get("current_price", 0)
        ep = p.get("entry_price", 0)
        sz = p.get("size", 0)
        if cp and ep:
            inst = p.get("instrument", "")
            inst_cfg = config.get("instruments", {}).get(inst, {})
            cs = inst_cfg.get("contract_size", 1.0)
            if p.get("direction") == "long":
                unrealized += (cp - ep) * sz * cs
            else:
                unrealized += (ep - cp) * sz * cs

    cushion = highest + unrealized + daily_pnl - floor

    # Check for broker override for today
    broker_override = None
    try:
        rconn = _get_report_db()
        today_str = date.today().isoformat()
        row = rconn.execute(
            "SELECT actual_balance, actual_pnl_today, actual_total_pnl FROM broker_snapshots WHERE report_date=?",
            (today_str,),
        ).fetchone()
        if row and row["actual_balance"]:
            broker_override = {
                "actual_balance": row["actual_balance"],
                "actual_pnl_today": row["actual_pnl_today"],
                "actual_total_pnl": row["actual_total_pnl"],
            }
        rconn.close()
    except Exception:
        pass

    profit_target = prop.get("profit_target_usd", 3000)
    total_pnl = daily_pnl + unrealized
    if broker_override and broker_override.get("actual_total_pnl") is not None:
        total_pnl = broker_override["actual_total_pnl"]

    return jsonify({
        "starting_balance": starting,
        "highest_balance": highest,
        "drawdown_floor": floor,
        "floor_locked": locked,
        "daily_pnl": round(daily_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "estimated_equity": round(starting + daily_pnl + unrealized, 2),
        "cushion": round(cushion, 2),
        "max_daily_loss": prop.get("max_daily_loss_usd", 1000),
        "profit_target": profit_target,
        "total_pnl": round(total_pnl, 2),
        "progress_pct": round(total_pnl / profit_target * 100, 1) if profit_target else 0,
        "broker_override": broker_override,
    })


# ── API: Open Positions ────────────────────────────────────────────────


@app.route("/api/positions")
def api_positions():
    positions = _read_json(POSITIONS_PATH) or []
    config = load_config()

    result = []
    for p in positions:
        inst = p.get("instrument", "")
        inst_cfg = config.get("instruments", {}).get(inst, {})
        cs = inst_cfg.get("contract_size", 1.0)
        cp = p.get("current_price", 0)
        ep = p.get("entry_price", 0)
        sz = p.get("size", 0)
        direction = p.get("direction", "long")

        if direction == "long":
            unrealized = (cp - ep) * sz * cs if cp else 0
        else:
            unrealized = (ep - cp) * sz * cs if cp else 0

        # Time held
        entry_time = p.get("entry_time", "")
        held_minutes = 0
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                held_minutes = round((datetime.now() - et).total_seconds() / 60, 1)
            except Exception:
                pass

        # TP/SL distances
        tp_dist = abs(p.get("take_profit", ep) - ep)
        sl_dist = abs(p.get("stop_loss", ep) - ep)
        tp_pct = round((cp - ep) / tp_dist * 100, 1) if tp_dist and cp and direction == "long" else 0
        if direction == "short" and tp_dist and cp:
            tp_pct = round((ep - cp) / tp_dist * 100, 1)

        result.append({
            "instrument": inst,
            "name": inst_cfg.get("name", inst),
            "direction": direction,
            "size": sz,
            "entry_price": ep,
            "current_price": cp,
            "stop_loss": round(p.get("stop_loss", 0), 2),
            "take_profit": round(p.get("take_profit", 0), 2),
            "unrealized_pnl": round(unrealized, 2),
            "held_minutes": held_minutes,
            "tp_progress_pct": tp_pct,
            "stale": held_minutes > 1440,  # >24h
        })

    return jsonify(result)


# ── API: Performance ───────────────────────────────────────────────────


@app.route("/api/performance")
def api_performance():
    conn = _get_db()
    if not conn:
        return jsonify({"error": "No database"})

    try:
        rows = conn.execute(
            "SELECT pnl_dollars, shot_tier, exit_reason, direction, execution_status "
            "FROM trades WHERE execution_status='executed' AND pnl_dollars IS NOT NULL "
            "ORDER BY timestamp"
        ).fetchall()

        if not rows:
            return jsonify({"total_trades": 0})

        pnls = [r["pnl_dollars"] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Equity curve
        import numpy as np
        equity_curve = list(np.cumsum(pnls).round(2))
        peak = np.maximum.accumulate(np.cumsum(pnls))
        dd = peak - np.cumsum(pnls)
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0

        # Per-tier
        tiers = {}
        for r in rows:
            tier = r["shot_tier"] or "unknown"
            if tier not in tiers:
                tiers[tier] = {"count": 0, "wins": 0, "pnl": 0.0, "gross_wins": 0.0, "gross_losses": 0.0}
            tiers[tier]["count"] += 1
            tiers[tier]["pnl"] += r["pnl_dollars"]
            if r["pnl_dollars"] > 0:
                tiers[tier]["wins"] += 1
                tiers[tier]["gross_wins"] += r["pnl_dollars"]
            else:
                tiers[tier]["gross_losses"] += abs(r["pnl_dollars"])

        tier_stats = {}
        for tier, s in tiers.items():
            tier_stats[tier] = {
                "count": s["count"],
                "wins": s["wins"],
                "win_rate": round(s["wins"] / s["count"] * 100, 1) if s["count"] else 0,
                "total_pnl": round(s["pnl"], 2),
                "avg_pnl": round(s["pnl"] / s["count"], 2) if s["count"] else 0,
                "profit_factor": round(s["gross_wins"] / s["gross_losses"], 2) if s["gross_losses"] > 0 else 99.0,
            }

        # Exit reasons
        exits = {}
        for r in rows:
            reason = r["exit_reason"] or "unknown"
            exits[reason] = exits.get(reason, 0) + 1

        # Direction breakdown
        longs = [r["pnl_dollars"] for r in rows if r["direction"] == "long"]
        shorts = [r["pnl_dollars"] for r in rows if r["direction"] == "short"]

        return jsonify({
            "total_trades": len(pnls),
            "win_rate": round(len(wins) / len(pnls) * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 99.0,
            "max_drawdown": round(max_dd, 2),
            "equity_curve": equity_curve,
            "per_tier": tier_stats,
            "exit_reasons": exits,
            "long_pnl": round(sum(longs), 2),
            "short_pnl": round(sum(shorts), 2),
            "long_count": len(longs),
            "short_count": len(shorts),
        })
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Recent Trades ─────────────────────────────────────────────────


@app.route("/api/trades/recent")
def api_recent_trades():
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        rows = conn.execute(
            "SELECT timestamp, instrument, direction, shot_tier, entry_price, "
            "stop_loss, take_profit, position_size, pnl_dollars, exit_reason, "
            "exit_price, time_in_trade_minutes, execution_status "
            "FROM trades ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Prediction Accuracy ──────────────────────────────────────────


@app.route("/api/predictions")
def api_predictions():
    conn = _get_db()
    if not conn:
        return jsonify({"error": "No database"})

    try:
        rows = conn.execute(
            "SELECT instrument, direction, composite_confidence, regime, "
            "current_price, forecast_end_price, signal_generated "
            "FROM predictions ORDER BY instrument, timestamp, id"
        ).fetchall()

        if not rows:
            return jsonify({"total": 0})

        preds = [dict(r) for r in rows]

        by_inst = {}
        for p in preds:
            inst = p["instrument"]
            if inst not in by_inst:
                by_inst[inst] = []
            by_inst[inst].append(p)

        correct = 0
        evaluated = 0
        inst_stats = {}

        for inst, ps in by_inst.items():
            inst_correct = 0
            inst_eval = 0
            for i in range(len(ps) - 1):
                curr = ps[i]
                nxt = ps[i + 1]
                if not curr.get("current_price") or not nxt.get("current_price"):
                    continue
                actual_move = nxt["current_price"] - curr["current_price"]
                if actual_move == 0:
                    continue
                predicted_dir = curr["direction"]
                actual_dir = "long" if actual_move > 0 else "short"
                evaluated += 1
                inst_eval += 1
                if predicted_dir == actual_dir:
                    correct += 1
                    inst_correct += 1

            if inst_eval > 0:
                inst_stats[inst] = {
                    "evaluated": inst_eval,
                    "accuracy": round(inst_correct / inst_eval * 100, 1),
                }

        conf_bins = {}
        for inst, ps in by_inst.items():
            for i in range(len(ps) - 1):
                curr = ps[i]
                nxt = ps[i + 1]
                if not curr.get("current_price") or not nxt.get("current_price"):
                    continue
                actual_move = nxt["current_price"] - curr["current_price"]
                if actual_move == 0:
                    continue

                conf = curr.get("composite_confidence", 0) or 0
                if conf < 0.35:
                    bin_name = "<0.35"
                elif conf < 0.45:
                    bin_name = "0.35-0.45"
                elif conf < 0.55:
                    bin_name = "0.45-0.55"
                elif conf < 0.65:
                    bin_name = "0.55-0.65"
                else:
                    bin_name = "0.65+"

                if bin_name not in conf_bins:
                    conf_bins[bin_name] = {"total": 0, "correct": 0}
                conf_bins[bin_name]["total"] += 1

                predicted_dir = curr["direction"]
                actual_dir = "long" if actual_move > 0 else "short"
                if predicted_dir == actual_dir:
                    conf_bins[bin_name]["correct"] += 1

        for b in conf_bins.values():
            b["accuracy"] = round(b["correct"] / b["total"] * 100, 1) if b["total"] > 0 else 0

        return jsonify({
            "total_predictions": len(preds),
            "evaluated": evaluated,
            "overall_accuracy": round(correct / evaluated * 100, 1) if evaluated else 0,
            "by_instrument": inst_stats,
            "by_confidence": conf_bins,
        })
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Daily P&L History ────────────────────────────────────────────


@app.route("/api/daily-history")
def api_daily_history():
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        rows = conn.execute(
            "SELECT DATE(timestamp) as trade_date, "
            "COUNT(*) as trades, "
            "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins, "
            "COALESCE(SUM(pnl_dollars), 0) as pnl "
            "FROM trades WHERE execution_status='executed' AND pnl_dollars IS NOT NULL "
            "GROUP BY DATE(timestamp) ORDER BY trade_date"
        ).fetchall()

        days = []
        cumulative = 0.0
        for r in rows:
            cumulative += r["pnl"]
            day = {
                "date": r["trade_date"],
                "trades": r["trades"],
                "wins": r["wins"],
                "pnl": round(r["pnl"], 2),
                "cumulative_pnl": round(cumulative, 2),
            }

            # Check for broker actual
            try:
                rconn = _get_report_db()
                snap = rconn.execute(
                    "SELECT actual_pnl_today, actual_total_pnl FROM broker_snapshots WHERE report_date=?",
                    (r["trade_date"],),
                ).fetchone()
                if snap:
                    day["actual_pnl"] = snap["actual_pnl_today"]
                    day["actual_total_pnl"] = snap["actual_total_pnl"]
                rconn.close()
            except Exception:
                pass

            days.append(day)

        return jsonify(days)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Instrument Breakdown ─────────────────────────────────────────


@app.route("/api/instruments")
def api_instruments():
    conn = _get_db()
    if not conn:
        return jsonify([])

    try:
        rows = conn.execute(
            "SELECT instrument, direction, pnl_dollars, shot_tier "
            "FROM trades WHERE execution_status='executed' AND pnl_dollars IS NOT NULL"
        ).fetchall()

        by_inst = {}
        for r in rows:
            inst = r["instrument"]
            if inst not in by_inst:
                by_inst[inst] = {"trades": 0, "wins": 0, "pnl": 0.0, "longs": 0, "shorts": 0}
            by_inst[inst]["trades"] += 1
            by_inst[inst]["pnl"] += r["pnl_dollars"]
            if r["pnl_dollars"] > 0:
                by_inst[inst]["wins"] += 1
            if r["direction"] == "long":
                by_inst[inst]["longs"] += 1
            else:
                by_inst[inst]["shorts"] += 1

        result = []
        for inst, s in sorted(by_inst.items()):
            result.append({
                "instrument": inst,
                "trades": s["trades"],
                "wins": s["wins"],
                "win_rate": round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0,
                "pnl": round(s["pnl"], 2),
                "avg_pnl": round(s["pnl"] / s["trades"], 2) if s["trades"] else 0,
                "longs": s["longs"],
                "shorts": s["shorts"],
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Report Upload ────────────────────────────────────────────────


@app.route("/api/reports/snapshot", methods=["POST"])
def api_upload_snapshot():
    """Upload a daily broker snapshot (balance, P&L)."""
    data = request.get_json()
    if not data or not data.get("report_date"):
        return jsonify({"error": "report_date is required"}), 400

    conn = _get_report_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO broker_snapshots "
            "(report_date, actual_balance, actual_pnl_today, actual_total_pnl, "
            "actual_trades_today, commissions, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                data["report_date"],
                data.get("actual_balance"),
                data.get("actual_pnl_today"),
                data.get("actual_total_pnl"),
                data.get("actual_trades_today"),
                data.get("commissions", 0),
                data.get("notes", ""),
            ),
        )
        conn.commit()
        return jsonify({"status": "ok", "date": data["report_date"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/reports/snapshots")
def api_list_snapshots():
    """List all broker snapshots."""
    conn = _get_report_db()
    try:
        rows = conn.execute(
            "SELECT * FROM broker_snapshots ORDER BY report_date DESC"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


@app.route("/api/reports/snapshot/<int:snap_id>", methods=["DELETE"])
def api_delete_snapshot(snap_id):
    """Delete a broker snapshot."""
    conn = _get_report_db()
    try:
        conn.execute("DELETE FROM broker_snapshots WHERE id=?", (snap_id,))
        conn.commit()
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/reports/upload-csv", methods=["POST"])
def api_upload_csv():
    """Upload a Tradovate trade history CSV."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Must be a CSV file"}), 400

    report_date = request.form.get("report_date", date.today().isoformat())

    try:
        content = file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))

        conn = _get_report_db()
        # Clear existing trades for this date
        conn.execute("DELETE FROM broker_trades WHERE report_date=?", (report_date,))

        imported = 0
        for row in reader:
            # Flexible column mapping for Tradovate exports
            instrument = (
                row.get("Product") or row.get("Symbol") or row.get("Contract")
                or row.get("product") or row.get("symbol") or row.get("instrument") or ""
            )
            direction = (
                row.get("Buy/Sell") or row.get("Side") or row.get("Action")
                or row.get("buy/sell") or row.get("side") or row.get("direction") or ""
            )
            if direction.lower() in ("buy", "long"):
                direction = "long"
            elif direction.lower() in ("sell", "short"):
                direction = "short"

            def _float(key):
                for k in [key, key.lower(), key.replace(" ", ""), key.title()]:
                    val = row.get(k)
                    if val:
                        try:
                            return float(str(val).replace(",", "").replace("$", ""))
                        except ValueError:
                            pass
                return None

            conn.execute(
                "INSERT INTO broker_trades "
                "(report_date, timestamp, instrument, direction, quantity, "
                "entry_price, exit_price, pnl, commission, order_id, raw_symbol) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report_date,
                    row.get("Fill Time") or row.get("Time") or row.get("Date") or row.get("timestamp") or "",
                    instrument,
                    direction,
                    _float("Qty") or _float("Quantity") or _float("quantity"),
                    _float("Avg Fill Price") or _float("Entry Price") or _float("entry_price"),
                    _float("Exit Price") or _float("exit_price"),
                    _float("Realized P&L") or _float("P&L") or _float("pnl") or _float("Realized P/L"),
                    _float("Commission") or _float("commission") or 0,
                    row.get("Order ID") or row.get("order_id") or "",
                    row.get("Contract") or row.get("Symbol") or "",
                ),
            )
            imported += 1

        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "imported": imported, "date": report_date})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports/trades")
def api_list_broker_trades():
    """List uploaded broker trades."""
    report_date = request.args.get("date")
    conn = _get_report_db()
    try:
        if report_date:
            rows = conn.execute(
                "SELECT * FROM broker_trades WHERE report_date=? ORDER BY timestamp",
                (report_date,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM broker_trades ORDER BY report_date DESC, timestamp LIMIT 100"
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn.close()


# ── API: Reconciliation ───────────────────────────────────────────────


@app.route("/api/reconciliation")
def api_reconciliation():
    """Compare local estimates vs broker actuals."""
    conn = _get_db()
    rconn = _get_report_db()

    result = {"days": [], "summary": {}}

    try:
        # Get all trading days from local DB
        local_days = {}
        if conn:
            rows = conn.execute(
                "SELECT DATE(timestamp) as trade_date, "
                "COUNT(*) as trades, "
                "COALESCE(SUM(pnl_dollars), 0) as pnl "
                "FROM trades WHERE execution_status='executed' AND pnl_dollars IS NOT NULL "
                "GROUP BY DATE(timestamp) ORDER BY trade_date"
            ).fetchall()
            for r in rows:
                local_days[r["trade_date"]] = {
                    "local_trades": r["trades"],
                    "local_pnl": round(r["pnl"], 2),
                }

        # Get broker snapshots
        broker_days = {}
        snaps = rconn.execute(
            "SELECT report_date, actual_balance, actual_pnl_today, actual_total_pnl, "
            "actual_trades_today, commissions FROM broker_snapshots ORDER BY report_date"
        ).fetchall()
        for s in snaps:
            broker_days[s["report_date"]] = {
                "actual_balance": s["actual_balance"],
                "actual_pnl": s["actual_pnl_today"],
                "actual_total_pnl": s["actual_total_pnl"],
                "actual_trades": s["actual_trades_today"],
                "commissions": s["commissions"],
            }

        # Merge
        all_dates = sorted(set(list(local_days.keys()) + list(broker_days.keys())))
        total_local = 0.0
        total_actual = 0.0
        total_delta = 0.0

        for d in all_dates:
            local = local_days.get(d, {"local_trades": 0, "local_pnl": 0})
            broker = broker_days.get(d, {})
            delta = None
            if broker.get("actual_pnl") is not None:
                delta = round(local["local_pnl"] - broker["actual_pnl"], 2)
                total_delta += delta
                total_actual += broker["actual_pnl"]
            total_local += local["local_pnl"]

            result["days"].append({
                "date": d,
                "local_trades": local["local_trades"],
                "local_pnl": local["local_pnl"],
                "actual_pnl": broker.get("actual_pnl"),
                "actual_balance": broker.get("actual_balance"),
                "actual_trades": broker.get("actual_trades"),
                "commissions": broker.get("commissions"),
                "delta": delta,
            })

        result["summary"] = {
            "total_local_pnl": round(total_local, 2),
            "total_actual_pnl": round(total_actual, 2),
            "total_delta": round(total_delta, 2),
            "days_with_actuals": len(broker_days),
            "days_total": len(all_dates),
        }

    except Exception as e:
        result["error"] = str(e)
    finally:
        if conn:
            conn.close()
        rconn.close()

    return jsonify(result)


# ── Main page ──────────────────────────────────────────────────────────


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


# ── Entry point ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="LaT-PFN Trading Dashboard")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    print(f"\n  LaT-PFN Trading Dashboard")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Auto-refreshes every 15 seconds\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
