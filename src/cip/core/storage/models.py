"""Data models for the health persistence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class HealthSnapshot:
    """A single point-in-time health data collection and analysis result.

    Raw health data (vitals, labs, etc.) is stored encrypted. Computed signal
    values (0-1 floats) are stored unencrypted for indexed longitudinal queries.
    """

    id: str
    timestamp: str  # ISO 8601
    source: str  # 'apple_health', 'manual', 'mock'
    period: str

    # Encrypted JSON blobs (raw health data) — stored encrypted at rest
    vitals_data: dict[str, Any] | None = None
    labs_data: list[dict[str, Any]] | None = None
    activity_data: dict[str, Any] | None = None
    preventive_data: dict[str, Any] | None = None
    biometrics_data: dict[str, Any] | None = None

    # Unencrypted computed signals (for indexed longitudinal queries)
    vital_stability: float | None = None
    metabolic_balance: float | None = None
    activity_recovery: float | None = None
    preventive_readiness: float | None = None

    # Mantic detection results
    friction_m_score: float | None = None
    friction_detected: bool = False
    emergence_m_score: float | None = None
    emergence_detected: bool = False
    emergence_window_type: str | None = None

    # Provenance
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def signal_values(self) -> dict[str, float | None]:
        """Return computed signal values as a dict."""
        return {
            "vital_stability": self.vital_stability,
            "metabolic_balance": self.metabolic_balance,
            "activity_recovery": self.activity_recovery,
            "preventive_readiness": self.preventive_readiness,
        }


@dataclass
class StoredLabResult:
    """A denormalized lab result for time-series queries."""

    id: str
    snapshot_id: str
    test_name: str
    value: float
    unit: str = ""
    status: str = ""
    test_date: str = ""
    created_at: str = ""


@dataclass
class StoredVitalReading:
    """A denormalized vital sign reading for time-series queries."""

    id: str
    snapshot_id: str
    metric: str  # e.g., 'resting_heart_rate', 'systolic_bp'
    value: float
    reading_date: str = ""
    created_at: str = ""


@dataclass
class DataSource:
    """Connector state tracking."""

    id: str
    source_type: str  # 'apple_health', 'manual', etc.
    display_name: str
    connected_at: str | None = None
    last_sync: str | None = None
    config_enc: str | None = None  # encrypted config blob
    is_active: bool = True
