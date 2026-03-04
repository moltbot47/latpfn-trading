"""Backtest tab — run backtests as subprocesses with live output."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog, Select, Static

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

INSTRUMENTS = [
    ("MNQ", "MNQ"),
    ("MYM", "MYM"),
    ("MES", "MES"),
    ("MBT", "MBT"),
    ("M2K", "M2K"),
    ("MCL", "MCL"),
    ("MGC", "MGC"),
    ("MET", "MET"),
]

INTERVALS = [
    ("5m", "5m"),
    ("15m", "15m"),
    ("1h", "1h"),
]

MODES = [
    ("standard", "standard"),
    ("scalp", "scalp"),
]


class BacktestTab(Static):
    """Backtest launcher and results viewer."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._process: subprocess.Popen | None = None
        self._running = False
        self._output_lines: list = []
        self._results: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="backtest-config"):
                yield Select(
                    INSTRUMENTS,
                    prompt="Instrument",
                    id="bt-instrument",
                    value="MNQ",
                )
                yield Input(
                    placeholder="Days (1-60)",
                    id="bt-days",
                    value="30",
                )
                yield Select(
                    INTERVALS,
                    prompt="Interval",
                    id="bt-interval",
                    value="5m",
                )
                yield Select(
                    MODES,
                    prompt="Mode",
                    id="bt-mode",
                    value="standard",
                )
                yield Input(
                    placeholder="Equity",
                    id="bt-equity",
                    value="50000",
                )
            with Horizontal(id="backtest-buttons"):
                yield Button("Run Backtest", variant="success", id="bt-run")
                yield Button("Stop", variant="error", id="bt-stop", disabled=True)
                yield Button("Clear", variant="default", id="bt-clear")
            with Horizontal(id="backtest-results"):
                yield Static(" [dim]Run a backtest to see results...[/]", id="backtest-metrics")
                yield RichLog(
                    id="backtest-log", highlight=True, markup=True,
                    max_lines=500,
                )

    def on_mount(self):
        self.query_one("#backtest-config").border_title = "CONFIGURATION"
        self.query_one("#backtest-metrics").border_title = "RESULTS"
        self.query_one("#backtest-log").border_title = "BACKTEST OUTPUT"

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "bt-run":
            self._start_backtest()
        elif event.button.id == "bt-stop":
            self._stop_backtest()
        elif event.button.id == "bt-clear":
            self._clear_output()

    def _start_backtest(self):
        if self._running:
            return

        # Read config values
        try:
            instrument = self.query_one("#bt-instrument", Select).value
            days = self.query_one("#bt-days", Input).value.strip()
            interval = self.query_one("#bt-interval", Select).value
            mode = self.query_one("#bt-mode", Select).value
            equity = self.query_one("#bt-equity", Input).value.strip()
        except Exception:
            return

        if not instrument or instrument == Select.BLANK:
            self.app.notify("Select an instrument", severity="warning")
            return

        days_int = int(days) if days.isdigit() else 30
        equity_int = int(equity) if equity.isdigit() else 50000

        # Build command
        backtest_script = str(PROJECT_ROOT / "scripts" / "backtest.py")
        cmd = [
            sys.executable, backtest_script,
            "--instrument", str(instrument),
            "--days", str(days_int),
            "--interval", str(interval),
            "--mode", str(mode),
            "--equity", str(equity_int),
            "--save-results",
        ]

        log = self.query_one("#backtest-log", RichLog)
        log.clear()
        log.write(f" [bold]Starting backtest: {instrument} {days_int}d {interval} {mode}[/]")
        log.write(f" [dim]{' '.join(cmd)}[/]")
        log.write("")

        self._output_lines = []
        self._results = None
        self._running = True
        self.query_one("#bt-run", Button).disabled = True
        self.query_one("#bt-stop", Button).disabled = False
        self.query_one("#backtest-metrics", Static).update(
            " [bold yellow]Running...[/]\n\n [dim]Backtest in progress[/]"
        )

        # Launch subprocess
        asyncio.create_task(self._run_subprocess(cmd))

    async def _run_subprocess(self, cmd: list):
        """Run backtest as subprocess and stream output."""
        log = self.query_one("#backtest-log", RichLog)

        try:
            self._process = await asyncio.to_thread(
                lambda: subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(PROJECT_ROOT),
                    bufsize=1,
                )
            )

            # Read output line by line
            while self._running and self._process.poll() is None:
                line = await asyncio.to_thread(self._process.stdout.readline)
                if line:
                    line = line.rstrip()
                    self._output_lines.append(line)
                    # Color trade results
                    if "WIN" in line:
                        log.write(f" [green]{line}[/]")
                    elif "LOSS" in line:
                        log.write(f" [red]{line}[/]")
                    elif "Summary" in line or "===" in line:
                        log.write(f" [bold]{line}[/]")
                    else:
                        log.write(f" {line}")

            # Read remaining output
            if self._process:
                remaining = await asyncio.to_thread(self._process.stdout.read)
                if remaining:
                    for line in remaining.strip().split("\n"):
                        self._output_lines.append(line)
                        log.write(f" {line}")

            rc = self._process.returncode if self._process else -1
            if rc == 0:
                log.write("")
                log.write(" [bold green]Backtest completed successfully[/]")
                self._parse_results()
            else:
                log.write(f" [bold red]Backtest exited with code {rc}[/]")

        except Exception as e:
            log.write(f" [bold red]Error: {e}[/]")
        finally:
            self._running = False
            self._process = None
            try:
                self.query_one("#bt-run", Button).disabled = False
                self.query_one("#bt-stop", Button).disabled = True
            except Exception:
                pass

    def _stop_backtest(self):
        if self._process and self._running:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._running = False
            log = self.query_one("#backtest-log", RichLog)
            log.write(" [bold yellow]Backtest stopped by user[/]")
            self.query_one("#bt-run", Button).disabled = False
            self.query_one("#bt-stop", Button).disabled = True

    def _clear_output(self):
        self.query_one("#backtest-log", RichLog).clear()
        self.query_one("#backtest-metrics", Static).update(
            " [dim]Run a backtest to see results...[/]"
        )
        self._output_lines = []
        self._results = None

    def _parse_results(self):
        """Parse results from output or from saved JSON report."""
        # Try to find the most recent report file
        try:
            instrument = self.query_one("#bt-instrument", Select).value
            if REPORTS_DIR.exists():
                reports = sorted(
                    REPORTS_DIR.glob(f"backtest_{instrument}_*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if reports:
                    with open(reports[0]) as f:
                        self._results = json.load(f)
                    self._render_results(self._results)
                    return
        except Exception:
            pass

        # Fallback: parse from output lines
        self._render_results_from_output()

    def _render_results(self, results: dict):
        """Render results from saved JSON report."""
        summary = results.get("summary", {})
        per_tier = results.get("per_tier", {})
        equity_curve = results.get("equity_curve", [])

        trades = summary.get("total_trades", 0)
        wr = summary.get("win_rate", 0)
        pnl = summary.get("total_pnl", 0)
        pf = summary.get("profit_factor", 0)
        max_dd = summary.get("max_drawdown", 0)
        avg_win = summary.get("avg_win", 0)
        avg_loss = summary.get("avg_loss", 0)
        ret_pct = summary.get("return_pct", 0)

        wr_c = "green" if wr >= 55 else "yellow" if wr >= 45 else "red"
        pnl_c = "green" if pnl >= 0 else "red"
        pf_c = "green" if pf >= 1.5 else "yellow" if pf >= 1.0 else "red"

        lines = [
            " [bold]BACKTEST RESULTS[/]",
            "",
            f" Trades: {trades}",
            f" Win Rate: [{wr_c}]{wr:.1f}%[/]",
            f" P&L: [{pnl_c}]${pnl:+,.2f}[/]",
            f" Profit Factor: [{pf_c}]{pf:.2f}[/]",
            f" Max Drawdown: ${max_dd:,.2f}",
            f" Return: [{pnl_c}]{ret_pct:.1f}%[/]",
            f" Avg Win: ${avg_win:+.2f}  Avg Loss: ${avg_loss:.2f}",
        ]

        # Per-tier breakdown
        if per_tier:
            lines.append("")
            lines.append(" [bold]Per-Tier Breakdown[/]")
            lines.append(f" {'Tier':14s} {'Tr':>4s} {'WR':>6s} {'PnL':>8s} {'PF':>5s}")
            lines.append(f" {'─' * 14} {'─' * 4} {'─' * 6} {'─' * 8} {'─' * 5}")
            for tier, t in per_tier.items():
                t_wr = t.get("win_rate", 0)
                t_pnl = t.get("total_pnl", 0)
                t_pf = t.get("profit_factor", 0)
                wr_c = "green" if t_wr >= 55 else "yellow" if t_wr >= 45 else "red"
                pnl_c = "green" if t_pnl >= 0 else "red"
                lines.append(
                    f" {tier[:14]:14s} {t.get('count', 0):4d}"
                    f" [{wr_c}]{t_wr:5.1f}%[/]"
                    f" [{pnl_c}]${t_pnl:+7.0f}[/]"
                    f" {t_pf:5.2f}"
                )

        # Simple equity curve spark
        if equity_curve and len(equity_curve) >= 2:
            spark_chars = "▁▂▃▄▅▆▇█"
            lo = min(equity_curve)
            hi = max(equity_curve)
            rng = hi - lo if hi != lo else 1
            width = 30
            step = max(1, len(equity_curve) // width)
            sampled = equity_curve[::step][-width:]
            spark = ""
            for v in sampled:
                idx = int((v - lo) / rng * 7)
                idx = max(0, min(7, idx))
                color = "green" if v >= 0 else "red"
                spark += f"[{color}]{spark_chars[idx]}[/]"
            lines.append("")
            lines.append(f" Equity: {spark}")

        self.query_one("#backtest-metrics", Static).update("\n".join(lines))

    def _render_results_from_output(self):
        """Fallback: parse summary from stdout output lines."""
        lines = [" [bold]BACKTEST RESULTS[/]", ""]

        # Look for summary section in output
        in_summary = False
        for line in self._output_lines:
            if "Summary" in line or "===" in line:
                in_summary = True
            if in_summary:
                lines.append(f" {line}")

        if len(lines) <= 2:
            lines.append(" [dim]No parseable results (check output log)[/]")

        self.query_one("#backtest-metrics", Static).update("\n".join(lines))
