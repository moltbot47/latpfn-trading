"""Alerts tab — live alert feed with severity filtering and acknowledgement."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Static

from monitoring.tui.alerts import Alert, AlertEngine, Severity


class AlertsTab(Static):
    """Live alert feed with severity colors and ack/dismiss."""

    class AckAll(Message):
        """Message to request acknowledging all alerts."""
        pass

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._alerts: list = []

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="alerts-header"):
                yield Static(" [dim]No alerts[/]", id="alerts-summary")
                yield Button("Ack All", variant="warning", id="ack-all-btn")
            yield DataTable(id="alerts-table")
            yield Static(" [dim]Select an alert for details...[/]", id="alert-detail")

    def on_mount(self):
        table = self.query_one("#alerts-table", DataTable)
        table.add_columns("Sev", "Time", "Source", "Title", "Age")
        table.cursor_type = "row"
        table.zebra_stripes = True

        self.query_one("#alerts-table").border_title = "ACTIVE ALERTS"
        self.query_one("#alerts-summary").border_title = "SUMMARY"
        self.query_one("#alert-detail").border_title = "ALERT DETAIL"

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "ack-all-btn":
            self.post_message(self.AckAll())

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if event.data_table.id == "alerts-table" and self._alerts:
            idx = event.cursor_row
            if 0 <= idx < len(self._alerts):
                self._render_detail(self._alerts[idx])

    def update_alerts(self, engine: AlertEngine):
        """Update the alert table and summary from engine state."""
        alerts = engine.all_active
        self._alerts = alerts

        # Summary
        total = len(engine.active_alerts)
        critical = engine.critical_count
        warn = sum(1 for a in engine.active_alerts if a.severity == Severity.WARN)
        info = sum(1 for a in engine.active_alerts if a.severity == Severity.INFO)

        if total == 0:
            summary = " [green]All clear — no active alerts[/]"
        else:
            parts = []
            if critical:
                parts.append(f"[bold red]{critical} CRITICAL[/]")
            if warn:
                parts.append(f"[yellow]{warn} WARN[/]")
            if info:
                parts.append(f"[dim]{info} INFO[/]")
            summary = f" {' | '.join(parts)}  ({total} total)"

        self.query_one("#alerts-summary", Static).update(summary)

        # Table
        table = self.query_one("#alerts-table", DataTable)
        table.clear()

        for a in alerts:
            if a.severity == Severity.CRITICAL:
                sev_str = "[bold red]CRIT[/]"
            elif a.severity == Severity.WARN:
                sev_str = "[yellow]WARN[/]"
            else:
                sev_str = "[dim]INFO[/]"

            title = a.title
            if a.acknowledged:
                title = f"[dim]{a.title}[/]"

            table.add_row(
                sev_str,
                a.time_str,
                a.source,
                title,
                a.age_str,
            )

    def _render_detail(self, alert: Alert):
        """Render detail panel for selected alert."""
        if alert.severity == Severity.CRITICAL:
            sev_color = "red"
        elif alert.severity == Severity.WARN:
            sev_color = "yellow"
        else:
            sev_color = "dim"

        lines = [
            f" [{sev_color}][bold]{alert.severity.value}[/]: {alert.title}[/]",
            "",
            f" Source: {alert.source}",
            f" Time: {alert.time_str} ({alert.age_str})",
            f" Ack'd: {'Yes' if alert.acknowledged else 'No'}",
            "",
            f" {alert.message}",
        ]

        self.query_one("#alert-detail", Static).update("\n".join(lines))
