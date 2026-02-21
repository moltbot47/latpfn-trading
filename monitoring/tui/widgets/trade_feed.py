"""Scrolling trade execution log."""

from textual.widgets import RichLog


class TradeFeed(RichLog):
    BORDER_TITLE = "TRADE FEED"

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, max_lines=200, **kwargs)
        self._seen_ids: set = set()

    def add_trade(self, trade):
        if trade.id in self._seen_ids:
            return
        self._seen_ids.add(trade.id)

        if trade.result == "win":
            result_tag = "[bold green] WIN [/]"
            pnl_str = f"[green]+${trade.pnl:.2f}[/]"
        elif trade.result == "loss":
            result_tag = "[bold red] LOSS[/]"
            pnl_str = f"[red]-${abs(trade.pnl):.2f}[/]"
        else:
            result_tag = "[yellow] PEND[/]"
            pnl_str = "..."

        dir_style = "green" if trade.direction == "Up" else "red"
        ts_short = trade.timestamp[11:19] if len(trade.timestamp) > 19 else trade.timestamp[-8:]

        self.write(
            f" {ts_short} [{dir_style}]{trade.direction:4s}[/] "
            f"{trade.asset.upper():3s} {trade.timeframe:3s} "
            f"@{trade.entry_price:.2f} "
            f"{result_tag} {pnl_str}"
        )
