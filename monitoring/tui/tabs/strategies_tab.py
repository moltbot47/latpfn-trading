"""Strategies tab — per-strategy performance and decay monitoring."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from monitoring.tui.strategy_decay import StrategyStats


class StrategiesTab(Static):
    """Strategy management and decay monitoring view."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._strategies: list = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="strategies-body"):
            yield DataTable(id="strategies-table")
            with Vertical(id="strategies-detail"):
                yield Static(" [dim]Analyzing strategies...[/]", id="decay-panel")
                yield Static(" [dim]Select a strategy...[/]", id="strategy-detail")

    def on_mount(self):
        table = self.query_one("#strategies-table", DataTable)
        table.add_columns("Strategy", "Plat", "Trades", "WR%", "P&L", "PF", "Decay", "Status")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#strategies-table").border_title = "STRATEGIES"
        self.query_one("#decay-panel").border_title = "DECAY MONITOR"
        self.query_one("#strategy-detail").border_title = "DETAIL"

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "strategies-table" and self._strategies:
            idx = event.cursor_row
            if 0 <= idx < len(self._strategies):
                self._render_detail(self._strategies[idx])

    def update_strategies(self, strategies: list):
        """Update strategy table and decay panel."""
        self._strategies = strategies
        table = self.query_one("#strategies-table", DataTable)
        table.clear()

        for s in strategies:
            wr = s.win_rate * 100
            wr_color = "green" if wr >= 55 else "yellow" if wr >= 45 else "red"
            pnl_color = "green" if s.total_pnl >= 0 else "red"
            pf_color = "green" if s.profit_factor >= 1.5 else "yellow" if s.profit_factor >= 1.0 else "red"

            # Decay indicator
            decay_pct = s.edge_decay * 100
            if s.status == "DECAYING":
                decay_str = f"[red]{decay_pct:+.1f}pp[/]"
                status_str = f"[bold red]{s.status}[/]"
            elif s.status == "WARNING":
                decay_str = f"[yellow]{decay_pct:+.1f}pp[/]"
                status_str = f"[yellow]{s.status}[/]"
            elif s.status == "INACTIVE":
                decay_str = "[dim]n/a[/]"
                status_str = f"[dim]{s.status}[/]"
            else:
                decay_str = f"[green]{decay_pct:+.1f}pp[/]"
                status_str = f"[green]{s.status}[/]"

            table.add_row(
                s.name,
                s.platform,
                str(s.total_trades),
                f"[{wr_color}]{wr:.1f}%[/]",
                f"[{pnl_color}]${s.total_pnl:+,.0f}[/]",
                f"[{pf_color}]{s.profit_factor:.2f}[/]",
                decay_str,
                status_str,
            )

        self._render_decay_panel(strategies)

    def _render_decay_panel(self, strategies: list):
        """Render decay monitor summary."""
        lines = [" [bold]EDGE DECAY MONITOR[/]", ""]

        decaying = [s for s in strategies if s.status == "DECAYING"]
        warning = [s for s in strategies if s.status == "WARNING"]
        stable = [s for s in strategies if s.status == "STABLE"]

        if decaying:
            lines.append(f" [bold red]DECAYING ({len(decaying)}):[/]")
            for s in decaying:
                lines.append(
                    f"   [red]{s.name}[/]: "
                    f"recent {s.recent_wr:.0%} vs overall {s.overall_wr:.0%} "
                    f"({s.edge_decay * 100:+.1f}pp)"
                )
            lines.append("")

        if warning:
            lines.append(f" [yellow]WARNING ({len(warning)}):[/]")
            for s in warning:
                lines.append(
                    f"   [yellow]{s.name}[/]: "
                    f"recent {s.recent_wr:.0%} vs overall {s.overall_wr:.0%} "
                    f"({s.edge_decay * 100:+.1f}pp)"
                )
            lines.append("")

        if stable:
            lines.append(f" [green]STABLE ({len(stable)}):[/]")
            for s in stable:
                delta = s.edge_decay * 100
                lines.append(
                    f"   [green]{s.name}[/]: "
                    f"{s.recent_wr:.0%}/{s.overall_wr:.0%} "
                    f"({delta:+.1f}pp)"
                )

        inactive = [s for s in strategies if s.status == "INACTIVE"]
        if inactive:
            lines.append("")
            lines.append(f" [dim]INACTIVE ({len(inactive)}): "
                         f"{', '.join(s.name for s in inactive)}[/]")

        self.query_one("#decay-panel", Static).update("\n".join(lines))

    def _render_detail(self, s: StrategyStats):
        """Render detailed view for a selected strategy."""
        lines = [
            f" [bold]{s.name}[/]  ({s.platform})",
            "",
            f" Trades: {s.total_trades}  ({s.wins}W / {s.losses}L)",
            f" Win Rate: {s.win_rate:.1%}",
            f" P&L: [{'green' if s.total_pnl >= 0 else 'red'}]${s.total_pnl:+,.2f}[/]",
            f" Profit Factor: {s.profit_factor:.2f}",
            f" Avg Win: ${s.avg_win:+.2f}  Avg Loss: ${s.avg_loss:.2f}",
            f" Best: ${s.best_trade:+.2f}  Worst: ${s.worst_trade:.2f}",
            "",
            " [bold]Decay Analysis[/]",
            f" Recent ({s.recent_n}t): {s.recent_wr:.1%}",
            f" Overall ({s.overall_n}t): {s.overall_wr:.1%}",
            f" Delta: {s.edge_decay * 100:+.1f}pp",
        ]

        if s.last_trade:
            lines.append(f" Last Trade: {s.last_trade}")

        # Tier/asset breakdown
        if s.tier_stats:
            lines.append("")
            label = "Assets" if s.platform == "POLY" else "Tiers"
            lines.append(f" [bold]Per-{label} Breakdown[/]")
            lines.append(f" {'Name':12s} {'Tr':>4s} {'WR':>6s} {'PnL':>8s}")
            lines.append(f" {'─' * 12} {'─' * 4} {'─' * 6} {'─' * 8}")
            for name, t in s.tier_stats.items():
                t_wr = t.get("wr", 0)
                t_pnl = t.get("pnl", 0)
                wr_c = "green" if t_wr >= 55 else "yellow" if t_wr >= 45 else "red"
                pnl_c = "green" if t_pnl >= 0 else "red"
                lines.append(
                    f" {name[:12]:12s} {t.get('trades', 0):4d}"
                    f" [{wr_c}]{t_wr:5.1f}%[/]"
                    f" [{pnl_c}]${t_pnl:+7.0f}[/]"
                )

        self.query_one("#strategy-detail", Static).update("\n".join(lines))
