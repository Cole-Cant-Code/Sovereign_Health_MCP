"""Tests for HealthRepository — CRUD with in-memory SQLite."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from cip.core.storage.database import HealthDatabase
from cip.core.storage.encryption import FieldEncryptor
from cip.core.storage.models import DataSource, HealthSnapshot
from cip.core.storage.repository import HealthRepository, RepositoryError


@pytest.fixture
def db():
    database = HealthDatabase(":memory:")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def encryptor():
    return FieldEncryptor(Fernet.generate_key().decode())


@pytest.fixture
def repo(db, encryptor):
    return HealthRepository(db, encryptor)


def _make_snapshot(**overrides) -> HealthSnapshot:
    """Create a test snapshot with sensible defaults."""
    defaults = dict(
        id="",
        timestamp="2026-02-01T12:00:00Z",
        source="mock",
        period="last_30_days",
        vitals_data={"resting_heart_rate": {"current_bpm": 68}},
        labs_data=[
            {"test_name": "Fasting Glucose", "value": 95.0, "unit": "mg/dL",
             "status": "normal", "date": "2026-01-10"},
            {"test_name": "LDL Cholesterol", "value": 130.0, "unit": "mg/dL",
             "status": "above_optimal", "date": "2026-01-10"},
        ],
        activity_data={"exercise": {"sessions_per_week": 3.5}},
        preventive_data={"screenings": {}},
        biometrics_data={"bmi": 25.5},
        vital_stability=0.72,
        metabolic_balance=0.58,
        activity_recovery=0.65,
        preventive_readiness=0.50,
        friction_m_score=0.3842,
        friction_detected=False,
        emergence_m_score=0.6025,
        emergence_detected=False,
        emergence_window_type=None,
        provenance={"data_source": "mock", "connector_version": "0.1.0"},
    )
    defaults.update(overrides)
    return HealthSnapshot(**defaults)


class TestSaveAndRetrieve:
    def test_save_returns_id(self, repo):
        snap = _make_snapshot()
        sid = repo.save_snapshot(snap)
        assert isinstance(sid, str)
        assert len(sid) == 36  # UUID format

    def test_round_trip_preserves_data(self, repo):
        snap = _make_snapshot()
        sid = repo.save_snapshot(snap)
        loaded = repo.get_snapshot(sid)

        assert loaded is not None
        assert loaded.source == "mock"
        assert loaded.period == "last_30_days"
        assert loaded.vital_stability == 0.72
        assert loaded.metabolic_balance == 0.58
        assert loaded.friction_m_score == 0.3842

    def test_encrypted_fields_decrypted(self, repo):
        snap = _make_snapshot(
            vitals_data={"resting_heart_rate": {"current_bpm": 72}},
            biometrics_data={"bmi": 24.0},
        )
        sid = repo.save_snapshot(snap)
        loaded = repo.get_snapshot(sid)

        assert loaded.vitals_data == {"resting_heart_rate": {"current_bpm": 72}}
        assert loaded.biometrics_data == {"bmi": 24.0}

    def test_labs_data_round_trip(self, repo):
        labs = [{"test_name": "Glucose", "value": 95.0, "unit": "mg/dL"}]
        snap = _make_snapshot(labs_data=labs)
        sid = repo.save_snapshot(snap)
        loaded = repo.get_snapshot(sid)
        assert loaded.labs_data == labs

    def test_none_raw_data_handled(self, repo):
        snap = _make_snapshot(
            vitals_data=None,
            labs_data=None,
            activity_data=None,
            preventive_data=None,
            biometrics_data=None,
        )
        sid = repo.save_snapshot(snap)
        loaded = repo.get_snapshot(sid)
        assert loaded.vitals_data is None
        assert loaded.labs_data is None

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get_snapshot("nonexistent-id") is None

    def test_provenance_preserved(self, repo):
        snap = _make_snapshot(provenance={"source": "test", "version": "1.0"})
        sid = repo.save_snapshot(snap)
        loaded = repo.get_snapshot(sid)
        assert loaded.provenance == {"source": "test", "version": "1.0"}

    def test_explicit_id_used(self, repo):
        snap = _make_snapshot(id="my-custom-id")
        sid = repo.save_snapshot(snap)
        assert sid == "my-custom-id"


class TestGetSnapshots:
    def test_returns_newest_first(self, repo):
        repo.save_snapshot(_make_snapshot(timestamp="2026-01-01T00:00:00Z"))
        repo.save_snapshot(_make_snapshot(timestamp="2026-02-01T00:00:00Z"))
        repo.save_snapshot(_make_snapshot(timestamp="2026-01-15T00:00:00Z"))

        snapshots = repo.get_snapshots()
        timestamps = [s.timestamp for s in snapshots]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_filter_by_source(self, repo):
        repo.save_snapshot(_make_snapshot(source="apple_health"))
        repo.save_snapshot(_make_snapshot(source="manual"))
        repo.save_snapshot(_make_snapshot(source="apple_health"))

        results = repo.get_snapshots(source="apple_health")
        assert len(results) == 2
        assert all(s.source == "apple_health" for s in results)

    def test_filter_by_since(self, repo):
        repo.save_snapshot(_make_snapshot(timestamp="2026-01-01T00:00:00Z"))
        repo.save_snapshot(_make_snapshot(timestamp="2026-02-01T00:00:00Z"))

        results = repo.get_snapshots(since="2026-01-15T00:00:00Z")
        assert len(results) == 1
        assert results[0].timestamp == "2026-02-01T00:00:00Z"

    def test_limit_respected(self, repo):
        for i in range(5):
            repo.save_snapshot(_make_snapshot(timestamp=f"2026-01-0{i+1}T00:00:00Z"))
        results = repo.get_snapshots(limit=3)
        assert len(results) == 3

    def test_latest_snapshot(self, repo):
        repo.save_snapshot(_make_snapshot(timestamp="2026-01-01T00:00:00Z"))
        repo.save_snapshot(_make_snapshot(timestamp="2026-02-01T00:00:00Z"))
        latest = repo.get_latest_snapshot()
        assert latest is not None
        assert latest.timestamp == "2026-02-01T00:00:00Z"

    def test_latest_snapshot_empty_db(self, repo):
        assert repo.get_latest_snapshot() is None


class TestCountSnapshots:
    def test_empty_db(self, repo):
        assert repo.count_snapshots() == 0

    def test_after_inserts(self, repo):
        repo.save_snapshot(_make_snapshot())
        repo.save_snapshot(_make_snapshot())
        assert repo.count_snapshots() == 2


class TestSignalHistory:
    def test_returns_values_newest_first(self, repo):
        repo.save_snapshot(_make_snapshot(
            timestamp="2026-01-01T00:00:00Z", vital_stability=0.65
        ))
        repo.save_snapshot(_make_snapshot(
            timestamp="2026-02-01T00:00:00Z", vital_stability=0.72
        ))

        history = repo.get_signal_history("vital_stability")
        assert len(history) == 2
        assert history[0] == ("2026-02-01T00:00:00Z", 0.72)
        assert history[1] == ("2026-01-01T00:00:00Z", 0.65)

    def test_filters_by_since(self, repo):
        repo.save_snapshot(_make_snapshot(
            timestamp="2026-01-01T00:00:00Z", metabolic_balance=0.5
        ))
        repo.save_snapshot(_make_snapshot(
            timestamp="2026-02-01T00:00:00Z", metabolic_balance=0.6
        ))

        history = repo.get_signal_history(
            "metabolic_balance", since="2026-01-15T00:00:00Z"
        )
        assert len(history) == 1

    def test_invalid_signal_name_raises(self, repo):
        with pytest.raises(RepositoryError, match="Invalid signal name"):
            repo.get_signal_history("invalid_signal")

    def test_limit_respected(self, repo):
        for i in range(5):
            repo.save_snapshot(_make_snapshot(
                timestamp=f"2026-01-0{i+1}T00:00:00Z",
                activity_recovery=0.6 + i * 0.02,
            ))
        history = repo.get_signal_history("activity_recovery", limit=3)
        assert len(history) == 3


class TestLabHistory:
    def test_returns_lab_values_for_test(self, repo):
        repo.save_snapshot(_make_snapshot(
            labs_data=[
                {"test_name": "Fasting Glucose", "value": 95.0, "unit": "mg/dL",
                 "status": "normal", "date": "2026-01-10"},
            ]
        ))
        repo.save_snapshot(_make_snapshot(
            labs_data=[
                {"test_name": "Fasting Glucose", "value": 92.0, "unit": "mg/dL",
                 "status": "normal", "date": "2026-02-10"},
                {"test_name": "LDL Cholesterol", "value": 125.0, "unit": "mg/dL",
                 "status": "above_optimal", "date": "2026-02-10"},
            ]
        ))

        glucose_history = repo.get_lab_history("Fasting Glucose")
        assert len(glucose_history) == 2
        values = [r.value for r in glucose_history]
        assert 95.0 in values
        assert 92.0 in values

    def test_empty_for_unknown_test(self, repo):
        repo.save_snapshot(_make_snapshot())
        assert repo.get_lab_history("Unknown Test") == []


class TestVitalHistory:
    def test_denormalizes_resting_heart_rate(self, repo):
        repo.save_snapshot(_make_snapshot(
            vitals_data={
                "resting_heart_rate": {"current_bpm": 68},
                "blood_pressure": {"systolic_avg": 122, "diastolic_avg": 78},
                "hrv": {"avg_ms": 42},
                "spo2": {"avg_pct": 97.2},
            },
        ))

        hr_readings = repo.get_vital_history("resting_heart_rate")
        assert len(hr_readings) == 1
        assert hr_readings[0].value == 68

    def test_denormalizes_blood_pressure(self, repo):
        repo.save_snapshot(_make_snapshot(
            vitals_data={
                "blood_pressure": {"systolic_avg": 130, "diastolic_avg": 85},
            },
        ))

        sys_readings = repo.get_vital_history("systolic_bp")
        assert len(sys_readings) == 1
        assert sys_readings[0].value == 130

        dia_readings = repo.get_vital_history("diastolic_bp")
        assert len(dia_readings) == 1
        assert dia_readings[0].value == 85

    def test_empty_vitals_no_readings(self, repo):
        repo.save_snapshot(_make_snapshot(vitals_data=None))
        assert repo.get_vital_history("resting_heart_rate") == []


class TestDataSources:
    def test_upsert_and_retrieve(self, repo):
        source = DataSource(
            id="ds-1",
            source_type="apple_health",
            display_name="Apple Health",
            connected_at="2026-01-01T00:00:00Z",
            is_active=True,
        )
        repo.upsert_data_source(source)
        sources = repo.get_data_sources()
        assert len(sources) == 1
        assert sources[0].source_type == "apple_health"

    def test_upsert_updates_existing(self, repo):
        source = DataSource(id="ds-1", source_type="manual", display_name="Manual Entry")
        repo.upsert_data_source(source)

        updated = DataSource(
            id="ds-2", source_type="manual",
            display_name="Manual Entry v2",
            last_sync="2026-02-01T00:00:00Z",
        )
        repo.upsert_data_source(updated)

        sources = repo.get_data_sources()
        assert len(sources) == 1
        assert sources[0].display_name == "Manual Entry v2"

    def test_inactive_sources_filtered(self, repo):
        active = DataSource(id="ds-1", source_type="apple_health",
                            display_name="Apple", is_active=True)
        inactive = DataSource(id="ds-2", source_type="manual",
                              display_name="Manual", is_active=False)
        repo.upsert_data_source(active)
        repo.upsert_data_source(inactive)

        assert len(repo.get_data_sources(active_only=True)) == 1
        assert len(repo.get_data_sources(active_only=False)) == 2
