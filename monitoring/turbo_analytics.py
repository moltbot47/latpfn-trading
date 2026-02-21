"""
Turbo strategy analytics — SQLite logger that captures every signal
evaluation, trade, and resolution for comprehensive performance analysis.

Tracks both executed trades AND shadow trades (what would have happened
if we had traded every signal), giving 4-8x more data points.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "turbo_analytics.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS turbo_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    window_start_ts INTEGER NOT NULL,
    window_end_ts INTEGER NOT NULL,
    seconds_left INTEGER,

    -- Market prices at evaluation time
    up_price REAL,
    down_price REAL,

    -- Momentum data from CoinGecko
    crypto_price REAL,
    pct_change_1m REAL,
    pct_change_3m REAL,
    momentum_strength REAL,
    momentum_direction TEXT,

    -- Signal decision
    signal_generated INTEGER NOT NULL DEFAULT 0,
    signal_type TEXT,
    signal_direction TEXT,
    signal_reason TEXT,
    skip_reason TEXT,

    -- Trade execution (null if no signal or not traded)
    traded INTEGER NOT NULL DEFAULT 0,
    entry_price REAL,
    shares REAL,
    size_usdc REAL,
    order_id TEXT,

    -- Resolution (filled later by log_resolution)
    outcome REAL,
    result TEXT,
    pnl REAL,

    -- Shadow: best signal at eval time even if we didn't trade
    shadow_direction TEXT,
    shadow_entry_price REAL,
    shadow_outcome REAL,
    shadow_pnl REAL,

    -- Agent intel at eval time
    intel_convergence REAL,
    intel_multiplier REAL
);

CREATE INDEX IF NOT EXISTS idx_ts_asset_tf
    ON turbo_signals(asset, timeframe, window_start_ts);
CREATE INDEX IF NOT EXISTS idx_ts_timestamp
    ON turbo_signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_ts_traded
    ON turbo_signals(traded, result);
"""


class TurboAnalytics:
    """SQLite-backed analytics for the turbo crypto scalper."""

    def __init__(self, db_path: str = None):
        self._db_path = db_path or str(DB_PATH)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        # Migrate: add intel columns if missing
        try:
            self._conn.execute(
                "ALTER TABLE turbo_signals ADD COLUMN intel_convergence REAL"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            self._conn.execute(
                "ALTER TABLE turbo_signals ADD COLUMN intel_multiplier REAL"
            )
        except sqlite3.OperationalError:
            pass
        self._conn.commit()
        logger.info("TurboAnalytics DB: %s", self._db_path)

    # ── Logging ─────────────────────────────────────────────────────

    def log_signal_check(
        self,
        asset: str,
        tf: str,
        window,  # TurboWindow
        momentum: Dict,
        signal: Optional[Dict],
        skip_reason: str = "",
        shadow_signal: Optional[Dict] = None,
        intel_convergence: float = 0.0,
        intel_multiplier: float = 1.0,
    ):
        """Log every signal evaluation — traded or not."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now = time.time()
        seconds_left = int(window.end_ts - now) if window else 0

        # Current crypto price
        crypto_price = None
        if momentum.get("_current_price"):
            crypto_price = momentum["_current_price"]

        # Determine signal type from reason string
        signal_type = None
        if signal and signal.get("reason"):
            r = signal["reason"]
            if "contrarian" in r:
                signal_type = "contrarian"
            elif "momentum" in r and "late" not in r:
                signal_type = "momentum"
            elif "market_lean" in r:
                signal_type = "market_lean"
            elif "late_momentum" in r:
                signal_type = "late_momentum"

        # Shadow: best available signal even if we didn't trade
        shadow_dir = None
        shadow_price = None
        if shadow_signal:
            shadow_dir = shadow_signal.get("direction")
            shadow_price = shadow_signal.get("price")

        try:
            self._conn.execute(
                """INSERT INTO turbo_signals (
                    timestamp, asset, timeframe, window_start_ts, window_end_ts,
                    seconds_left, up_price, down_price,
                    crypto_price, pct_change_1m, pct_change_3m,
                    momentum_strength, momentum_direction,
                    signal_generated, signal_type, signal_direction,
                    signal_reason, skip_reason,
                    traded, entry_price, shares, size_usdc, order_id,
                    shadow_direction, shadow_entry_price,
                    intel_convergence, intel_multiplier
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    0, NULL, NULL, NULL, NULL,
                    ?, ?,
                    ?, ?
                )""",
                (
                    now_iso, asset, tf, window.start_ts, window.end_ts,
                    seconds_left, window.up_price, window.down_price,
                    crypto_price, momentum.get("pct_change_1m", 0),
                    momentum.get("pct_change_3m", 0),
                    momentum.get("strength", 0), momentum.get("direction"),
                    1 if signal else 0, signal_type,
                    signal.get("direction") if signal else None,
                    signal.get("reason") if signal else None,
                    skip_reason or None,
                    shadow_dir, shadow_price,
                    intel_convergence, intel_multiplier,
                ),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("TurboAnalytics log error: %s", e)

    def log_trade_execution(
        self, asset: str, tf: str, window_start_ts: int,
        entry_price: float, shares: float, size_usdc: float, order_id: str,
    ):
        """Update the most recent signal row with trade execution data."""
        try:
            self._conn.execute(
                """UPDATE turbo_signals SET
                    traded = 1, entry_price = ?, shares = ?,
                    size_usdc = ?, order_id = ?
                WHERE id = (
                    SELECT id FROM turbo_signals
                    WHERE asset = ? AND timeframe = ? AND window_start_ts = ?
                      AND signal_generated = 1
                    ORDER BY id DESC LIMIT 1
                )""",
                (entry_price, shares, size_usdc, order_id,
                 asset, tf, window_start_ts),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("TurboAnalytics trade log error: %s", e)

    def log_resolution(
        self, asset: str, tf: str, window_start_ts: int,
        outcome: float, pnl: float,
    ):
        """Fill in resolution data for all rows matching this window."""
        try:
            # Update traded row
            self._conn.execute(
                """UPDATE turbo_signals SET outcome = ?, result = ?, pnl = ?
                WHERE asset = ? AND timeframe = ? AND window_start_ts = ?
                  AND traded = 1""",
                (
                    outcome,
                    "win" if outcome > 0.5 else "loss",
                    pnl,
                    asset, tf, window_start_ts,
                ),
            )

            # Update shadow outcomes for all rows in this window
            # Shadow PnL = (outcome - shadow_entry_price) * hypothetical_shares
            # We use $1 / shadow_price as hypothetical shares
            self._conn.execute(
                """UPDATE turbo_signals SET
                    shadow_outcome = ?,
                    shadow_pnl = CASE
                        WHEN shadow_direction IS NOT NULL AND shadow_entry_price > 0 THEN
                            (? - shadow_entry_price) * (1.0 / shadow_entry_price)
                        ELSE NULL
                    END
                WHERE asset = ? AND timeframe = ? AND window_start_ts = ?
                  AND shadow_direction IS NOT NULL""",
                (outcome, outcome, asset, tf, window_start_ts),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("TurboAnalytics resolution log error: %s", e)

    # ── Queries ─────────────────────────────────────────────────────

    def get_scorecard(self, hours: int = 24) -> Dict:
        """Comprehensive performance scorecard."""
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - hours * 3600),
        )

        rows = self._conn.execute(
            "SELECT * FROM turbo_signals WHERE timestamp >= ?", (cutoff,)
        ).fetchall()

        if not rows:
            return {"total_evaluations": 0}

        total = len(rows)
        signals = [r for r in rows if r["signal_generated"]]
        traded = [r for r in rows if r["traded"]]
        resolved = [r for r in traded if r["result"]]

        wins = [r for r in resolved if r["result"] == "win"]
        losses = [r for r in resolved if r["result"] == "loss"]

        # By signal type
        by_type = {}
        for r in resolved:
            st = r["signal_type"] or "unknown"
            by_type.setdefault(st, {"w": 0, "l": 0, "pnl": 0.0})
            if r["result"] == "win":
                by_type[st]["w"] += 1
            else:
                by_type[st]["l"] += 1
            by_type[st]["pnl"] += r["pnl"] or 0

        # By asset
        by_asset = {}
        for r in resolved:
            a = r["asset"]
            by_asset.setdefault(a, {"w": 0, "l": 0, "pnl": 0.0})
            if r["result"] == "win":
                by_asset[a]["w"] += 1
            else:
                by_asset[a]["l"] += 1
            by_asset[a]["pnl"] += r["pnl"] or 0

        # By direction
        by_dir = {}
        for r in resolved:
            d = r["signal_direction"] or "?"
            by_dir.setdefault(d, {"w": 0, "l": 0, "pnl": 0.0})
            if r["result"] == "win":
                by_dir[d]["w"] += 1
            else:
                by_dir[d]["l"] += 1
            by_dir[d]["pnl"] += r["pnl"] or 0

        # Shadow performance
        shadow_rows = [r for r in rows if r["shadow_outcome"] is not None]
        shadow_wins = sum(1 for r in shadow_rows if r["shadow_outcome"] > 0.5)

        # Skip reasons distribution
        skip_reasons = {}
        for r in rows:
            if r["skip_reason"]:
                skip_reasons[r["skip_reason"]] = skip_reasons.get(r["skip_reason"], 0) + 1

        total_pnl = sum(r["pnl"] or 0 for r in resolved)

        return {
            "hours": hours,
            "total_evaluations": total,
            "signals_generated": len(signals),
            "trades_executed": len(traded),
            "trades_resolved": len(resolved),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(resolved) * 100 if resolved else 0,
            "total_pnl": round(total_pnl, 2),
            "by_signal_type": by_type,
            "by_asset": by_asset,
            "by_direction": by_dir,
            "shadow_evaluations": len(shadow_rows),
            "shadow_win_rate": shadow_wins / len(shadow_rows) * 100 if shadow_rows else 0,
            "skip_reasons": skip_reasons,
        }

    def get_edge_report(self, hours: int = 24) -> str:
        """Formatted text report for Discord."""
        sc = self.get_scorecard(hours)
        if sc["total_evaluations"] == 0:
            return "No turbo analytics data yet."

        lines = [
            f"**Turbo Analytics ({sc['hours']}h)**",
            f"Evaluations: {sc['total_evaluations']} | "
            f"Signals: {sc['signals_generated']} | "
            f"Trades: {sc['trades_executed']}",
            f"Resolved: {sc['wins']}W/{sc['losses']}L "
            f"({sc['win_rate']:.0f}%) | "
            f"PnL: ${sc['total_pnl']:+.2f}",
            "",
        ]

        if sc["by_signal_type"]:
            lines.append("**By Signal Type:**")
            for st, s in sc["by_signal_type"].items():
                t = s["w"] + s["l"]
                wr = s["w"] / t * 100 if t else 0
                lines.append(
                    f"  {st}: {s['w']}W/{s['l']}L ({wr:.0f}%) ${s['pnl']:+.2f}"
                )
            lines.append("")

        if sc["by_direction"]:
            lines.append("**By Direction:**")
            for d, s in sc["by_direction"].items():
                t = s["w"] + s["l"]
                wr = s["w"] / t * 100 if t else 0
                lines.append(
                    f"  {d}: {s['w']}W/{s['l']}L ({wr:.0f}%) ${s['pnl']:+.2f}"
                )
            lines.append("")

        if sc["shadow_evaluations"] > 0:
            lines.append(
                f"**Shadow (untaken signals):** {sc['shadow_evaluations']} eval, "
                f"{sc['shadow_win_rate']:.0f}% would-win"
            )

        if sc["skip_reasons"]:
            lines.append("")
            lines.append("**Skip Reasons:**")
            for reason, cnt in sorted(
                sc["skip_reasons"].items(), key=lambda x: -x[1]
            )[:5]:
                lines.append(f"  {reason}: {cnt}")

        return "\n".join(lines)
