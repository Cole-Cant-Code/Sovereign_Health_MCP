"""Apple Health data provider — reads from exported Health data XML.

Users export via iOS Health app → Share → Export Health Data → produces
export.xml. This provider parses that XML to implement HealthDataProvider.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cip.domains.health.connectors.apple_health_parser import (
    AppleHealthParseError,
    aggregate_activity,
    aggregate_biometrics,
    aggregate_vitals,
    parse_apple_health_export,
)

logger = logging.getLogger(__name__)


class AppleHealthProvider:
    """HealthDataProvider backed by an Apple Health XML export.

    Usage::

        provider = AppleHealthProvider("/path/to/export.xml")
        if provider.is_connected():
            vitals = await provider.get_vitals("last_30_days")
    """

    def __init__(self, export_path: str) -> None:
        self._export_path = export_path
        self._cache: dict[str, dict[str, list]] = {}
        self._connected = bool(export_path) and Path(export_path).exists()

    async def get_vitals(self, period: str = "last_30_days") -> dict[str, Any]:
        """Parse vitals from Apple Health export."""
        parsed = self._parse(period)
        return aggregate_vitals(parsed)

    async def get_lab_results(self) -> list[dict[str, Any]]:
        """Apple Health doesn't export lab results — return empty list."""
        return []

    async def get_activity_data(self, period: str = "last_30_days") -> dict[str, Any]:
        """Parse activity data from Apple Health export."""
        days_map = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}
        parsed = self._parse(period)
        return aggregate_activity(parsed, period_days=days_map.get(period, 30))

    async def get_preventive_care(self) -> dict[str, Any]:
        """Apple Health doesn't export preventive care — return empty dict."""
        return {}

    async def get_biometrics(self) -> dict[str, Any]:
        """Parse biometrics from Apple Health export."""
        parsed = self._parse("last_365_days")  # Biometrics use latest reading
        return aggregate_biometrics(parsed)

    def is_connected(self) -> bool:
        """Check if the export file exists and is readable."""
        return self._connected

    @property
    def data_source(self) -> str:
        return "apple_health"

    def get_provenance(self) -> dict[str, str]:
        return {
            "data_source": self.data_source,
            "data_source_note": "Data from Apple Health export.",
            "export_path": self._export_path,
        }

    def _parse(self, period: str) -> dict[str, list]:
        """Parse export with caching per period."""
        if period not in self._cache:
            try:
                self._cache[period] = parse_apple_health_export(
                    self._export_path, period
                )
            except AppleHealthParseError:
                logger.exception("Failed to parse Apple Health export")
                return {}
        return self._cache[period]
