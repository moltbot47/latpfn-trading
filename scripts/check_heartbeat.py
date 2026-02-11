#!/usr/bin/env python3
"""
Check the trading system heartbeat file and report status.

Exit codes:
    0 — system is alive (last heartbeat < 10 minutes ago)
    1 — system appears down (heartbeat stale or missing)

Usage:
    python scripts/check_heartbeat.py
    # Or in a cron/monitoring script:
    python scripts/check_heartbeat.py && echo "OK" || echo "ALERT"
"""

import json
import os
import sys
from datetime import datetime, timedelta

HEARTBEAT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "heartbeat.json",
)

MAX_AGE_MINUTES = 10


def main():
    if not os.path.exists(HEARTBEAT_PATH):
        print(f"ALERT: Heartbeat file not found at {HEARTBEAT_PATH}")
        print("Trading system may not have started yet.")
        sys.exit(1)

    try:
        with open(HEARTBEAT_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"ALERT: Failed to read heartbeat file: {e}")
        sys.exit(1)

    ts_str = data.get("timestamp")
    if not ts_str:
        print("ALERT: Heartbeat file has no timestamp field.")
        sys.exit(1)

    try:
        heartbeat_time = datetime.fromisoformat(ts_str)
    except ValueError as e:
        print(f"ALERT: Invalid timestamp format: {ts_str} ({e})")
        sys.exit(1)

    now = datetime.now()
    age = now - heartbeat_time
    age_minutes = age.total_seconds() / 60.0

    cycle = data.get("cycle", "?")
    status = data.get("status", "?")
    instruments = data.get("instruments", "?")

    if age_minutes > MAX_AGE_MINUTES:
        print(
            f"ALERT: Last heartbeat was {age_minutes:.1f} minutes ago "
            f"(threshold: {MAX_AGE_MINUTES} min)"
        )
        print(f"  Cycle: {cycle}  Status: {status}  Instruments: {instruments}")
        print(f"  Timestamp: {ts_str}")
        sys.exit(1)
    else:
        print(
            f"OK: Trading system alive — last heartbeat {age_minutes:.1f} minutes ago"
        )
        print(f"  Cycle: {cycle}  Status: {status}  Instruments: {instruments}")
        print(f"  Timestamp: {ts_str}")
        sys.exit(0)


if __name__ == "__main__":
    main()
