"""Mock health data generators for development and testing.

All mock data represents a median healthy adult — not in crisis, not perfectly
optimized. Signals derived from this data should land in [0.3, 0.9].
"""

from __future__ import annotations


def get_mock_vitals_data(period: str = "last_30_days") -> dict:
    """Return mock vital signs data."""
    return {
        "period": period,
        "resting_heart_rate": {
            "current_bpm": 68,
            "trend_30d": -2,  # bpm change over 30 days (negative = improving)
            "variability": "normal",
        },
        "blood_pressure": {
            "systolic_avg": 122,
            "diastolic_avg": 78,
            "trend_30d": "stable",
            "readings_count": 12,
        },
        "hrv": {
            "avg_ms": 42,
            "trend_30d": 3,  # ms change (positive = improving)
            "age_percentile": 55,
        },
        "spo2": {
            "avg_pct": 97.2,
            "min_pct": 94.0,
            "readings_below_95": 2,
        },
        "body_temperature": {
            "avg_f": 98.4,
            "max_f": 99.1,
            "elevated_days": 1,
        },
    }


def get_mock_lab_results() -> list[dict]:
    """Return mock lab test results."""
    return [
        {
            "test_name": "Fasting Glucose",
            "value": 95.0,
            "unit": "mg/dL",
            "reference_range": {"low": 70, "high": 100},
            "status": "normal",
            "date": "2026-01-10",
        },
        {
            "test_name": "HbA1c",
            "value": 5.4,
            "unit": "%",
            "reference_range": {"low": 4.0, "high": 5.7},
            "status": "normal",
            "date": "2026-01-10",
        },
        {
            "test_name": "Total Cholesterol",
            "value": 210.0,
            "unit": "mg/dL",
            "reference_range": {"low": 0, "high": 200},
            "status": "borderline_high",
            "date": "2026-01-10",
        },
        {
            "test_name": "LDL Cholesterol",
            "value": 130.0,
            "unit": "mg/dL",
            "reference_range": {"low": 0, "high": 100},
            "status": "above_optimal",
            "date": "2026-01-10",
        },
        {
            "test_name": "HDL Cholesterol",
            "value": 55.0,
            "unit": "mg/dL",
            "reference_range": {"low": 40, "high": 999},
            "status": "normal",
            "date": "2026-01-10",
        },
        {
            "test_name": "Triglycerides",
            "value": 140.0,
            "unit": "mg/dL",
            "reference_range": {"low": 0, "high": 150},
            "status": "normal",
            "date": "2026-01-10",
        },
    ]


def get_mock_activity_data(period: str = "last_30_days") -> dict:
    """Return mock activity and recovery data."""
    return {
        "period": period,
        "exercise": {
            "sessions_per_week": 3.5,
            "avg_duration_min": 42,
            "types": ["running", "strength", "yoga"],
            "consistency_pct": 75,
            "trend_30d": "stable",
        },
        "sleep": {
            "avg_duration_hours": 7.1,
            "avg_quality_score": 72,
            "avg_deep_sleep_pct": 18,
            "avg_rem_pct": 22,
            "disturbances_per_night": 1.3,
            "consistency_pct": 68,
        },
        "steps": {
            "daily_avg": 8200,
            "trend_30d": 300,
        },
        "recovery": {
            "avg_recovery_score": 65,
            "rest_days_per_week": 2,
            "strain_balance": "slightly_high",
        },
    }


def get_mock_preventive_care() -> dict:
    """Return mock preventive care status."""
    return {
        "screenings": {
            "annual_physical": {"last_date": "2025-08-15", "status": "current"},
            "dental_cleaning": {"last_date": "2025-11-01", "status": "current"},
            "eye_exam": {"last_date": "2024-06-20", "status": "overdue"},
            "dermatology_screen": {"last_date": None, "status": "never_done"},
        },
        "vaccinations": {
            "flu_shot": {"last_date": "2025-10-01", "status": "current"},
            "covid_booster": {"last_date": "2025-09-15", "status": "current"},
            "tdap": {"last_date": "2020-03-01", "status": "current"},
        },
        "medications": {
            "active_prescriptions": 1,
            "adherence_pct": 92,
            "refills_on_time": True,
        },
        "chronic_conditions": [],
    }


def get_mock_biometrics() -> dict:
    """Return mock body measurements."""
    return {
        "weight_lbs": 178.0,
        "height_inches": 70,
        "bmi": 25.5,
        "bmi_trend_90d": -0.3,
        "body_fat_pct": 22.0,
        "waist_circumference_inches": 34.5,
    }
