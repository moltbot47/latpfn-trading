#!/usr/bin/env python3
"""Simple load test for the funding dashboard.

Sends concurrent requests and measures response times.

Usage:
    python scripts/load_test.py                     # Default: 100 requests, 10 concurrent
    python scripts/load_test.py -n 500 -c 20        # 500 requests, 20 concurrent
    python scripts/load_test.py --url http://host:5055  # Custom base URL
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BASE_URL = "http://localhost:5055"

ENDPOINTS = [
    ("GET", "/health"),
    ("GET", "/api/summary"),
    ("GET", "/api/products"),
    ("GET", "/api/applications"),
    ("GET", "/api/partner-programs"),
    ("GET", "/api/partner-programs/summary"),
    ("GET", "/api/referrals/summary"),
    ("GET", "/metrics"),
]


def make_request(base_url: str, method: str, path: str) -> dict:
    """Make a single HTTP request and return timing data."""
    url = f"{base_url}{path}"
    start = time.time()
    try:
        req = urllib.request.Request(url, method=method)
        resp = urllib.request.urlopen(req, timeout=10)
        elapsed_ms = (time.time() - start) * 1000
        return {
            "path": path,
            "status": resp.status,
            "latency_ms": elapsed_ms,
            "error": None,
        }
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.time() - start) * 1000
        return {
            "path": path,
            "status": e.code,
            "latency_ms": elapsed_ms,
            "error": str(e),
        }
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return {
            "path": path,
            "status": 0,
            "latency_ms": elapsed_ms,
            "error": str(e),
        }


def run_load_test(base_url: str, num_requests: int, concurrency: int) -> dict:
    """Run the load test and return aggregate results."""
    results = []
    tasks = []

    # Distribute requests across endpoints
    for i in range(num_requests):
        method, path = ENDPOINTS[i % len(ENDPOINTS)]
        tasks.append((method, path))

    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(make_request, base_url, method, path): (method, path)
            for method, path in tasks
        }
        for future in as_completed(futures):
            results.append(future.result())
    total_time = time.time() - start

    # Aggregate
    latencies = [r["latency_ms"] for r in results if r["status"] == 200]
    errors = [r for r in results if r["status"] != 200]
    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    return {
        "total_requests": num_requests,
        "concurrency": concurrency,
        "total_time_s": round(total_time, 2),
        "requests_per_second": round(num_requests / total_time, 1),
        "success_count": len(latencies),
        "error_count": len(errors),
        "status_codes": status_counts,
        "latency_ms": {
            "min": round(min(latencies), 1) if latencies else 0,
            "max": round(max(latencies), 1) if latencies else 0,
            "avg": round(statistics.mean(latencies), 1) if latencies else 0,
            "median": round(statistics.median(latencies), 1) if latencies else 0,
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0, 1),
            "p99": round(sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0, 1),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Load test the funding dashboard")
    parser.add_argument("-n", "--requests", type=int, default=100, help="Total requests")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base URL")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Check service is up first
    try:
        urllib.request.urlopen(f"{args.url}/health", timeout=5)
    except Exception:
        print(f"Error: Service not reachable at {args.url}/health")
        sys.exit(1)

    print(f"Load testing {args.url} — {args.requests} requests, {args.concurrency} concurrent\n")

    results = run_load_test(args.url, args.requests, args.concurrency)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"  Total time:    {results['total_time_s']}s")
        print(f"  Requests/sec:  {results['requests_per_second']}")
        print(f"  Success:       {results['success_count']}/{results['total_requests']}")
        print(f"  Errors:        {results['error_count']}")
        print()
        lat = results["latency_ms"]
        print(f"  Latency (ms):  min={lat['min']}  avg={lat['avg']}  median={lat['median']}  p95={lat['p95']}  p99={lat['p99']}  max={lat['max']}")
        print(f"  Status codes:  {results['status_codes']}")


if __name__ == "__main__":
    main()
