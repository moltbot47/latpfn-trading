"""
Terminal dashboard using the ``rich`` library.
Shows positions, signals, risk status, and recent log entries.
"""

import logging
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

logger = logging.getLogger(__name__)

console = Console()


def print_header(config: dict):
    """Print startup banner."""
    mode = config["system"]["mode"]
    env = config["system"]["environment"]
    instruments = ", ".join(config["instruments"].keys())
    console.rule("[bold cyan]LaT-PFN Automated Futures Trading System")
    console.print(f"  Mode: [bold]{mode}[/]  |  Environment: [bold]{env}[/]")
    console.print(f"  Instruments: [bold]{instruments}[/]")
    console.print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    console.rule()


def print_cycle_summary(
    cycle: int,
    predictions: dict,
    positions: dict,
    account_equity: float,
    daily_pnl: float,
):
    """Print summary after each prediction cycle."""
    console.print()
    console.rule(f"[dim]Cycle {cycle} — {datetime.now().strftime('%H:%M:%S')}[/dim]")

    # ── Predictions table ─────────────────────────────────────────
    pred_table = Table(title="Predictions", show_lines=False, expand=True)
    pred_table.add_column("Instrument", style="bold")
    pred_table.add_column("Direction")
    pred_table.add_column("Confidence")
    pred_table.add_column("Regime")
    pred_table.add_column("Forecast End")

    for inst, pred in predictions.items():
        if pred is None:
            pred_table.add_row(inst, "[dim]no data[/]", "", "", "")
            continue

        dir_style = {"long": "green", "short": "red", "neutral": "dim"}.get(
            pred["direction"], "dim"
        )
        conf_bar = _bar(pred["confidence"])
        forecast_end = f"${pred['forecast_prices'][-1]:.2f}" if len(pred["forecast_prices"]) > 0 else "—"

        pred_table.add_row(
            inst,
            f"[{dir_style}]{pred['direction'].upper()}[/]",
            conf_bar,
            pred["regime"],
            forecast_end,
        )

    console.print(pred_table)

    # ── Positions table ───────────────────────────────────────────
    if positions:
        pos_table = Table(title="Open Positions", show_lines=False, expand=True)
        pos_table.add_column("Instrument", style="bold")
        pos_table.add_column("Dir")
        pos_table.add_column("Size")
        pos_table.add_column("Entry")
        pos_table.add_column("Current")
        pos_table.add_column("P&L (pts)")

        for inst, pos in positions.items():
            pnl = pos.unrealized_pnl_points
            pnl_style = "green" if pnl >= 0 else "red"
            pos_table.add_row(
                inst,
                pos.direction,
                str(pos.size),
                f"${pos.entry_price:.2f}",
                f"${pos.current_price:.2f}" if pos.current_price else "—",
                f"[{pnl_style}]{pnl:+.2f}[/]",
            )
        console.print(pos_table)

    # ── Account summary ───────────────────────────────────────────
    pnl_style = "green" if daily_pnl >= 0 else "red"
    console.print(
        f"  Equity: [bold]${account_equity:,.2f}[/]  |  "
        f"Daily P&L: [{pnl_style}]${daily_pnl:+,.2f}[/]  |  "
        f"Positions: {len(positions)}"
    )


def print_signal(instrument: str, signal):
    """Print a generated signal."""
    if signal is None:
        return
    dir_style = "green" if signal.direction == "long" else "red"
    console.print(
        f"  [bold {dir_style}]SIGNAL[/] {instrument} "
        f"{signal.direction.upper()} {signal.position_size} "
        f"@ ${signal.entry_price:.2f}  "
        f"SL=${signal.stop_loss:.2f}  TP=${signal.take_profit:.2f}  "
        f"conf={signal.confidence:.3f}"
    )


def print_risk_decision(instrument: str, approved: bool, reason: str):
    """Print risk validation result."""
    if approved:
        console.print(f"  [green]APPROVED[/] {instrument}: {reason}")
    else:
        console.print(f"  [red]REJECTED[/] {instrument}: {reason}")


def print_order_result(instrument: str, result: dict | None):
    """Print order placement result."""
    if result and "orderId" in result:
        console.print(
            f"  [bold green]ORDER PLACED[/] {instrument}: id={result['orderId']}"
        )
    else:
        console.print(f"  [bold red]ORDER FAILED[/] {instrument}")


def _bar(value: float, width: int = 10) -> str:
    """Simple text-based progress bar."""
    filled = int(value * width)
    return f"{'█' * filled}{'░' * (width - filled)} {value:.2f}"
