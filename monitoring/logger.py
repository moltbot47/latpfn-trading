"""
Structured logging setup for the trading system.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(config: dict):
    """Configure logging to both console and file."""
    level = getattr(logging, config["system"]["log_level"].upper(), logging.INFO)
    log_dir = Path(config["system"].get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"trading_{date_str}.log"

    fmt = "%(asctime)s [%(levelname)-7s] %(name)-25s  %(message)s"
    datefmt = "%H:%M:%S"

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(console)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(fh)

    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    logging.info("Logging initialized → %s", log_file)
