"""CME Futures tab — Apex prop firm trading."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, RichLog, Static

from monitoring.tui.screens.position_modal import PositionDetailScreen

SPARK = "▁▂▃▄▅▆▇█"


class CMETab(Static):
    """Apex/CME futures trading view."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._positions_data = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="platform-tab"):
            with Vertical(classes="platform-left"):
                yield DataTable(id="cme-positions", classes="positions-table")
                yield Static(" [dim]Loading...[/]", id="cme-scorecard", classes="scorecard-panel")
                with Horizontal(classes="bottom-row"):
                    yield Static(" [dim]...[/]", id="cme-instruments", classes="regime-panel")
                    yield Static(" [dim]...[/]", id="cme-pnl-chart", classes="chart-panel")
            with Vertical(classes="platform-right"):
                yield RichLog(
                    id="cme-feed", highlight=True, markup=True,
                    max_lines=200, classes="trade-feed",
                )

    def on_mount(self):
        table = self.query_one("#cme-positions", DataTable)
        table.add_columns("Symbol", "Dir", "Size", "Entry", "SL", "TP", "Age")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#cme-positions").border_title = "OPEN POSITIONS"
        self.query_one("#cme-scorecard").border_title = "SCORECARD (24h)"
        self.query_one("#cme-instruments").border_title = "PER-INSTRUMENT"
        self.query_one("#cme-pnl-chart").border_title = "PnL CHART"
        self.query_one("#cme-feed").border_title = "TRADE FEED"

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "cme-positions" and self._positions_data:
            idx = event.cursor_row
            if 0 <= idx < len(self._positions_data):
                self.app.push_screen(
                    PositionDetailScreen(self._positions_data[idx], "CME")
                )

    def update_positions(self, positions: list):
        self._positions_data = positions
        table = self.query_one("#cme-positions", DataTable)
        table.clear()
        for p in positions:
            direction = p.get("direction", "?")
            dir_str = f"[green]L[/]" if direction == "long" else f"[red]S[/]"
            entry_time = p.get("entry_time", "")
            age = entry_time[-8:] if entry_time else ""
            table.add_row(
                p.get("instrument", "?"),
                dir_str,
                str(p.get("size", p.get("position_size", 1))),
                f"${p.get('entry_price', 0):,.2f}",
                f"${p.get('stop_loss', 0):,.2f}",
                f"${p.get('take_profit', 0):,.2f}",
                age,
            )

    def update_scorecard(self, sc: dict):
        if not sc:
            return
        wr = sc.get("win_rate", 0)
        wr_color = "green" if wr >= 55 else "yellow" if wr >= 50 else "red"

        lines = [
            f" {sc.get('wins', 0)}W/{sc.get('losses', 0)}L "
            f"[{wr_color}]{wr:.1f}%[/] | "
            f"PF: {sc.get('payoff_ratio', 0):.2f}",
            "",
            f" P&L: [{'green' if sc.get('total_pnl', 0) >= 0 else 'red'}]"
            f"${sc.get('total_pnl', 0):+,.2f}[/]  "
            f"DD: ${sc.get('current_dd', 0):,.0f}/${sc.get('max_drawdown', 0):,.0f}",
            "",
            f" Avg Win: ${sc.get('avg_win', 0):+.2f}  "
            f"Avg Loss: ${sc.get('avg_loss', 0):.2f}",
            f" Best: ${sc.get('best_trade', 0):+.2f}  "
            f"Worst: ${sc.get('worst_trade', 0):.2f}",
        ]
        self.query_one("#cme-scorecard", Static).update("\n".join(lines))

    def update_instruments(self, instruments: list):
        if not instruments:
            return
        lines = []
        for inst in instruments:
            pnl = inst.get("pnl", 0)
            color = "green" if pnl >= 0 else "red"
            lines.append(
                f" {inst['instrument']:4s} {inst.get('trades', 0):3d}t "
                f"{inst.get('wr', 0):4.1f}% "
                f"[{color}]${pnl:+,.0f}[/]"
            )
        self.query_one("#cme-instruments", Static).update("\n".join(lines))

    def update_pnl_chart(self, series: list):
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
        self.query_one("#cme-pnl-chart", Static).update("\n".join(lines))

    def update_feed(self, trades: list):
        feed = self.query_one("#cme-feed", RichLog)
        feed.clear()
        for t in reversed(trades[:100]):
            ts = t.get("timestamp", "")[-8:]
            d = t.get("direction", "?")
            d_icon = "[green]▲[/]" if d == "long" else "[red]▼[/]"
            inst = t.get("instrument", "?")
            pnl = t.get("pnl", 0)
            result = t.get("result", "?")
            r_str = "[green]W[/]" if result == "win" else "[red]L[/]"
            pnl_color = "green" if pnl >= 0 else "red"
            tier = t.get("tier", "")[:3]
            feed.write(
                f" {ts} {d_icon}{inst:4s} {tier:3s} "
                f"${t.get('entry', 0):,.0f} {r_str} "
                f"[{pnl_color}]${pnl:+.2f}[/]"
            )
