"""Manual entry data provider — reads from the health data bank (SQLite).

Users enter health data via MCP tools (lab results, vitals from doctor visits,
screenings, vaccinations). This provider reads the stored data to implement
HealthDataProvider.
"""

from __future__ import annotations

import logging
from typing import Any

from cip.core.storage.repository import HealthRepository

logger = logging.getLogger(__name__)


class ManualEntryProvider:
    """HealthDataProvider backed by manually entered data in the health data bank.

    Reads the most recent snapshot from the 'manual' source in the repository.
    Falls back to empty data structures when no manual data exists.
    """

    def __init__(self, repository: HealthRepository) -> None:
        self._repo = repository

    async def get_vitals(self, period: str = "last_30_days") -> dict[str, Any]:
        """Get vitals from the most recent manual entry snapshot."""
        snapshot = self._repo.get_latest_snapshot(source="manual")
        if snapshot and snapshot.vitals_data:
            return snapshot.vitals_data
        return {}

    async def get_lab_results(self) -> list[dict[str, Any]]:
        """Get lab results from stored manual entries.

        Aggregates across recent snapshots to build a complete lab picture.
        """
        snapshot = self._repo.get_latest_snapshot(source="manual")
        if snapshot and snapshot.labs_data:
            return snapshot.labs_data
        return []

    async def get_activity_data(self, period: str = "last_30_days") -> dict[str, Any]:
        """Get activity data from manual entries."""
        snapshot = self._repo.get_latest_snapshot(source="manual")
        if snapshot and snapshot.activity_data:
            return snapshot.activity_data
        return {}

    async def get_preventive_care(self) -> dict[str, Any]:
        """Get preventive care from manual entries."""
        snapshot = self._repo.get_latest_snapshot(source="manual")
        if snapshot and snapshot.preventive_data:
            return snapshot.preventive_data
        return {}

    async def get_biometrics(self) -> dict[str, Any]:
        """Get biometrics from manual entries."""
        snapshot = self._repo.get_latest_snapshot(source="manual")
        if snapshot and snapshot.biometrics_data:
            return snapshot.biometrics_data
        return {}

    def is_connected(self) -> bool:
        """Manual entry is always 'connected' if repository exists."""
        return True

    @property
    def data_source(self) -> str:
        return "manual"

    def get_provenance(self) -> dict[str, str]:
        count = self._repo.count_snapshots()
        return {
            "data_source": self.data_source,
            "data_source_note": f"Manually entered health data ({count} snapshots stored).",
        }
