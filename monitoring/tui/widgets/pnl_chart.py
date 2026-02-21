"""ASCII sparkline cumulative PnL chart."""

from textual.widgets import Static

SPARK_CHARS = "▁▂▃▄▅▆▇█"


class PnLChart(Static):
    BORDER_TITLE = "PnL CHART"

    def __init__(self, **kwargs):
        super().__init__(" [dim]Waiting for data...[/]", **kwargs)

    def update_series(self, series: list):
        if not series or len(series) < 2:
            self.update(" [dim]Waiting for trade data...[/]")
            return

        try:
            width = max(self.size.width - 6, 20) if self.size.width > 6 else 40
        except Exception:
            width = 40

        if len(series) > width:
            step = len(series) / width
            series = [series[int(i * step)] for i in range(width)]

        min_val = min(series)
        max_val = max(series)
        val_range = max_val - min_val or 1

        line = ""
        for v in series:
            idx = int((v - min_val) / val_range * (len(SPARK_CHARS) - 1))
            char = SPARK_CHARS[idx]
            line += f"[green]{char}[/]" if v >= 0 else f"[red]{char}[/]"

        current = series[-1]
        pnl_style = "green" if current >= 0 else "red"

        self.update(
            f" [{pnl_style}]${current:+.2f}[/]  "
            f"[dim]lo ${min_val:.0f} / hi ${max_val:.0f}[/]\n\n"
            f"  {line}"
        )
