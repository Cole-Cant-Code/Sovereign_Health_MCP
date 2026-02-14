"""SQLite database management for the CIP Health data bank.

Handles connection lifecycle, schema creation, and migrations.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
-- One row per data collection event
CREATE TABLE IF NOT EXISTS health_snapshots (
    id                   TEXT PRIMARY KEY,
    timestamp            TEXT NOT NULL,
    source               TEXT NOT NULL,
    period               TEXT NOT NULL,

    -- Encrypted JSON blobs (raw health data)
    vitals_enc           TEXT,
    labs_enc             TEXT,
    activity_enc         TEXT,
    preventive_enc       TEXT,
    biometrics_enc       TEXT,

    -- Unencrypted computed signals (for indexed longitudinal queries)
    vital_stability      REAL,
    metabolic_balance    REAL,
    activity_recovery    REAL,
    preventive_readiness REAL,

    -- Mantic results
    friction_m_score     REAL,
    friction_detected    INTEGER,
    emergence_m_score    REAL,
    emergence_detected   INTEGER,
    emergence_window_type TEXT,

    provenance_json      TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Denormalized for "show me all LDL values over time" without decrypting every snapshot
CREATE TABLE IF NOT EXISTS lab_results (
    id          TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES health_snapshots(id),
    test_name   TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    status      TEXT,
    test_date   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Denormalized for time-series queries on individual vitals
CREATE TABLE IF NOT EXISTS vital_readings (
    id           TEXT PRIMARY KEY,
    snapshot_id  TEXT NOT NULL REFERENCES health_snapshots(id),
    metric       TEXT NOT NULL,
    value        REAL NOT NULL,
    reading_date TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Connector state tracking
CREATE TABLE IF NOT EXISTS data_sources (
    id           TEXT PRIMARY KEY,
    source_type  TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    connected_at TEXT,
    last_sync    TEXT,
    config_enc   TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_snapshots_source   ON health_snapshots(source);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts       ON health_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_labs_test_name     ON lab_results(test_name);
CREATE INDEX IF NOT EXISTS idx_labs_snapshot      ON lab_results(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_vitals_metric      ON vital_readings(metric);
CREATE INDEX IF NOT EXISTS idx_vitals_snapshot    ON vital_readings(snapshot_id);
"""

# ---------------------------------------------------------------------------
# V2: Audit log table (HIPAA compliance — access logging + LLM disclosure)
# ---------------------------------------------------------------------------

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    action          TEXT NOT NULL,
    tool_name       TEXT,
    tool_input_hash TEXT,
    privacy_mode    TEXT,
    llm_provider    TEXT,
    llm_disclosed   INTEGER DEFAULT 0,
    snapshot_id     TEXT,
    duration_ms     REAL,
    status          TEXT NOT NULL DEFAULT 'success',
    error_type      TEXT,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_tool      ON audit_log(tool_name);
"""


class DatabaseError(Exception):
    """Raised when database operations fail."""


class HealthDatabase:
    """SQLite database manager for CIP Health data bank.

    Supports both file-based and in-memory (`:memory:`) databases.
    In-memory mode is used for testing.

    Usage::

        db = HealthDatabase(":memory:")
        db.initialize()
        conn = db.connection
        # ... use connection ...
        db.close()
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialize database manager.

        Args:
            db_path: Path to SQLite file, or ":memory:" for in-memory DB.
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the active database connection.

        Raises:
            DatabaseError: If the database has not been initialized.
        """
        if self._conn is None:
            raise DatabaseError("Database not initialized. Call initialize() first.")
        return self._conn

    def initialize(self) -> None:
        """Create the database connection and ensure schema exists.

        For file-based databases, creates parent directories if needed.
        Idempotent: safe to call multiple times.
        """
        if self._conn is not None:
            return  # Already initialized

        if self._db_path != ":memory:":
            db_file = Path(self._db_path).expanduser()
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_file))
        else:
            self._conn = sqlite3.connect(":memory:")

        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._ensure_schema()
        logger.info("Health database initialized: %s", self._db_path)

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist and apply migrations."""
        conn = self.connection

        # V1: Core tables (always applied — CREATE IF NOT EXISTS is idempotent)
        conn.executescript(_SCHEMA_V1)

        # Check current version
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        current_version = row[0] if row[0] is not None else 0

        # V2: Audit log table
        if current_version < 2:
            conn.executescript(_SCHEMA_V2)
            logger.info("Applied schema migration V2: audit_log table")

        # Record schema version
        if current_version < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            logger.info(
                "Schema updated from version %d to %d", current_version, SCHEMA_VERSION
            )

    def get_schema_version(self) -> int:
        """Return the current schema version."""
        cursor = self.connection.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row[0] is not None else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("Health database closed")

    def __enter__(self) -> HealthDatabase:
        self.initialize()
        return self

    def __exit__(self, *args) -> None:
        self.close()
