"""Tests for the database maintenance utility."""

import sqlite3

from scripts.db_maintenance import maintain_database


class TestMaintainDatabase:
    def test_full_maintenance(self, tmp_path):
        """VACUUM + ANALYZE on a valid database."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, data TEXT)")
        # Insert and delete rows to create reclaimable space
        for i in range(100):
            conn.execute("INSERT INTO t VALUES (?, ?)", (i, "x" * 200))
        conn.execute("DELETE FROM t WHERE id > 10")
        conn.commit()
        conn.close()

        result = maintain_database(db_path)
        assert result["integrity"] == "ok"
        assert result["vacuumed"] is True
        assert result["analyzed"] is True
        assert result["duration_ms"] >= 0

    def test_check_only(self, tmp_path):
        """Check-only mode should not vacuum or analyze."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        result = maintain_database(db_path, check_only=True)
        assert result["integrity"] == "ok"
        assert result["vacuumed"] is False
        assert result["analyzed"] is False

    def test_corrupt_database(self, tmp_path):
        """Corrupt database should report integrity failure."""
        db_path = tmp_path / "corrupt.db"
        # Write valid SQLite header but corrupt data
        db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84 + b"corrupt data")

        result = maintain_database(db_path)
        assert result["integrity"] != "ok"
        assert result["vacuumed"] is False
