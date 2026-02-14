"""Health data connectors — abstraction layer for health data retrieval."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HealthDataProvider(Protocol):
    """Abstract interface for personal health data retrieval.

    Tools call these methods without knowing whether data comes from
    IoT devices, manual entry, clinical records, or mock generators.
    """

    async def get_vitals(self, period: str = "last_30_days") -> dict[str, Any]:
        """Vital signs: heart rate, blood pressure, HRV, SpO2."""
        ...

    async def get_lab_results(self) -> list[dict[str, Any]]:
        """Lab test results: blood glucose, cholesterol, CBC, etc."""
        ...

    async def get_activity_data(self, period: str = "last_30_days") -> dict[str, Any]:
        """Activity and recovery: exercise sessions, sleep, steps."""
        ...

    async def get_preventive_care(self) -> dict[str, Any]:
        """Preventive care status: screenings, vaccinations, medications."""
        ...

    async def get_biometrics(self) -> dict[str, Any]:
        """Body measurements: weight, BMI, body fat, height."""
        ...

    def is_connected(self) -> bool:
        """Whether real health data is available."""
        ...

    @property
    def data_source(self) -> str:
        """Label for the active data source: 'apple_health', 'manual', or 'mock'."""
        ...

    def get_provenance(self) -> dict[str, str]:
        """Return provenance metadata suitable for merging into data_context."""
        ...
