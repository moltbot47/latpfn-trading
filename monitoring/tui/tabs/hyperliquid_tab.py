"""Hyperliquid tab — crypto perpetuals trading."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, RichLog, Static

from monitoring.tui.screens.position_modal import PositionDetailScreen

SPARK = "▁▂▃▄▅▆▇█"


class HyperliquidTab(Static):
    """Hyperliquid perpetuals trading view."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._positions_data = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="platform-tab"):
            with Vertical(classes="platform-left"):
                yield DataTable(id="hl-positions", classes="positions-table")
                yield Static(" [dim]Loading...[/]", id="hl-account", classes="scorecard-panel")
                with Horizontal(classes="bottom-row"):
                    yield Static(" [dim]...[/]", id="hl-funding", classes="regime-panel")
                    yield Static(" [dim]...[/]", id="hl-pnl-chart", classes="chart-panel")
            with Vertical(classes="platform-right"):
                yield RichLog(
                    id="hl-feed", highlight=True, markup=True,
                    max_lines=200, classes="trade-feed",
                )

    def on_mount(self):
        table = self.query_one("#hl-positions", DataTable)
        table.add_columns("Coin", "Dir", "Size", "Entry", "Mark", "uPnL", "ROE")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#hl-positions").border_title = "OPEN POSITIONS"
        self.query_one("#hl-account").border_title = "ACCOUNT"
        self.query_one("#hl-funding").border_title = "FUNDING RATES"
        self.query_one("#hl-pnl-chart").border_title = "EQUITY"
        self.query_one("#hl-feed").border_title = "ACTIVITY FEED"

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "hl-positions" and self._positions_data:
            idx = event.cursor_row
            if 0 <= idx < len(self._positions_data):
                self.app.push_screen(
                    PositionDetailScreen(self._positions_data[idx], "HL")
                )

    def update_positions(self, hl_data: dict):
        """Update positions table from poll_hl_data() result."""
        if not hl_data:
            return
        positions = hl_data.get("positions", {})
        self._positions_data = []
        table = self.query_one("#hl-positions", DataTable)
        table.clear()

        for coin, p in positions.items():
            sz = p.get("size", 0)
            direction = "long" if sz > 0 else "short"
            dir_str = f"[green]L[/]" if sz > 0 else f"[red]S[/]"
            entry = p.get("entry", 0)
            pnl = p.get("pnl", 0)
            roe = p.get("roe", 0)
            pnl_color = "green" if pnl >= 0 else "red"
            roe_color = "green" if roe >= 0 else "red"

            self._positions_data.append({
                "coin": coin,
                "direction": direction,
                "size": abs(sz),
                "entry_price": entry,
                "unrealized_pnl": pnl,
                "roe": roe,
            })

            table.add_row(
                coin,
                dir_str,
                f"{abs(sz):.4f}",
                f"${entry:,.2f}",
                "",  # mark price not available from user_state
                f"[{pnl_color}]${pnl:+,.2f}[/]",
                f"[{roe_color}]{roe:+.1%}[/]",
            )

    def update_account(self, hl_data: dict):
        """Update account summary panel."""
        if not hl_data:
            return

        equity = hl_data.get("equity", 0)
        leverage = hl_data.get("leverage", 0)
        pos_count = hl_data.get("position_count", 0)
        unrealized = hl_data.get("unrealized_pnl", 0)

        lev_color = "green" if leverage < 3 else "yellow" if leverage < 5 else "red"
        u_color = "green" if unrealized >= 0 else "red"

        lines = [
            f" Equity: [bold]${equity:,.2f}[/]",
            f" Leverage: [{lev_color}]{leverage:.1f}x[/]",
            f" Positions: {pos_count}",
            f" Unrealized: [{u_color}]${unrealized:+,.2f}[/]",
        ]

        # Recent PM actions
        actions = hl_data.get("recent_actions", [])
        if actions:
            latest = actions[-1]
            a_color = "red" if "loss" in latest.get("action", "") else "yellow"
            lines.append("")
            lines.append(
                f" PM: [{a_color}]{latest.get('action', '?')}[/]"
                f" {latest.get('coin', '?')}"
            )

        self.query_one("#hl-account", Static).update("\n".join(lines))

    def update_funding(self, hl_data: dict):
        """Update funding rates panel."""
        if not hl_data:
            return
        funding = hl_data.get("funding_rates", {})
        if not funding:
            return

        lines = []
        for coin in ("btc", "eth", "sol", "xrp"):
            f_data = funding.get(coin, {})
            if not f_data:
                continue
            annual = f_data.get("annual", 0) * 100
            rate_8h = f_data.get("rate_8h", 0) * 100
            direction = f_data.get("direction", "")
            f_color = "green" if annual < 0 else "red" if annual > 20 else "yellow"
            lines.append(
                f" {coin.upper():4s} "
                f"8h: {rate_8h:+.4f}%  "
                f"[{f_color}]{annual:+.0f}%/yr[/]"
            )

        if not lines:
            lines.append(" [dim]No funding data[/]")
        self.query_one("#hl-funding", Static).update("\n".join(lines))

    def update_equity_chart(self, equity: float):
        """Simple equity display (no historical series available)."""
        e_color = "green" if equity > 0 else "red"
        lines = [
            f" [{e_color}]${equity:,.2f}[/]",
            "",
            " [dim]Live equity from HL API[/]",
        ]
        self.query_one("#hl-pnl-chart", Static).update("\n".join(lines))

    def update_feed(self, hl_data: dict):
        """Update activity feed with gate blocks and PM actions."""
        if not hl_data:
            return
        feed = self.query_one("#hl-feed", RichLog)
        feed.clear()

        # Gate blocks
        blocks = hl_data.get("gate_blocks", [])
        for b in blocks[-20:]:
            if isinstance(b, (list, tuple)) and len(b) >= 2:
                feed.write(f" [red]GATE[/] {b[0]} — {b[1][:50]}")

        # PM actions
        actions = hl_data.get("recent_actions", [])
        for a in actions[-20:]:
            a_color = "red" if "loss" in a.get("action", "") else "yellow"
            feed.write(
                f" [{a_color}]{a.get('action', '?')}[/]"
                f" {a.get('coin', '?')} — {a.get('reason', '')[:40]}"
            )

        # Cross-platform WR
        turbo_wr = hl_data.get("turbo_asset_wr", {})
        if turbo_wr:
            parts = []
            for asset, wr in turbo_wr.items():
                w_color = "green" if wr >= 0.35 else "yellow" if wr >= 0.25 else "red"
                parts.append(f"[{w_color}]{asset.upper()}:{wr:.0%}[/]")
            feed.write(f" Turbo WR: {' '.join(parts)}")
