"""Unit tests for the health signal translator.

Tests cover all 4 compute functions, the orchestrator, and domain constants.
"""

from __future__ import annotations

import pytest

from cip.domains.health.connectors.mock_data import (
    get_mock_activity_data,
    get_mock_biometrics,
    get_mock_lab_results,
    get_mock_preventive_care,
    get_mock_vitals_data,
)
from cip.domains.health.domain_logic.signal_models import (
    FALLBACK_GOOD_DEFAULT,
    FALLBACK_NO_DATA,
    FALLBACK_NO_LABS,
    FALLBACK_PARTIAL_DATA,
    HEALTH_WEIGHTS,
    LAYER_NAMES,
    HealthSignals,
)
from cip.domains.health.domain_logic.signal_translator import (
    compute_activity_recovery,
    compute_metabolic_balance,
    compute_preventive_readiness,
    compute_vital_stability,
    translate_health_to_mantic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vitals(rhr=68, systolic=122, diastolic=78, hrv=42, spo2=97.2, rhr_trend=0):
    return {
        "resting_heart_rate": {"current_bpm": rhr, "trend_30d": rhr_trend},
        "blood_pressure": {"systolic_avg": systolic, "diastolic_avg": diastolic},
        "hrv": {"avg_ms": hrv},
        "spo2": {"avg_pct": spo2},
    }


def _labs(glucose=95, hba1c=5.4, ldl=130, hdl=55, trig=140):
    labs = []
    if glucose is not None:
        labs.append({"test_name": "Fasting Glucose", "value": glucose})
    if hba1c is not None:
        labs.append({"test_name": "HbA1c", "value": hba1c})
    if ldl is not None:
        labs.append({"test_name": "LDL Cholesterol", "value": ldl})
    if hdl is not None:
        labs.append({"test_name": "HDL Cholesterol", "value": hdl})
    if trig is not None:
        labs.append({"test_name": "Triglycerides", "value": trig})
    return labs


def _biometrics(bmi=25.5, trend=-0.3):
    return {"bmi": bmi, "bmi_trend_90d": trend}


def _activity(sessions=3.5, consistency=75, sleep_hours=7.1, sleep_quality=72, recovery=65, strain="slightly_high"):
    return {
        "exercise": {"sessions_per_week": sessions, "consistency_pct": consistency},
        "sleep": {"avg_duration_hours": sleep_hours, "avg_quality_score": sleep_quality},
        "recovery": {"avg_recovery_score": recovery, "strain_balance": strain},
    }


def _preventive(screenings_current=2, screenings_total=4, vaxx_current=3, vaxx_total=3, adherence=92, active_rx=1):
    screenings = {}
    for i in range(screenings_total):
        status = "current" if i < screenings_current else "overdue"
        screenings[f"screening_{i}"] = {"status": status}
    vaccinations = {}
    for i in range(vaxx_total):
        status = "current" if i < vaxx_current else "overdue"
        vaccinations[f"vaxx_{i}"] = {"status": status}
    return {
        "screenings": screenings,
        "vaccinations": vaccinations,
        "medications": {"active_prescriptions": active_rx, "adherence_pct": adherence},
    }


# ===========================================================================
# Test: Vital Stability
# ===========================================================================

class TestVitalStability:
    def test_healthy_vitals_gives_high(self):
        signal, _ = compute_vital_stability(_vitals())
        assert signal > 0.6

    def test_hypertensive_bp_gives_low(self):
        signal, _ = compute_vital_stability(_vitals(systolic=160, diastolic=100))
        # BP signal is 0.0 at 160/100, but other sub-signals (HR, HRV, SpO2)
        # remain healthy — composite drops but stays above 0.5.
        # Verify meaningful penalty vs healthy baseline.
        healthy, _ = compute_vital_stability(_vitals())
        assert signal < healthy - 0.15  # significant penalty
        assert signal < 0.55

    def test_empty_vitals_returns_fallback(self):
        signal, details = compute_vital_stability({})
        assert signal == FALLBACK_NO_DATA
        assert "fallback" in details

    def test_low_hrv_penalizes_signal(self):
        low_hrv, _ = compute_vital_stability(_vitals(hrv=15))
        high_hrv, _ = compute_vital_stability(_vitals(hrv=50))
        assert high_hrv > low_hrv

    def test_signal_always_in_bounds(self):
        for rhr in [40, 55, 65, 80, 100, 120]:
            for systolic in [90, 120, 150, 180]:
                signal, _ = compute_vital_stability(
                    _vitals(rhr=rhr, systolic=systolic)
                )
                assert 0.0 <= signal <= 1.0, f"Out of bounds: {signal}"

    def test_monotonicity_resting_hr(self):
        """Signal should decrease as HR moves away from optimal (65)."""
        at_65, _ = compute_vital_stability(_vitals(rhr=65))
        at_85, _ = compute_vital_stability(_vitals(rhr=85))
        assert at_65 > at_85

    def test_spo2_below_95_penalizes(self):
        low, _ = compute_vital_stability(_vitals(spo2=93))
        high, _ = compute_vital_stability(_vitals(spo2=98))
        assert high > low

    def test_improving_hr_trend_bonus(self):
        improving, _ = compute_vital_stability(_vitals(rhr=70, rhr_trend=-3))
        worsening, _ = compute_vital_stability(_vitals(rhr=70, rhr_trend=5))
        assert improving > worsening


# ===========================================================================
# Test: Metabolic Balance
# ===========================================================================

class TestMetabolicBalance:
    def test_healthy_labs_and_bmi_gives_high(self):
        signal, _ = compute_metabolic_balance(_labs(glucose=85, ldl=70, hdl=60, trig=100), _biometrics(bmi=22))
        assert signal > 0.7

    def test_elevated_cholesterol_lowers_signal(self):
        signal, _ = compute_metabolic_balance(_labs(ldl=160), _biometrics())
        normal, _ = compute_metabolic_balance(_labs(ldl=70), _biometrics())
        assert normal > signal

    def test_no_labs_returns_fallback(self):
        signal, details = compute_metabolic_balance([], {})
        assert signal == FALLBACK_NO_LABS

    def test_no_biometrics_uses_partial_fallback(self):
        signal, details = compute_metabolic_balance(_labs(), {})
        assert 0.0 <= signal <= 1.0

    def test_high_glucose_lowers_signal(self):
        high, _ = compute_metabolic_balance(_labs(glucose=140), _biometrics())
        normal, _ = compute_metabolic_balance(_labs(glucose=85), _biometrics())
        assert normal > high

    def test_signal_always_in_bounds(self):
        for glucose in [70, 100, 140]:
            for ldl in [50, 100, 170]:
                signal, _ = compute_metabolic_balance(
                    _labs(glucose=glucose, ldl=ldl), _biometrics()
                )
                assert 0.0 <= signal <= 1.0

    def test_bmi_optimal_range_gives_high(self):
        optimal, _ = compute_metabolic_balance(_labs(), _biometrics(bmi=22))
        obese, _ = compute_metabolic_balance(_labs(), _biometrics(bmi=35))
        assert optimal > obese


# ===========================================================================
# Test: Activity & Recovery
# ===========================================================================

class TestActivityRecovery:
    def test_active_good_sleep_gives_high(self):
        signal, _ = compute_activity_recovery(
            _activity(sessions=4, sleep_hours=7.5, sleep_quality=80, recovery=80, strain="balanced")
        )
        assert signal > 0.7

    def test_sedentary_poor_sleep_gives_low(self):
        signal, _ = compute_activity_recovery(
            _activity(sessions=0, sleep_hours=5, sleep_quality=40, recovery=30, strain="high")
        )
        assert signal < 0.3

    def test_empty_activity_returns_fallback(self):
        signal, details = compute_activity_recovery({})
        assert signal == FALLBACK_NO_DATA

    def test_monotonicity_exercise_frequency(self):
        low, _ = compute_activity_recovery(_activity(sessions=1))
        high, _ = compute_activity_recovery(_activity(sessions=4))
        assert high > low

    def test_sleep_duration_sweet_spot(self):
        optimal, _ = compute_activity_recovery(_activity(sleep_hours=8))
        short, _ = compute_activity_recovery(_activity(sleep_hours=5))
        assert optimal > short

    def test_signal_always_in_bounds(self):
        for sessions in [0, 2, 5, 7]:
            for sleep in [4, 7, 10]:
                signal, _ = compute_activity_recovery(
                    _activity(sessions=sessions, sleep_hours=sleep)
                )
                assert 0.0 <= signal <= 1.0

    def test_high_strain_penalizes(self):
        high_strain, _ = compute_activity_recovery(_activity(strain="high"))
        balanced, _ = compute_activity_recovery(_activity(strain="balanced"))
        assert balanced > high_strain


# ===========================================================================
# Test: Preventive Readiness
# ===========================================================================

class TestPreventiveReadiness:
    def test_all_current_gives_high(self):
        signal, _ = compute_preventive_readiness(
            _preventive(screenings_current=4, screenings_total=4, vaxx_current=3, vaxx_total=3, adherence=95)
        )
        assert signal > 0.8

    def test_all_overdue_gives_low(self):
        signal, _ = compute_preventive_readiness(
            _preventive(screenings_current=0, screenings_total=4, vaxx_current=0, vaxx_total=3, adherence=30)
        )
        assert signal < 0.3

    def test_no_medications_uses_good_default(self):
        signal, details = compute_preventive_readiness(
            _preventive(active_rx=0)
        )
        assert details["medication_signal"] == round(FALLBACK_GOOD_DEFAULT, 4)

    def test_low_adherence_lowers_signal(self):
        low, _ = compute_preventive_readiness(_preventive(adherence=50))
        high, _ = compute_preventive_readiness(_preventive(adherence=95))
        assert high > low

    def test_empty_preventive_care_returns_fallback(self):
        signal, details = compute_preventive_readiness({})
        assert signal == FALLBACK_PARTIAL_DATA

    def test_signal_always_in_bounds(self):
        for sc in [0, 2, 4]:
            for vc in [0, 1, 3]:
                signal, _ = compute_preventive_readiness(
                    _preventive(screenings_current=sc, vaxx_current=vc)
                )
                assert 0.0 <= signal <= 1.0


# ===========================================================================
# Test: Orchestrator
# ===========================================================================

class TestTranslateOrchestrator:
    def test_returns_health_signals_type(self):
        result = translate_health_to_mantic(
            get_mock_vitals_data(),
            get_mock_lab_results(),
            get_mock_activity_data(),
            get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        assert isinstance(result, HealthSignals)

    def test_as_layer_values_matches_layer_names_order(self):
        result = translate_health_to_mantic(
            get_mock_vitals_data(),
            get_mock_lab_results(),
            get_mock_activity_data(),
            get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        values = result.as_layer_values()
        assert len(values) == len(LAYER_NAMES)

    def test_all_signals_in_bounds(self):
        result = translate_health_to_mantic(
            get_mock_vitals_data(),
            get_mock_lab_results(),
            get_mock_activity_data(),
            get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        for v in result.as_layer_values():
            assert 0.0 <= v <= 1.0

    def test_details_has_all_signals(self):
        result = translate_health_to_mantic(
            get_mock_vitals_data(),
            get_mock_lab_results(),
            get_mock_activity_data(),
            get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        for name in LAYER_NAMES:
            assert name in result.details

    def test_determinism(self):
        """100 identical calls produce identical output."""
        results = [
            translate_health_to_mantic(
                get_mock_vitals_data(),
                get_mock_lab_results(),
                get_mock_activity_data(),
                get_mock_preventive_care(),
                get_mock_biometrics(),
            ).as_layer_values()
            for _ in range(100)
        ]
        assert all(r == results[0] for r in results)

    def test_mock_data_golden_band(self):
        """Mock data should produce all signals in [0.3, 0.9] golden band."""
        result = translate_health_to_mantic(
            get_mock_vitals_data(),
            get_mock_lab_results(),
            get_mock_activity_data(),
            get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        for name, value in zip(LAYER_NAMES, result.as_layer_values()):
            assert 0.3 <= value <= 0.9, f"{name} = {value} outside golden band [0.3, 0.9]"


# ===========================================================================
# Test: Domain Constants
# ===========================================================================

class TestDomainConstants:
    def test_weights_sum_to_one(self):
        assert abs(sum(HEALTH_WEIGHTS) - 1.0) < 1e-9

    def test_layer_names_count_matches_weights(self):
        assert len(LAYER_NAMES) == len(HEALTH_WEIGHTS)

    def test_layer_names_are_unique(self):
        assert len(set(LAYER_NAMES)) == len(LAYER_NAMES)
