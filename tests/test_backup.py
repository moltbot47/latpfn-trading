"""Tests for the database backup utility."""

import sqlite3

from scripts.backup import backup_database, list_backups, cleanup_old_backups, verify_backup


class TestBackupDatabase:
    def test_backup_creates_file(self, tmp_path, monkeypatch):
        """Backing up a real database should create a timestamped copy."""
        # Create a test database
        src = tmp_path / "test.db"
        conn = sqlite3.connect(str(src))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        monkeypatch.setattr("scripts.backup.DATA_DIR", tmp_path)
        monkeypatch.setattr("scripts.backup.BACKUP_DIR", backup_dir)

        result = backup_database("test.db")
        assert result is not None
        assert result.exists()
        assert "test_backup_" in result.name

        # Verify content is intact
        conn = sqlite3.connect(str(result))
        row = conn.execute("SELECT val FROM t WHERE id=1").fetchone()
        conn.close()
        assert row[0] == "hello"

    def test_backup_nonexistent_db_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.backup.DATA_DIR", tmp_path)
        monkeypatch.setattr("scripts.backup.BACKUP_DIR", tmp_path / "backups")
        result = backup_database("does_not_exist.db")
        assert result is None

    def test_verify_backup_valid(self, tmp_path):
        db_path = tmp_path / "valid.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()
        assert verify_backup(db_path) is True

    def test_verify_backup_corrupt(self, tmp_path):
        bad_path = tmp_path / "corrupt.db"
        bad_path.write_bytes(b"not a database")
        assert verify_backup(bad_path) is False


class TestListAndCleanup:
    def test_list_backups_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.backup.BACKUP_DIR", tmp_path / "empty")
        result = list_backups()
        assert result == []

    def test_list_backups_finds_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scripts.backup.BACKUP_DIR", tmp_path)
        # Create fake backup files
        (tmp_path / "funding_backup_20260301_070000.db").write_bytes(b"x" * 100)
        (tmp_path / "trade_log_backup_20260301_070000.db").write_bytes(b"x" * 200)

        result = list_backups()
        assert len(result) == 2
        assert result[0]["size_kb"] > 0

    def test_cleanup_removes_old_backups(self, tmp_path, monkeypatch):
        import time
        monkeypatch.setattr("scripts.backup.BACKUP_DIR", tmp_path)

        # Create a "backup" file and set its mtime to 10 days ago
        old_file = tmp_path / "funding_backup_20260220_070000.db"
        old_file.write_bytes(b"old")
        old_mtime = time.time() - (10 * 86400)
        import os
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Create a recent file
        new_file = tmp_path / "funding_backup_20260301_070000.db"
        new_file.write_bytes(b"new")

        cleanup_old_backups(retain_days=7)

        assert not old_file.exists()  # deleted
        assert new_file.exists()       # kept
