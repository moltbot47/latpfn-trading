#!/usr/bin/env python3
"""SQLite database backup utility.

Creates timestamped copies of all SQLite databases in data/.
Supports retention policy to auto-delete old backups.

Usage:
    python scripts/backup.py                    # Backup all databases
    python scripts/backup.py --db funding.db    # Backup specific database
    python scripts/backup.py --retain 7         # Keep only last 7 days
    python scripts/backup.py --list             # List existing backups
"""

import argparse
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"

# Databases to back up (name, priority)
DATABASES = [
    ("funding.db", "critical"),
    ("trade_log.db", "important"),
    ("turbo_analytics.db", "analytics"),
    ("polymarket_forecasts.db", "analytics"),
    ("broker_reports.db", "important"),
]

logger = logging.getLogger("backup")


def backup_database(db_name: str) -> Path | None:
    """Create a timestamped backup of a single SQLite database.

    Uses SQLite's online backup API for consistency (no corruption
    from concurrent writes with WAL mode).
    """
    src = DATA_DIR / db_name
    if not src.exists():
        logger.warning("Database not found: %s", src)
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = src.stem
    dest = BACKUP_DIR / f"{stem}_backup_{timestamp}.db"

    try:
        # Use SQLite online backup API for WAL-safe copies
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dest))
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        size_kb = dest.stat().st_size / 1024
        logger.info("Backed up %s → %s (%.1f KB)", db_name, dest.name, size_kb)
        return dest
    except Exception:
        logger.exception("Failed to backup %s", db_name)
        if dest.exists():
            dest.unlink()
        return None


def list_backups() -> list[dict]:
    """List all existing backups with size and age."""
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for f in sorted(BACKUP_DIR.glob("*_backup_*.db")):
        stat = f.stat()
        backups.append({
            "file": f.name,
            "size_kb": stat.st_size / 1024,
            "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        })
    return backups


def cleanup_old_backups(retain_days: int):
    """Delete backups older than retain_days."""
    if not BACKUP_DIR.exists():
        return

    cutoff = datetime.now(tz=timezone.utc).timestamp() - (retain_days * 86400)
    removed = 0
    for f in BACKUP_DIR.glob("*_backup_*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
            logger.info("Removed old backup: %s", f.name)

    if removed:
        logger.info("Cleaned up %d old backup(s) (retain=%d days)", removed, retain_days)


def verify_backup(backup_path: Path) -> bool:
    """Run SQLite integrity check on a backup file."""
    try:
        conn = sqlite3.connect(str(backup_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        return result[0] == "ok"
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Backup SQLite databases")
    parser.add_argument("--db", help="Specific database file to backup")
    parser.add_argument("--retain", type=int, help="Delete backups older than N days")
    parser.add_argument("--list", action="store_true", help="List existing backups")
    parser.add_argument("--verify", action="store_true", help="Verify backup integrity")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found.")
            return
        print(f"\n{'File':<50} {'Size':>10} {'Created':>22}")
        print("-" * 84)
        for b in backups:
            print(f"{b['file']:<50} {b['size_kb']:>8.1f} KB {b['created'].strftime('%Y-%m-%d %H:%M:%S'):>22}")
        print(f"\nTotal: {len(backups)} backup(s), {sum(b['size_kb'] for b in backups):.1f} KB")
        return

    # Determine which databases to back up
    if args.db:
        targets = [(args.db, "manual")]
    else:
        targets = DATABASES

    # Run backups
    results = []
    for db_name, priority in targets:
        dest = backup_database(db_name)
        if dest:
            if args.verify:
                ok = verify_backup(dest)
                status = "verified" if ok else "CORRUPT"
                logger.info("Integrity check %s: %s", dest.name, status)
            results.append(dest)

    # Cleanup old backups
    if args.retain:
        cleanup_old_backups(args.retain)

    logger.info("Backup complete: %d/%d successful", len(results), len(targets))


if __name__ == "__main__":
    main()
