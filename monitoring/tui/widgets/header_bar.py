"""Global header — multi-platform equity, bot status, clock, alert badge."""

import time
from typing import Dict, Optional

from textual.widgets import Static


class GlobalHeader(Static):
    """Multi-platform command center header."""

    def __init__(self, **kwargs):
        super().__init__(
            " [bold]TRADING COMMAND CENTER[/]  |  Loading...", **kwargs
        )
        self._bots: Dict[str, bool] = {}
        self._cme_pnl: float = 0
        self._hl_pnl: float = 0
        self._poly_pnl: float = 0
        self._cme_equity: float = 0
        self._hl_equity: float = 0
        self._poly_equity: float = 0
        self._positions: int = 0
        self._alert_count: int = 0
        self._critical_count: int = 0

    def update_data(
        self,
        bots: Optional[Dict[str, bool]] = None,
        cme_equity: float = 0,
        cme_pnl: float = 0,
        hl_equity: float = 0,
        hl_pnl: float = 0,
        poly_equity: float = 0,
        poly_pnl: float = 0,
        positions: int = 0,
        alert_count: int = 0,
        critical_count: int = 0,
    ):
        if bots is not None:
            self._bots = bots
        self._cme_equity = cme_equity
        self._cme_pnl = cme_pnl
        self._hl_equity = hl_equity
        self._hl_pnl = hl_pnl
        self._poly_equity = poly_equity
        self._poly_pnl = poly_pnl
        self._positions = positions
        self._alert_count = alert_count
        self._critical_count = critical_count
        self._refresh_display()

    def _refresh_display(self):
        now = time.strftime("%H:%M:%S")

        total_equity = self._cme_equity + self._hl_equity + self._poly_equity
        total_pnl = self._cme_pnl + self._hl_pnl + self._poly_pnl

        # Bot status indicators
        bot_parts = []
        for name, alive in self._bots.items():
            if alive:
                bot_parts.append(f"[green]{name}[/]")
            else:
                bot_parts.append(f"[red]{name}[/]")
        bots_str = " ".join(bot_parts) if bot_parts else "[dim]no bots[/]"

        # P&L coloring
        pnl_color = "green" if total_pnl >= 0 else "red"
        cme_color = "green" if self._cme_pnl >= 0 else "red"
        hl_color = "green" if self._hl_pnl >= 0 else "red"
        poly_color = "green" if self._poly_pnl >= 0 else "red"

        # Alert badge
        if self._critical_count > 0:
            alert_str = f"[bold red on white] {self._alert_count} ALERTS [/]"
        elif self._alert_count > 0:
            alert_str = f"[yellow]{self._alert_count} alerts[/]"
        else:
            alert_str = "[green]OK[/]"

        self.update(
            f" [bold]COMMAND CENTER[/]  {now}  |  "
            f"[{pnl_color}]${total_equity:,.0f} ({total_pnl:+,.2f})[/]  |  "
            f"CME:[{cme_color}]{self._cme_pnl:+,.0f}[/] "
            f"HL:[{hl_color}]{self._hl_pnl:+,.0f}[/] "
            f"Poly:[{poly_color}]{self._poly_pnl:+,.0f}[/]  |  "
            f"Pos:{self._positions}  |  {alert_str}  |  {bots_str}"
        )
