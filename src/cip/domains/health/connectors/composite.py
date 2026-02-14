"""Composite health data provider — merges multiple sources with priority.

Priority order: apple_health > manual > mock.
Each provider method queries sources in priority order, returning the first
non-empty result. This allows wearable data to take precedence over manual
entries, with mock data as the fallback.
"""

from __future__ import annotations

import logging
from typing import Any

from cip.domains.health.connectors import HealthDataProvider

logger = logging.getLogger(__name__)


class CompositeHealthProvider:
    """Merges multiple HealthDataProviders with priority ordering.

    Usage::

        composite = CompositeHealthProvider([
            apple_health_provider,  # Highest priority
            manual_provider,        # Middle priority
            mock_provider,          # Fallback
        ])
        vitals = await composite.get_vitals("last_30_days")
    """

    def __init__(self, providers: list[HealthDataProvider]) -> None:
        """Initialize with providers in priority order (highest first).

        Args:
            providers: Ordered list of HealthDataProviders. First provider
                with data wins for each method call.
        """
        if not providers:
            raise ValueError("At least one provider is required")
        self._providers = providers

    async def get_vitals(self, period: str = "last_30_days") -> dict[str, Any]:
        """Return vitals from the highest-priority provider with data."""
        for provider in self._providers:
            result = await provider.get_vitals(period)
            if result:
                return result
        return {}

    async def get_lab_results(self) -> list[dict[str, Any]]:
        """Return lab results from the highest-priority provider with data."""
        for provider in self._providers:
            result = await provider.get_lab_results()
            if result:
                return result
        return []

    async def get_activity_data(self, period: str = "last_30_days") -> dict[str, Any]:
        """Return activity data from the highest-priority provider with data."""
        for provider in self._providers:
            result = await provider.get_activity_data(period)
            if result:
                return result
        return {}

    async def get_preventive_care(self) -> dict[str, Any]:
        """Return preventive care from the highest-priority provider with data."""
        for provider in self._providers:
            result = await provider.get_preventive_care()
            if result:
                return result
        return {}

    async def get_biometrics(self) -> dict[str, Any]:
        """Return biometrics from the highest-priority provider with data."""
        for provider in self._providers:
            result = await provider.get_biometrics()
            if result:
                return result
        return {}

    def is_connected(self) -> bool:
        """True if any provider is connected."""
        return any(p.is_connected() for p in self._providers)

    @property
    def data_source(self) -> str:
        """Return the data source of the first connected provider."""
        for provider in self._providers:
            if provider.is_connected():
                return provider.data_source
        return self._providers[-1].data_source

    def get_provenance(self) -> dict[str, str]:
        """Return provenance info including all active sources."""
        active = [
            p.data_source for p in self._providers if p.is_connected()
        ]
        return {
            "data_source": self.data_source,
            "active_sources": ", ".join(active) if active else "none",
            "data_source_note": (
                f"Composite provider with {len(active)} active source(s). "
                f"Priority: {' > '.join(p.data_source for p in self._providers)}."
            ),
        }
