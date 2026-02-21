"""L2 order book depth display."""

from textual.widgets import Static


class LiveOrderBook(Static):
    BORDER_TITLE = "ORDER BOOK"

    def __init__(self, **kwargs):
        super().__init__(
            " [dim]Waiting for WebSocket data...[/]\n\n"
            " Book populates when turbo\n"
            " positions are open.",
            **kwargs,
        )
        self._label = ""

    def update_depth(self, bids: list, asks: list, label: str = ""):
        if label:
            self._label = label

        lines = [f" [bold]{self._label}[/]", ""]
        lines.append(f" {'BidSz':>6s}  {'Bid':>7s}  {'Ask':>7s}  {'AskSz':>6s}")
        lines.append(f" {'─'*6}  {'─'*7}  {'─'*7}  {'─'*6}")

        max_levels = max(len(bids), len(asks), 1)
        for i in range(min(max_levels, 10)):
            bid_price = bid_size = ask_price = ask_size = ""

            if i < len(bids):
                bp = bids[i].get("price", "")
                bs = bids[i].get("size", "")
                if bp:
                    bid_price = f"[green]{float(bp):.4f}[/]"
                if bs:
                    bid_size = f"{float(bs):>6.0f}"

            if i < len(asks):
                ap = asks[i].get("price", "")
                az = asks[i].get("size", "")
                if ap:
                    ask_price = f"[red]{float(ap):.4f}[/]"
                if az:
                    ask_size = f"{float(az):>6.0f}"

            lines.append(f" {bid_size:>6s}  {bid_price:>16s}  {ask_price:>14s}  {ask_size:>6s}")

        self.update("\n".join(lines))
