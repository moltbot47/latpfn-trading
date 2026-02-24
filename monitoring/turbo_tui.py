#!/usr/bin/env python3
"""Launch the Turbo TUI dashboard. Run alongside the bot in a separate terminal."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env so TUI has access to HYPERLIQUID_WALLET_ADDRESS etc.
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from monitoring.tui.app import TurboTUIApp

if __name__ == "__main__":
    app = TurboTUIApp()
    app.run()
