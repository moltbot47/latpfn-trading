"""Polymarket tab — turbo contrarian trading."""

import time
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, RichLog, Static

SPARK = "▁▂▃▄▅▆▇█"
SCORE_BAR = "■"


class PolymarketTab(Static):
    """Polymarket turbo contrarian trading view."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="platform-tab"):
            with Vertical(classes="platform-left"):
                yield DataTable(id="poly-positions", classes="positions-table")
                yield Static(" [dim]Loading...[/]", id="poly-scorecard", classes="scorecard-panel")
                with Horizontal(classes="bottom-row"):
                    yield Static(" [dim]...[/]", id="poly-assets", classes="regime-panel")
                    yield Static(" [dim]...[/]", id="poly-pnl-chart", classes="chart-panel")
            with Vertical(classes="platform-right"):
                yield RichLog(
                    id="poly-feed", highlight=True, markup=True,
                    max_lines=200, classes="trade-feed",
                )

    def on_mount(self):
        table = self.query_one("#poly-positions", DataTable)
        table.add_columns("Asset", "Dir", "Entry", "Size", "Age", "TTL")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#poly-positions").border_title = "TURBO POSITIONS"
        self.query_one("#poly-scorecard").border_title = "SCORECARD + EDGE"
        self.query_one("#poly-assets").border_title = "ASSET PERFORMANCE"
        self.query_one("#poly-pnl-chart").border_title = "PnL CHART"
        self.query_one("#poly-feed").border_title = "TRADE FEED"

    def update_positions(self, positions: list):
        """Update positions table from poll_positions()."""
        table = self.query_one("#poly-positions", DataTable)
        table.clear()
        now = time.time()

        for pos in positions:
            question = pos.get("question", "")
            asset = question.split(" ")[0] if question else "?"
            direction = pos.get("direction", "?")
            entry = pos.get("entry_price", 0) or 0
            size = pos.get("size_usdc", 0) or 0
            d_color = "green" if direction == "Up" else "red"

            # Age
            age_str = ""
            opened = pos.get("opened_at", "")
            if opened:
                try:
                    dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
                    age_s = now - dt.timestamp()
                    m, s = divmod(int(age_s), 60)
                    age_str = f"{m}:{s:02d}"
                except Exception:
                    pass

            # TTL countdown
            ttl_str = ""
            res_date = pos.get("resolution_date", "")
            if res_date:
                try:
                    dt = datetime.fromisoformat(res_date.replace("Z", "+00:00"))
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

            table.add_row(
                asset[:5],
                f"[{d_color}]{direction}[/]",
                f"{entry:.3f}",
                f"${size:.1f}",
                age_str,
                ttl_str,
            )

    def update_scorecard(self, scorecard: dict, edge_metrics=None):
        """Update combined scorecard + edge panel."""
        sc = scorecard
        if not sc:
            return

        wins = sc.get("wins", 0)
        losses = sc.get("losses", 0)
        total_pnl = sc.get("total_pnl", 0)
        win_rate = sc.get("win_rate", 0)
        streak = sc.get("streak", 0)
        streak_type = sc.get("streak_type", "")
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

        ps = "green" if total_pnl >= 0 else "red"
        ws = "green" if win_rate >= 34 else "red"
        sc_char = streak_type[0].upper() if streak_type else ""
        ss = "green" if streak_type == "win" else "red" if streak_type == "loss" else "dim"

        lines = []

        # Row 1: Record + PnL
        ev = total_pnl / (wins + losses) if (wins + losses) > 0 else 0
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
            f"  DD:[{dd_s}]${cur_dd:.0f}[/][dim]/${max_dd:.0f}[/]"
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

        # Edge metrics
        if edge_metrics:
            m = edge_metrics
            lines.append(" [dim]─────────────────────────────────[/]")

            score = m.edge_score
            sc_s = "green" if score >= 70 else "yellow" if score >= 40 else "red"
            filled = score // 10
            bar = f"[{sc_s}]{SCORE_BAR * filled}[/][dim]{'□' * (10 - filled)}[/]"
            lines.append(
                f" EDGE:[{sc_s}]{score}[/] {bar}"
                f"  [{sc_s}]Filter:{br:.0f}%[/]"
            )

            # Decay indicator
            decay = m.edge_decay
            if decay >= 0.02:
                d_tag = "[green]GAIN[/]"
            elif decay >= -0.03:
                d_tag = "[green]STABLE[/]"
            elif decay >= -0.06:
                d_tag = "[yellow]FADE[/]"
            else:
                d_tag = "[red]DECAY[/]"

            r_s = "green" if m.recent_wr >= 0.30 else "yellow" if m.recent_wr >= 0.25 else "red"
            lines.append(
                f" Recent:[{r_s}]{m.recent_wr:.0%}[/]"
                f"/{m.overall_wr:.0%}"
                f"  {d_tag}"
            )

        self.query_one("#poly-scorecard", Static).update("\n".join(lines))

    def update_assets(self, asset_dir_stats: list):
        """Update per-asset performance panel."""
        if not asset_dir_stats:
            return

        assets = {}
        for s in asset_dir_stats:
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
            f" {'':4s} {'W':>3s} {'L':>3s} {'WR':>5s} {'PnL':>7s}",
            f" {'─' * 4} {'─' * 3} {'─' * 3} {'─' * 5} {'─' * 7}",
        ]

        for a in sorted(assets.keys()):
            d = assets[a]
            total = d["w"] + d["l"]
            wr = d["w"] / total if total > 0 else 0
            wr_s = "green" if wr >= 0.34 else "yellow" if wr >= 0.28 else "red"
            p_s = "green" if d["pnl"] >= 0 else "red"
            lines.append(
                f" {a.upper():4s} {d['w']:3d} {d['l']:3d}"
                f" [{wr_s}]{wr:5.1%}[/]"
                f" [{p_s}]${d['pnl']:+6.0f}[/]"
            )

        self.query_one("#poly-assets", Static).update("\n".join(lines))

    def update_pnl_chart(self, series: list):
        """Update PnL sparkline chart."""
        if not series or len(series) < 2:
            return
        current = series[-1]
        lo = min(series)
        hi = max(series)
        rng = hi - lo if hi != lo else 1

        width = 30
        step = max(1, len(series) // width)
        sampled = series[::step][-width:]
        spark = ""
        for v in sampled:
            idx = int((v - lo) / rng * 7)
            idx = max(0, min(7, idx))
            color = "green" if v >= 0 else "red"
            spark += f"[{color}]{SPARK[idx]}[/]"

        pnl_color = "green" if current >= 0 else "red"
        lines = [
            f" [{pnl_color}]${current:+,.2f}[/]  [dim]lo ${lo:,.0f} / hi ${hi:,.0f}[/]",
            "",
            f" {spark}",
        ]
        self.query_one("#poly-pnl-chart", Static).update("\n".join(lines))

    def update_feed(self, trades: list):
        """Update trade feed from poll_db() trades."""
        feed = self.query_one("#poly-feed", RichLog)
        feed.clear()
        for trade in reversed(trades[:100]):
            if trade.result == "win":
                tag = "[green]W[/]"
                pnl = f"[green]+${trade.pnl:.2f}[/]"
            elif trade.result == "loss":
                tag = "[red]L[/]"
                pnl = f"[red]-${abs(trade.pnl):.2f}[/]"
            else:
                tag = "[yellow]?[/]"
                pnl = "..."

            d_color = "green" if trade.direction == "Up" else "red"
            ts = trade.timestamp[11:16] if len(trade.timestamp) > 16 else trade.timestamp[-5:]
            d_ch = "▲" if trade.direction == "Up" else "▼"

            feed.write(
                f" {ts} [{d_color}]{d_ch}[/]"
                f"{trade.asset.upper():3s}"
                f" {trade.entry_price:.2f}"
                f" {tag} {pnl}"
            )
