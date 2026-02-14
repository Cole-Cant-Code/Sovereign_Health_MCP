"""Concrete HealthDataProvider implementations."""

from __future__ import annotations

from typing import Any

from cip.domains.health.connectors.mock_data import (
    get_mock_activity_data,
    get_mock_biometrics,
    get_mock_lab_results,
    get_mock_preventive_care,
    get_mock_vitals_data,
)


class MockHealthDataProvider:
    """Uses mock data generators. Always available."""

    async def get_vitals(self, period: str = "last_30_days") -> dict[str, Any]:
        return get_mock_vitals_data(period)

    async def get_lab_results(self) -> list[dict[str, Any]]:
        return get_mock_lab_results()

    async def get_activity_data(self, period: str = "last_30_days") -> dict[str, Any]:
        return get_mock_activity_data(period)

    async def get_preventive_care(self) -> dict[str, Any]:
        return get_mock_preventive_care()

    async def get_biometrics(self) -> dict[str, Any]:
        return get_mock_biometrics()

    def is_connected(self) -> bool:
        return False

    @property
    def data_source(self) -> str:
        return "mock"

    def get_provenance(self) -> dict[str, str]:
        return {
            "data_source": self.data_source,
            "data_source_note": (
                "Using simulated health data. "
                "Connect a health data source for real measurements."
            ),
        }
