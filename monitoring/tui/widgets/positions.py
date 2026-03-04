"""Open positions with live mark-to-market PnL."""

import time
from textual.widgets import Static


class OpenPositions(Static):
    BORDER_TITLE = "OPEN POSITIONS"

    def __init__(self, **kwargs):
        super().__init__(" [dim]Loading positions...[/]", **kwargs)
        self._positions: list = []
        self._prices: dict = {}

    def update_positions(self, positions: list):
        self._positions = positions
        self._refresh_display()

    def update_price(self, token_id: str, mid: float):
        self._prices[token_id] = mid
        self._refresh_display()

    def _refresh_display(self):
        lines = [
            f" {'Asset':5s} {'Dir':4s} {'Entry':>6s} {'Mark':>6s} {'$Size':>6s} {'Unreal':>8s} {'Age':>4s}",
            f" {'─'*5} {'─'*4} {'─'*6} {'─'*6} {'─'*6} {'─'*8} {'─'*4}",
        ]

        total_unrealized = 0.0

        for pos in self._positions:
            token_id = pos.get("token_id", "")
            entry = pos.get("entry_price", 0) or 0
            shares = pos.get("shares", 0) or 0
            size = pos.get("size_usdc", 0) or 0
            direction = pos.get("direction", "?")
            question = pos.get("question", "")
            asset = question.split(" ")[0] if question else "?"

            mark = self._prices.get(token_id, entry)
            unrealized = (mark - entry) * shares
            total_unrealized += unrealized
            pnl_style = "green" if unrealized >= 0 else "red"
            dir_style = "green" if direction == "Up" else "red"

            age = ""
            opened = pos.get("opened_at", "")
            if opened:
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(opened.replace("Z", "+00:00"))
                    age_s = time.time() - dt.timestamp()
                    age = f"{int(age_s)}s" if age_s < 60 else f"{int(age_s // 60)}m"
                except Exception:
                    pass

            lines.append(
                f" {asset:5s} [{dir_style}]{direction:4s}[/] {entry:6.3f} {mark:6.3f} "
                f"${size:5.2f} "
                f"[{pnl_style}]${unrealized:+7.2f}[/] {age:>4s}"
            )

        if not self._positions:
            lines.append(" [dim]No open turbo positions[/]")
        else:
            pnl_style = "green" if total_unrealized >= 0 else "red"
            lines.append(
                f"\n Total: [{pnl_style}]${total_unrealized:+.2f}[/]  "
                f"({len(self._positions)} pos)"
            )

        self.update("\n".join(lines))
