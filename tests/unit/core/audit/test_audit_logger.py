"""Tests for the AuditLogger and related utilities."""

from __future__ import annotations

import json
import time

import pytest

from cip.core.audit.logger import AuditEvent, AuditLogger, _hash_input
from cip.core.storage.database import HealthDatabase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_db():
    """In-memory database with V2 schema for audit tests."""
    db = HealthDatabase(":memory:")
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def audit_logger(audit_db):
    return AuditLogger(audit_db)


# ---------------------------------------------------------------------------
# _hash_input tests
# ---------------------------------------------------------------------------

class TestHashInput:
    def test_hashes_dict(self):
        h = _hash_input({"key": "value"})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_deterministic(self):
        data = {"a": 1, "b": 2}
        assert _hash_input(data) == _hash_input(data)

    def test_order_independent(self):
        """Canonical JSON sorts keys, so order doesn't matter."""
        h1 = _hash_input({"z": 1, "a": 2})
        h2 = _hash_input({"a": 2, "z": 1})
        assert h1 == h2

    def test_different_inputs_differ(self):
        assert _hash_input({"a": 1}) != _hash_input({"a": 2})

    def test_non_serializable_returns_empty(self):
        assert _hash_input(object()) == ""

    def test_none_returns_empty_string_or_hash(self):
        # None is valid JSON (null), so it should hash
        h = _hash_input(None)
        assert isinstance(h, str)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# AuditLogger.log_event / log_tool_call
# ---------------------------------------------------------------------------

class TestLogEvent:
    def test_log_event_returns_uuid(self, audit_logger):
        event = AuditEvent(action="tool_invocation", tool_name="test_tool")
        eid = audit_logger.log_event(event)
        assert isinstance(eid, str)
        assert len(eid) == 36  # UUID format

    def test_log_tool_call_convenience(self, audit_logger):
        eid = audit_logger.log_tool_call(
            tool_name="personal_health_signal",
            tool_input={"period": "last_30_days"},
            privacy_mode="strict",
            llm_provider="anthropic",
            llm_disclosed=True,
            duration_ms=150.5,
        )
        assert len(eid) == 36

    def test_logged_event_retrievable(self, audit_logger):
        audit_logger.log_tool_call(
            tool_name="test_tool",
            tool_input={"key": "val"},
            llm_disclosed=False,
        )
        events = audit_logger.get_events()
        assert len(events) == 1
        assert events[0]["tool_name"] == "test_tool"
        assert events[0]["action"] == "tool_invocation"
        assert events[0]["llm_disclosed"] == 0

    def test_llm_disclosed_stored_as_integer(self, audit_logger):
        audit_logger.log_tool_call(
            "test", llm_disclosed=True, llm_provider="anthropic",
        )
        events = audit_logger.get_events()
        assert events[0]["llm_disclosed"] == 1

    def test_tool_input_hash_stored(self, audit_logger):
        audit_logger.log_tool_call(
            "test",
            tool_input={"period": "last_30_days"},
        )
        events = audit_logger.get_events()
        assert events[0]["tool_input_hash"] is not None
        assert len(events[0]["tool_input_hash"]) == 64

    def test_metadata_json_stored(self, audit_logger):
        audit_logger.log_tool_call(
            "test",
            metadata={"extra_key": "extra_val"},
        )
        events = audit_logger.get_events()
        meta = json.loads(events[0]["metadata_json"])
        assert meta["extra_key"] == "extra_val"


# ---------------------------------------------------------------------------
# AuditLogger.log_data_delete
# ---------------------------------------------------------------------------

class TestLogDataDelete:
    def test_log_delete_event(self, audit_logger):
        eid = audit_logger.log_data_delete(
            tool_name="delete_health_snapshot",
            snapshot_id="snap-123",
            count=1,
        )
        assert len(eid) == 36

        events = audit_logger.get_events(action="data_delete")
        assert len(events) == 1
        assert events[0]["action"] == "data_delete"
        assert events[0]["snapshot_id"] == "snap-123"

        meta = json.loads(events[0]["metadata_json"])
        assert meta["records_deleted"] == 1


# ---------------------------------------------------------------------------
# AuditLogger.get_events (filtering)
# ---------------------------------------------------------------------------

class TestGetEvents:
    def test_filter_by_action(self, audit_logger):
        audit_logger.log_tool_call("tool_a")
        audit_logger.log_data_delete(tool_name="tool_b", count=5)
        audit_logger.log_tool_call("tool_c")

        invocations = audit_logger.get_events(action="tool_invocation")
        assert len(invocations) == 2

        deletes = audit_logger.get_events(action="data_delete")
        assert len(deletes) == 1

    def test_filter_by_tool_name(self, audit_logger):
        audit_logger.log_tool_call("alpha")
        audit_logger.log_tool_call("beta")
        audit_logger.log_tool_call("alpha")

        events = audit_logger.get_events(tool_name="alpha")
        assert len(events) == 2

    def test_limit_respected(self, audit_logger):
        for i in range(10):
            audit_logger.log_tool_call(f"tool_{i}")
        events = audit_logger.get_events(limit=3)
        assert len(events) == 3

    def test_newest_first(self, audit_logger):
        audit_logger.log_tool_call("first")
        # Tiny sleep to ensure different timestamps
        time.sleep(0.01)
        audit_logger.log_tool_call("second")

        events = audit_logger.get_events()
        assert len(events) == 2
        # Newest first
        assert events[0]["tool_name"] == "second"
        assert events[1]["tool_name"] == "first"


# ---------------------------------------------------------------------------
# AuditLogger.count_events / count_disclosures
# ---------------------------------------------------------------------------

class TestCounts:
    def test_count_events_empty(self, audit_logger):
        assert audit_logger.count_events() == 0

    def test_count_events_after_inserts(self, audit_logger):
        audit_logger.log_tool_call("a")
        audit_logger.log_tool_call("b")
        assert audit_logger.count_events() == 2

    def test_count_disclosures(self, audit_logger):
        audit_logger.log_tool_call("t1", llm_disclosed=True, llm_provider="anthropic")
        audit_logger.log_tool_call("t2", llm_disclosed=False)
        audit_logger.log_tool_call("t3", llm_disclosed=True, llm_provider="openai")

        assert audit_logger.count_disclosures() == 2

    def test_count_disclosures_with_since(self, audit_logger):
        audit_logger.log_tool_call("t1", llm_disclosed=True, llm_provider="anthropic")
        # All events have "now" timestamp, so filtering with a past "since" gets all
        assert audit_logger.count_disclosures(since="2020-01-01T00:00:00Z") == 1


# ---------------------------------------------------------------------------
# Schema V2 integration
# ---------------------------------------------------------------------------

class TestSchemaV2:
    def test_audit_log_table_exists(self, audit_db):
        cursor = audit_db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
        )
        assert cursor.fetchone() is not None

    def test_audit_log_indexes_exist(self, audit_db):
        cursor = audit_db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_audit_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_audit_timestamp" in indexes
        assert "idx_audit_action" in indexes
        assert "idx_audit_tool" in indexes

    def test_schema_version_is_2(self, audit_db):
        assert audit_db.get_schema_version() == 2
