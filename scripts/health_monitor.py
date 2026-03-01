#!/usr/bin/env python3
"""Health monitor for all dashboard services.

Checks health endpoints and reports status. Designed for cron or
continuous monitoring. Returns exit code 1 if any service is down.

Usage:
    python scripts/health_monitor.py              # Check all services
    python scripts/health_monitor.py --json        # JSON output for log aggregation
    python scripts/health_monitor.py --verbose     # Detailed output

Cron example (every 5 minutes):
    */5 * * * * cd /path/to/latpfn-trading && venv/bin/python scripts/health_monitor.py >> logs/health.log 2>&1
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SERVICES = [
    {
        "name": "Funding Dashboard",
        "url": "http://localhost:5055/health",
        "detail_url": "http://localhost:5055/health/detail",
    },
    {
        "name": "Trading Dashboard",
        "url": "http://localhost:5050/api/status",
    },
]


def check_service(service: dict, timeout: int = 5) -> dict:
    """Check a single service health endpoint."""
    result = {
        "name": service["name"],
        "url": service["url"],
        "status": "down",
        "response_ms": None,
        "details": None,
        "error": None,
    }

    start = time.time()
    try:
        req = urllib.request.Request(service["url"])
        resp = urllib.request.urlopen(req, timeout=timeout)
        elapsed_ms = (time.time() - start) * 1000
        result["response_ms"] = round(elapsed_ms, 1)

        data = json.loads(resp.read().decode())
        result["status"] = "up"
        result["details"] = data

        # Check detail endpoint if available
        if "detail_url" in service:
            try:
                detail_resp = urllib.request.urlopen(service["detail_url"], timeout=timeout)
                result["details"] = json.loads(detail_resp.read().decode())
            except Exception:
                pass  # Detail is optional

    except urllib.error.URLError as e:
        result["error"] = str(e.reason)
    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description="Check service health")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", action="store_true", help="Show details")
    parser.add_argument("--timeout", type=int, default=5, help="Request timeout (seconds)")
    args = parser.parse_args()

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    results = []
    all_up = True

    for svc in SERVICES:
        result = check_service(svc, timeout=args.timeout)
        results.append(result)
        if result["status"] != "up":
            all_up = False

    if args.json:
        output = {
            "timestamp": timestamp,
            "all_healthy": all_up,
            "services": results,
        }
        print(json.dumps(output))
    else:
        print(f"[{timestamp}] Health Check")
        print("-" * 50)
        for r in results:
            icon = "OK" if r["status"] == "up" else "DOWN"
            ms = f" ({r['response_ms']}ms)" if r["response_ms"] else ""
            print(f"  [{icon}] {r['name']}{ms}")
            if r["error"]:
                print(f"        Error: {r['error']}")
            if args.verbose and r["details"]:
                for k, v in r["details"].items():
                    if k not in ("status",):
                        print(f"        {k}: {v}")
        print()
        status = "ALL HEALTHY" if all_up else "DEGRADED"
        print(f"  Status: {status}")

    sys.exit(0 if all_up else 1)


if __name__ == "__main__":
    main()
