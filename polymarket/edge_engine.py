"""
Adaptive Edge Engine — self-adjusting trade filter that monitors performance
across multiple dimensions and auto-adjusts to maintain edge.

Reads from turbo_analytics.db (read-only), computes rolling stats, and
provides gate decisions for the turbo strategy.

Dimensions monitored:
  1. Per-asset rolling WR + PnL
  2. Per-direction rolling WR + PnL
  3. Per-hour-of-day rolling WR + PnL
  4. Per-entry-price-bucket rolling WR + PnL
  5. Overall edge health (recent vs historical)
  6. Circuit breakers (hourly drawdown, loss streaks)
"""

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "turbo_analytics.db"

# ── Thresholds ──────────────────────────────────────────────────

# Minimum WR to allow trading (below this = auto-disable)
ASSET_MIN_WR = 0.30          # Per-asset: disable below 30% WR
DIRECTION_MIN_WR = 0.32      # Per-direction: disable below 32%
HOUR_MIN_WR = 0.28           # Per-hour: disable below 28%

# Minimum sample size before applying filters
MIN_SAMPLES_ASSET = 20
MIN_SAMPLES_DIRECTION = 30
MIN_SAMPLES_HOUR = 15
MIN_SAMPLES_BUCKET = 15

# Entry price buckets (boundaries)
PRICE_BUCKETS = [
    (0.10, 0.20),
    (0.20, 0.25),
    (0.25, 0.30),
    (0.30, 0.35),
    (0.35, 0.40),
    (0.40, 0.50),
]

# Circuit breakers
HOURLY_LOSS_LIMIT = -15.0       # Pause if lose $15 in 1 hour
LOSS_STREAK_COOLDOWN = 2        # After 2 consecutive losses, add cooldown
                                # Data: WR after 2L = 21.2%, -$378 damage
COOLDOWN_BASE_SECONDS = 60      # Base cooldown: 60s, doubles each level
                                # 2L=60s, 3L=120s, 4L=240s, 5L=480s

# Win streak scaling
WIN_STREAK_BONUS_THRESHOLD = 2  # After 2 consecutive wins, scale up
                                # Data: WR after win = 53.2% (+$257)

# Edge decay
EDGE_DECAY_LOOKBACK_RECENT = 50
EDGE_DECAY_LOOKBACK_OVERALL = 200
EDGE_DECAY_THRESHOLD = -0.05    # If recent WR is 5pp below overall, flag decay

# Refresh interval
REFRESH_INTERVAL = 30  # Recalculate from DB every 30 seconds


@dataclass
class DimensionStats:
    """Rolling stats for one dimension value (e.g., asset='btc')."""
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    enabled: bool = True
    reason: str = ""

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.0


@dataclass
class EdgeMetrics:
    """All metrics exported to TUI and strategy."""
    # Per-dimension stats
    asset_stats: Dict[str, DimensionStats] = field(default_factory=dict)
    direction_stats: Dict[str, DimensionStats] = field(default_factory=dict)
    hour_stats: Dict[int, DimensionStats] = field(default_factory=dict)
    bucket_stats: Dict[str, DimensionStats] = field(default_factory=dict)

    # Circuit breakers
    hourly_pnl: float = 0.0
    hourly_limit: float = HOURLY_LOSS_LIMIT
    hourly_paused: bool = False
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    cooldown_until: float = 0.0
    cooldown_active: bool = False
    win_streak_active: bool = False  # True when on a hot streak

    # Edge health
    recent_wr: float = 0.0
    recent_n: int = 0
    overall_wr: float = 0.0
    overall_n: int = 0
    edge_decay: float = 0.0  # recent_wr - overall_wr (negative = fading)
    edge_decaying: bool = False

    # Composite score (0-100)
    edge_score: int = 50

    # Active filters summary
    blocked_assets: List[str] = field(default_factory=list)
    blocked_directions: List[str] = field(default_factory=list)
    blocked_hours: List[int] = field(default_factory=list)
    allowed_price_range: Tuple[float, float] = (0.28, 0.42)

    # Optimal entry band (recalculated from data)
    optimal_floor: float = 0.30
    optimal_ceiling: float = 0.42

    last_refresh: float = 0.0


class AdaptiveEdgeEngine:
    """Self-adjusting trade filter that reads DB and gates trades."""

    def __init__(self, db_path: str = None):
        self._db_path = db_path or str(DB_PATH)
        self._metrics = EdgeMetrics()
        self._last_refresh = 0.0

        # Streak tracking (in-memory, fed by strategy)
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._cooldown_until = 0.0
        self._hourly_trades: list = []  # (timestamp, pnl) tuples

    def refresh(self, force: bool = False):
        """Recalculate all stats from DB. Called every ~30s."""
        now = time.time()
        if not force and (now - self._last_refresh) < REFRESH_INTERVAL:
            return
        self._last_refresh = now

        try:
            conn = sqlite3.connect(self._db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            self._refresh_asset_stats(conn)
            self._refresh_direction_stats(conn)
            self._refresh_hour_stats(conn)
            self._refresh_bucket_stats(conn)
            self._refresh_edge_decay(conn)
            self._refresh_optimal_band(conn)
            self._refresh_hourly_circuit_breaker(conn)
            conn.close()
        except Exception as e:
            logger.warning("[EDGE] DB refresh error: %s", e)
            return

        self._update_cooldown_state()
        self._compute_edge_score()
        self._metrics.last_refresh = now

    def record_outcome(self, is_win: bool, pnl: float):
        """Called by strategy after each resolution to update in-memory state."""
        now = time.time()
        self._hourly_trades.append((now, pnl))

        # Prune old hourly trades
        cutoff = now - 3600
        self._hourly_trades = [(t, p) for t, p in self._hourly_trades if t > cutoff]

        if is_win:
            self._consecutive_losses = 0
            self._consecutive_wins += 1
            if self._consecutive_wins >= WIN_STREAK_BONUS_THRESHOLD:
                logger.info(
                    "[EDGE] Win streak %d — HOT mode active",
                    self._consecutive_wins,
                )
        else:
            self._consecutive_wins = 0
            self._consecutive_losses += 1
            if self._consecutive_losses >= LOSS_STREAK_COOLDOWN:
                # Exponential cooldown: 60s * 2^(streak - threshold)
                level = self._consecutive_losses - LOSS_STREAK_COOLDOWN
                cooldown_secs = COOLDOWN_BASE_SECONDS * (2 ** min(level, 4))
                self._cooldown_until = now + cooldown_secs
                logger.info(
                    "[EDGE] Loss streak %d → cooldown %ds",
                    self._consecutive_losses, cooldown_secs,
                )

    def should_trade(
        self, asset: str, direction: str, entry_price: float,
        signal_type: str = "contrarian",
    ) -> Tuple[bool, str]:
        """
        Gate function: should we take this trade?

        Returns (allowed, reason). If reason is non-empty, trade is blocked.
        """
        self.refresh()  # Auto-refresh if stale
        now = time.time()
        is_market_lean = signal_type == "market_lean"

        # 1. Cooldown (loss streak) — always applies
        if now < self._cooldown_until:
            remaining = int(self._cooldown_until - now)
            return False, f"cooldown_{remaining}s"

        # 2. Hourly circuit breaker — always applies
        hourly_pnl = sum(p for _, p in self._hourly_trades)
        self._metrics.hourly_pnl = hourly_pnl
        if hourly_pnl < HOURLY_LOSS_LIMIT:
            self._metrics.hourly_paused = True
            return False, f"hourly_loss_${hourly_pnl:.0f}"
        self._metrics.hourly_paused = False

        # 3. Asset filter — always applies
        asset_stat = self._metrics.asset_stats.get(asset)
        if asset_stat and asset_stat.total >= MIN_SAMPLES_ASSET and not asset_stat.enabled:
            return False, f"asset_{asset}_blocked_{asset_stat.win_rate:.0%}"

        # 4. Direction filter — skip for market_lean (77.8% WR overrides direction stats)
        if not is_market_lean:
            dir_stat = self._metrics.direction_stats.get(direction)
            if dir_stat and dir_stat.total >= MIN_SAMPLES_DIRECTION and not dir_stat.enabled:
                return False, f"dir_{direction}_blocked_{dir_stat.win_rate:.0%}"

        # 5. Hour filter
        hour_utc = int(time.strftime("%H", time.gmtime()))
        hour_stat = self._metrics.hour_stats.get(hour_utc)
        if hour_stat and hour_stat.total >= MIN_SAMPLES_HOUR and not hour_stat.enabled:
            return False, f"hour_{hour_utc}_blocked_{hour_stat.win_rate:.0%}"

        # 6. Entry price band — two zones allowed:
        #    Momentum zone: 0.30-0.45 — high payoff when momentum confirms
        #    Lean zone (market_lean): 0.45-0.85 — lower payoff, highest WR
        #    Below 0.30: TOXIC (18.6% WR, -$222) — hard blocked
        floor = max(self._metrics.optimal_floor, 0.30)  # hard floor
        ceiling = self._metrics.optimal_ceiling
        in_momentum_zone = floor <= entry_price <= ceiling
        in_lean_zone = 0.45 <= entry_price <= 0.85
        if not in_momentum_zone and not in_lean_zone:
            return False, f"price_blocked_{entry_price:.2f}"

        # 7. Edge decay — if edge is severely fading, require tighter entry
        if self._metrics.edge_decaying and self._metrics.edge_decay < -0.08:
            # Tighten band by 2 cents on each side when edge is rapidly fading
            tight_floor = floor + 0.02
            tight_ceiling = ceiling - 0.02
            if entry_price < tight_floor or entry_price > tight_ceiling:
                return False, f"edge_decay_tight_{entry_price:.2f}"

        return True, ""

    def get_streak_multiplier(self) -> float:
        """
        Bet sizing multiplier based on streak state.

        Data-driven:
          - After 2+ consecutive wins: 1.5x (53.2% WR post-win)
          - After 1 win: 1.0x (normal)
          - After 1 loss: 0.5x (21.8% WR post-loss)
          - During cooldown: 0.0x (blocked by should_trade)
        """
        if self._consecutive_wins >= 3:
            return 1.75  # Hot streak — max confidence
        if self._consecutive_wins >= WIN_STREAK_BONUS_THRESHOLD:
            return 1.5   # Warm streak
        if self._consecutive_losses >= 1:
            return 0.5   # Any loss = half size until proven otherwise
        return 1.0

    def get_metrics(self) -> EdgeMetrics:
        """Return current metrics for TUI display."""
        self.refresh()  # Auto-refresh if stale
        return self._metrics

    # ── Internal Refresh Methods ────────────────────────────────

    def _refresh_asset_stats(self, conn):
        rows = conn.execute("""
            SELECT asset,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                SUM(pnl) as pnl
            FROM turbo_signals
            WHERE traded=1 AND result IS NOT NULL
            GROUP BY asset
        """).fetchall()

        stats = {}
        blocked = []
        for r in rows:
            s = DimensionStats(
                wins=r["w"] or 0, losses=r["l"] or 0, pnl=r["pnl"] or 0.0,
            )
            if s.total >= MIN_SAMPLES_ASSET:
                if s.win_rate < ASSET_MIN_WR:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%} < {ASSET_MIN_WR:.0%}"
                    blocked.append(r["asset"])
                elif s.win_rate < 0.30 and s.pnl < -50:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%} PnL ${s.pnl:.0f}"
                    blocked.append(r["asset"])
            stats[r["asset"]] = s

        self._metrics.asset_stats = stats
        self._metrics.blocked_assets = blocked

    def _refresh_direction_stats(self, conn):
        rows = conn.execute("""
            SELECT signal_direction as d,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                SUM(pnl) as pnl
            FROM turbo_signals
            WHERE traded=1 AND result IS NOT NULL
            GROUP BY signal_direction
        """).fetchall()

        stats = {}
        blocked = []
        for r in rows:
            s = DimensionStats(
                wins=r["w"] or 0, losses=r["l"] or 0, pnl=r["pnl"] or 0.0,
            )
            # Block if: WR below hard floor OR (WR below soft floor AND losing money)
            if s.total >= MIN_SAMPLES_DIRECTION:
                if s.win_rate < DIRECTION_MIN_WR:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%} < {DIRECTION_MIN_WR:.0%}"
                    blocked.append(r["d"])
                elif s.win_rate < 0.30 and s.pnl < -30:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%} + PnL ${s.pnl:.0f}"
                    blocked.append(r["d"])
            stats[r["d"]] = s

        self._metrics.direction_stats = stats
        self._metrics.blocked_directions = blocked

    def _refresh_hour_stats(self, conn):
        rows = conn.execute("""
            SELECT CAST(SUBSTR(timestamp,12,2) AS INTEGER) as hr,
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                SUM(pnl) as pnl
            FROM turbo_signals
            WHERE traded=1 AND result IS NOT NULL
            GROUP BY hr
        """).fetchall()

        stats = {}
        blocked = []
        for r in rows:
            s = DimensionStats(
                wins=r["w"] or 0, losses=r["l"] or 0, pnl=r["pnl"] or 0.0,
            )
            if s.total >= MIN_SAMPLES_HOUR:
                if s.win_rate < HOUR_MIN_WR:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%}"
                    blocked.append(r["hr"])
                elif s.win_rate < 0.28 and s.pnl < -15:
                    s.enabled = False
                    s.reason = f"WR {s.win_rate:.0%} PnL ${s.pnl:.0f}"
                    blocked.append(r["hr"])
            stats[r["hr"]] = s

        self._metrics.hour_stats = stats
        self._metrics.blocked_hours = blocked

    def _refresh_bucket_stats(self, conn):
        stats = {}
        for lo, hi in PRICE_BUCKETS:
            row = conn.execute("""
                SELECT
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                    SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                    SUM(pnl) as pnl
                FROM turbo_signals
                WHERE traded=1 AND result IS NOT NULL
                AND entry_price >= ? AND entry_price < ?
            """, (lo, hi)).fetchone()

            key = f"${lo:.2f}-${hi:.2f}"
            s = DimensionStats(
                wins=row["w"] or 0, losses=row["l"] or 0, pnl=row["pnl"] or 0.0,
            )
            # Buckets with enough data and negative PnL get flagged
            if s.total >= MIN_SAMPLES_BUCKET and s.pnl < 0 and s.win_rate < 0.30:
                s.enabled = False
                s.reason = f"WR {s.win_rate:.0%} PnL ${s.pnl:.0f}"
            stats[key] = s

        self._metrics.bucket_stats = stats

    def _refresh_edge_decay(self, conn):
        """Compare recent N trades to overall to detect edge fading."""
        recent = conn.execute(f"""
            SELECT
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l
            FROM (
                SELECT result FROM turbo_signals
                WHERE traded=1 AND result IS NOT NULL
                ORDER BY id DESC LIMIT {EDGE_DECAY_LOOKBACK_RECENT}
            )
        """).fetchone()

        overall = conn.execute(f"""
            SELECT
                SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l
            FROM (
                SELECT result FROM turbo_signals
                WHERE traded=1 AND result IS NOT NULL
                ORDER BY id DESC LIMIT {EDGE_DECAY_LOOKBACK_OVERALL}
            )
        """).fetchone()

        r_total = (recent["w"] or 0) + (recent["l"] or 0)
        o_total = (overall["w"] or 0) + (overall["l"] or 0)

        r_wr = (recent["w"] or 0) / r_total if r_total > 0 else 0
        o_wr = (overall["w"] or 0) / o_total if o_total > 0 else 0

        self._metrics.recent_wr = r_wr
        self._metrics.recent_n = r_total
        self._metrics.overall_wr = o_wr
        self._metrics.overall_n = o_total
        self._metrics.edge_decay = r_wr - o_wr
        self._metrics.edge_decaying = (
            r_total >= 30 and self._metrics.edge_decay < EDGE_DECAY_THRESHOLD
        )

    def _refresh_optimal_band(self, conn):
        """Recalculate the optimal entry price band from data."""
        best_floor = 0.28
        best_ceiling = 0.42  # Cheap zone ceiling (lean zone 0.55-0.85 handled separately)

        # Find which price buckets are profitable
        profitable_ranges = []
        for lo, hi in PRICE_BUCKETS:
            row = conn.execute("""
                SELECT
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                    SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                    SUM(pnl) as pnl
                FROM turbo_signals
                WHERE traded=1 AND result IS NOT NULL
                AND entry_price >= ? AND entry_price < ?
            """, (lo, hi)).fetchone()

            total = (row["w"] or 0) + (row["l"] or 0)
            pnl = row["pnl"] or 0

            if total >= MIN_SAMPLES_BUCKET and pnl > 0:
                profitable_ranges.append((lo, hi, pnl))

        if profitable_ranges:
            # Use the range covered by profitable buckets
            best_floor = min(lo for lo, hi, p in profitable_ranges)
            best_ceiling = max(hi for lo, hi, p in profitable_ranges)
        else:
            # No profitable buckets — use the least-bad one
            least_bad = None
            for lo, hi in PRICE_BUCKETS:
                row = conn.execute("""
                    SELECT SUM(pnl) as pnl,
                        SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                        SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l
                    FROM turbo_signals
                    WHERE traded=1 AND result IS NOT NULL
                    AND entry_price >= ? AND entry_price < ?
                """, (lo, hi)).fetchone()
                total = (row["w"] or 0) + (row["l"] or 0)
                if total >= MIN_SAMPLES_BUCKET:
                    pnl = row["pnl"] or 0
                    if least_bad is None or pnl > least_bad[2]:
                        least_bad = (lo, hi, pnl)
            if least_bad:
                best_floor = least_bad[0]
                best_ceiling = least_bad[1]

        # Hard cap: entries above 0.42 have 40%+ breakeven WR which we can't achieve
        best_ceiling = min(best_ceiling, 0.42)
        self._metrics.optimal_floor = best_floor
        self._metrics.optimal_ceiling = best_ceiling
        self._metrics.allowed_price_range = (best_floor, best_ceiling)

    def _refresh_hourly_circuit_breaker(self, conn):
        """Check PnL in the last hour from DB."""
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 3600),
        )
        row = conn.execute("""
            SELECT SUM(pnl) as pnl
            FROM turbo_signals
            WHERE traded=1 AND result IS NOT NULL
            AND timestamp >= ?
        """, (cutoff,)).fetchone()

        db_hourly = row["pnl"] or 0.0

        # Merge with in-memory (for trades not yet in DB)
        inmem_hourly = sum(p for _, p in self._hourly_trades)
        self._metrics.hourly_pnl = max(db_hourly, inmem_hourly)  # Use the more negative

    def _update_cooldown_state(self):
        now = time.time()
        self._metrics.consecutive_losses = self._consecutive_losses
        self._metrics.consecutive_wins = self._consecutive_wins
        self._metrics.cooldown_until = self._cooldown_until
        self._metrics.cooldown_active = now < self._cooldown_until
        self._metrics.win_streak_active = (
            self._consecutive_wins >= WIN_STREAK_BONUS_THRESHOLD
        )

    def _compute_edge_score(self):
        """
        Composite edge health score 0-100.

        Components:
          - Direction health (25 pts): Up profitable = full, Down profitable = bonus
          - Asset health (20 pts): % of assets above WR threshold
          - Hour coverage (15 pts): % of active hours that are profitable
          - Entry band width (15 pts): wider profitable band = better
          - Edge trend (15 pts): recent WR vs overall
          - Circuit breaker (10 pts): no breakers active = full
        """
        score = 0

        # Direction health (25 pts)
        dir_pts = 0
        for d, s in self._metrics.direction_stats.items():
            if s.total >= 10 and s.enabled:
                dir_pts += 12.5
        score += min(dir_pts, 25)

        # Asset health (20 pts)
        total_assets = len(self._metrics.asset_stats)
        enabled_assets = sum(
            1 for s in self._metrics.asset_stats.values()
            if s.enabled
        )
        if total_assets > 0:
            score += 20 * (enabled_assets / total_assets)

        # Hour coverage (15 pts)
        total_hours = len(self._metrics.hour_stats)
        enabled_hours = sum(
            1 for s in self._metrics.hour_stats.values()
            if s.enabled
        )
        if total_hours > 0:
            score += 15 * (enabled_hours / total_hours)

        # Entry band width (15 pts) — wider band = more opportunities
        band_width = self._metrics.optimal_ceiling - self._metrics.optimal_floor
        # 0.05 = minimal, 0.20 = full range
        band_score = min(band_width / 0.20, 1.0)
        score += 15 * band_score

        # Edge trend (15 pts)
        if self._metrics.recent_n >= 30:
            decay = self._metrics.edge_decay
            if decay >= 0.05:
                score += 15  # Edge improving
            elif decay >= 0:
                score += 12  # Stable
            elif decay >= -0.05:
                score += 7   # Slight fade
            else:
                score += 0   # Rapid decay
        else:
            score += 7  # Not enough data, neutral

        # Circuit breaker (10 pts)
        breaker_penalty = 0
        if self._metrics.hourly_paused:
            breaker_penalty += 5
        if self._metrics.cooldown_active:
            breaker_penalty += 5
        score += 10 - breaker_penalty

        self._metrics.edge_score = max(0, min(100, int(score)))
