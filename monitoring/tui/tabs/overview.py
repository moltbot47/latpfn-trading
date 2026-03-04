"""Overview tab — unified cross-platform portfolio view."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from monitoring.tui.widgets.platform_summary import PlatformSummary

SPARK = "▁▂▃▄▅▆▇█"


class OverviewTab(Static):
    """Unified view of all 3 trading platforms."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="overview-cards"):
            yield PlatformSummary("CME", id="card-cme", classes="platform-card")
            yield PlatformSummary("Hyperliquid", id="card-hl", classes="platform-card")
            yield PlatformSummary("Polymarket", id="card-poly", classes="platform-card")
        with Horizontal(id="overview-body"):
            yield DataTable(id="unified-trades")
            yield Static(" [dim]Loading risk data...[/]", id="risk-dashboard")

    def on_mount(self):
        table = self.query_one("#unified-trades", DataTable)
        table.add_columns("Time", "Platform", "Asset", "Dir", "Entry", "Result", "P&L")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#unified-trades").border_title = "RECENT TRADES (all platforms)"
        self.query_one("#risk-dashboard").border_title = "RISK DASHBOARD"

    def update_data(self, portfolio: dict):
        cme = portfolio.get("cme", {})
        hl = portfolio.get("hl", {})
        poly = portfolio.get("poly", {})

        self.query_one("#card-cme", PlatformSummary).update_data(cme)
        self.query_one("#card-hl", PlatformSummary).update_data(hl)
        self.query_one("#card-poly", PlatformSummary).update_data(poly)

    def update_trades(self, cme_trades: list, poly_trades: list):
        """Merge and display trades from all platforms."""
        table = self.query_one("#unified-trades", DataTable)
        table.clear()

        unified = []
        for t in cme_trades[:50]:
            unified.append({
                "time": t.get("timestamp", "")[-8:],
                "platform": "CME",
                "asset": t.get("instrument", "?"),
                "dir": t.get("direction", "?")[:1].upper(),
                "entry": f"${t.get('entry', 0):,.2f}",
                "result": t.get("result", "?"),
                "pnl": t.get("pnl", 0),
            })

        for t in poly_trades[:50]:
            pnl = t.pnl if hasattr(t, "pnl") else (t.get("pnl") if isinstance(t, dict) else 0)
            asset = t.asset if hasattr(t, "asset") else (t.get("asset") if isinstance(t, dict) else "?")
            direction = t.direction if hasattr(t, "direction") else (t.get("direction") if isinstance(t, dict) else "?")
            result = t.result if hasattr(t, "result") else (t.get("result") if isinstance(t, dict) else "?")
            ts = t.timestamp if hasattr(t, "timestamp") else (t.get("timestamp") if isinstance(t, dict) else "")

            unified.append({
                "time": str(ts)[-8:] if ts else "",
                "platform": "POLY",
                "asset": str(asset)[:6],
                "dir": str(direction)[:1].upper(),
                "entry": "",
                "result": str(result) if result else "?",
                "pnl": float(pnl) if pnl else 0,
            })

        # Sort by time descending
        unified.sort(key=lambda x: x["time"], reverse=True)

        for t in unified[:100]:
            pnl = t["pnl"]
            pnl_str = f"${pnl:+,.2f}" if pnl else "$0.00"
            result_str = t["result"]
            table.add_row(
                t["time"], t["platform"], t["asset"],
                t["dir"], t["entry"], result_str, pnl_str,
            )

    def update_risk(self, cme_sc: dict, portfolio: dict):
        """Update risk dashboard panel."""
        lines = [" [bold]RISK OVERVIEW[/]", ""]

        # CME drawdown
        cme_dd = cme_sc.get("current_dd", 0)
        cme_max_dd = cme_sc.get("max_drawdown", 0)
        cme_peak = cme_sc.get("peak_pnl", 0)
        lines.append(f" CME Drawdown: ${cme_dd:,.0f} / ${cme_max_dd:,.0f} max")
        lines.append(f" CME Peak P&L: ${cme_peak:,.0f}")
        lines.append("")

        # HL leverage
        hl = portfolio.get("hl", {})
        lev = hl.get("leverage", 0)
        lev_color = "green" if lev < 3 else "yellow" if lev < 5 else "red"
        lines.append(f" HL Leverage: [{lev_color}]{lev:.1f}x[/]")
        lines.append("")

        # Aggregate
        total_positions = sum(
            portfolio.get(p, {}).get("positions", 0)
            for p in ("cme", "hl", "poly")
        )
        lines.append(f" Total Positions: {total_positions}")
        lines.append(f" Active Platforms: {sum(1 for p in ('cme', 'hl', 'poly') if portfolio.get(p, {}).get('positions', 0) > 0)}/3")

        self.query_one("#risk-dashboard", Static).update("\n".join(lines))
