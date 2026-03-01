"""
Structured logging setup for the trading system.

Supports two output formats:
  - "text" (default): Human-readable lines for console/file
  - "json": Machine-parseable JSON lines for log aggregation
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(config: dict):
    """Configure logging to both console and file.

    Config keys used:
      - config["system"]["log_level"]  — DEBUG/INFO/WARNING/ERROR (default: INFO)
      - config["system"]["log_dir"]    — directory for log files (default: ./logs)
      - config["system"]["log_format"] — "text" or "json" (default: text)
    """
    level = getattr(logging, config["system"]["log_level"].upper(), logging.INFO)
    log_dir = Path(config["system"].get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"trading_{date_str}.log"

    log_format = config["system"].get("log_format", "text")

    if log_format == "json":
        formatter = JSONFormatter()
    else:
        fmt = "%(asctime)s [%(levelname)-7s] %(name)-25s  %(message)s"
        formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    logging.info("Logging initialized → %s (format=%s)", log_file, log_format)


class ErrorAggregator:
    """Track and deduplicate errors for alerting.

    Collects errors over a time window and reports unique ones,
    preventing alert storms from repeated failures.

    Usage:
        agg = ErrorAggregator(window_seconds=300)
        agg.record("DB connection failed")
        summary = agg.flush()  # returns counts of unique errors
    """

    def __init__(self, window_seconds: int = 300):
        self._window = window_seconds
        self._errors: dict[str, list[float]] = {}  # message → [timestamps]

    def record(self, message: str, timestamp: float | None = None):
        """Record an error occurrence."""
        import time
        ts = timestamp or time.time()
        if message not in self._errors:
            self._errors[message] = []
        self._errors[message].append(ts)

    def flush(self) -> list[dict]:
        """Return unique errors with counts, then clear the buffer."""
        import time
        cutoff = time.time() - self._window
        summary = []
        for msg, timestamps in self._errors.items():
            recent = [t for t in timestamps if t > cutoff]
            if recent:
                summary.append({
                    "message": msg,
                    "count": len(recent),
                    "first_seen": min(recent),
                    "last_seen": max(recent),
                })
        self._errors.clear()
        return summary

    @property
    def error_count(self) -> int:
        return sum(len(ts) for ts in self._errors.values())
