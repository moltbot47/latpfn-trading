"""Risk tab — Apex drawdown gauge, daily limits, consistency tracking."""

import json
import time
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DRAWDOWN_STATE_PATH = PROJECT_ROOT / "data" / "drawdown_state.json"

# Visual gauge characters
GAUGE_FILL = "\u2588"  # █
GAUGE_EMPTY = "\u2591"  # ░
GAUGE_WIDTH = 30


def _gauge(value: float, maximum: float, width: int = GAUGE_WIDTH, warn_pct: float = 0.4, crit_pct: float = 0.2) -> str:
    """Render a colored gauge bar. value/maximum where lower value = more danger."""
    if maximum <= 0:
        return f"[dim]{GAUGE_EMPTY * width}[/]"

    pct = max(0, min(1, value / maximum))
    filled = int(pct * width)
    empty = width - filled

    if pct <= crit_pct:
        color = "bold red"
    elif pct <= warn_pct:
        color = "yellow"
    else:
        color = "green"

    return f"[{color}]{GAUGE_FILL * filled}[/][dim]{GAUGE_EMPTY * empty}[/]"


def _progress_bar(value: float, target: float, width: int = GAUGE_WIDTH) -> str:
    """Render a progress bar toward a target. value/target where higher = better."""
    if target <= 0:
        return f"[dim]{GAUGE_EMPTY * width}[/]"

    pct = max(0, min(1, value / target))
    filled = int(pct * width)
    empty = width - filled

    if pct >= 0.9:
        color = "bold green"
    elif pct >= 0.5:
        color = "cyan"
    else:
        color = "dim"

    return f"[{color}]{GAUGE_FILL * filled}[/][dim]{GAUGE_EMPTY * empty}[/]"


class RiskTab(Static):
    """Dedicated risk management dashboard."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._drawdown_state: dict = {}
        self._cme_equity: float = 50000
        self._cme_scorecard: dict = {}
        self._hl_data: dict = {}
        self._strategies: list = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="risk-body"):
            with Vertical(id="risk-left"):
                yield Static(" [dim]Loading drawdown data...[/]", id="drawdown-gauge")
                yield Static(" [dim]Loading daily P&L...[/]", id="daily-limits")
            with Vertical(id="risk-right"):
                yield Static(" [dim]Loading consistency data...[/]", id="consistency-panel")
                yield Static(" [dim]Loading position risk...[/]", id="position-risk")

    def on_mount(self):
        self.query_one("#drawdown-gauge").border_title = "APEX TRAILING DRAWDOWN"
        self.query_one("#daily-limits").border_title = "DAILY P&L LIMITS"
        self.query_one("#consistency-panel").border_title = "CONSISTENCY RULE"
        self.query_one("#position-risk").border_title = "POSITION RISK"

    def update_risk(
        self,
        cme_equity: float,
        cme_scorecard: dict,
        hl_data: dict | None,
        strategies: list,
    ):
        """Full risk update from app polling."""
        self._cme_equity = cme_equity
        self._cme_scorecard = cme_scorecard
        self._hl_data = hl_data or {}
        self._strategies = strategies

        # Read drawdown state
        try:
            if DRAWDOWN_STATE_PATH.exists():
                with open(DRAWDOWN_STATE_PATH) as f:
                    self._drawdown_state = json.load(f)
        except Exception:
            pass

        self._render_drawdown()
        self._render_daily_limits()
        self._render_consistency()
        self._render_position_risk()

    def _render_drawdown(self):
        """Render Apex trailing drawdown gauge."""
        ds = self._drawdown_state
        if not ds:
            self.query_one("#drawdown-gauge", Static).update(
                " [dim]No drawdown state — bot may not be running[/]"
            )
            return

        highest = ds.get("highest_balance", 50000)
        floor = ds.get("drawdown_floor", 47500)
        locked = ds.get("floor_locked", False)
        max_dd = 2500  # Apex trailing drawdown

        balance = self._cme_equity
        cushion = balance - floor
        cushion_pct = (cushion / max_dd) * 100 if max_dd > 0 else 100
        profit_target = 53000
        to_target = profit_target - balance

        # Color by danger level
        if cushion_pct <= 20:
            cush_color = "bold red"
        elif cushion_pct <= 40:
            cush_color = "yellow"
        else:
            cush_color = "green"

        gauge = _gauge(cushion, max_dd)

        lines = [
            " [bold]APEX TRAILING DRAWDOWN[/]",
            "",
            f" Balance:     ${balance:>10,.2f}",
            f" High Water:  ${highest:>10,.2f}",
            f" Floor:       ${floor:>10,.2f}  {'[cyan]LOCKED[/]' if locked else ''}",
            "",
            f" Cushion: [{cush_color}]${cushion:>8,.2f}  ({cushion_pct:.0f}%)[/]",
            f" {gauge}",
            "",
            f" To Target ($53k): ${to_target:>8,.2f}",
            f" {_progress_bar(balance - 50000, 3000)}",
        ]

        if locked:
            lines.append("")
            lines.append(" [bold cyan]Floor locked at profit target — drawdown stops trailing[/]")

        if cushion_pct <= 20:
            lines.append("")
            lines.append(" [bold red]DANGER: Close to drawdown floor! Consider reducing size.[/]")

        self.query_one("#drawdown-gauge", Static).update("\n".join(lines))

    def _render_daily_limits(self):
        """Render daily P&L vs limits."""
        sc = self._cme_scorecard
        daily_pnl = sc.get("total_pnl", 0)
        daily_limit = 1000  # $1000 daily loss limit

        # P&L color
        pnl_color = "green" if daily_pnl >= 0 else "red"

        # Loss gauge (how much of limit used)
        loss_used = abs(min(0, daily_pnl))
        loss_pct = (loss_used / daily_limit) * 100 if daily_limit > 0 else 0
        loss_gauge = _gauge(daily_limit - loss_used, daily_limit)

        lines = [
            " [bold]DAILY P&L TRACKING[/]",
            "",
            f" Today's P&L: [{pnl_color}]${daily_pnl:>+10,.2f}[/]",
            f" Daily Limit: ${daily_limit:>10,.2f}",
            "",
        ]

        if daily_pnl < 0:
            lines.append(f" Loss Used: ${loss_used:,.0f} / ${daily_limit:,.0f} ({loss_pct:.0f}%)")
            lines.append(f" {loss_gauge}")
            lines.append(f" Remaining: ${daily_limit - loss_used:,.0f}")
        else:
            lines.append(f" [green]Profitable — full limit available[/]")
            lines.append(f" {_gauge(daily_limit, daily_limit)}")

        # Trade stats
        trades = sc.get("trades", 0)
        wins = sc.get("wins", 0)
        losses = sc.get("losses", 0)
        wr = sc.get("win_rate", 0)
        lines.append("")
        lines.append(f" Trades: {trades}  ({wins}W/{losses}L)  WR: {wr:.1f}%")

        # P&L windows
        pnl_1h = sc.get("pnl_1h", 0)
        pnl_6h = sc.get("pnl_6h", 0)
        if pnl_1h or pnl_6h:
            c1 = "green" if pnl_1h >= 0 else "red"
            c6 = "green" if pnl_6h >= 0 else "red"
            lines.append(f" 1h: [{c1}]${pnl_1h:+,.0f}[/]  6h: [{c6}]${pnl_6h:+,.0f}[/]")

        self.query_one("#daily-limits", Static).update("\n".join(lines))

    def _render_consistency(self):
        """Render Apex 30% consistency rule tracking."""
        sc = self._cme_scorecard
        total_pnl = sc.get("total_pnl", 0)

        lines = [
            " [bold]APEX 30% CONSISTENCY RULE[/]",
            "",
            " No single day's profit can exceed 30%",
            " of total profit at payout time.",
            "",
        ]

        if total_pnl <= 0:
            lines.append(" [dim]No profit yet — rule not active[/]")
        else:
            max_day_allowed = total_pnl * 0.30
            today_pnl = total_pnl  # Simplified — today's 24h window

            lines.append(f" Total Profit: ${total_pnl:+,.2f}")
            lines.append(f" Max Single Day: ${max_day_allowed:,.2f} (30%)")
            lines.append(f" Today's P&L:   ${today_pnl:+,.2f}")
            lines.append("")

            if today_pnl > 0:
                pct = today_pnl / total_pnl if total_pnl > 0 else 0
                if pct > 0.30:
                    lines.append(
                        f" [bold red]TODAY = {pct:.0%} of total — OVER 30% LIMIT[/]"
                    )
                    needed = today_pnl / 0.30 - total_pnl
                    lines.append(
                        f" Need ${needed:,.0f} more total profit before payout"
                    )
                elif pct > 0.25:
                    lines.append(
                        f" [yellow]Today = {pct:.0%} of total — approaching 30%[/]"
                    )
                else:
                    lines.append(
                        f" [green]Today = {pct:.0%} of total — within limits[/]"
                    )

        # Decaying strategies summary
        if self._strategies:
            decaying = [s for s in self._strategies if s.status == "DECAYING"]
            if decaying:
                lines.append("")
                lines.append(f" [bold red]DECAYING STRATEGIES ({len(decaying)}):[/]")
                for s in decaying[:5]:
                    lines.append(
                        f"   [red]{s.name}[/]: {s.recent_wr:.0%} recent "
                        f"(was {s.overall_wr:.0%})"
                    )

        self.query_one("#consistency-panel", Static).update("\n".join(lines))

    def _render_position_risk(self):
        """Render position concentration and risk metrics."""
        sc = self._cme_scorecard
        hl = self._hl_data
        instruments = sc.get("instruments", [])

        lines = [
            " [bold]POSITION & CONCENTRATION RISK[/]",
            "",
        ]

        # CME instrument exposure
        if instruments:
            lines.append(" [bold]CME Instrument Exposure[/]")
            total_abs_pnl = sum(abs(i.get("pnl", 0)) for i in instruments)
            for inst in instruments:
                pnl = inst.get("pnl", 0)
                trades = inst.get("trades", 0)
                wr = inst.get("wr", 0)
                pnl_c = "green" if pnl >= 0 else "red"
                conc = abs(pnl) / total_abs_pnl * 100 if total_abs_pnl > 0 else 0

                lines.append(
                    f"   {inst['instrument']:6s} {trades:3d}t "
                    f"{wr:5.1f}% [{pnl_c}]${pnl:>+8,.0f}[/] "
                    f"({conc:.0f}%)"
                )
            lines.append("")

        # HL leverage
        if hl:
            lev = hl.get("leverage", 0)
            lev_color = "green" if lev < 3 else "yellow" if lev < 5 else "red"
            equity = hl.get("equity", 0)
            pnl = hl.get("unrealized_pnl", 0)
            pnl_c = "green" if pnl >= 0 else "red"

            lines.append(" [bold]Hyperliquid[/]")
            lines.append(f"   Equity: ${equity:,.2f}")
            lines.append(f"   Leverage: [{lev_color}]{lev:.1f}x[/]")
            lines.append(f"   Unrealized: [{pnl_c}]${pnl:+,.2f}[/]")

            positions = hl.get("positions", {})
            if positions:
                for coin, pos in positions.items():
                    pos_pnl = pos.get("pnl", 0)
                    pos_c = "green" if pos_pnl >= 0 else "red"
                    lines.append(
                        f"   {coin:6s} ${pos.get('notional', 0):>8,.0f} "
                        f"[{pos_c}]${pos_pnl:>+8,.2f}[/]"
                    )
            lines.append("")

        # Drawdown context
        max_dd = sc.get("max_drawdown", 0)
        peak = sc.get("peak_pnl", 0)
        current_dd = sc.get("current_dd", 0)
        if max_dd > 0 or peak > 0:
            lines.append(" [bold]Drawdown History[/]")
            lines.append(f"   Peak P&L: ${peak:+,.2f}")
            lines.append(f"   Max Drawdown: ${max_dd:,.2f}")
            lines.append(f"   Current DD: ${current_dd:,.2f}")

        self.query_one("#position-risk", Static).update("\n".join(lines))
