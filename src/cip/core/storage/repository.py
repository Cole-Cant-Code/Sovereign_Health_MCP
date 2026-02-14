"""Health data repository — CRUD operations for the encrypted data bank.

The repository mediates between domain objects (HealthSnapshot, etc.) and
the SQLite database, using FieldEncryptor to encrypt/decrypt raw health data.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from cip.core.storage.database import HealthDatabase
from cip.core.storage.encryption import FieldEncryptor
from cip.core.storage.models import (
    DataSource,
    HealthSnapshot,
    StoredLabResult,
    StoredVitalReading,
)

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Raised when repository operations fail."""


class HealthRepository:
    """CRUD repository for encrypted health snapshots and denormalized data.

    Usage::

        db = HealthDatabase(":memory:")
        db.initialize()
        encryptor = FieldEncryptor(key="...")
        repo = HealthRepository(db, encryptor)

        snapshot_id = repo.save_snapshot(snapshot)
        history = repo.get_signal_history("vital_stability", limit=30)
    """

    def __init__(self, database: HealthDatabase, encryptor: FieldEncryptor) -> None:
        self._db = database
        self._enc = encryptor

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: HealthSnapshot) -> str:
        """Persist a health snapshot with encrypted raw data.

        Args:
            snapshot: The snapshot to save. If ``snapshot.id`` is empty,
                a UUID will be generated.

        Returns:
            The snapshot ID.
        """
        conn = self._db.connection
        sid = snapshot.id or self._new_id()
        now = snapshot.created_at or self._now_iso()

        conn.execute(
            """INSERT INTO health_snapshots (
                id, timestamp, source, period,
                vitals_enc, labs_enc, activity_enc, preventive_enc, biometrics_enc,
                vital_stability, metabolic_balance, activity_recovery, preventive_readiness,
                friction_m_score, friction_detected,
                emergence_m_score, emergence_detected, emergence_window_type,
                provenance_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                snapshot.timestamp,
                snapshot.source,
                snapshot.period,
                self._enc.encrypt(snapshot.vitals_data),
                self._enc.encrypt(snapshot.labs_data),
                self._enc.encrypt(snapshot.activity_data),
                self._enc.encrypt(snapshot.preventive_data),
                self._enc.encrypt(snapshot.biometrics_data),
                snapshot.vital_stability,
                snapshot.metabolic_balance,
                snapshot.activity_recovery,
                snapshot.preventive_readiness,
                snapshot.friction_m_score,
                int(snapshot.friction_detected) if snapshot.friction_detected else 0,
                snapshot.emergence_m_score,
                int(snapshot.emergence_detected) if snapshot.emergence_detected else 0,
                snapshot.emergence_window_type,
                json.dumps(snapshot.provenance, separators=(",", ":")),
                now,
            ),
        )

        # Denormalize lab results
        if snapshot.labs_data:
            for lab in snapshot.labs_data:
                conn.execute(
                    """INSERT INTO lab_results
                       (id, snapshot_id, test_name, value, unit, status, test_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._new_id(),
                        sid,
                        lab.get("test_name", ""),
                        lab.get("value"),
                        lab.get("unit", ""),
                        lab.get("status", ""),
                        lab.get("date", lab.get("test_date", "")),
                    ),
                )

        # Denormalize key vital readings
        if snapshot.vitals_data:
            self._denormalize_vitals(sid, snapshot.vitals_data, snapshot.timestamp)

        conn.commit()
        logger.info("Saved snapshot %s (source=%s, period=%s)", sid, snapshot.source, snapshot.period)
        return sid

    def _denormalize_vitals(
        self, snapshot_id: str, vitals: dict[str, Any], reading_date: str
    ) -> None:
        """Extract key vital readings for time-series queries."""
        conn = self._db.connection
        mappings: list[tuple[str, Any]] = []

        rhr = vitals.get("resting_heart_rate", {})
        if isinstance(rhr, dict) and rhr.get("current_bpm") is not None:
            mappings.append(("resting_heart_rate", rhr["current_bpm"]))

        bp = vitals.get("blood_pressure", {})
        if isinstance(bp, dict):
            if bp.get("systolic_avg") is not None:
                mappings.append(("systolic_bp", bp["systolic_avg"]))
            if bp.get("diastolic_avg") is not None:
                mappings.append(("diastolic_bp", bp["diastolic_avg"]))

        hrv = vitals.get("hrv", {})
        if isinstance(hrv, dict) and hrv.get("avg_ms") is not None:
            mappings.append(("hrv_ms", hrv["avg_ms"]))

        spo2 = vitals.get("spo2", {})
        if isinstance(spo2, dict) and spo2.get("avg_pct") is not None:
            mappings.append(("spo2_pct", spo2["avg_pct"]))

        for metric, value in mappings:
            conn.execute(
                """INSERT INTO vital_readings
                   (id, snapshot_id, metric, value, reading_date)
                   VALUES (?, ?, ?, ?, ?)""",
                (self._new_id(), snapshot_id, metric, value, reading_date),
            )

    def get_snapshot(self, snapshot_id: str) -> HealthSnapshot | None:
        """Retrieve a snapshot by ID, decrypting raw data fields.

        Returns:
            The decrypted snapshot, or None if not found.
        """
        conn = self._db.connection
        row = conn.execute(
            "SELECT * FROM health_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        if row is None:
            return None
        return self._row_to_snapshot(row)

    def get_snapshots(
        self,
        *,
        source: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[HealthSnapshot]:
        """Query snapshots with optional filters.

        Args:
            source: Filter by data source (e.g., 'apple_health', 'manual').
            since: ISO 8601 timestamp lower bound (inclusive).
            until: ISO 8601 timestamp upper bound (inclusive).
            limit: Maximum results to return.

        Returns:
            List of decrypted snapshots, newest first.
        """
        conn = self._db.connection
        conditions: list[str] = []
        params: list[Any] = []

        if source:
            conditions.append("source = ?")
            params.append(source)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = " AND ".join(conditions)
        query = "SELECT * FROM health_snapshots"
        if where:
            query += f" WHERE {where}"
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def get_latest_snapshot(self, source: str | None = None) -> HealthSnapshot | None:
        """Get the most recent snapshot, optionally filtered by source."""
        results = self.get_snapshots(source=source, limit=1)
        return results[0] if results else None

    def count_snapshots(self) -> int:
        """Return total number of stored snapshots."""
        conn = self._db.connection
        row = conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Signal history (unencrypted, indexed)
    # ------------------------------------------------------------------

    def get_signal_history(
        self,
        signal_name: str,
        *,
        since: str | None = None,
        limit: int = 90,
    ) -> list[tuple[str, float]]:
        """Get time-series of a computed signal value.

        Args:
            signal_name: One of 'vital_stability', 'metabolic_balance',
                'activity_recovery', 'preventive_readiness'.
            since: Optional ISO 8601 lower bound.
            limit: Maximum results.

        Returns:
            List of (timestamp, value) tuples, newest first.
        """
        valid_signals = {
            "vital_stability",
            "metabolic_balance",
            "activity_recovery",
            "preventive_readiness",
        }
        if signal_name not in valid_signals:
            raise RepositoryError(
                f"Invalid signal name: {signal_name!r}. Valid: {valid_signals}"
            )

        conditions = [f"{signal_name} IS NOT NULL"]
        params: list[Any] = []

        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        where = " AND ".join(conditions)
        # Column name is safe — validated above against known set
        query = f"SELECT timestamp, {signal_name} FROM health_snapshots WHERE {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._db.connection.execute(query, params).fetchall()
        return [(row[0], row[1]) for row in rows]

    # ------------------------------------------------------------------
    # Lab history (denormalized)
    # ------------------------------------------------------------------

    def get_lab_history(
        self,
        test_name: str,
        *,
        limit: int = 20,
    ) -> list[StoredLabResult]:
        """Get historical values for a specific lab test.

        Args:
            test_name: Lab test name (e.g., 'Fasting Glucose', 'LDL Cholesterol').
            limit: Maximum results.

        Returns:
            List of lab results, newest first.
        """
        rows = self._db.connection.execute(
            """SELECT id, snapshot_id, test_name, value, unit, status, test_date, created_at
               FROM lab_results WHERE test_name = ?
               ORDER BY test_date DESC, created_at DESC LIMIT ?""",
            (test_name, limit),
        ).fetchall()

        return [
            StoredLabResult(
                id=row[0],
                snapshot_id=row[1],
                test_name=row[2],
                value=row[3],
                unit=row[4] or "",
                status=row[5] or "",
                test_date=row[6] or "",
                created_at=row[7] or "",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Vital readings history (denormalized)
    # ------------------------------------------------------------------

    def get_vital_history(
        self,
        metric: str,
        *,
        limit: int = 30,
    ) -> list[StoredVitalReading]:
        """Get historical readings for a specific vital metric.

        Args:
            metric: Vital metric name (e.g., 'resting_heart_rate', 'systolic_bp').
            limit: Maximum results.

        Returns:
            List of vital readings, newest first.
        """
        rows = self._db.connection.execute(
            """SELECT id, snapshot_id, metric, value, reading_date, created_at
               FROM vital_readings WHERE metric = ?
               ORDER BY reading_date DESC, created_at DESC LIMIT ?""",
            (metric, limit),
        ).fetchall()

        return [
            StoredVitalReading(
                id=row[0],
                snapshot_id=row[1],
                metric=row[2],
                value=row[3],
                reading_date=row[4] or "",
                created_at=row[5] or "",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Deletion / data retention (HIPAA: right to deletion)
    # ------------------------------------------------------------------

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a single snapshot and its denormalized data.

        Args:
            snapshot_id: The snapshot to delete.

        Returns:
            True if a snapshot was found and deleted, False otherwise.
        """
        conn = self._db.connection
        row = conn.execute(
            "SELECT id FROM health_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return False

        # Delete denormalized data first (FK references)
        conn.execute("DELETE FROM lab_results WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM vital_readings WHERE snapshot_id = ?", (snapshot_id,))
        conn.execute("DELETE FROM health_snapshots WHERE id = ?", (snapshot_id,))
        conn.commit()
        logger.info("Deleted snapshot %s", snapshot_id)
        return True

    def purge_before(self, before_timestamp: str) -> int:
        """Delete all snapshots older than a given timestamp.

        Also removes associated lab_results and vital_readings.

        Args:
            before_timestamp: ISO 8601 timestamp. Snapshots with
                ``timestamp < before_timestamp`` are deleted.

        Returns:
            Number of snapshots deleted.
        """
        conn = self._db.connection

        # Find affected snapshot IDs
        rows = conn.execute(
            "SELECT id FROM health_snapshots WHERE timestamp < ?",
            (before_timestamp,),
        ).fetchall()
        snapshot_ids = [row[0] for row in rows]

        if not snapshot_ids:
            return 0

        placeholders = ",".join("?" for _ in snapshot_ids)
        conn.execute(
            f"DELETE FROM lab_results WHERE snapshot_id IN ({placeholders})",
            snapshot_ids,
        )
        conn.execute(
            f"DELETE FROM vital_readings WHERE snapshot_id IN ({placeholders})",
            snapshot_ids,
        )
        conn.execute(
            f"DELETE FROM health_snapshots WHERE id IN ({placeholders})",
            snapshot_ids,
        )
        conn.commit()
        logger.info("Purged %d snapshots older than %s", len(snapshot_ids), before_timestamp)
        return len(snapshot_ids)

    def purge_before_days(self, days: int) -> int:
        """Delete all snapshots older than N days.

        Convenience wrapper around :meth:`purge_before`.

        Args:
            days: Number of days. Snapshots older than ``now - days`` are deleted.

        Returns:
            Number of snapshots deleted.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.purge_before(cutoff)

    def delete_all_data(self) -> int:
        """Delete ALL health data — nuclear option.

        Removes all snapshots, lab results, vital readings, and data sources.

        Returns:
            Total number of snapshot rows deleted.
        """
        conn = self._db.connection
        count_row = conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()
        count = count_row[0]

        conn.execute("DELETE FROM lab_results")
        conn.execute("DELETE FROM vital_readings")
        conn.execute("DELETE FROM health_snapshots")
        conn.execute("DELETE FROM data_sources")
        conn.commit()
        logger.warning("Deleted ALL health data: %d snapshots removed", count)
        return count

    # ------------------------------------------------------------------
    # Data sources
    # ------------------------------------------------------------------

    def upsert_data_source(self, source: DataSource) -> None:
        """Insert or update a data source record."""
        conn = self._db.connection
        conn.execute(
            """INSERT INTO data_sources (id, source_type, display_name, connected_at, last_sync, config_enc, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_type) DO UPDATE SET
                   display_name = excluded.display_name,
                   last_sync = excluded.last_sync,
                   config_enc = excluded.config_enc,
                   is_active = excluded.is_active""",
            (
                source.id or self._new_id(),
                source.source_type,
                source.display_name,
                source.connected_at,
                source.last_sync,
                source.config_enc,
                int(source.is_active),
            ),
        )
        conn.commit()

    def get_data_sources(self, *, active_only: bool = True) -> list[DataSource]:
        """List registered data sources."""
        query = "SELECT * FROM data_sources"
        if active_only:
            query += " WHERE is_active = 1"
        rows = self._db.connection.execute(query).fetchall()
        return [
            DataSource(
                id=row["id"],
                source_type=row["source_type"],
                display_name=row["display_name"],
                connected_at=row["connected_at"],
                last_sync=row["last_sync"],
                config_enc=row["config_enc"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_snapshot(self, row: Any) -> HealthSnapshot:
        """Convert a database row to a HealthSnapshot with decrypted data."""
        provenance = {}
        if row["provenance_json"]:
            try:
                provenance = json.loads(row["provenance_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        return HealthSnapshot(
            id=row["id"],
            timestamp=row["timestamp"],
            source=row["source"],
            period=row["period"],
            vitals_data=self._enc.decrypt(row["vitals_enc"] or ""),
            labs_data=self._enc.decrypt(row["labs_enc"] or ""),
            activity_data=self._enc.decrypt(row["activity_enc"] or ""),
            preventive_data=self._enc.decrypt(row["preventive_enc"] or ""),
            biometrics_data=self._enc.decrypt(row["biometrics_enc"] or ""),
            vital_stability=row["vital_stability"],
            metabolic_balance=row["metabolic_balance"],
            activity_recovery=row["activity_recovery"],
            preventive_readiness=row["preventive_readiness"],
            friction_m_score=row["friction_m_score"],
            friction_detected=bool(row["friction_detected"]),
            emergence_m_score=row["emergence_m_score"],
            emergence_detected=bool(row["emergence_detected"]),
            emergence_window_type=row["emergence_window_type"],
            provenance=provenance,
            created_at=row["created_at"],
        )
