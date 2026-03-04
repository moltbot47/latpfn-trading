"""SQLite storage for KJ strategy setups."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

from kj_strategy.setup import KJSetup

logger = logging.getLogger(__name__)

DB_PATH = "data/kj_setups.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kj_setups (
    setup_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    trend_direction TEXT NOT NULL,
    active_fib_level TEXT NOT NULL,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    risk_points REAL,
    reward_points REAL,
    reward_risk_ratio REAL,
    classification TEXT,
    textbook_score REAL,
    outcome TEXT,
    actual_rr REAL,
    exit_price REAL,
    bars_to_exit INTEGER,
    pattern_types TEXT,
    pattern_confidence REAL,
    entry_timestamp TEXT,
    chart_path TEXT,
    narration_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_instrument ON kj_setups(instrument);
CREATE INDEX IF NOT EXISTS idx_classification ON kj_setups(classification);
CREATE INDEX IF NOT EXISTS idx_outcome ON kj_setups(outcome);
"""


def _get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE + _CREATE_INDEX)
    return conn


def save_setup(setup: KJSetup, narration_path: Optional[str] = None, db_path: str = DB_PATH) -> None:
    """Save a KJSetup to the database."""
    conn = _get_conn(db_path)
    try:
        pattern_types = ",".join(p.pattern_type for p in setup.patterns) if setup.patterns else ""
        pattern_conf = setup.patterns[0].confidence if setup.patterns else 0.0
        entry_ts = setup.entry_timestamp.isoformat() if setup.entry_timestamp else None

        conn.execute(
            """
            INSERT OR REPLACE INTO kj_setups
            (setup_id, instrument, trend_direction, active_fib_level,
             entry_price, stop_loss, take_profit, risk_points, reward_points,
             reward_risk_ratio, classification, textbook_score,
             outcome, actual_rr, exit_price, bars_to_exit,
             pattern_types, pattern_confidence, entry_timestamp,
             chart_path, narration_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                setup.setup_id, setup.instrument, setup.trend_direction,
                setup.active_fib_level, setup.entry_price, setup.stop_loss,
                setup.take_profit, setup.risk_points, setup.reward_points,
                setup.reward_risk_ratio, setup.classification, setup.textbook_score,
                setup.outcome, setup.actual_rr, setup.exit_price, setup.bars_to_exit,
                pattern_types, pattern_conf, entry_ts,
                setup.chart_path, narration_path,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_setups(
    instrument: Optional[str] = None,
    classification: Optional[str] = None,
    outcome: Optional[str] = None,
    db_path: str = DB_PATH,
) -> list[dict]:
    """Load setups from the database with optional filters."""
    conn = _get_conn(db_path)
    try:
        query = "SELECT * FROM kj_setups WHERE 1=1"
        params: list = []

        if instrument:
            query += " AND instrument = ?"
            params.append(instrument)
        if classification:
            query += " AND classification = ?"
            params.append(classification)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)

        query += " ORDER BY entry_timestamp DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats(instrument: Optional[str] = None, db_path: str = DB_PATH) -> dict:
    """Get aggregate statistics for stored setups."""
    conn = _get_conn(db_path)
    try:
        where = "WHERE instrument = ?" if instrument else ""
        params = [instrument] if instrument else []

        row = conn.execute(
            f"SELECT COUNT(*) as total FROM kj_setups {where}", params
        ).fetchone()
        total = row["total"]

        if total == 0:
            return {"total": 0}

        stats = {"total": total}

        # By classification
        for cls in ("textbook", "regular"):
            r = conn.execute(
                f"SELECT COUNT(*) as n FROM kj_setups {where} {'AND' if where else 'WHERE'} classification = ?",
                params + [cls],
            ).fetchone()
            stats[cls] = r["n"]

        # By outcome
        for oc in ("win", "loss", "timeout"):
            r = conn.execute(
                f"SELECT COUNT(*) as n FROM kj_setups {where} {'AND' if where else 'WHERE'} outcome = ?",
                params + [oc],
            ).fetchone()
            stats[oc] = r["n"]

        # Win rates
        decided = stats.get("win", 0) + stats.get("loss", 0)
        stats["win_rate"] = stats.get("win", 0) / decided * 100 if decided > 0 else 0

        # Textbook win rate
        tb_wins = conn.execute(
            f"SELECT COUNT(*) as n FROM kj_setups {where} {'AND' if where else 'WHERE'} classification = 'textbook' AND outcome = 'win'",
            params,
        ).fetchone()["n"]
        tb_decided = conn.execute(
            f"SELECT COUNT(*) as n FROM kj_setups {where} {'AND' if where else 'WHERE'} classification = 'textbook' AND outcome IN ('win', 'loss')",
            params,
        ).fetchone()["n"]
        stats["textbook_win_rate"] = tb_wins / tb_decided * 100 if tb_decided > 0 else 0

        # Average R:R
        r = conn.execute(
            f"SELECT AVG(actual_rr) as avg_rr FROM kj_setups {where} {'AND' if where else 'WHERE'} actual_rr IS NOT NULL",
            params,
        ).fetchone()
        stats["avg_rr"] = r["avg_rr"] or 0

        # Average textbook score
        r = conn.execute(
            f"SELECT AVG(textbook_score) as avg_score FROM kj_setups {where}",
            params,
        ).fetchone()
        stats["avg_score"] = r["avg_score"] or 0

        return stats
    finally:
        conn.close()
