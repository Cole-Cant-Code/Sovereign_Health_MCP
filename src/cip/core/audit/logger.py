"""Audit logger — HIPAA-aligned access logging and LLM disclosure tracking.

Records every tool invocation, data access, and deletion event in a
PHI-free audit trail. Inspired by the HIPAA compliance project's
``mcp_audit_event.json`` schema, adapted for a personal health MCP:

* ``tool_input_hash`` — SHA-256 of canonical JSON (no raw PHI in logs).
* ``llm_disclosed``  — boolean tracking whether health data left the device.
* ``privacy_mode``   — records which filter was active (implicit consent).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cip.core.storage.database import HealthDatabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input hashing (ported from HIPAA project's audit_middleware pattern)
# ---------------------------------------------------------------------------

def _hash_input(data: Any) -> str:
    """SHA-256 hash of canonical JSON — no PHI stored in audit logs.

    Args:
        data: Tool input to hash. Must be JSON-serializable.

    Returns:
        Hex-encoded SHA-256 digest, or empty string on failure.
    """
    try:
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# AuditEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class AuditEvent:
    """A single audit log entry."""

    action: str                          # 'tool_invocation' | 'data_access' | 'data_delete'
    tool_name: str = ""
    tool_input_hash: str = ""
    privacy_mode: str | None = None      # 'strict' | 'standard' | 'explicit'
    llm_provider: str | None = None      # 'anthropic' | 'openai' | 'mock'
    llm_disclosed: bool = False          # True if health data was sent to external LLM
    snapshot_id: str | None = None
    duration_ms: float | None = None
    status: str = "success"              # 'success' | 'failure'
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

class AuditLogger:
    """Records audit events to the ``audit_log`` SQLite table.

    Thread-safe via SQLite's internal locking. All writes are committed
    immediately so no audit entry is lost on crash.

    Usage::

        audit = AuditLogger(health_db)
        event_id = audit.log_tool_call(
            tool_name="personal_health_signal",
            tool_input={"period": "last_30_days"},
            llm_disclosed=True,
            llm_provider="anthropic",
            privacy_mode="strict",
        )
    """

    def __init__(self, database: HealthDatabase) -> None:
        self._db = database

    # ---------------------------------------------------------------
    # Write
    # ---------------------------------------------------------------

    def log_event(self, event: AuditEvent) -> str:
        """Insert an audit event and return its UUID.

        Args:
            event: Fully populated ``AuditEvent``.

        Returns:
            The generated event ID (UUID4 hex).
        """
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        metadata_json = (
            json.dumps(event.metadata, separators=(",", ":"))
            if event.metadata
            else None
        )

        try:
            conn = self._db.connection
            conn.execute(
                """INSERT INTO audit_log
                   (id, timestamp, action, tool_name, tool_input_hash,
                    privacy_mode, llm_provider, llm_disclosed, snapshot_id,
                    duration_ms, status, error_type, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    now,
                    event.action,
                    event.tool_name or None,
                    event.tool_input_hash or None,
                    event.privacy_mode,
                    event.llm_provider,
                    1 if event.llm_disclosed else 0,
                    event.snapshot_id,
                    event.duration_ms,
                    event.status,
                    event.error_type,
                    metadata_json,
                ),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to write audit event — event lost")
            return ""

        return event_id

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: Any = None,
        *,
        privacy_mode: str | None = None,
        llm_provider: str | None = None,
        llm_disclosed: bool = False,
        snapshot_id: str | None = None,
        duration_ms: float | None = None,
        status: str = "success",
        error_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Convenience wrapper for logging a tool invocation.

        Args:
            tool_name: Name of the MCP tool.
            tool_input: Tool input data (hashed, never stored raw).
            privacy_mode: Active privacy filter level.
            llm_provider: LLM provider used ('anthropic', 'openai', 'mock').
            llm_disclosed: Whether health data was sent to an external LLM.
            snapshot_id: ID of any persisted snapshot.
            duration_ms: Tool execution duration in milliseconds.
            status: 'success' or 'failure'.
            error_type: Exception class name on failure.
            metadata: Additional non-PHI metadata.

        Returns:
            The generated event ID.
        """
        return self.log_event(AuditEvent(
            action="tool_invocation",
            tool_name=tool_name,
            tool_input_hash=_hash_input(tool_input) if tool_input else "",
            privacy_mode=privacy_mode,
            llm_provider=llm_provider,
            llm_disclosed=llm_disclosed,
            snapshot_id=snapshot_id,
            duration_ms=duration_ms,
            status=status,
            error_type=error_type,
            metadata=metadata or {},
        ))

    def log_data_delete(
        self,
        *,
        tool_name: str = "",
        snapshot_id: str | None = None,
        count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Log a data deletion event.

        Args:
            tool_name: Tool that initiated the delete.
            snapshot_id: Specific snapshot deleted (if applicable).
            count: Number of records deleted.
            metadata: Additional context.

        Returns:
            The generated event ID.
        """
        return self.log_event(AuditEvent(
            action="data_delete",
            tool_name=tool_name,
            snapshot_id=snapshot_id,
            metadata={**(metadata or {}), "records_deleted": count},
        ))

    # ---------------------------------------------------------------
    # Read
    # ---------------------------------------------------------------

    def get_events(
        self,
        *,
        action: str | None = None,
        tool_name: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query audit events with optional filters.

        All fields are PHI-free by design (tool_input is hashed, no raw
        health data is stored in audit_log).

        Args:
            action: Filter by action type.
            tool_name: Filter by tool name.
            since: ISO 8601 timestamp lower bound.
            limit: Maximum events to return.

        Returns:
            List of event dicts, newest first.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if action:
            conditions.append("action = ?")
            params.append(action)
        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM audit_log{where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._db.connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_events(self, *, since: str | None = None) -> int:
        """Count total audit events, optionally since a timestamp."""
        if since:
            row = self._db.connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE timestamp >= ?", (since,)
            ).fetchone()
        else:
            row = self._db.connection.execute(
                "SELECT COUNT(*) FROM audit_log"
            ).fetchone()
        return row[0]

    def count_disclosures(self, *, since: str | None = None) -> int:
        """Count events where health data was sent to an external LLM.

        This answers: "How many times has my health data left this device?"

        Args:
            since: Optional ISO 8601 lower bound.

        Returns:
            Number of events with ``llm_disclosed = 1``.
        """
        if since:
            row = self._db.connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE llm_disclosed = 1 AND timestamp >= ?",
                (since,),
            ).fetchone()
        else:
            row = self._db.connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE llm_disclosed = 1"
            ).fetchone()
        return row[0]
