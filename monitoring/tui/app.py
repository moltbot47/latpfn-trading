"""Turbo TUI Dashboard — real-time terminal trading dashboard.

Layout:
  ┌────────────────────────────┬──────────────────────┐
  │ POSITIONS (live timers)    │                      │
  ├────────────────────────────┤  TRADE FEED          │
  │ STATS + EDGE               │  (full-height        │
  ├──────────────┬─────────────┤   vertical column,   │
  │ ASSET PERF   │ PnL CHART  │   scrollable ↑↓)     │
  └──────────────┴─────────────┴──────────────────────┘
  Press 't' to focus trade feed for scrolling, Esc to unfocus.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static

from monitoring.tui.data_layer import DataManager

SPARK_CHARS = "▁▂▃▄▅▆▇█"
SCORE_BAR = "■"


class TurboTUIApp(App):
    """Real-time Turbo trading dashboard."""

    TITLE = "TURBO CONTRARIAN"
    CSS_PATH = "turbo_tui.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("d", "toggle_dark", "Theme"),
        ("t", "focus_feed", "Trade Feed"),
        ("escape", "unfocus", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self.data_mgr = DataManager()
        self._bot_pid = 0
        self._edge_score = 0
        self._scorecard_cache = {}
        self._edge_cache = None
        self._positions_cache = []
        self._trade_feed_focused = False
        self._hl_data = None
        self._hl_poll_count = 0

    def compose(self) -> ComposeResult:
        yield Static(
            " [bold]TURBO CONTRARIAN[/]  |  Loading...",
            id="status-header",
        )
        with Horizontal(id="main-row"):
            with Vertical(id="left-col"):
                yield Static(
                    " [dim]Loading positions...[/]",
                    id="open-positions",
                )
                yield Static(
                    " [dim]Loading stats...[/]",
                    id="stats-panel",
                )
                with Horizontal(id="bottom-stats"):
                    yield Static(
                        " [dim]Loading assets...[/]",
                        id="asset-perf",
                    )
                    yield Static(
                        " [dim]Waiting for PnL...[/]",
                        id="pnl-chart",
                    )
                yield Static(
                    " [dim]Connecting to Hyperliquid...[/]",
                    id="hl-intel",
                )
            yield Static(
                " [dim]Waiting for trade data...[/]",
                id="trade-feed",
            )
        yield Footer()

    def on_mount(self):
        try:
            self.query_one("#open-positions").border_title = "POSITIONS (live)"
            self.query_one("#stats-panel").border_title = "SCORECARD + EDGE"
            self.query_one("#asset-perf").border_title = "ASSET PERFORMANCE"
            self.query_one("#pnl-chart").border_title = "PnL CHART"
            self.query_one("#trade-feed").border_title = (
                "TRADE FEED  [dim](t=focus, ↑↓=scroll)[/]"
            )
            self.query_one("#hl-intel").border_title = (
                "HL INTEL  [dim](cross-platform)[/]"
            )
            # Make trade feed focusable for keyboard scrolling
            self.query_one("#trade-feed").can_focus = True
        except Exception:
            pass

        self._bot_pid = self._find_bot_pid()

        self.set_timer(1.5, self._do_poll)
        self.set_interval(2.0, self._do_poll)
        # 1-second timer for live position countdown + header clock
        self.set_interval(1.0, self._tick_second)

    # ── Actions ─────────────────────────────────────────────────

    def action_focus_feed(self):
        try:
            feed = self.query_one("#trade-feed")
            feed.focus()
            self._trade_feed_focused = True
            feed.border_title = (
                "TRADE FEED  [bold green]FOCUSED[/]"
                "  [dim](↑↓=scroll, Esc=back)[/]"
            )
        except Exception:
            pass

    def action_unfocus(self):
        try:
            self.query_one("#trade-feed").border_title = (
                "TRADE FEED  [dim](t=focus, ↑↓=scroll)[/]"
            )
            self._trade_feed_focused = False
            self.screen.focus_next()
        except Exception:
            pass

    def action_refresh(self):
        asyncio.create_task(self._do_poll())
        self._bot_pid = self._find_bot_pid()

    # ── Bot PID ─────────────────────────────────────────────────

    def _find_bot_pid(self) -> int:
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-f", "discord_bot.runner"],
                capture_output=True, text=True, timeout=2,
            )
            pids = result.stdout.strip().split("\n")
            if pids and pids[0]:
                return int(pids[0])
        except Exception:
            pass
        return 0

    # ── 1-second tick (timers + header) ─────────────────────────

    def _tick_second(self):
        """Update positions countdown timers and header every second."""
        self._update_header()
        self._render_positions()

    # ── 2-second polling ────────────────────────────────────────

    async def _do_poll(self):
        try:
            data = await asyncio.to_thread(self.data_mgr.poll_db)
            self._scorecard_cache = data.get("scorecard", {})
            self._apply_trades(data.get("trades", []))
            self._apply_pnl_chart(data.get("pnl_series", []))
            self._apply_asset_perf(
                self._scorecard_cache.get("asset_dir_stats", [])
            )
        except Exception:
            pass

        try:
            self._positions_cache = await asyncio.to_thread(
                self.data_mgr.poll_positions
            )
            self._render_positions()
        except Exception:
            pass

        try:
            self._edge_cache = await asyncio.to_thread(
                self.data_mgr.poll_edge_metrics
            )
            if self._edge_cache:
                self._edge_score = self._edge_cache.edge_score
        except Exception:
            pass

        # Render combined stats panel (needs both scorecard + edge)
        self._render_stats_panel()

        # Poll HL data every 5 cycles (~10 seconds) to avoid API rate limits
        self._hl_poll_count += 1
        if self._hl_poll_count % 5 == 0:
            try:
                self._hl_data = await asyncio.to_thread(
                    self.data_mgr.poll_hl_data
                )
            except Exception:
                pass
        self._render_hl_intel()

    # ── Positions with LIVE countdown ──────────────────────────

    def _render_positions(self):
        try:
            positions = self._positions_cache
            now = time.time()

            lines = [
                f" {'Asset':5s} {'Dir':4s} {'Entry':>6s}"
                f" {'$':>5s} {'Age':>5s} {'TTL':>5s}",
                f" {'─' * 5} {'─' * 4} {'─' * 6}"
                f" {'─' * 5} {'─' * 5} {'─' * 5}",
            ]

            for pos in positions:
                question = pos.get("question", "")
                asset = question.split(" ")[0] if question else "?"
                direction = pos.get("direction", "?")
                entry = pos.get("entry_price", 0) or 0
                size = pos.get("size_usdc", 0) or 0
                ds = "green" if direction == "Up" else "red"

                # Age
                age_str = ""
                opened = pos.get("opened_at", "")
                if opened:
                    try:
                        dt = datetime.fromisoformat(
                            opened.replace("Z", "+00:00")
                        )
                        age_s = now - dt.timestamp()
                        m, s = divmod(int(age_s), 60)
                        age_str = f"{m}:{s:02d}"
                    except Exception:
                        pass

                # TTL countdown to resolution
                ttl_str = ""
                res_date = pos.get("resolution_date", "")
                if res_date:
                    try:
                        dt = datetime.fromisoformat(
                            res_date.replace("Z", "+00:00")
                        )
                        ttl_s = dt.timestamp() - now
                        if ttl_s > 0:
                            m, s = divmod(int(ttl_s), 60)
                            if ttl_s <= 30:
                                ttl_str = f"[bold red]{m}:{s:02d}[/]"
                            elif ttl_s <= 60:
                                ttl_str = f"[yellow]{m}:{s:02d}[/]"
                            else:
                                ttl_str = f"[green]{m}:{s:02d}[/]"
                        else:
                            ttl_str = "[bold]DONE[/]"
                    except Exception:
                        pass

                lines.append(
                    f" {asset:5s} [{ds}]{direction:4s}[/]"
                    f" {entry:6.3f} ${size:4.1f}"
                    f" [dim]{age_str:>5s}[/] {ttl_str:>5s}"
                )

            if not positions:
                lines.append(" [dim]No open turbo positions[/]")
            else:
                total_size = sum(
                    (p.get("size_usdc", 0) or 0) for p in positions
                )
                lines.append(
                    f"\n [bold]{len(positions)}[/] pos"
                    f"  [dim]${total_size:.2f} deployed[/]"
                )

            self.query_one("#open-positions", Static).update(
                "\n".join(lines)
            )
        except Exception:
            pass

    # ── Combined Stats Panel (scorecard + edge) ─────────────────

    def _render_stats_panel(self):
        try:
            sc = self._scorecard_cache
            m = self._edge_cache
            if not sc:
                return

            wins = sc.get("wins", 0)
            losses = sc.get("losses", 0)
            total_pnl = sc.get("total_pnl", 0)
            win_rate = sc.get("win_rate", 0)
            streak = sc.get("streak", 0)
            streak_type = sc.get("streak_type", "")
            trades = sc.get("trades", 0)
            payoff = sc.get("payoff_ratio", 0)
            avg_win = sc.get("avg_win", 0)
            avg_loss = sc.get("avg_loss", 0)
            max_dd = sc.get("max_drawdown", 0)
            cur_dd = sc.get("current_dd", 0)
            kelly = sc.get("kelly_pct", 0)
            pnl_1h = sc.get("pnl_1h", 0)
            pnl_6h = sc.get("pnl_6h", 0)
            tph = sc.get("trades_per_hour", 0)
            br = sc.get("block_rate", 0)
            eb = sc.get("edge_blocks", 0)

            ps = "green" if total_pnl >= 0 else "red"
            ws = "green" if win_rate >= 34 else "red"
            sc_char = streak_type[0].upper() if streak_type else ""
            ss = (
                "green" if streak_type == "win"
                else "red" if streak_type == "loss"
                else "dim"
            )

            lines = []

            # Row 1: Record + PnL
            ev = total_pnl / trades if trades > 0 else 0
            es = "green" if ev >= 0 else "red"
            lines.append(
                f" [green]{wins}W[/]/[red]{losses}L[/]"
                f" [{ws}]{win_rate:.1f}%[/]"
                f"  [{ps}]${total_pnl:+.2f}[/]"
                f"  EV:[{es}]${ev:+.3f}[/]"
                f"  [{ss}]{streak}{sc_char}[/]"
                f"  [dim]{tph:.0f}t/hr[/]"
            )

            # Row 2: Payoff + DD + Kelly
            pf_s = "green" if payoff >= 1.5 else "yellow" if payoff >= 1.0 else "red"
            dd_s = "green" if cur_dd < 50 else "yellow" if cur_dd < 150 else "red"
            ks = "green" if kelly > 5 else "yellow" if kelly > 0 else "red"
            lines.append(
                f" Payoff:[{pf_s}]{payoff:.2f}x[/]"
                f" [dim](W${avg_win:+.1f}/L${avg_loss:.1f})[/]"
                f"  DD:[{dd_s}]${cur_dd:.0f}[/]"
                f"[dim]/${max_dd:.0f}[/]"
                f"  Kelly:[{ks}]{kelly:.1f}%[/]"
            )

            # Row 3: Time PnL
            p1s = "green" if pnl_1h >= 0 else "red"
            p6s = "green" if pnl_6h >= 0 else "red"
            lines.append(
                f" 1h:[{p1s}]${pnl_1h:+.2f}[/]"
                f"  6h:[{p6s}]${pnl_6h:+.2f}[/]"
                f"  24h:[{ps}]${total_pnl:+.2f}[/]"
            )

            # Divider
            lines.append(" [dim]─────────────────────────────────────────[/]")

            # Edge metrics (if available)
            if m:
                score = m.edge_score
                sc_s = (
                    "green" if score >= 70
                    else "yellow" if score >= 40
                    else "red"
                )
                filled = score // 10
                bar = (
                    f"[{sc_s}]{SCORE_BAR * filled}[/]"
                    f"[dim]{'□' * (10 - filled)}[/]"
                )
                br_s = "green" if br > 30 else "yellow" if br > 10 else "dim"
                lines.append(
                    f" EDGE:[{sc_s}]{score}[/] {bar}"
                    f"  [{br_s}]Filter:{br:.0f}%[/]"
                    f"[dim]({eb}blk)[/]"
                )

                # Direction + Assets
                dir_parts = []
                for d in ["Up", "Down"]:
                    s = m.direction_stats.get(d)
                    if s:
                        st = "green" if s.enabled else "red"
                        dir_parts.append(
                            f"[{st}]{d}({s.win_rate:.0%})[/]"
                        )
                asset_parts = []
                for a in sorted(m.asset_stats.keys()):
                    s = m.asset_stats[a]
                    st = "green" if s.enabled else "red"
                    asset_parts.append(f"[{st}]{a.upper()}[/]")

                lines.append(
                    f" Dir: {' '.join(dir_parts)}"
                    f"  Assets: {' '.join(asset_parts)}"
                )

                # Hours heatmap
                hm = ""
                for hr in range(24):
                    s = m.hour_stats.get(hr)
                    if s and s.total >= 5:
                        if s.pnl > 5:
                            hm += "[green]█[/]"
                        elif s.pnl > 0:
                            hm += "[green]▒[/]"
                        elif s.pnl > -10:
                            hm += "[yellow]░[/]"
                        else:
                            hm += "[red]█[/]"
                    else:
                        hm += "[dim]·[/]"

                lines.append(
                    f" Band:[bold]${m.optimal_floor:.2f}"
                    f"-${m.optimal_ceiling:.2f}[/]"
                    f"  Hr: {hm}"
                )
                lines.append(
                    "             [dim]"
                    "0     6    12    18  23[/]"
                )

                # Breakers + health
                hp_s = "red" if m.hourly_paused else "green"
                hp_t = "STOP" if m.hourly_paused else "OK"

                # Streak state
                streak_str = ""
                if m.cooldown_active:
                    rem = max(0, int(m.cooldown_until - time.time()))
                    streak_str = f" [red]COOL:{rem}s[/]"
                elif m.win_streak_active:
                    streak_str = (
                        f" [bold green]HOT:{m.consecutive_wins}W"
                        f" 1.5x[/]"
                    )
                elif m.consecutive_losses >= 1:
                    streak_str = (
                        f" [red]{m.consecutive_losses}L"
                        f" 0.5x[/]"
                    )
                else:
                    streak_str = " [dim]0[/]"

                decay = m.edge_decay
                if decay >= 0.02:
                    d_tag = "[green]▲GAIN[/]"
                elif decay >= -0.03:
                    d_tag = "[green]STABLE[/]"
                elif decay >= -0.06:
                    d_tag = "[yellow]▼FADE[/]"
                else:
                    d_tag = "[red]▼DECAY[/]"

                r_s = (
                    "green" if m.recent_wr >= 0.30
                    else "yellow" if m.recent_wr >= 0.25
                    else "red"
                )
                lines.append(
                    f" HrPnL:[{hp_s}]${m.hourly_pnl:+.1f}[/]"
                    f"/{m.hourly_limit:.0f}[{hp_s}]{hp_t}[/]"
                    f"{streak_str}"
                    f"  [{r_s}]{m.recent_wr:.0%}[/]"
                    f"/{m.overall_wr:.0%}"
                    f" {d_tag}"
                )

            self.query_one("#stats-panel", Static).update(
                "\n".join(lines)
            )
        except Exception:
            pass

    # ── Asset Performance ──────────────────────────────────────

    def _apply_asset_perf(self, stats: list):
        try:
            if not stats:
                return

            assets = {}
            for s in stats:
                a = s["asset"]
                if a not in assets:
                    assets[a] = {"w": 0, "l": 0, "pnl": 0.0, "dirs": {}}
                assets[a]["w"] += s["wins"]
                assets[a]["l"] += s["losses"]
                assets[a]["pnl"] += s["pnl"]
                assets[a]["dirs"][s["direction"]] = {
                    "w": s["wins"], "l": s["losses"], "pnl": s["pnl"],
                }

            lines = [
                f" {'':4s} {'W':>3s} {'L':>3s} {'WR':>5s}"
                f" {'PnL':>7s} {'Up$':>6s} {'Dn$':>6s}",
                f" {'─' * 4} {'─' * 3} {'─' * 3} {'─' * 5}"
                f" {'─' * 7} {'─' * 6} {'─' * 6}",
            ]

            for a in sorted(assets.keys()):
                d = assets[a]
                total = d["w"] + d["l"]
                wr = d["w"] / total if total > 0 else 0
                wr_s = (
                    "green" if wr >= 0.34
                    else "yellow" if wr >= 0.28
                    else "red"
                )
                p_s = "green" if d["pnl"] >= 0 else "red"

                up_pnl = d["dirs"].get("Up", {}).get("pnl", 0)
                dn_pnl = d["dirs"].get("Down", {}).get("pnl", 0)
                up_s = "green" if up_pnl >= 0 else "red"
                dn_s = "green" if dn_pnl >= 0 else "red"

                lines.append(
                    f" {a.upper():4s}"
                    f" {d['w']:3d} {d['l']:3d}"
                    f" [{wr_s}]{wr:5.1%}[/]"
                    f" [{p_s}]${d['pnl']:+6.0f}[/]"
                    f" [{up_s}]${up_pnl:+5.0f}[/]"
                    f" [{dn_s}]${dn_pnl:+5.0f}[/]"
                )

            # Totals
            up_t = sum(
                s["pnl"] for s in stats if s["direction"] == "Up"
            )
            dn_t = sum(
                s["pnl"] for s in stats if s["direction"] == "Down"
            )
            us = "green" if up_t >= 0 else "red"
            ds = "green" if dn_t >= 0 else "red"
            lines.append(
                f" [dim]{'─' * 4} {'─' * 3} {'─' * 3}"
                f" {'─' * 5} {'─' * 7}[/]"
                f" [{us}]${up_t:+5.0f}[/]"
                f" [{ds}]${dn_t:+5.0f}[/]"
            )

            self.query_one("#asset-perf", Static).update(
                "\n".join(lines)
            )
        except Exception:
            pass

    # ── Trade Feed (vertical column, scrollable) ────────────────

    def _apply_trades(self, trades: list):
        try:
            lines = []
            # Trades come DESC from DB, reverse for chronological
            # (oldest at top, newest at bottom)
            for trade in reversed(trades):
                if trade.result == "win":
                    tag = "[green]W[/]"
                    pnl = f"[green]+${trade.pnl:.2f}[/]"
                elif trade.result == "loss":
                    tag = "[red]L[/]"
                    pnl = f"[red]-${abs(trade.pnl):.2f}[/]"
                else:
                    tag = "[yellow]?[/]"
                    pnl = "..."

                d_s = "green" if trade.direction == "Up" else "red"
                ts = (
                    trade.timestamp[11:16]
                    if len(trade.timestamp) > 16
                    else trade.timestamp[-5:]
                )
                d_ch = "▲" if trade.direction == "Up" else "▼"

                lines.append(
                    f" {ts} [{d_s}]{d_ch}[/]"
                    f"{trade.asset.upper():3s}"
                    f" {trade.entry_price:.2f}"
                    f" {tag} {pnl}"
                )

            if lines:
                feed = self.query_one("#trade-feed", Static)
                feed.update("\n".join(lines))
                # Auto-scroll to bottom (newest) unless user is scrolling
                if not self._trade_feed_focused:
                    feed.scroll_end(animate=False)
            else:
                self.query_one("#trade-feed", Static).update(
                    " [dim]No trades yet...[/]"
                )
        except Exception:
            pass

    # ── PnL Chart ───────────────────────────────────────────────

    def _apply_pnl_chart(self, series: list):
        try:
            if not series or len(series) < 2:
                return

            width = 35
            try:
                w = self.query_one("#pnl-chart", Static)
                if w.size.width > 6:
                    width = max(w.size.width - 6, 20)
            except Exception:
                pass

            if len(series) > width:
                step = len(series) / width
                series = [series[int(i * step)] for i in range(width)]

            min_v = min(series)
            max_v = max(series)
            rng = max_v - min_v or 1

            spark = ""
            for v in series:
                idx = int((v - min_v) / rng * (len(SPARK_CHARS) - 1))
                ch = SPARK_CHARS[idx]
                spark += (
                    f"[green]{ch}[/]" if v >= 0 else f"[red]{ch}[/]"
                )

            cur = series[-1]
            cs = "green" if cur >= 0 else "red"

            peak = self._scorecard_cache.get("peak_pnl", 0)
            max_dd = self._scorecard_cache.get("max_drawdown", 0)
            best = self._scorecard_cache.get("best_trade", 0)
            worst = self._scorecard_cache.get("worst_trade", 0)

            self.query_one("#pnl-chart", Static).update(
                f" [{cs}]${cur:+.2f}[/]\n"
                f" [dim]lo ${min_v:.0f}/hi ${max_v:.0f}[/]\n\n"
                f" {spark}\n\n"
                f" [dim]Peak ${peak:.0f}"
                f" DD ${max_dd:.0f}[/]\n"
                f" [dim]Best ${best:+.1f}"
                f" Worst ${worst:.1f}[/]"
            )
        except Exception:
            pass

    # ── HL Intel Panel ─────────────────────────────────────────

    def _render_hl_intel(self):
        """Render Hyperliquid cross-platform intelligence panel."""
        try:
            hl = self._hl_data
            if not hl:
                self.query_one("#hl-intel", Static).update(
                    " [dim]No HL data — API not connected[/]"
                )
                return

            lines = []

            # Row 1: Account summary
            equity = hl.get("equity", 0)
            leverage = hl.get("leverage", 0)
            pos_count = hl.get("position_count", 0)
            unrealized = hl.get("unrealized_pnl", 0)
            u_s = "green" if unrealized >= 0 else "red"
            l_s = "green" if leverage < 5 else "yellow" if leverage < 8 else "red"

            lines.append(
                f" HL: ${equity:.0f}"
                f"  [{l_s}]{leverage:.1f}x[/]"
                f"  {pos_count}pos"
                f"  [{u_s}]${unrealized:+.2f}[/]"
            )

            # Row 2: Funding rates for core pairs
            funding = hl.get("funding_rates", {})
            if funding:
                parts = []
                for coin in ("btc", "eth", "sol"):
                    f_data = funding.get(coin, {})
                    annual = f_data.get("annual", 0) * 100
                    if abs(annual) > 1:
                        f_s = "green" if annual < 0 else "red"  # negative = shorts pay = bullish
                        parts.append(f"{coin.upper()}:[{f_s}]{annual:+.0f}%/yr[/]")
                    else:
                        parts.append(f"{coin.upper()}:[dim]~0[/]")
                lines.append(f" Fund: {' '.join(parts)}")

            # Row 3: Position manager actions
            pm_actions = hl.get("recent_actions", [])
            if pm_actions:
                latest = pm_actions[-1]
                a_s = "red" if "loss" in latest.get("action", "") else "yellow"
                lines.append(
                    f" PM: [{a_s}]{latest.get('action', '?')}[/]"
                    f" {latest.get('coin', '?')}"
                    f" — {latest.get('reason', '')[:40]}"
                )
            else:
                lines.append(" PM: [dim]no recent actions[/]")

            # Row 4: Cross-platform feedback status
            turbo_wr = hl.get("turbo_asset_wr", {})
            if turbo_wr:
                parts = []
                for asset, wr in turbo_wr.items():
                    w_s = "green" if wr >= 0.35 else "yellow" if wr >= 0.25 else "red"
                    parts.append(f"[{w_s}]{asset.upper()}:{wr:.0%}[/]")
                lines.append(f" Turbo WR→HL: {' '.join(parts)}")

            hl_wr = hl.get("hl_asset_wr", {})
            if hl_wr:
                parts = []
                for asset, wr in list(hl_wr.items())[:4]:
                    w_s = "green" if wr >= 0.50 else "yellow" if wr >= 0.30 else "red"
                    parts.append(f"[{w_s}]{asset.upper()}:{wr:.0%}[/]")
                lines.append(f" HL WR→Turbo: {' '.join(parts)}")

            # Row 5: Gatekeeper blocks
            blocks = hl.get("gate_blocks", [])
            if blocks:
                latest_block = blocks[-1]
                lines.append(
                    f" Gate: [red]BLOCKED[/] {latest_block[0]}"
                    f" — {latest_block[1][:45]}"
                )

            self.query_one("#hl-intel", Static).update("\n".join(lines))
        except Exception:
            pass

    # ── Header ──────────────────────────────────────────────────

    def _update_header(self):
        try:
            now = time.strftime("%H:%M:%S")
            bot_alive = False

            if self._bot_pid:
                try:
                    os.kill(self._bot_pid, 0)
                    bot_alive = True
                except (OSError, ProcessLookupError):
                    self._bot_pid = self._find_bot_pid()
                    bot_alive = self._bot_pid > 0

            bt = (
                f"[bold green]BOT:{self._bot_pid}[/]"
                if bot_alive
                else "[bold red]BOT:DOWN[/]"
            )

            es = self._edge_score
            es_tag = (
                f"[bold green]EDGE:{es}[/]" if es >= 70
                else f"[bold yellow]EDGE:{es}[/]" if es >= 40
                else f"[bold red]EDGE:{es}[/]"
            )

            pnl = self._scorecard_cache.get("total_pnl", 0)
            p_s = "green" if pnl >= 0 else "red"

            p1h = self._scorecard_cache.get("pnl_1h", 0)
            p1s = "green" if p1h >= 0 else "red"

            n_pos = len(self._positions_cache)

            self.query_one("#status-header", Static).update(
                f" [bold]TURBO[/] | {now} | "
                f"{bt} | {es_tag} | "
                f"[{p_s}]${pnl:+.2f}[/] | "
                f"[{p1s}]1h:${p1h:+.0f}[/] | "
                f"Pos:{n_pos}"
            )
        except Exception:
            pass
