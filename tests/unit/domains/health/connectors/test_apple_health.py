"""Tests for Apple Health XML parser and provider."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from cip.domains.health.connectors.apple_health import AppleHealthProvider
from cip.domains.health.connectors.apple_health_parser import (
    AppleHealthParseError,
    aggregate_activity,
    aggregate_biometrics,
    aggregate_vitals,
    parse_apple_health_export,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Sample Apple Health XML with records from recent dates
_SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
]>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierHeartRate"
         sourceName="Apple Watch"
         unit="count/min"
         value="68"
         startDate="2026-02-01 08:00:00 -0500"
         endDate="2026-02-01 08:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierHeartRate"
         sourceName="Apple Watch"
         unit="count/min"
         value="72"
         startDate="2026-02-02 09:00:00 -0500"
         endDate="2026-02-02 09:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureSystolic"
         sourceName="Blood Pressure Monitor"
         unit="mmHg"
         value="120"
         startDate="2026-02-01 10:00:00 -0500"
         endDate="2026-02-01 10:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureDiastolic"
         sourceName="Blood Pressure Monitor"
         unit="mmHg"
         value="78"
         startDate="2026-02-01 10:00:00 -0500"
         endDate="2026-02-01 10:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
         sourceName="Apple Watch"
         unit="ms"
         value="45"
         startDate="2026-02-01 23:00:00 -0500"
         endDate="2026-02-01 23:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierOxygenSaturation"
         sourceName="Apple Watch"
         unit="%"
         value="0.97"
         startDate="2026-02-01 08:00:00 -0500"
         endDate="2026-02-01 08:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierStepCount"
         sourceName="iPhone"
         unit="count"
         value="4500"
         startDate="2026-02-01 06:00:00 -0500"
         endDate="2026-02-01 12:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierStepCount"
         sourceName="iPhone"
         unit="count"
         value="3700"
         startDate="2026-02-01 12:00:00 -0500"
         endDate="2026-02-01 18:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierBodyMass"
         sourceName="Smart Scale"
         unit="lb"
         value="178"
         startDate="2026-02-01 07:00:00 -0500"
         endDate="2026-02-01 07:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierHeight"
         sourceName="Manual"
         unit="in"
         value="70"
         startDate="2025-06-01 10:00:00 -0500"
         endDate="2025-06-01 10:00:00 -0500"/>
 <Record type="HKQuantityTypeIdentifierBodyFatPercentage"
         sourceName="Smart Scale"
         unit="%"
         value="0.22"
         startDate="2026-02-01 07:00:00 -0500"
         endDate="2026-02-01 07:00:00 -0500"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis"
         sourceName="Apple Watch"
         value="HKCategoryValueSleepAnalysisAsleepUnspecified"
         startDate="2026-02-01 23:00:00 -0500"
         endDate="2026-02-02 06:30:00 -0500"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning"
          duration="35.5"
          totalEnergyBurned="320"
          startDate="2026-02-01 17:00:00 -0500"
          endDate="2026-02-01 17:35:00 -0500"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeYoga"
          duration="45"
          totalEnergyBurned="150"
          startDate="2026-02-02 08:00:00 -0500"
          endDate="2026-02-02 08:45:00 -0500"/>
</HealthData>
"""


@pytest.fixture
def sample_xml_path(tmp_path):
    path = tmp_path / "export.xml"
    path.write_text(_SAMPLE_XML)
    return str(path)


class TestAppleHealthParser:
    def test_parses_heart_rate(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        hr_key = "HKQuantityTypeIdentifierHeartRate"
        assert hr_key in parsed
        assert len(parsed[hr_key]) == 2
        assert parsed[hr_key][0]["value"] == 68.0

    def test_parses_blood_pressure(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        assert "HKQuantityTypeIdentifierBloodPressureSystolic" in parsed
        assert "HKQuantityTypeIdentifierBloodPressureDiastolic" in parsed

    def test_parses_steps(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        steps_key = "HKQuantityTypeIdentifierStepCount"
        assert steps_key in parsed
        assert len(parsed[steps_key]) == 2

    def test_parses_workouts(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        assert "workouts" in parsed
        assert len(parsed["workouts"]) == 2

    def test_parses_sleep(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        assert "sleep" in parsed
        assert len(parsed["sleep"]) == 1
        assert parsed["sleep"][0]["duration_hours"] == pytest.approx(7.5, abs=0.1)

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(AppleHealthParseError, match="not found"):
            parse_apple_health_export(str(tmp_path / "missing.xml"))

    def test_invalid_xml_raises(self, tmp_path):
        bad = tmp_path / "bad.xml"
        bad.write_text("<broken>")
        with pytest.raises(AppleHealthParseError, match="Invalid XML"):
            parse_apple_health_export(str(bad))


class TestAggregateVitals:
    def test_aggregates_heart_rate(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        vitals = aggregate_vitals(parsed)
        assert "resting_heart_rate" in vitals
        assert vitals["resting_heart_rate"]["current_bpm"] == 70.0  # avg of 68, 72

    def test_aggregates_blood_pressure(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        vitals = aggregate_vitals(parsed)
        assert "blood_pressure" in vitals
        assert vitals["blood_pressure"]["systolic_avg"] == 120.0

    def test_aggregates_hrv(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        vitals = aggregate_vitals(parsed)
        assert "hrv" in vitals
        assert vitals["hrv"]["avg_ms"] == 45.0

    def test_aggregates_spo2(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        vitals = aggregate_vitals(parsed)
        assert "spo2" in vitals
        assert vitals["spo2"]["avg_pct"] == 97.0


class TestAggregateActivity:
    def test_aggregates_exercise(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        activity = aggregate_activity(parsed)
        assert "exercise" in activity
        assert activity["exercise"]["sessions_per_week"] > 0

    def test_aggregates_sleep(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        activity = aggregate_activity(parsed)
        assert "sleep" in activity
        assert activity["sleep"]["avg_duration_hours"] == pytest.approx(7.5, abs=0.1)

    def test_aggregates_steps(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_30_days")
        activity = aggregate_activity(parsed)
        assert "steps" in activity
        assert activity["steps"]["daily_avg"] == 8200  # 4500 + 3700 on same day


class TestAggregateBiometrics:
    def test_aggregates_weight(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_365_days")
        bio = aggregate_biometrics(parsed)
        assert "weight_lbs" in bio
        assert bio["weight_lbs"] == 178.0

    def test_aggregates_body_fat(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_365_days")
        bio = aggregate_biometrics(parsed)
        assert "body_fat_pct" in bio
        assert bio["body_fat_pct"] == 22.0

    def test_calculates_bmi_from_weight_height(self, sample_xml_path):
        parsed = parse_apple_health_export(sample_xml_path, "last_365_days")
        bio = aggregate_biometrics(parsed)
        assert "bmi" in bio
        expected_bmi = (178.0 / (70 ** 2)) * 703
        assert bio["bmi"] == pytest.approx(expected_bmi, abs=0.2)


class TestAppleHealthProvider:
    def test_is_connected_with_file(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        assert provider.is_connected()

    def test_not_connected_without_file(self):
        provider = AppleHealthProvider("/nonexistent/path.xml")
        assert not provider.is_connected()

    def test_data_source_is_apple_health(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        assert provider.data_source == "apple_health"

    def test_get_vitals_returns_data(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        vitals = _run(provider.get_vitals("last_30_days"))
        assert "resting_heart_rate" in vitals

    def test_get_lab_results_empty(self, sample_xml_path):
        """Apple Health doesn't export lab results."""
        provider = AppleHealthProvider(sample_xml_path)
        labs = _run(provider.get_lab_results())
        assert labs == []

    def test_get_activity_returns_data(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        activity = _run(provider.get_activity_data("last_30_days"))
        assert "exercise" in activity or "steps" in activity

    def test_get_biometrics_returns_data(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        bio = _run(provider.get_biometrics())
        assert "weight_lbs" in bio

    def test_provenance_includes_path(self, sample_xml_path):
        provider = AppleHealthProvider(sample_xml_path)
        prov = provider.get_provenance()
        assert prov["data_source"] == "apple_health"
        assert "export_path" in prov
