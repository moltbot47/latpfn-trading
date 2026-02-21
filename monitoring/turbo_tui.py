#!/usr/bin/env python3
"""Launch the Turbo TUI dashboard. Run alongside the bot in a separate terminal."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.tui.app import TurboTUIApp

if __name__ == "__main__":
    app = TurboTUIApp()
    app.run()
