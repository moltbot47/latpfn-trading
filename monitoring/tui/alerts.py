"""Alert engine — rule-based alert generation from trading state."""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DRAWDOWN_STATE_PATH = PROJECT_ROOT / "data" / "drawdown_state.json"
HEARTBEAT_PATH = PROJECT_ROOT / "data" / "heartbeat.json"
ALERT_HISTORY_PATH = PROJECT_ROOT / "data" / "alert_history.json"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """A single alert instance."""
    id: str
    severity: Severity
    title: str
    message: str
    source: str  # "decay", "drawdown", "bot", "pnl", "consistency", "position"
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    @property
    def age_str(self) -> str:
        elapsed = time.time() - self.timestamp
        if elapsed < 60:
            return f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            return f"{int(elapsed / 60)}m ago"
        else:
            return f"{elapsed / 3600:.1f}h ago"

    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))


# Thresholds
DRAWDOWN_WARN_PCT = 40   # warn when <40% cushion remains
DRAWDOWN_CRIT_PCT = 20   # critical when <20% cushion remains
DAILY_LOSS_WARN = 500    # warn at $500 daily loss
DAILY_LOSS_CRIT = 800    # critical at $800 (close to $1000 limit)
LARGE_TRADE_THRESHOLD = 200  # single trade > $200
HEARTBEAT_STALE_SECS = 120  # bot heartbeat stale after 2 min
CONSISTENCY_WARN_PCT = 25    # warn when best day > 25% of total


class AlertEngine:
    """Evaluates trading state and generates alerts."""

    def __init__(self):
        self._active_alerts: Dict[str, Alert] = {}
        self._history: List[Alert] = []
        self._last_strategy_statuses: Dict[str, str] = {}
        self._last_bot_statuses: Dict[str, bool] = {}
        self._alert_counter = 0

    def _make_id(self) -> str:
        self._alert_counter += 1
        return f"alert-{int(time.time())}-{self._alert_counter}"

    def _fire(self, key: str, severity: Severity, title: str, message: str, source: str):
        """Fire or update an alert by dedup key."""
        if key in self._active_alerts and not self._active_alerts[key].acknowledged:
            # Already active and unacknowledged — update timestamp
            self._active_alerts[key].timestamp = time.time()
            self._active_alerts[key].message = message
            return

        alert = Alert(
            id=self._make_id(),
            severity=severity,
            title=title,
            message=message,
            source=source,
        )
        self._active_alerts[key] = alert
        self._history.append(alert)
        # Trim history
        if len(self._history) > 200:
            self._history = self._history[-200:]

    def _clear(self, key: str):
        """Clear an alert by dedup key (condition resolved)."""
        self._active_alerts.pop(key, None)

    def acknowledge(self, alert_id: str):
        """Mark an alert as acknowledged."""
        for alert in self._active_alerts.values():
            if alert.id == alert_id:
                alert.acknowledged = True
                return

    def acknowledge_all(self):
        """Acknowledge all active alerts."""
        for alert in self._active_alerts.values():
            alert.acknowledged = True

    @property
    def active_alerts(self) -> List[Alert]:
        """Return active unacknowledged alerts, sorted by severity then time."""
        severity_order = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}
        return sorted(
            [a for a in self._active_alerts.values() if not a.acknowledged],
            key=lambda a: (severity_order.get(a.severity, 9), -a.timestamp),
        )

    @property
    def all_active(self) -> List[Alert]:
        """Return all active alerts including acknowledged."""
        severity_order = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}
        return sorted(
            self._active_alerts.values(),
            key=lambda a: (severity_order.get(a.severity, 9), -a.timestamp),
        )

    @property
    def alert_count(self) -> int:
        return len(self.active_alerts)

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.active_alerts if a.severity == Severity.CRITICAL)

    # ── Rule evaluators ──────────────────────────────────────────

    def evaluate_all(
        self,
        strategies: list,
        drawdown_state: Optional[dict] = None,
        bot_statuses: Optional[Dict[str, bool]] = None,
        cme_scorecard: Optional[dict] = None,
        daily_pnl: float = 0,
        recent_trades: Optional[list] = None,
    ):
        """Run all alert rules against current state."""
        self._check_strategy_decay(strategies)
        self._check_drawdown(drawdown_state)
        self._check_bots(bot_statuses)
        self._check_daily_pnl(daily_pnl, cme_scorecard)
        self._check_large_trades(recent_trades)
        self._check_consistency(cme_scorecard)
        self._check_heartbeat()

    def _check_strategy_decay(self, strategies: list):
        """Alert on strategy status changes (STABLE->WARNING->DECAYING)."""
        if not strategies:
            return

        for s in strategies:
            key = f"decay-{s.name}"
            prev = self._last_strategy_statuses.get(s.name, "STABLE")

            if s.status == "DECAYING":
                self._fire(
                    key, Severity.WARN,
                    f"{s.name} DECAYING",
                    f"Recent WR {s.recent_wr:.0%} vs overall {s.overall_wr:.0%} "
                    f"({s.edge_decay * 100:+.1f}pp) — {s.total_trades} trades",
                    "decay",
                )
            elif s.status == "WARNING" and prev in ("STABLE", "INACTIVE"):
                self._fire(
                    key, Severity.INFO,
                    f"{s.name} edge warning",
                    f"Recent WR {s.recent_wr:.0%} vs overall {s.overall_wr:.0%} "
                    f"({s.edge_decay * 100:+.1f}pp)",
                    "decay",
                )
            elif s.status == "STABLE" and prev in ("DECAYING", "WARNING"):
                self._clear(key)

            self._last_strategy_statuses[s.name] = s.status

    def _check_drawdown(self, state: Optional[dict]):
        """Alert on Apex trailing drawdown proximity."""
        if not state:
            # Try reading from file
            try:
                if DRAWDOWN_STATE_PATH.exists():
                    with open(DRAWDOWN_STATE_PATH) as f:
                        state = json.load(f)
                else:
                    return
            except Exception:
                return

        highest = state.get("highest_balance", 50000)
        floor = state.get("drawdown_floor", 47500)
        locked = state.get("floor_locked", False)

        # We need current balance to compute cushion.
        # Approximate from highest (conservative — actual balance <= highest)
        # The real cushion is computed in the app with live equity data.
        cushion = highest - floor
        max_dd = 2500  # Apex trailing drawdown amount

        if locked:
            self._clear("drawdown-proximity")
            self._fire(
                "drawdown-locked", Severity.INFO,
                "Drawdown floor locked",
                f"Floor locked at ${floor:,.0f} — trailing stopped",
                "drawdown",
            )
            return

        self._clear("drawdown-locked")

        # These alerts get updated with real balance in evaluate_drawdown_live()
        cushion_pct = (cushion / max_dd) * 100 if max_dd > 0 else 100
        if cushion_pct <= DRAWDOWN_CRIT_PCT:
            self._fire(
                "drawdown-proximity", Severity.CRITICAL,
                "DRAWDOWN CRITICAL",
                f"Only ${cushion:,.0f} cushion remaining ({cushion_pct:.0f}%) — "
                f"floor ${floor:,.0f}",
                "drawdown",
            )
        elif cushion_pct <= DRAWDOWN_WARN_PCT:
            self._fire(
                "drawdown-proximity", Severity.WARN,
                "Drawdown warning",
                f"${cushion:,.0f} cushion remaining ({cushion_pct:.0f}%) — "
                f"floor ${floor:,.0f}",
                "drawdown",
            )
        else:
            self._clear("drawdown-proximity")

    def evaluate_drawdown_live(self, current_balance: float, floor: float, max_dd: float = 2500):
        """Update drawdown alerts with live balance data."""
        cushion = current_balance - floor
        cushion_pct = (cushion / max_dd) * 100 if max_dd > 0 else 100

        if cushion_pct <= DRAWDOWN_CRIT_PCT:
            self._fire(
                "drawdown-proximity", Severity.CRITICAL,
                "DRAWDOWN CRITICAL",
                f"Balance ${current_balance:,.0f} — only ${cushion:,.0f} above "
                f"floor ${floor:,.0f} ({cushion_pct:.0f}%)",
                "drawdown",
            )
        elif cushion_pct <= DRAWDOWN_WARN_PCT:
            self._fire(
                "drawdown-proximity", Severity.WARN,
                "Drawdown warning",
                f"Balance ${current_balance:,.0f} — ${cushion:,.0f} above "
                f"floor ${floor:,.0f} ({cushion_pct:.0f}%)",
                "drawdown",
            )
        else:
            self._clear("drawdown-proximity")

    def _check_bots(self, statuses: Optional[Dict[str, bool]]):
        """Alert when bots go offline."""
        if not statuses:
            return

        for name, alive in statuses.items():
            key = f"bot-{name}"
            prev = self._last_bot_statuses.get(name, True)

            if not alive and prev:
                # Just went offline
                self._fire(
                    key, Severity.CRITICAL,
                    f"{name} bot OFFLINE",
                    f"{name} trading bot is not running — trades will not execute",
                    "bot",
                )
            elif alive and not prev:
                # Came back online
                self._clear(key)
                self._fire(
                    f"bot-recovered-{name}", Severity.INFO,
                    f"{name} bot recovered",
                    f"{name} trading bot is back online",
                    "bot",
                )

            self._last_bot_statuses[name] = alive

    def _check_daily_pnl(self, daily_pnl: float, cme_sc: Optional[dict]):
        """Alert on daily loss thresholds."""
        pnl = daily_pnl
        if cme_sc:
            pnl = cme_sc.get("total_pnl", 0)

        if pnl <= -DAILY_LOSS_CRIT:
            self._fire(
                "daily-loss", Severity.CRITICAL,
                "DAILY LOSS LIMIT",
                f"Daily P&L ${pnl:+,.0f} approaching $1,000 limit — "
                f"consider stopping trading",
                "pnl",
            )
        elif pnl <= -DAILY_LOSS_WARN:
            self._fire(
                "daily-loss", Severity.WARN,
                "Daily loss warning",
                f"Daily P&L ${pnl:+,.0f} — approaching daily limit",
                "pnl",
            )
        else:
            self._clear("daily-loss")

    def _check_large_trades(self, trades: Optional[list]):
        """Alert on unusually large individual trades."""
        if not trades:
            return

        # Only check the most recent trade
        for t in trades[:1]:
            pnl = 0
            if isinstance(t, dict):
                pnl = t.get("pnl", 0)
            elif hasattr(t, "pnl"):
                pnl = t.pnl or 0

            if abs(pnl) >= LARGE_TRADE_THRESHOLD:
                if pnl > 0:
                    self._fire(
                        "large-trade", Severity.INFO,
                        f"Large win: ${pnl:+,.0f}",
                        f"Single trade P&L ${pnl:+,.2f}",
                        "pnl",
                    )
                else:
                    self._fire(
                        "large-trade", Severity.WARN,
                        f"Large loss: ${pnl:+,.0f}",
                        f"Single trade loss ${pnl:+,.2f} — review position sizing",
                        "pnl",
                    )

    def _check_consistency(self, cme_sc: Optional[dict]):
        """Alert on Apex consistency rule risk."""
        if not cme_sc:
            return

        total_pnl = cme_sc.get("total_pnl", 0)
        if total_pnl <= 0:
            self._clear("consistency")
            return

        # Check if today's P&L is too large a fraction of total
        # (simplified — full check needs per-day tracking)
        pnl_today = cme_sc.get("total_pnl", 0)  # 24h window as proxy
        if total_pnl > 0 and pnl_today > 0:
            pct = pnl_today / total_pnl
            if pct > 0.30:
                self._fire(
                    "consistency", Severity.WARN,
                    "Consistency rule risk",
                    f"Today's P&L ${pnl_today:+,.0f} is {pct:.0%} of total "
                    f"${total_pnl:+,.0f} — Apex max is 30%",
                    "consistency",
                )
            elif pct > CONSISTENCY_WARN_PCT / 100:
                self._fire(
                    "consistency", Severity.INFO,
                    "Consistency watch",
                    f"Today's P&L ${pnl_today:+,.0f} is {pct:.0%} of total "
                    f"${total_pnl:+,.0f} — approaching 30% limit",
                    "consistency",
                )
            else:
                self._clear("consistency")

    def _check_heartbeat(self):
        """Alert if bot heartbeat is stale."""
        try:
            if not HEARTBEAT_PATH.exists():
                self._fire(
                    "heartbeat", Severity.WARN,
                    "No heartbeat",
                    "Heartbeat file not found — bot may not be running",
                    "bot",
                )
                return

            with open(HEARTBEAT_PATH) as f:
                hb = json.load(f)

            ts_str = hb.get("timestamp", "")
            if not ts_str:
                return

            from datetime import datetime
            try:
                dt = datetime.fromisoformat(ts_str)
                age = time.time() - dt.timestamp()
            except Exception:
                age = 999

            if age > HEARTBEAT_STALE_SECS:
                self._fire(
                    "heartbeat", Severity.WARN,
                    "Stale heartbeat",
                    f"Last heartbeat {age:.0f}s ago (cycle {hb.get('cycle', '?')}) — "
                    f"bot may be stuck",
                    "bot",
                )
            else:
                self._clear("heartbeat")

        except Exception:
            pass
