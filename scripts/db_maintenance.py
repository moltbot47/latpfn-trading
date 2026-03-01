#!/usr/bin/env python3
"""SQLite database maintenance utility.

Runs VACUUM, ANALYZE, and integrity checks on all databases.
Optimizes storage and updates query planner statistics.

Usage:
    python scripts/db_maintenance.py              # Maintain all databases
    python scripts/db_maintenance.py --db funding.db  # Specific database
    python scripts/db_maintenance.py --check-only     # Integrity check only
"""

import argparse
import logging
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

DATABASES = [
    "funding.db",
    "trade_log.db",
    "turbo_analytics.db",
    "polymarket_forecasts.db",
    "broker_reports.db",
]

logger = logging.getLogger("db_maintenance")


def maintain_database(db_path: Path, check_only: bool = False) -> dict:
    """Run maintenance tasks on a single database."""
    result = {
        "database": db_path.name,
        "size_kb": db_path.stat().st_size / 1024,
        "integrity": None,
        "vacuumed": False,
        "analyzed": False,
        "duration_ms": 0,
    }

    start = time.time()
    try:
        conn = sqlite3.connect(str(db_path))

        # Integrity check
        check = conn.execute("PRAGMA integrity_check").fetchone()
        result["integrity"] = check[0]

        if check[0] != "ok":
            logger.warning("Integrity check FAILED for %s: %s", db_path.name, check[0])
            conn.close()
            return result

        if not check_only:
            # ANALYZE: update query planner statistics
            conn.execute("ANALYZE")
            result["analyzed"] = True
            logger.info("ANALYZE complete: %s", db_path.name)

            # VACUUM: reclaim space and defragment
            conn.execute("VACUUM")
            result["vacuumed"] = True
            new_size = db_path.stat().st_size / 1024
            saved = result["size_kb"] - new_size
            logger.info("VACUUM complete: %s (saved %.1f KB)", db_path.name, saved)
            result["size_kb"] = new_size

        conn.close()
    except Exception as e:
        logger.exception("Maintenance failed for %s", db_path.name)
        result["integrity"] = f"error: {e}"

    result["duration_ms"] = round((time.time() - start) * 1000, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description="SQLite database maintenance")
    parser.add_argument("--db", help="Specific database file to maintain")
    parser.add_argument("--check-only", action="store_true", help="Only run integrity checks")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.db:
        targets = [args.db]
    else:
        targets = DATABASES

    results = []
    for db_name in targets:
        db_path = DATA_DIR / db_name
        if not db_path.exists():
            logger.warning("Database not found: %s", db_path)
            continue
        result = maintain_database(db_path, check_only=args.check_only)
        results.append(result)

    # Summary
    print(f"\n{'Database':<30} {'Size':>10} {'Integrity':>12} {'Duration':>10}")
    print("-" * 66)
    for r in results:
        integrity = "OK" if r["integrity"] == "ok" else "FAIL"
        print(f"{r['database']:<30} {r['size_kb']:>8.1f} KB {integrity:>12} {r['duration_ms']:>8.1f}ms")

    failed = [r for r in results if r["integrity"] != "ok"]
    if failed:
        logger.error("%d database(s) failed integrity check", len(failed))
        return 1
    logger.info("All %d database(s) healthy", len(results))
    return 0


if __name__ == "__main__":
    exit(main())
