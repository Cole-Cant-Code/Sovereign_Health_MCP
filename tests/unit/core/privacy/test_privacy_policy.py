"""Unit tests for the privacy policy module."""

from __future__ import annotations

import pytest

from cip.core.privacy.policy import _round_floats, build_llm_data_context


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

def _make_full_context() -> dict:
    """Create a realistic full_data_context for testing."""
    return {
        "period": "last_30_days",
        "resting_heart_rate": 68,
        "blood_pressure_systolic": 122,
        "blood_pressure_diastolic": 78,
        "hrv_ms": 42.5,
        "exercise_sessions_per_week": 3,
        "sleep_duration_hours": 7.2,
        "bmi": 24.1,
        "lab_count": 5,
        "signals": {
            "vital_stability": 0.7123,
            "metabolic_balance": 0.5567,
            "activity_recovery": 0.6512,
            "preventive_readiness": 0.4987,
        },
        "signal_details": {"some_detail": "value"},
        "mantic_summary": {
            "friction_level": "moderate",
            "emergence_window": False,
            "limiting_factor": "preventive_readiness",
            "dominant_layer": "vital_stability",
            "coherence": 0.72,
        },
        "mantic_raw": {
            "friction": {"m_score": 0.38, "alert": None},
            "emergence": {"m_score": 0.60, "window_detected": False},
        },
        "friction": {"m_score": 0.38, "detected": False},
        "emergence": {"m_score": 0.60, "detected": False},
        "data_source": "mock",
        "data_source_note": "Test data",
    }


# ---------------------------------------------------------------------------
# _round_floats tests
# ---------------------------------------------------------------------------

class TestRoundFloats:
    def test_rounds_float(self):
        assert _round_floats(3.14159, ndigits=2) == 3.14

    def test_rounds_nested_dict(self):
        result = _round_floats({"a": 1.2345, "b": {"c": 9.8765}}, ndigits=2)
        assert result == {"a": 1.23, "b": {"c": 9.88}}

    def test_rounds_list(self):
        result = _round_floats([1.111, 2.222, 3.333], ndigits=1)
        assert result == [1.1, 2.2, 3.3]

    def test_passes_through_non_floats(self):
        assert _round_floats("hello") == "hello"
        assert _round_floats(42) == 42
        assert _round_floats(None) is None

    def test_mixed_nested_structure(self):
        data = {"a": [1.999, "keep"], "b": 7}
        result = _round_floats(data, ndigits=1)
        assert result == {"a": [2.0, "keep"], "b": 7}


# ---------------------------------------------------------------------------
# build_llm_data_context — strict mode
# ---------------------------------------------------------------------------

class TestPrivacyStrict:
    def test_strict_minimizes_to_signals_mantic_provenance(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="strict",
            include_mantic_raw=False,
        )
        # Must include
        assert "signals" in result
        assert "mantic" in result
        assert "period" in result
        assert "provenance" in result

        # Must NOT include raw vitals
        assert "resting_heart_rate" not in result
        assert "blood_pressure" not in result
        assert "hrv_ms" not in result
        assert "sleep_duration_hours" not in result
        assert "exercise_sessions_per_week" not in result
        assert "bmi" not in result
        assert "lab_count" not in result

        # Must NOT include raw Mantic
        assert "mantic_raw" not in result

        # Must NOT include friction/emergence detail blocks
        assert "friction" not in result
        assert "emergence" not in result
        assert "signal_details" not in result

    def test_strict_rounds_signals(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="strict",
            include_mantic_raw=False,
        )
        for v in result["signals"].values():
            # Should be rounded to 4 decimal places (ndigits=4 in policy)
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# build_llm_data_context — standard mode
# ---------------------------------------------------------------------------

class TestPrivacyStandard:
    def test_standard_includes_selected_metrics(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="standard",
            include_mantic_raw=False,
        )
        # Base fields
        assert "signals" in result
        assert "mantic" in result
        assert "period" in result

        # Friendly vitals
        assert "resting_heart_rate_bpm" in result
        assert "blood_pressure" in result
        assert "hrv_ms" in result
        assert "sleep_duration_hours" in result
        assert "exercise_sessions_per_week" in result
        assert "bmi" in result
        assert "lab_count" in result

    def test_standard_rounds_to_2_decimals(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="standard",
            include_mantic_raw=False,
        )
        # Floats should be rounded to 2 decimal places
        for v in result["signals"].values():
            s = str(v)
            if "." in s:
                assert len(s.split(".")[1]) <= 2


# ---------------------------------------------------------------------------
# build_llm_data_context — explicit mode
# ---------------------------------------------------------------------------

class TestPrivacyExplicit:
    def test_explicit_passes_everything(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="explicit",
            include_mantic_raw=True,
        )
        # Should include everything
        assert "signals" in result
        assert "mantic_raw" in result
        assert "friction" in result
        assert "emergence" in result
        assert "signal_details" in result
        assert "resting_heart_rate" in result

    def test_explicit_strips_mantic_raw_when_disabled(self):
        ctx = _make_full_context()
        result = build_llm_data_context(
            full_data_context=ctx,
            privacy_mode="explicit",
            include_mantic_raw=False,
        )
        assert "mantic_raw" not in result
        # But other raw fields remain
        assert "friction" in result
        assert "resting_heart_rate" in result
