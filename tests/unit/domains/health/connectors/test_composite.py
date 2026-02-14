"""Tests for the CompositeHealthProvider."""

from __future__ import annotations

import asyncio

import pytest

from cip.domains.health.connectors.composite import CompositeHealthProvider
from cip.domains.health.connectors.providers import MockHealthDataProvider


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class EmptyProvider:
    """Provider that returns empty data for all methods."""

    async def get_vitals(self, period="last_30_days"):
        return {}

    async def get_lab_results(self):
        return []

    async def get_activity_data(self, period="last_30_days"):
        return {}

    async def get_preventive_care(self):
        return {}

    async def get_biometrics(self):
        return {}

    def is_connected(self):
        return True

    @property
    def data_source(self):
        return "empty"

    def get_provenance(self):
        return {"data_source": "empty"}


class TestPriorityOrdering:
    def test_first_provider_with_data_wins(self):
        mock = MockHealthDataProvider()
        empty = EmptyProvider()
        composite = CompositeHealthProvider([empty, mock])

        vitals = _run(composite.get_vitals())
        # Empty returns {}, so mock should win
        assert "resting_heart_rate" in vitals

    def test_first_provider_wins_if_has_data(self):
        mock = MockHealthDataProvider()
        composite = CompositeHealthProvider([mock, EmptyProvider()])

        vitals = _run(composite.get_vitals())
        assert "resting_heart_rate" in vitals

    def test_labs_priority(self):
        mock = MockHealthDataProvider()
        empty = EmptyProvider()
        composite = CompositeHealthProvider([empty, mock])

        labs = _run(composite.get_lab_results())
        assert len(labs) > 0  # Mock has lab data

    def test_all_empty_returns_empty(self):
        composite = CompositeHealthProvider([EmptyProvider(), EmptyProvider()])
        assert _run(composite.get_vitals()) == {}
        assert _run(composite.get_lab_results()) == []


class TestIsConnected:
    def test_connected_if_any_connected(self):
        composite = CompositeHealthProvider([EmptyProvider(), MockHealthDataProvider()])
        assert composite.is_connected()

    def test_not_connected_if_none_connected(self):
        mock = MockHealthDataProvider()
        # MockHealthDataProvider.is_connected() returns False
        composite = CompositeHealthProvider([mock])
        assert not composite.is_connected()


class TestDataSource:
    def test_returns_first_connected_source(self):
        empty = EmptyProvider()
        mock = MockHealthDataProvider()
        composite = CompositeHealthProvider([empty, mock])
        # Empty is connected, so its data_source is returned
        assert composite.data_source == "empty"

    def test_returns_last_if_none_connected(self):
        mock = MockHealthDataProvider()
        composite = CompositeHealthProvider([mock])
        assert composite.data_source == "mock"


class TestProvenance:
    def test_provenance_lists_active_sources(self):
        empty = EmptyProvider()
        mock = MockHealthDataProvider()
        composite = CompositeHealthProvider([empty, mock])
        prov = composite.get_provenance()
        assert "active_sources" in prov
        assert "empty" in prov["active_sources"]

    def test_provenance_shows_priority(self):
        empty = EmptyProvider()
        mock = MockHealthDataProvider()
        composite = CompositeHealthProvider([empty, mock])
        prov = composite.get_provenance()
        assert "empty > mock" in prov["data_source_note"]


class TestValidation:
    def test_empty_providers_raises(self):
        with pytest.raises(ValueError, match="At least one"):
            CompositeHealthProvider([])
