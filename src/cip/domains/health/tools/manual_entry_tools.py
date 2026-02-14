"""MCP tools for manual health data entry.

These tools allow users to enter health data that wearables can't capture:
lab results, vitals from doctor visits, preventive screenings, vaccinations.
Data is persisted to the encrypted health data bank.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.storage.repository import HealthRepository

from cip.core.storage.models import HealthSnapshot

logger = logging.getLogger(__name__)


def register_manual_entry_tools(
    mcp: FastMCP,
    repository: HealthRepository,
) -> None:
    """Register manual health data entry tools on the MCP server."""

    @mcp.tool
    async def enter_lab_result(
        ctx: Context,
        test_name: str,
        value: float,
        unit: str = "",
        test_date: str = "",
        status: str = "",
        notes: str = "",
    ) -> str:
        """Record a lab test result in your health data bank.

        Args:
            test_name: Name of the lab test (e.g., 'Fasting Glucose', 'LDL Cholesterol').
            value: Numeric test result value.
            unit: Unit of measurement (e.g., 'mg/dL', '%').
            test_date: Date of the test (ISO 8601, e.g., '2026-01-15'). Defaults to today.
            status: Result status (e.g., 'normal', 'borderline_high', 'above_optimal').
            notes: Optional notes about the result.
        """
        if not test_date:
            test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lab_entry = {
            "test_name": test_name,
            "value": value,
            "unit": unit,
            "status": status,
            "date": test_date,
        }
        if notes:
            lab_entry["notes"] = notes

        snapshot = HealthSnapshot(
            id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="manual",
            period="point_in_time",
            labs_data=[lab_entry],
        )
        sid = repository.save_snapshot(snapshot)
        logger.info("Manual lab entry saved: %s = %s %s (snapshot %s)", test_name, value, unit, sid)
        return json.dumps({
            "status": "saved",
            "snapshot_id": sid,
            "test_name": test_name,
            "value": value,
            "unit": unit,
            "test_date": test_date,
        })

    @mcp.tool
    async def enter_vitals(
        ctx: Context,
        resting_heart_rate: float | None = None,
        systolic_bp: float | None = None,
        diastolic_bp: float | None = None,
        hrv_ms: float | None = None,
        spo2_pct: float | None = None,
        body_temperature_f: float | None = None,
        reading_date: str = "",
    ) -> str:
        """Record vital signs from a doctor visit or home measurement.

        Args:
            resting_heart_rate: Resting heart rate in BPM.
            systolic_bp: Systolic blood pressure (top number).
            diastolic_bp: Diastolic blood pressure (bottom number).
            hrv_ms: Heart rate variability in milliseconds.
            spo2_pct: Blood oxygen saturation percentage.
            body_temperature_f: Body temperature in Fahrenheit.
            reading_date: Date of the reading (ISO 8601). Defaults to today.
        """
        if not reading_date:
            reading_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        vitals: dict = {}
        if resting_heart_rate is not None:
            vitals["resting_heart_rate"] = {"current_bpm": resting_heart_rate}
        if systolic_bp is not None or diastolic_bp is not None:
            vitals["blood_pressure"] = {}
            if systolic_bp is not None:
                vitals["blood_pressure"]["systolic_avg"] = systolic_bp
            if diastolic_bp is not None:
                vitals["blood_pressure"]["diastolic_avg"] = diastolic_bp
        if hrv_ms is not None:
            vitals["hrv"] = {"avg_ms": hrv_ms}
        if spo2_pct is not None:
            vitals["spo2"] = {"avg_pct": spo2_pct}
        if body_temperature_f is not None:
            vitals["body_temperature"] = {"avg_f": body_temperature_f}

        if not vitals:
            return json.dumps({"status": "error", "message": "No vitals provided"})

        snapshot = HealthSnapshot(
            id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="manual",
            period="point_in_time",
            vitals_data=vitals,
        )
        sid = repository.save_snapshot(snapshot)
        recorded = list(vitals.keys())
        logger.info("Manual vitals entry saved: %s (snapshot %s)", recorded, sid)
        return json.dumps({
            "status": "saved",
            "snapshot_id": sid,
            "recorded_vitals": recorded,
            "reading_date": reading_date,
        })

    @mcp.tool
    async def enter_screening(
        ctx: Context,
        screening_name: str,
        date: str,
        status: str = "current",
        notes: str = "",
    ) -> str:
        """Record a preventive screening (annual physical, dental, eye exam, etc.).

        Args:
            screening_name: Name of the screening (e.g., 'annual_physical', 'dental_cleaning').
            date: Date of the screening (ISO 8601, e.g., '2026-01-15').
            status: Status (e.g., 'current', 'overdue', 'scheduled').
            notes: Optional notes about the screening.
        """
        preventive = {
            "screenings": {
                screening_name: {
                    "last_date": date,
                    "status": status,
                }
            }
        }
        if notes:
            preventive["screenings"][screening_name]["notes"] = notes

        snapshot = HealthSnapshot(
            id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="manual",
            period="point_in_time",
            preventive_data=preventive,
        )
        sid = repository.save_snapshot(snapshot)
        logger.info("Manual screening entry saved: %s on %s (snapshot %s)", screening_name, date, sid)
        return json.dumps({
            "status": "saved",
            "snapshot_id": sid,
            "screening_name": screening_name,
            "date": date,
        })

    @mcp.tool
    async def enter_vaccination(
        ctx: Context,
        vaccine_name: str,
        date: str,
        status: str = "current",
    ) -> str:
        """Record a vaccination.

        Args:
            vaccine_name: Name of the vaccine (e.g., 'flu_shot', 'covid_booster', 'tdap').
            date: Date of the vaccination (ISO 8601, e.g., '2026-01-15').
            status: Status (e.g., 'current', 'overdue').
        """
        preventive = {
            "vaccinations": {
                vaccine_name: {
                    "last_date": date,
                    "status": status,
                }
            }
        }

        snapshot = HealthSnapshot(
            id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="manual",
            period="point_in_time",
            preventive_data=preventive,
        )
        sid = repository.save_snapshot(snapshot)
        logger.info("Manual vaccination entry saved: %s on %s (snapshot %s)", vaccine_name, date, sid)
        return json.dumps({
            "status": "saved",
            "snapshot_id": sid,
            "vaccine_name": vaccine_name,
            "date": date,
        })

    @mcp.tool
    async def list_entered_data(
        ctx: Context,
        data_type: str = "all",
        limit: int = 10,
    ) -> str:
        """List previously entered health data.

        Args:
            data_type: Type of data to list: 'labs', 'vitals', 'screenings', 'all'.
            limit: Maximum number of entries to return.
        """
        snapshots = repository.get_snapshots(source="manual", limit=limit)

        entries = []
        for snap in snapshots:
            entry: dict = {
                "snapshot_id": snap.id,
                "timestamp": snap.timestamp,
            }

            if data_type in ("all", "labs") and snap.labs_data:
                entry["labs"] = snap.labs_data
            if data_type in ("all", "vitals") and snap.vitals_data:
                entry["vitals"] = snap.vitals_data
            if data_type in ("all", "screenings") and snap.preventive_data:
                entry["preventive_care"] = snap.preventive_data

            if len(entry) > 2:  # Has data beyond id+timestamp
                entries.append(entry)

        return json.dumps({
            "status": "ok",
            "count": len(entries),
            "entries": entries,
        }, indent=2)
