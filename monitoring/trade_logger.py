"""
Structured trade logging system using SQLite.

Provides persistent storage for predictions and trades, enabling
post-hoc analysis of model accuracy, tier performance, and P&L tracking.

Usage:
    from monitoring.trade_logger import TradeLogger

    trade_log = TradeLogger()  # defaults to ./data/trade_log.db
    pred_id = trade_log.log_prediction(cycle=1, instrument="MNQ", ...)
    trade_id = trade_log.log_trade(prediction_id=pred_id, ...)
    trade_log.update_trade_exit(trade_id, exit_price=18250.0, ...)

Integration points (see comments at bottom of file):
    - orchestrator/main_loop.py  _process_instrument()
    - execution/order_manager.py  close_position()

IMPORTANT: All public methods swallow exceptions so that logging
failures never crash the trading loop.
"""

import logging
import os
import sqlite3
from datetime import datetime, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------

_SCHEMA_PREDICTIONS = """
CREATE TABLE IF NOT EXISTS predictions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT    NOT NULL,
    cycle                 INTEGER NOT NULL,
    instrument            TEXT    NOT NULL,
    direction             TEXT    NOT NULL,
    model_confidence      REAL,
    trend_clarity         REAL,
    uncertainty_inverse   REAL,
    composite_confidence  REAL,
    regime                TEXT,
    shot_tier             TEXT,
    current_price         REAL,
    forecast_end_price    REAL,
    signal_generated      BOOLEAN NOT NULL DEFAULT 0
);
"""

_SCHEMA_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id         INTEGER REFERENCES predictions(id),
    timestamp             TEXT    NOT NULL,
    instrument            TEXT    NOT NULL,
    direction             TEXT    NOT NULL,
    shot_tier             TEXT,
    entry_price           REAL,
    stop_loss             REAL,
    take_profit           REAL,
    position_size         INTEGER,
    contract_size         REAL,
    risk_dollars          REAL,
    reward_dollars        REAL,
    rr_ratio              REAL,
    regime                TEXT,
    drawdown_cushion      REAL,
    effective_risk_pct    REAL,
    execution_status      TEXT    NOT NULL DEFAULT 'dry_run',
    rejection_reason      TEXT,
    exit_price            REAL,
    exit_reason           TEXT,
    pnl_dollars           REAL,
    mae_points            REAL,
    mfe_points            REAL,
    time_in_trade_minutes REAL
);
"""

_INDEX_PREDICTIONS_INSTRUMENT = """
CREATE INDEX IF NOT EXISTS idx_pred_instrument
    ON predictions(instrument, timestamp);
"""

_INDEX_TRADES_INSTRUMENT = """
CREATE INDEX IF NOT EXISTS idx_trade_instrument
    ON trades(instrument, timestamp);
"""

_INDEX_TRADES_STATUS = """
CREATE INDEX IF NOT EXISTS idx_trade_status
    ON trades(execution_status);
"""


class TradeLogger:
    """
    SQLite-backed trade and prediction logger.

    All public methods catch exceptions internally so that a logging
    failure can never propagate up and crash the trading loop.
    """

    def __init__(self, db_path: str = "./data/trade_log.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Database initialisation
    # ------------------------------------------------------------------

    def _init_db(self):
        """Create the database file, tables, and indexes if they do not exist."""
        try:
            # Ensure parent directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")

            self._conn.executescript(
                _SCHEMA_PREDICTIONS
                + _SCHEMA_TRADES
                + _INDEX_PREDICTIONS_INSTRUMENT
                + _INDEX_TRADES_INSTRUMENT
                + _INDEX_TRADES_STATUS
            )
            self._conn.commit()
            logger.info("TradeLogger initialised — db=%s", self.db_path)
        except Exception as e:
            logger.error("TradeLogger failed to initialise database: %s", e, exc_info=True)
            self._conn = None

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """Return the active connection, or attempt to reconnect."""
        if self._conn is not None:
            return self._conn
        try:
            self._init_db()
        except Exception:
            pass
        return self._conn

    # ------------------------------------------------------------------
    # Prediction logging
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        cycle: int,
        instrument: str,
        prediction: dict,
        composite_confidence: float,
        shot_tier: str,
        signal_generated: bool,
    ) -> Optional[int]:
        """
        Record a model prediction.

        Args:
            cycle:                Current orchestrator cycle number.
            instrument:           Instrument symbol (e.g. 'MNQ').
            prediction:           Raw prediction dict from LaTPFNPredictor.predict().
                                  Expected keys: direction, confidence, regime,
                                  current_price, forecast_prices, uncertainty.
            composite_confidence: The weighted composite confidence score (0..1).
            shot_tier:            NBA shot tier name or 'no_trade'.
            signal_generated:     Whether a TradingSignal was produced.

        Returns:
            The prediction row id, or None on failure.
        """
        conn = self._get_conn()
        if conn is None:
            return None

        try:
            import numpy as np

            direction = prediction.get("direction", "neutral")
            model_confidence = float(prediction.get("confidence", 0.0))
            regime = prediction.get("regime", "unknown")
            current_price = float(prediction.get("current_price", 0.0))

            # Decompose confidence components for analysis
            forecast = prediction.get("forecast_prices")
            uncertainty = prediction.get("uncertainty")

            trend_clarity = None
            uncertainty_inverse = None

            if forecast is not None and current_price > 0:
                x = np.arange(len(forecast), dtype=np.float64)
                slope = np.polyfit(x, forecast, 1)[0]
                trend_clarity = float(min(abs(slope) / (current_price * 0.001 + 1e-8), 1.0))

            if uncertainty is not None and current_price > 0:
                avg_unc_pct = float(np.mean(uncertainty)) / (current_price + 1e-8)
                uncertainty_inverse = float(1.0 / (1.0 + avg_unc_pct * 100))

            # Forecast end price (average of last 10 steps, matching exits.py)
            forecast_end_price = None
            if forecast is not None and len(forecast) > 0:
                forecast_end_price = float(np.mean(forecast[-10:]))

            cursor = conn.execute(
                """
                INSERT INTO predictions (
                    timestamp, cycle, instrument, direction,
                    model_confidence, trend_clarity, uncertainty_inverse,
                    composite_confidence, regime, shot_tier,
                    current_price, forecast_end_price, signal_generated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    cycle,
                    instrument,
                    direction,
                    model_confidence,
                    trend_clarity,
                    uncertainty_inverse,
                    float(composite_confidence),
                    regime,
                    shot_tier,
                    current_price,
                    forecast_end_price,
                    1 if signal_generated else 0,
                ),
            )
            conn.commit()
            pred_id = cursor.lastrowid
            logger.debug(
                "Logged prediction id=%d: %s cycle=%d dir=%s conf=%.3f tier=%s",
                pred_id, instrument, cycle, direction, composite_confidence, shot_tier,
            )
            return pred_id

        except Exception as e:
            logger.error("Failed to log prediction: %s", e, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Trade logging
    # ------------------------------------------------------------------

    def log_trade(
        self,
        prediction_id: Optional[int],
        instrument: str,
        signal: Any,
        regime: str,
        drawdown_cushion: float,
        effective_risk_pct: float,
        execution_status: str,
        rejection_reason: Optional[str] = None,
    ) -> Optional[int]:
        """
        Record a trade entry (executed, rejected, or dry_run).

        Args:
            prediction_id:     FK to the predictions table (from log_prediction).
            instrument:        Instrument symbol.
            signal:            TradingSignal dataclass instance. Expected attrs:
                               direction, shot_type, entry_price, stop_loss,
                               take_profit, position_size.
            regime:            Market regime string.
            drawdown_cushion:  Current drawdown cushion in dollars.
            effective_risk_pct: Effective risk as percent of equity.
            execution_status:  'executed' | 'rejected' | 'dry_run'.
            rejection_reason:  Reason string when status is 'rejected'.

        Returns:
            The trade row id, or None on failure.
        """
        conn = self._get_conn()
        if conn is None:
            return None

        try:
            direction = getattr(signal, "direction", "unknown")
            shot_tier = getattr(signal, "shot_type", "unknown")
            entry_price = float(getattr(signal, "entry_price", 0.0))
            stop_loss = float(getattr(signal, "stop_loss", 0.0))
            take_profit = float(getattr(signal, "take_profit", 0.0))
            position_size = int(getattr(signal, "position_size", 0))

            # Derive contract_size from config if available — caller can also
            # monkey-patch signal.contract_size; we fall back to 1.0.
            contract_size = float(getattr(signal, "contract_size", 1.0))

            risk_points = abs(entry_price - stop_loss)
            reward_points = abs(take_profit - entry_price)
            risk_dollars = risk_points * contract_size * position_size
            reward_dollars = reward_points * contract_size * position_size
            rr_ratio = (reward_points / risk_points) if risk_points > 0 else 0.0

            cursor = conn.execute(
                """
                INSERT INTO trades (
                    prediction_id, timestamp, instrument, direction,
                    shot_tier, entry_price, stop_loss, take_profit,
                    position_size, contract_size, risk_dollars, reward_dollars,
                    rr_ratio, regime, drawdown_cushion, effective_risk_pct,
                    execution_status, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction_id,
                    datetime.utcnow().isoformat(),
                    instrument,
                    direction,
                    shot_tier,
                    entry_price,
                    stop_loss,
                    take_profit,
                    position_size,
                    contract_size,
                    risk_dollars,
                    reward_dollars,
                    rr_ratio,
                    regime,
                    drawdown_cushion,
                    effective_risk_pct,
                    execution_status,
                    rejection_reason,
                ),
            )
            conn.commit()
            trade_id = cursor.lastrowid
            logger.debug(
                "Logged trade id=%d: %s %s %s status=%s",
                trade_id, instrument, direction, shot_tier, execution_status,
            )
            return trade_id

        except Exception as e:
            logger.error("Failed to log trade: %s", e, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Trade exit update
    # ------------------------------------------------------------------

    def update_trade_exit(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
        pnl_dollars: float,
        mae_points: Optional[float] = None,
        mfe_points: Optional[float] = None,
        time_in_trade_minutes: Optional[float] = None,
    ) -> bool:
        """
        Update a trade row with exit information.

        Args:
            trade_id:              Row id from log_trade().
            exit_price:            Actual exit price.
            exit_reason:           'take_profit' | 'stop_loss' | 'timeout' | 'flatten'.
            pnl_dollars:           Realized P&L in dollars.
            mae_points:            Max adverse excursion in points (optional).
            mfe_points:            Max favorable excursion in points (optional).
            time_in_trade_minutes: Duration of the trade in minutes (optional).

        Returns:
            True on success, False on failure.
        """
        conn = self._get_conn()
        if conn is None:
            return False

        try:
            conn.execute(
                """
                UPDATE trades
                   SET exit_price            = ?,
                       exit_reason           = ?,
                       pnl_dollars           = ?,
                       mae_points            = ?,
                       mfe_points            = ?,
                       time_in_trade_minutes = ?
                 WHERE id = ?
                """,
                (
                    exit_price,
                    exit_reason,
                    pnl_dollars,
                    mae_points,
                    mfe_points,
                    time_in_trade_minutes,
                    trade_id,
                ),
            )
            conn.commit()
            logger.debug(
                "Updated trade id=%d exit: price=%.2f reason=%s pnl=$%.2f",
                trade_id, exit_price, exit_reason, pnl_dollars,
            )
            return True

        except Exception as e:
            logger.error("Failed to update trade exit id=%d: %s", trade_id, e, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch the most recent trades ordered by timestamp descending.

        Returns:
            List of trade dicts (empty list on failure).
        """
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            cursor = conn.execute(
                """
                SELECT t.*, p.composite_confidence, p.forecast_end_price
                  FROM trades t
                  LEFT JOIN predictions p ON t.prediction_id = p.id
                 ORDER BY t.timestamp DESC
                 LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error("Failed to fetch recent trades: %s", e, exc_info=True)
            return []

    def get_daily_summary(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Compute a summary for a single trading day.

        Args:
            date_str: ISO date string (YYYY-MM-DD). Defaults to today (UTC).

        Returns:
            Dict with keys: date, trade_count, executed_count, win_count,
            loss_count, win_rate, total_pnl, avg_rr, best_trade, worst_trade,
            by_tier (dict of tier-level stats).  Empty dict on failure.
        """
        conn = self._get_conn()
        if conn is None:
            return {}

        if date_str is None:
            date_str = date.today().isoformat()

        try:
            # Fetch all trades for the day (match on date prefix of timestamp)
            rows = conn.execute(
                """
                SELECT *
                  FROM trades
                 WHERE timestamp LIKE ? || '%'
                 ORDER BY timestamp
                """,
                (date_str,),
            ).fetchall()

            trades = [dict(r) for r in rows]

            if not trades:
                return {
                    "date": date_str,
                    "trade_count": 0,
                    "executed_count": 0,
                    "win_count": 0,
                    "loss_count": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_rr": 0.0,
                    "best_trade": 0.0,
                    "worst_trade": 0.0,
                    "by_tier": {},
                }

            executed = [t for t in trades if t["execution_status"] == "executed"]
            closed = [t for t in executed if t["pnl_dollars"] is not None]
            wins = [t for t in closed if t["pnl_dollars"] > 0]
            losses = [t for t in closed if t["pnl_dollars"] <= 0]

            total_pnl = sum(t["pnl_dollars"] for t in closed)
            pnl_values = [t["pnl_dollars"] for t in closed]
            rr_values = [t["rr_ratio"] for t in executed if t["rr_ratio"] is not None]

            # Per-tier breakdown
            by_tier: Dict[str, Dict[str, Any]] = {}
            for t in executed:
                tier = t.get("shot_tier", "unknown") or "unknown"
                if tier not in by_tier:
                    by_tier[tier] = {
                        "count": 0,
                        "closed": 0,
                        "wins": 0,
                        "pnl": 0.0,
                    }
                by_tier[tier]["count"] += 1
                if t["pnl_dollars"] is not None:
                    by_tier[tier]["closed"] += 1
                    by_tier[tier]["pnl"] += t["pnl_dollars"]
                    if t["pnl_dollars"] > 0:
                        by_tier[tier]["wins"] += 1

            for tier_stats in by_tier.values():
                c = tier_stats["closed"]
                tier_stats["win_rate"] = (
                    tier_stats["wins"] / c if c > 0 else 0.0
                )

            return {
                "date": date_str,
                "trade_count": len(trades),
                "executed_count": len(executed),
                "win_count": len(wins),
                "loss_count": len(losses),
                "win_rate": len(wins) / len(closed) if closed else 0.0,
                "total_pnl": total_pnl,
                "avg_rr": sum(rr_values) / len(rr_values) if rr_values else 0.0,
                "best_trade": max(pnl_values) if pnl_values else 0.0,
                "worst_trade": min(pnl_values) if pnl_values else 0.0,
                "by_tier": by_tier,
            }

        except Exception as e:
            logger.error("Failed to compute daily summary: %s", e, exc_info=True)
            return {}

    def get_tier_stats(self, days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        Compute per-tier performance stats over the last N days.

        Returns:
            Dict keyed by tier name, each containing:
            count, wins, losses, win_rate, total_pnl, avg_pnl,
            expectancy, profit_factor.
        """
        conn = self._get_conn()
        if conn is None:
            return {}

        try:
            # Compute cutoff date
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            rows = conn.execute(
                """
                SELECT shot_tier, direction, pnl_dollars, risk_dollars,
                       reward_dollars, rr_ratio, execution_status
                  FROM trades
                 WHERE timestamp >= ?
                   AND execution_status = 'executed'
                   AND pnl_dollars IS NOT NULL
                 ORDER BY shot_tier
                """,
                (cutoff,),
            ).fetchall()

            tiers: Dict[str, Dict[str, Any]] = {}

            for row in rows:
                r = dict(row)
                tier = r.get("shot_tier", "unknown") or "unknown"
                if tier not in tiers:
                    tiers[tier] = {
                        "count": 0,
                        "wins": 0,
                        "losses": 0,
                        "total_pnl": 0.0,
                        "total_gross_wins": 0.0,
                        "total_gross_losses": 0.0,
                        "rr_values": [],
                    }

                stats = tiers[tier]
                stats["count"] += 1
                pnl = r["pnl_dollars"] or 0.0
                stats["total_pnl"] += pnl

                if pnl > 0:
                    stats["wins"] += 1
                    stats["total_gross_wins"] += pnl
                else:
                    stats["losses"] += 1
                    stats["total_gross_losses"] += abs(pnl)

                if r["rr_ratio"] is not None:
                    stats["rr_values"].append(r["rr_ratio"])

            # Compute derived metrics
            result: Dict[str, Dict[str, Any]] = {}
            for tier, s in tiers.items():
                count = s["count"]
                wins = s["wins"]
                losses = s["losses"]
                win_rate = wins / count if count > 0 else 0.0
                avg_pnl = s["total_pnl"] / count if count > 0 else 0.0
                avg_rr = (
                    sum(s["rr_values"]) / len(s["rr_values"])
                    if s["rr_values"]
                    else 0.0
                )

                # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
                avg_win = s["total_gross_wins"] / wins if wins > 0 else 0.0
                avg_loss = s["total_gross_losses"] / losses if losses > 0 else 0.0
                loss_rate = 1.0 - win_rate
                expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

                # Profit factor = gross_wins / gross_losses
                profit_factor = (
                    s["total_gross_wins"] / s["total_gross_losses"]
                    if s["total_gross_losses"] > 0
                    else float("inf") if s["total_gross_wins"] > 0 else 0.0
                )

                result[tier] = {
                    "count": count,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": win_rate,
                    "total_pnl": s["total_pnl"],
                    "avg_pnl": avg_pnl,
                    "avg_rr": avg_rr,
                    "expectancy": expectancy,
                    "profit_factor": profit_factor,
                }

            return result

        except Exception as e:
            logger.error("Failed to compute tier stats: %s", e, exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ---------------------------------------------------------------------------
# Integration guide
# ---------------------------------------------------------------------------
#
# 1. ORCHESTRATOR — orchestrator/main_loop.py
#
#    In TradingSystem.__init__(), add:
#
#        from monitoring.trade_logger import TradeLogger
#        self.trade_logger = TradeLogger()
#
#    In _process_instrument(), AFTER the prediction (step 3) and
#    composite confidence calculation, add:
#
#        # --- Trade Logger: log prediction ---
#        composite_conf = score_confidence(
#            model_confidence=prediction["confidence"],
#            forecast=prediction["forecast_prices"],
#            uncertainty=prediction["uncertainty"],
#            current_price=prediction["current_price"],
#            regime=prediction["regime"],
#            signal_config=self.signal_config,
#        )
#        # (composite_conf is already computed inside signal_gen.generate();
#        #  you can also retrieve it from signal.confidence if signal is not None)
#        shot_tier = signal.shot_type if signal else "no_trade"
#        pred_id = self.trade_logger.log_prediction(
#            cycle=self.cycle,
#            instrument=instrument,
#            prediction=prediction,
#            composite_confidence=signal.confidence if signal else composite_conf,
#            shot_tier=shot_tier,
#            signal_generated=(signal is not None),
#        )
#
#    AFTER risk validation (step 5) and Apex compliance (step 5b), add:
#
#        # --- Trade Logger: log trade ---
#        if signal is not None:
#            dd_status = self.apex.get_drawdown_status(self.account_equity)
#            inst_cfg = self.config["instruments"][instrument]
#            risk_pts = abs(signal.entry_price - signal.stop_loss)
#            eff_risk_pct = (
#                (risk_pts * inst_cfg["contract_size"] * signal.position_size)
#                / self.account_equity * 100
#            ) if self.account_equity > 0 else 0.0
#
#            # Attach contract_size for the logger
#            signal.contract_size = inst_cfg["contract_size"]
#
#            if not approved:
#                status = "rejected"
#            elif not self.executor:
#                status = "dry_run"
#            else:
#                status = "executed"
#
#            trade_id = self.trade_logger.log_trade(
#                prediction_id=pred_id,
#                instrument=instrument,
#                signal=signal,
#                regime=prediction["regime"],
#                drawdown_cushion=dd_status["cushion"],
#                effective_risk_pct=eff_risk_pct,
#                execution_status=status,
#                rejection_reason=reason if not approved else None,
#            )
#            # Store trade_id on the Position so close_position() can use it
#            # e.g.  position.trade_log_id = trade_id
#
#
# 2. ORDER MANAGER — execution/order_manager.py
#
#    In OrderManager.close_position(), after computing pnl_dollars, add:
#
#        # --- Trade Logger: record exit ---
#        # (requires trade_log_id stored on Position and a TradeLogger reference)
#        if hasattr(pos, 'trade_log_id') and pos.trade_log_id and self.trade_logger:
#            from datetime import datetime
#            duration = (datetime.now() - pos.entry_time).total_seconds() / 60.0
#            self.trade_logger.update_trade_exit(
#                trade_id=pos.trade_log_id,
#                exit_price=exit_price,
#                exit_reason=exit_reason,  # 'take_profit'|'stop_loss'|'timeout'|'flatten'
#                pnl_dollars=pnl_dollars,
#                mae_points=None,   # populate from tick tracking if available
#                mfe_points=None,   # populate from tick tracking if available
#                time_in_trade_minutes=duration,
#            )
#
