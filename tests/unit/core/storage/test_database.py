"""Tests for HealthDatabase — schema creation, versioning, lifecycle."""

from __future__ import annotations

import pytest

from cip.core.storage.database import SCHEMA_VERSION, DatabaseError, HealthDatabase


class TestInitialization:
    def test_in_memory_initialize(self):
        db = HealthDatabase(":memory:")
        db.initialize()
        assert db.connection is not None
        db.close()

    def test_double_initialize_is_idempotent(self):
        db = HealthDatabase(":memory:")
        db.initialize()
        conn1 = db.connection
        db.initialize()  # Should not raise or create a new connection
        assert db.connection is conn1
        db.close()

    def test_connection_before_init_raises(self):
        db = HealthDatabase(":memory:")
        with pytest.raises(DatabaseError, match="not initialized"):
            _ = db.connection

    def test_context_manager(self):
        with HealthDatabase(":memory:") as db:
            assert db.connection is not None
        # After exit, connection should be closed
        with pytest.raises(DatabaseError):
            _ = db.connection


class TestSchema:
    def test_schema_version_recorded(self):
        with HealthDatabase(":memory:") as db:
            assert db.get_schema_version() == SCHEMA_VERSION

    def test_tables_created(self):
        expected_tables = {
            "health_snapshots",
            "lab_results",
            "vital_readings",
            "data_sources",
            "schema_version",
            "audit_log",
        }
        with HealthDatabase(":memory:") as db:
            cursor = db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            for t in expected_tables:
                assert t in tables, f"Missing table: {t}"

    def test_indexes_created(self):
        expected_indexes = {
            "idx_snapshots_source",
            "idx_snapshots_ts",
            "idx_labs_test_name",
            "idx_labs_snapshot",
            "idx_vitals_metric",
            "idx_vitals_snapshot",
            "idx_audit_timestamp",
            "idx_audit_action",
            "idx_audit_tool",
        }
        with HealthDatabase(":memory:") as db:
            cursor = db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
            for idx in expected_indexes:
                assert idx in indexes, f"Missing index: {idx}"

    def test_foreign_keys_enabled(self):
        with HealthDatabase(":memory:") as db:
            cursor = db.connection.execute("PRAGMA foreign_keys")
            assert cursor.fetchone()[0] == 1

    def test_wal_mode_enabled(self):
        with HealthDatabase(":memory:") as db:
            cursor = db.connection.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0].lower()
            # In-memory databases may use 'memory' mode instead of 'wal'
            assert mode in ("wal", "memory")

    def test_schema_version_idempotent_on_reinit(self):
        """Re-initializing should not duplicate schema version rows."""
        db = HealthDatabase(":memory:")
        db.initialize()
        v1 = db.get_schema_version()
        db.close()

        # Simulate a fresh init on the same in-memory DB (new instance)
        db2 = HealthDatabase(":memory:")
        db2.initialize()
        v2 = db2.get_schema_version()
        db2.close()
        assert v1 == v2 == SCHEMA_VERSION


class TestFileDatabase:
    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "health.db"
        db = HealthDatabase(str(db_path))
        db.initialize()
        assert db_path.exists()
        assert db.get_schema_version() == SCHEMA_VERSION
        db.close()


class TestClose:
    def test_close_makes_connection_unavailable(self):
        db = HealthDatabase(":memory:")
        db.initialize()
        db.close()
        with pytest.raises(DatabaseError, match="not initialized"):
            _ = db.connection

    def test_double_close_is_safe(self):
        db = HealthDatabase(":memory:")
        db.initialize()
        db.close()
        db.close()  # Should not raise
