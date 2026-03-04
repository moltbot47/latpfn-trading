"""Strategy decay detection — rolling performance analysis per instrument/tier."""

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
CME_DB_PATH = PROJECT_ROOT / "data" / "trade_log.db"
TURBO_DB_PATH = PROJECT_ROOT / "data" / "turbo_analytics.db"

RECENT_WINDOW = 50
OVERALL_WINDOW = 200
DECAY_THRESHOLD = -0.05  # 5pp drop = decaying
WARNING_THRESHOLD = -0.03  # 3pp drop = warning


@dataclass
class StrategyStats:
    """Performance stats for a single strategy (instrument or instrument+tier)."""
    name: str
    platform: str
    instrument: str
    mode: str = "standard"
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    # Decay
    recent_wr: float = 0.0
    recent_n: int = 0
    overall_wr: float = 0.0
    overall_n: int = 0
    edge_decay: float = 0.0
    status: str = "STABLE"  # STABLE, WARNING, DECAYING, INACTIVE
    # Tier breakdown
    tier_stats: Dict[str, dict] = field(default_factory=dict)
    last_trade: str = ""
    enabled: bool = True

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0


def compute_cme_strategies() -> List[StrategyStats]:
    """Compute per-instrument strategy stats from trade_log.db."""
    if not CME_DB_PATH.exists():
        return []

    try:
        conn = sqlite3.connect(str(CME_DB_PATH), timeout=1.0)
        conn.row_factory = sqlite3.Row

        # Get all instruments that have trades
        instruments = conn.execute(
            """SELECT DISTINCT instrument FROM trades
               WHERE exit_price IS NOT NULL AND execution_status = 'executed'"""
        ).fetchall()

        strategies = []
        for row in instruments:
            inst = row["instrument"]
            stats = _compute_instrument_stats(conn, inst)
            if stats:
                strategies.append(stats)

        conn.close()
        return strategies
    except Exception as e:
        logger.debug("CME strategy computation failed: %s", e)
        return []


def _compute_instrument_stats(conn, instrument: str) -> Optional[StrategyStats]:
    """Compute full stats for one CME instrument."""
    # Overall stats
    row = conn.execute(
        """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_dollars <= 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl_dollars) as total_pnl,
            AVG(CASE WHEN pnl_dollars > 0 THEN pnl_dollars END) as avg_win,
            AVG(CASE WHEN pnl_dollars <= 0 THEN pnl_dollars END) as avg_loss,
            MAX(pnl_dollars) as best,
            MIN(pnl_dollars) as worst,
            MAX(timestamp) as last_ts
           FROM trades
           WHERE instrument = ? AND exit_price IS NOT NULL
             AND execution_status = 'executed'""",
        (instrument,),
    ).fetchone()

    total = row["total"] or 0
    if total == 0:
        return None

    wins = row["wins"] or 0
    losses = row["losses"] or 0
    avg_win = row["avg_win"] or 0
    avg_loss = row["avg_loss"] or 0
    pf = abs(avg_win * wins / (avg_loss * losses)) if (avg_loss and losses) else 0

    # Decay detection: recent vs overall
    recent = conn.execute(
        """SELECT
            COUNT(*) as n,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as w
           FROM (
               SELECT pnl_dollars FROM trades
               WHERE instrument = ? AND exit_price IS NOT NULL
                 AND execution_status = 'executed'
               ORDER BY id DESC LIMIT ?
           )""",
        (instrument, RECENT_WINDOW),
    ).fetchone()

    overall = conn.execute(
        """SELECT
            COUNT(*) as n,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as w
           FROM (
               SELECT pnl_dollars FROM trades
               WHERE instrument = ? AND exit_price IS NOT NULL
                 AND execution_status = 'executed'
               ORDER BY id DESC LIMIT ?
           )""",
        (instrument, OVERALL_WINDOW),
    ).fetchone()

    recent_n = recent["n"] or 0
    recent_wr = (recent["w"] or 0) / recent_n if recent_n > 0 else 0
    overall_n = overall["n"] or 0
    overall_wr = (overall["w"] or 0) / overall_n if overall_n > 0 else 0
    decay = recent_wr - overall_wr

    if recent_n < 10:
        status = "INACTIVE"
    elif decay <= DECAY_THRESHOLD:
        status = "DECAYING"
    elif decay <= WARNING_THRESHOLD:
        status = "WARNING"
    else:
        status = "STABLE"

    # Per-tier breakdown
    tier_rows = conn.execute(
        """SELECT shot_tier,
            COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(pnl_dollars) as pnl,
            AVG(CASE WHEN pnl_dollars > 0 THEN pnl_dollars END) as avg_w,
            AVG(CASE WHEN pnl_dollars <= 0 THEN pnl_dollars END) as avg_l
           FROM trades
           WHERE instrument = ? AND exit_price IS NOT NULL
             AND execution_status = 'executed'
           GROUP BY shot_tier
           ORDER BY SUM(pnl_dollars) DESC""",
        (instrument,),
    ).fetchall()

    tier_stats = {}
    for t in tier_rows:
        tier_name = t["shot_tier"] or "unknown"
        t_total = t["total"] or 0
        t_wins = t["wins"] or 0
        t_avg_w = t["avg_w"] or 0
        t_avg_l = t["avg_l"] or 0
        t_pf = abs(t_avg_w * t_wins / (t_avg_l * (t_total - t_wins))) if (t_avg_l and (t_total - t_wins)) else 0
        tier_stats[tier_name] = {
            "trades": t_total,
            "wins": t_wins,
            "wr": round(t_wins / t_total * 100, 1) if t_total > 0 else 0,
            "pnl": round(t["pnl"] or 0, 2),
            "pf": round(t_pf, 2),
        }

    return StrategyStats(
        name=f"{instrument}",
        platform="CME",
        instrument=instrument,
        total_trades=total,
        wins=wins,
        losses=losses,
        total_pnl=round(row["total_pnl"] or 0, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        profit_factor=round(pf, 2),
        best_trade=round(row["best"] or 0, 2),
        worst_trade=round(row["worst"] or 0, 2),
        recent_wr=round(recent_wr, 3),
        recent_n=recent_n,
        overall_wr=round(overall_wr, 3),
        overall_n=overall_n,
        edge_decay=round(decay, 3),
        status=status,
        tier_stats=tier_stats,
        last_trade=row["last_ts"] or "",
    )


def compute_poly_strategy() -> Optional[StrategyStats]:
    """Compute turbo contrarian strategy stats from turbo_analytics.db."""
    if not TURBO_DB_PATH.exists():
        return None

    try:
        conn = sqlite3.connect(str(TURBO_DB_PATH), timeout=1.0)
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN traded=1 AND result IS NOT NULL THEN pnl ELSE 0 END) as total_pnl,
                AVG(CASE WHEN result='win' THEN pnl END) as avg_win,
                AVG(CASE WHEN result='loss' THEN pnl END) as avg_loss,
                MAX(pnl) as best,
                MIN(pnl) as worst,
                MAX(timestamp) as last_ts
               FROM turbo_signals
               WHERE traded=1 AND result IS NOT NULL"""
        ).fetchone()

        total = row["total"] or 0
        if total == 0:
            conn.close()
            return None

        wins = row["wins"] or 0
        losses = row["losses"] or 0
        avg_win = row["avg_win"] or 0
        avg_loss = row["avg_loss"] or 0
        pf = abs(avg_win * wins / (avg_loss * losses)) if (avg_loss and losses) else 0

        # Decay
        recent = conn.execute(
            """SELECT COUNT(*) as n,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w
               FROM (
                   SELECT result FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL
                   ORDER BY id DESC LIMIT ?
               )""",
            (RECENT_WINDOW,),
        ).fetchone()

        overall = conn.execute(
            """SELECT COUNT(*) as n,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w
               FROM (
                   SELECT result FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL
                   ORDER BY id DESC LIMIT ?
               )""",
            (OVERALL_WINDOW,),
        ).fetchone()

        recent_n = recent["n"] or 0
        recent_wr = (recent["w"] or 0) / recent_n if recent_n > 0 else 0
        overall_n = overall["n"] or 0
        overall_wr = (overall["w"] or 0) / overall_n if overall_n > 0 else 0
        decay = recent_wr - overall_wr

        if recent_n < 10:
            status = "INACTIVE"
        elif decay <= DECAY_THRESHOLD:
            status = "DECAYING"
        elif decay <= WARNING_THRESHOLD:
            status = "WARNING"
        else:
            status = "STABLE"

        # Per-asset breakdown (serves as tier proxy for Poly)
        asset_rows = conn.execute(
            """SELECT asset,
                COUNT(*) as total,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as pnl
               FROM turbo_signals
               WHERE traded=1 AND result IS NOT NULL
               GROUP BY asset
               ORDER BY SUM(pnl) DESC"""
        ).fetchall()

        tier_stats = {}
        for a in asset_rows:
            a_total = a["total"] or 0
            a_wins = a["wins"] or 0
            tier_stats[a["asset"]] = {
                "trades": a_total,
                "wins": a_wins,
                "wr": round(a_wins / a_total * 100, 1) if a_total > 0 else 0,
                "pnl": round(a["pnl"] or 0, 2),
            }

        conn.close()

        return StrategyStats(
            name="Turbo Contrarian",
            platform="POLY",
            instrument="turbo",
            total_trades=total,
            wins=wins,
            losses=losses,
            total_pnl=round(row["total_pnl"] or 0, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            profit_factor=round(pf, 2),
            best_trade=round(row["best"] or 0, 2),
            worst_trade=round(row["worst"] or 0, 2),
            recent_wr=round(recent_wr, 3),
            recent_n=recent_n,
            overall_wr=round(overall_wr, 3),
            overall_n=overall_n,
            edge_decay=round(decay, 3),
            status=status,
            tier_stats=tier_stats,
            last_trade=row["last_ts"] or "",
        )
    except Exception as e:
        logger.debug("Poly strategy computation failed: %s", e)
        return None


def compute_all_strategies() -> List[StrategyStats]:
    """Compute strategy stats across all platforms."""
    strategies = compute_cme_strategies()
    poly = compute_poly_strategy()
    if poly:
        strategies.append(poly)
    return strategies
