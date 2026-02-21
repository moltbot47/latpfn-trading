"""Session performance scorecard."""

from textual.widgets import Static


class SessionScorecard(Static):
    BORDER_TITLE = "SCORECARD (24h)"

    def __init__(self, **kwargs):
        super().__init__(" [dim]Loading...[/]", **kwargs)

    def update_scorecard(self, sc: dict):
        wins = sc.get("wins", 0)
        losses = sc.get("losses", 0)
        total_pnl = sc.get("total_pnl", 0)
        win_rate = sc.get("win_rate", 0)
        streak = sc.get("streak", 0)
        streak_type = sc.get("streak_type", "")
        trades = sc.get("trades", 0)

        pnl_style = "green" if total_pnl >= 0 else "red"
        streak_style = "green" if streak_type == "win" else "red" if streak_type == "loss" else "dim"
        wr_style = "green" if win_rate >= 34 else "red"

        lines = [
            f"  Record:   [green]{wins}W[/] / [red]{losses}L[/]",
            f"  Win Rate: [{wr_style}]{win_rate:.1f}%[/]",
            f"  PnL:      [{pnl_style}]${total_pnl:+.2f}[/]",
        ]

        if trades > 0:
            ev = total_pnl / trades
            ev_style = "green" if ev >= 0 else "red"
            lines.append(f"  EV/Trade: [{ev_style}]${ev:+.3f}[/]")

        st_char = streak_type[0].upper() if streak_type else ""
        lines.append(f"  Streak:   [{streak_style}]{streak}{st_char}[/]")
        lines.append(f"  Trades:   {trades}")

        self.update("\n".join(lines))
