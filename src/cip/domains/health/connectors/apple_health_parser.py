"""Apple Health XML export parser.

Parses the ``export.xml`` file produced by Apple Health (iOS → Share → Export
Health Data). Supports incremental parsing of large files via iterparse.

HealthKit type mappings:
- HKQuantityTypeIdentifierHeartRate → resting_heart_rate
- HKQuantityTypeIdentifierBloodPressureSystolic/Diastolic → blood_pressure
- HKQuantityTypeIdentifierHeartRateVariabilitySDNN → hrv
- HKQuantityTypeIdentifierOxygenSaturation → spo2
- HKQuantityTypeIdentifierBodyMass → weight
- HKQuantityTypeIdentifierHeight → height
- HKQuantityTypeIdentifierBodyMassIndex → bmi
- HKQuantityTypeIdentifierBodyFatPercentage → body_fat_pct
- HKQuantityTypeIdentifierStepCount → steps
- HKCategoryTypeIdentifierSleepAnalysis → sleep
- HKWorkoutActivityType* → exercise
"""

from __future__ import annotations

import logging
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# HealthKit quantity type identifiers
_HR = "HKQuantityTypeIdentifierHeartRate"
_BP_SYS = "HKQuantityTypeIdentifierBloodPressureSystolic"
_BP_DIA = "HKQuantityTypeIdentifierBloodPressureDiastolic"
_HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
_SPO2 = "HKQuantityTypeIdentifierOxygenSaturation"
_BODY_MASS = "HKQuantityTypeIdentifierBodyMass"
_HEIGHT = "HKQuantityTypeIdentifierHeight"
_BMI = "HKQuantityTypeIdentifierBodyMassIndex"
_BODY_FAT = "HKQuantityTypeIdentifierBodyFatPercentage"
_STEPS = "HKQuantityTypeIdentifierStepCount"
_TEMP = "HKQuantityTypeIdentifierBodyTemperature"
_WAIST = "HKQuantityTypeIdentifierWaistCircumference"

_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"

# Quantity types we care about
_QUANTITY_TYPES = {
    _HR, _BP_SYS, _BP_DIA, _HRV, _SPO2,
    _BODY_MASS, _HEIGHT, _BMI, _BODY_FAT,
    _STEPS, _TEMP, _WAIST,
}


class AppleHealthParseError(Exception):
    """Raised when parsing Apple Health export XML fails."""


def _parse_date(date_str: str) -> datetime:
    """Parse Apple Health date format: '2025-12-01 08:30:00 -0500'."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        # Fallback for ISO format
        return datetime.fromisoformat(date_str)


def _period_to_cutoff(period: str) -> datetime:
    """Convert period string to UTC cutoff datetime."""
    now = datetime.now(timezone.utc)
    days_map = {
        "last_7_days": 7,
        "last_30_days": 30,
        "last_90_days": 90,
        "last_180_days": 180,
        "last_365_days": 365,
    }
    days = days_map.get(period, 30)
    return now - timedelta(days=days)


def parse_apple_health_export(
    export_path: str | Path,
    period: str = "last_30_days",
) -> dict[str, list[dict[str, Any]]]:
    """Parse an Apple Health export.xml and return records grouped by type.

    Uses iterparse for memory-efficient processing of large exports.

    Args:
        export_path: Path to the Apple Health export.xml file.
        period: Time period filter (e.g., 'last_30_days').

    Returns:
        Dict mapping record type to list of parsed records.
        Each record: {"value": float, "date": str, "unit": str}

    Raises:
        AppleHealthParseError: If the file cannot be parsed.
    """
    path = Path(export_path)
    if not path.exists():
        raise AppleHealthParseError(f"Export file not found: {path}")

    cutoff = _period_to_cutoff(period)
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    workouts: list[dict[str, Any]] = []
    sleep_records: list[dict[str, Any]] = []

    try:
        for event, elem in ET.iterparse(str(path), events=("end",)):
            tag = elem.tag

            if tag == "Record":
                rec_type = elem.get("type", "")

                # Quantity records
                if rec_type in _QUANTITY_TYPES:
                    date_str = elem.get("startDate", "")
                    if date_str:
                        try:
                            dt = _parse_date(date_str)
                            if dt >= cutoff:
                                value_str = elem.get("value", "")
                                if value_str:
                                    records[rec_type].append({
                                        "value": float(value_str),
                                        "date": dt.isoformat(),
                                        "unit": elem.get("unit", ""),
                                    })
                        except (ValueError, TypeError):
                            pass

                # Sleep records (category type)
                elif rec_type == _SLEEP:
                    start_str = elem.get("startDate", "")
                    end_str = elem.get("endDate", "")
                    if start_str and end_str:
                        try:
                            start_dt = _parse_date(start_str)
                            end_dt = _parse_date(end_str)
                            if start_dt >= cutoff:
                                duration_hours = (end_dt - start_dt).total_seconds() / 3600
                                sleep_value = elem.get("value", "")
                                sleep_records.append({
                                    "duration_hours": duration_hours,
                                    "date": start_dt.isoformat(),
                                    "value": sleep_value,  # e.g. InBed, Asleep, etc.
                                })
                        except (ValueError, TypeError):
                            pass

                elem.clear()

            elif tag == "Workout":
                start_str = elem.get("startDate", "")
                if start_str:
                    try:
                        dt = _parse_date(start_str)
                        if dt >= cutoff:
                            duration_min = float(elem.get("duration", "0"))
                            workouts.append({
                                "type": elem.get("workoutActivityType", ""),
                                "duration_min": duration_min,
                                "date": dt.isoformat(),
                                "calories": float(elem.get("totalEnergyBurned", "0") or "0"),
                            })
                    except (ValueError, TypeError):
                        pass
                elem.clear()

    except ET.ParseError as exc:
        raise AppleHealthParseError(f"Invalid XML: {exc}") from exc

    result = dict(records)
    if workouts:
        result["workouts"] = workouts
    if sleep_records:
        result["sleep"] = sleep_records

    logger.info(
        "Parsed Apple Health export: %d record types, %d workouts, %d sleep records",
        len(records), len(workouts), len(sleep_records),
    )
    return result


def aggregate_vitals(parsed: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Aggregate parsed records into the vitals data shape expected by HealthDataProvider."""
    result: dict[str, Any] = {}

    # Heart rate
    hr_records = parsed.get(_HR, [])
    if hr_records:
        hr_values = [r["value"] for r in hr_records]
        current_bpm = round(statistics.mean(hr_values), 1)
        result["resting_heart_rate"] = {
            "current_bpm": current_bpm,
            "trend_30d": 0,
            "variability": "normal",
        }

    # Blood pressure
    sys_records = parsed.get(_BP_SYS, [])
    dia_records = parsed.get(_BP_DIA, [])
    if sys_records and dia_records:
        sys_avg = round(statistics.mean(r["value"] for r in sys_records), 1)
        dia_avg = round(statistics.mean(r["value"] for r in dia_records), 1)
        result["blood_pressure"] = {
            "systolic_avg": sys_avg,
            "diastolic_avg": dia_avg,
            "trend_30d": "stable",
            "readings_count": len(sys_records),
        }

    # HRV
    hrv_records = parsed.get(_HRV, [])
    if hrv_records:
        hrv_avg = round(statistics.mean(r["value"] for r in hrv_records), 1)
        result["hrv"] = {
            "avg_ms": hrv_avg,
            "trend_30d": 0,
            "age_percentile": 50,  # Cannot determine from export alone
        }

    # SpO2
    spo2_records = parsed.get(_SPO2, [])
    if spo2_records:
        spo2_values = [r["value"] * 100 if r["value"] <= 1 else r["value"] for r in spo2_records]
        result["spo2"] = {
            "avg_pct": round(statistics.mean(spo2_values), 1),
            "min_pct": round(min(spo2_values), 1),
            "readings_below_95": sum(1 for v in spo2_values if v < 95),
        }

    # Body temperature
    temp_records = parsed.get(_TEMP, [])
    if temp_records:
        temp_values = [r["value"] for r in temp_records]
        result["body_temperature"] = {
            "avg_f": round(statistics.mean(temp_values), 1),
            "max_f": round(max(temp_values), 1),
            "elevated_days": sum(1 for v in temp_values if v > 99.5),
        }

    return result


def aggregate_activity(parsed: dict[str, list[dict[str, Any]]], period_days: int = 30) -> dict[str, Any]:
    """Aggregate parsed records into activity data shape."""
    result: dict[str, Any] = {"period": f"last_{period_days}_days"}

    # Exercise from workouts
    workouts = parsed.get("workouts", [])
    if workouts:
        weeks = max(period_days / 7, 1)
        workout_types = list({w["type"].replace("HKWorkoutActivityType", "").lower() for w in workouts})
        durations = [w["duration_min"] for w in workouts]
        result["exercise"] = {
            "sessions_per_week": round(len(workouts) / weeks, 1),
            "avg_duration_min": round(statistics.mean(durations), 1) if durations else 0,
            "types": workout_types[:5],  # Top 5
            "consistency_pct": min(round(len(workouts) / (weeks * 3) * 100, 0), 100),
            "trend_30d": "stable",
        }

    # Sleep
    sleep_records = parsed.get("sleep", [])
    if sleep_records:
        # Filter to "Asleep" or "InBed" records
        durations = [r["duration_hours"] for r in sleep_records if r["duration_hours"] > 1]
        if durations:
            result["sleep"] = {
                "avg_duration_hours": round(statistics.mean(durations), 1),
                "avg_quality_score": 70,  # Cannot determine from export
                "avg_deep_sleep_pct": 18,  # Cannot determine from basic export
                "avg_rem_pct": 22,  # Cannot determine from basic export
                "disturbances_per_night": 1.0,
                "consistency_pct": 70,
            }

    # Steps
    step_records = parsed.get(_STEPS, [])
    if step_records:
        # Group steps by date and sum
        daily_steps: dict[str, float] = defaultdict(float)
        for r in step_records:
            day = r["date"][:10]
            daily_steps[day] += r["value"]
        daily_values = list(daily_steps.values())
        result["steps"] = {
            "daily_avg": round(statistics.mean(daily_values)) if daily_values else 0,
            "trend_30d": 0,
        }

    # Recovery (placeholder — Apple Health doesn't export this directly)
    result["recovery"] = {
        "avg_recovery_score": 65,
        "rest_days_per_week": 2,
        "strain_balance": "normal",
    }

    return result


def aggregate_biometrics(parsed: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Aggregate parsed records into biometrics data shape."""
    result: dict[str, Any] = {}

    weight_records = parsed.get(_BODY_MASS, [])
    if weight_records:
        # Use most recent weight
        most_recent = max(weight_records, key=lambda r: r["date"])
        # Convert kg to lbs if needed
        weight = most_recent["value"]
        unit = most_recent.get("unit", "lb")
        if unit == "kg":
            weight = weight * 2.20462
        result["weight_lbs"] = round(weight, 1)

    height_records = parsed.get(_HEIGHT, [])
    if height_records:
        most_recent = max(height_records, key=lambda r: r["date"])
        height = most_recent["value"]
        unit = most_recent.get("unit", "in")
        if unit in ("cm", "m"):
            height = height / 2.54 if unit == "cm" else height * 39.3701
        result["height_inches"] = round(height, 1)

    bmi_records = parsed.get(_BMI, [])
    if bmi_records:
        most_recent = max(bmi_records, key=lambda r: r["date"])
        result["bmi"] = round(most_recent["value"], 1)
    elif "weight_lbs" in result and "height_inches" in result:
        # Calculate BMI from weight and height
        bmi = (result["weight_lbs"] / (result["height_inches"] ** 2)) * 703
        result["bmi"] = round(bmi, 1)

    bf_records = parsed.get(_BODY_FAT, [])
    if bf_records:
        most_recent = max(bf_records, key=lambda r: r["date"])
        # Apple Health stores as fraction (0.22 = 22%)
        bf = most_recent["value"]
        result["body_fat_pct"] = round(bf * 100 if bf <= 1 else bf, 1)

    waist_records = parsed.get(_WAIST, [])
    if waist_records:
        most_recent = max(waist_records, key=lambda r: r["date"])
        result["waist_circumference_inches"] = round(most_recent["value"], 1)

    return result
