"""Status header — connection state, clock, bot PID."""

import time
from textual.widgets import Static


class StatusHeader(Static):

    def __init__(self, **kwargs):
        super().__init__(" [bold]TURBO CONTRARIAN[/]  |  Loading...", **kwargs)
        self._ws_connected = False
        self._active_tokens = 0
        self._bot_pid = 0
        self._bot_alive = False

    def update_status(
        self,
        ws_connected: bool,
        active_tokens: int,
        bot_pid: int = 0,
        bot_alive: bool = False,
    ):
        self._ws_connected = ws_connected
        self._active_tokens = active_tokens
        self._bot_pid = bot_pid
        self._bot_alive = bot_alive
        self._render_header()

    def _render_header(self):
        now = time.strftime("%H:%M:%S")

        if self._bot_alive:
            bot_text = f"[bold green]BOT: PID {self._bot_pid}[/]"
        else:
            bot_text = "[bold red]BOT: DOWN[/]"

        if self._ws_connected:
            ws_text = "[green]WS: ON[/]"
        else:
            ws_text = "[dim]WS: OFF[/]"

        self.update(
            f" [bold]TURBO CONTRARIAN[/]  |  {now}  |  "
            f"{bot_text}  |  {ws_text}  |  "
            f"Tokens: {self._active_tokens}"
        )
