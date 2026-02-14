"""Tests for the ManualEntryProvider."""

from __future__ import annotations

import asyncio

import pytest

from cip.core.storage.models import HealthSnapshot
from cip.domains.health.connectors.manual_entry import ManualEntryProvider


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestManualEntryProvider:
    def test_empty_repo_returns_empty(self, health_repository):
        provider = ManualEntryProvider(health_repository)
        assert _run(provider.get_vitals()) == {}
        assert _run(provider.get_lab_results()) == []
        assert _run(provider.get_activity_data()) == {}
        assert _run(provider.get_preventive_care()) == {}
        assert _run(provider.get_biometrics()) == {}

    def test_returns_vitals_from_manual_snapshot(self, health_repository):
        vitals = {"resting_heart_rate": {"current_bpm": 72}}
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="manual",
            period="point_in_time", vitals_data=vitals,
        ))

        provider = ManualEntryProvider(health_repository)
        result = _run(provider.get_vitals())
        assert result == vitals

    def test_returns_labs_from_manual_snapshot(self, health_repository):
        labs = [{"test_name": "Glucose", "value": 95.0, "unit": "mg/dL"}]
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="manual",
            period="point_in_time", labs_data=labs,
        ))

        provider = ManualEntryProvider(health_repository)
        result = _run(provider.get_lab_results())
        assert result == labs

    def test_ignores_non_manual_snapshots(self, health_repository):
        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="mock",
            period="last_30_days",
            vitals_data={"resting_heart_rate": {"current_bpm": 68}},
        ))

        provider = ManualEntryProvider(health_repository)
        assert _run(provider.get_vitals()) == {}

    def test_is_connected_always_true(self, health_repository):
        provider = ManualEntryProvider(health_repository)
        assert provider.is_connected()

    def test_data_source_is_manual(self, health_repository):
        provider = ManualEntryProvider(health_repository)
        assert provider.data_source == "manual"

    def test_provenance_includes_count(self, health_repository):
        provider = ManualEntryProvider(health_repository)
        prov = provider.get_provenance()
        assert "0 snapshots" in prov["data_source_note"]

        health_repository.save_snapshot(HealthSnapshot(
            id="", timestamp="2026-02-01T00:00:00Z", source="manual",
            period="point_in_time",
        ))
        prov2 = provider.get_provenance()
        assert "1 snapshots" in prov2["data_source_note"]
