"""Compact platform summary card for the overview tab."""

from textual.widgets import Static


class PlatformSummary(Static):
    """Shows equity, P&L, positions, and key metric for one platform."""

    def __init__(self, platform: str, **kwargs):
        super().__init__(f" [dim]{platform}: loading...[/]", **kwargs)
        self.platform = platform

    def update_data(self, data: dict):
        equity = data.get("equity", 0)
        pnl = data.get("pnl_24h", 0)
        positions = data.get("positions", 0)
        pnl_color = "green" if pnl >= 0 else "red"

        lines = [
            f" [bold]{self.platform}[/]",
            f" Equity: ${equity:,.2f}",
            f" P&L 24h: [{pnl_color}]{pnl:+,.2f}[/]",
            f" Positions: {positions}",
        ]

        # Platform-specific extras
        if "win_rate" in data and data.get("trades", 0) > 0:
            wr = data["win_rate"]
            trades = data["trades"]
            lines.append(f" {trades} trades | {wr:.1f}% WR")
        if "leverage" in data and data["leverage"] > 0:
            lines.append(f" Leverage: {data['leverage']:.1f}x")
        if "pf" in data and data["pf"] > 0:
            lines.append(f" PF: {data['pf']:.2f}")

        self.update("\n".join(lines))
