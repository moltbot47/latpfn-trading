"""Position detail modal with close/modify actions."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from monitoring.tui.screens.confirm_dialog import ConfirmScreen


class PositionDetailScreen(ModalScreen):
    """Modal showing full position details with action buttons."""

    def __init__(self, position: dict, platform: str, **kwargs):
        super().__init__(**kwargs)
        self._position = position
        self._platform = platform

    def compose(self) -> ComposeResult:
        p = self._position
        with Vertical(id="position-modal"):
            yield Static(self._render_details(), id="pos-details")
            with Horizontal(id="position-modal-buttons"):
                if self._platform in ("HL", "CME"):
                    yield Button(
                        "Close Position", variant="error", id="close-btn"
                    )
                yield Button("Back", variant="default", id="back-btn")

    def _render_details(self) -> str:
        p = self._position
        lines = [
            f" [bold]{self._platform} Position Detail[/]",
            "",
        ]

        symbol = p.get("instrument") or p.get("coin") or p.get("asset", "?")
        direction = p.get("direction", "?")
        dir_color = "green" if direction.lower() in ("long", "up") else "red"

        lines.append(f" Symbol:    [bold]{symbol}[/]")
        lines.append(f" Direction: [{dir_color}]{direction.upper()}[/]")

        if "entry_price" in p:
            lines.append(f" Entry:     ${p['entry_price']:,.2f}")
        elif "entry" in p:
            lines.append(f" Entry:     ${p['entry']:,.4f}")

        if "stop_loss" in p:
            lines.append(f" Stop Loss: ${p['stop_loss']:,.2f}")
        if "take_profit" in p:
            lines.append(f" Take Prof: ${p['take_profit']:,.2f}")

        if "size" in p:
            lines.append(f" Size:      {p['size']}")
        elif "position_size" in p:
            lines.append(f" Contracts: {p['position_size']}")

        pnl = p.get("pnl") or p.get("unrealized_pnl", 0)
        if pnl:
            pnl_color = "green" if pnl >= 0 else "red"
            lines.append(f" P&L:       [{pnl_color}]${pnl:+,.2f}[/]")

        if "entry_time" in p:
            lines.append(f" Opened:    {p['entry_time']}")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close-btn":
            self.app.push_screen(
                ConfirmScreen(
                    f"Close {self._position.get('instrument', self._position.get('coin', '?'))} position?"
                ),
                callback=self._on_confirm,
            )
        elif event.button.id == "back-btn":
            self.dismiss()

    def _on_confirm(self, confirmed: bool):
        if confirmed:
            self.app.call_later(self._execute_close)

    async def _execute_close(self):
        p = self._position
        try:
            if self._platform == "HL":
                from execution.hyperliquid_client import HyperliquidClient
                from config.loader import load_config
                config = load_config()
                client = HyperliquidClient(config)
                await client.connect()
                coin = p.get("coin", p.get("instrument", ""))
                await client.close_position(coin)
                self.app.notify(f"Closed HL position: {coin}", severity="information")

            elif self._platform == "CME":
                from execution.traderspost_client import TradersPostClient
                from config.loader import load_config
                config = load_config()
                client = TradersPostClient(config)
                symbol = p.get("instrument", "")
                await client.close_position(symbol)
                self.app.notify(f"Close sent for: {symbol}", severity="information")

        except Exception as e:
            self.app.notify(f"Close failed: {e}", severity="error")

        self.dismiss()
