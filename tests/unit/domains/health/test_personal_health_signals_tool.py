"""Unit tests for the personal_health_signal MCP tool."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from cip.core.server.app import create_app


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio required)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def client(mock_mantic_client):
    """Create an MCP client connected to the server with mock Mantic."""
    mcp = create_app(mantic_client_override=mock_mantic_client)
    return Client(mcp)


def test_tool_returns_content(client):
    """personal_health_signal should return non-empty LLM content."""
    async def _check():
        async with client:
            result = await client.call_tool("personal_health_signal", {})
            assert result
    _run(_check())


def test_tool_accepts_period(client):
    """Tool should accept a period parameter."""
    async def _check():
        async with client:
            result = await client.call_tool(
                "personal_health_signal", {"period": "last_90_days"}
            )
            assert result
    _run(_check())


def test_tool_appears_in_tool_list(client):
    """personal_health_signal should be discoverable."""
    async def _check():
        async with client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "personal_health_signal" in tool_names
    _run(_check())


def test_tool_accepts_tone_variant(client):
    """Tool should accept tone_variant parameter."""
    async def _check():
        async with client:
            result = await client.call_tool(
                "personal_health_signal", {"tone_variant": "clinical"}
            )
            assert result
    _run(_check())


def test_escalation_trigger_bypasses_llm_and_mantic():
    """High-risk vitals should return a deterministic escalation response."""

    class _HighBPMockProvider:
        async def get_vitals(self, period: str = "last_30_days"):
            return {
                "period": period,
                "resting_heart_rate": {"current_bpm": 70, "trend_30d": 0},
                "blood_pressure": {"systolic_avg": 190, "diastolic_avg": 95},
                "hrv": {"avg_ms": 35},
                "spo2": {"avg_pct": 97},
            }

        async def get_lab_results(self):
            return []

        async def get_activity_data(self, period: str = "last_30_days"):
            return {
                "period": period,
                "exercise": {"sessions_per_week": 2, "consistency_pct": 60},
                "sleep": {"avg_duration_hours": 7, "avg_quality_score": 60},
                "recovery": {"avg_recovery_score": 60, "strain_balance": "balanced"},
            }

        async def get_preventive_care(self):
            return {}

        async def get_biometrics(self):
            return {}

        def is_connected(self) -> bool:
            return True

        @property
        def data_source(self) -> str:
            return "mock"

        def get_provenance(self) -> dict[str, str]:
            return {"data_source": "mock", "data_source_note": "test"}

    class _FailingMantic:
        async def list_profiles(self):
            return {"profiles": ["consumer_health"]}

        async def detect_friction(self, *args, **kwargs):
            raise AssertionError("Mantic should not be called on escalation path")

        async def detect_emergence(self, *args, **kwargs):
            raise AssertionError("Mantic should not be called on escalation path")

    mcp = create_app(
        health_data_provider_override=_HighBPMockProvider(),
        mantic_client_override=_FailingMantic(),
    )
    client = Client(mcp)

    async def _check():
        async with client:
            result = await client.call_tool("personal_health_signal", {})
            text = str(result)
            assert "Safety escalation" in text
            assert "systolic" in text.lower()
            assert "Disclaimers" in text

    _run(_check())


def test_missing_data_does_not_trigger_all_signals_escalation():
    """Missing health data should NOT trigger the all-signals-low escalation.

    When a connector returns empty data, the signal translator produces fallback
    values (e.g. 0.3).  Those are pessimistic defaults, not real measurements.
    The safety gate should only fire on genuinely low real data, so the user gets
    a normal LLM analysis (not a scary escalation) when data is simply absent.
    """

    class _EmptyDataProvider:
        """Returns empty/missing data for everything — simulates a bare connection."""

        async def get_vitals(self, period: str = "last_30_days"):
            return {}

        async def get_lab_results(self):
            return []

        async def get_activity_data(self, period: str = "last_30_days"):
            return {}

        async def get_preventive_care(self):
            return {}

        async def get_biometrics(self):
            return {}

        def is_connected(self) -> bool:
            return True

        @property
        def data_source(self) -> str:
            return "mock"

        def get_provenance(self) -> dict[str, str]:
            return {"data_source": "mock", "data_source_note": "test"}

    class _PassthroughMantic:
        async def list_profiles(self):
            return {"profiles": ["consumer_health"]}

        async def detect_friction(self, *args, **kwargs):
            return {
                "status": "ok", "contract_version": "1.0.0",
                "domain_profile": {"domain_name": "consumer_health", "version": "1.0.0"},
                "mode": "friction", "layer_values": [0.3, 0.3, 0.3, 0.3],
                "result": {
                    "m_score": 0.3, "alert": None, "severity": 0,
                    "mismatch_score": 0.0, "spatial_component": 0.3,
                    "layer_attribution": {}, "layer_coupling": {"coherence": 1.0},
                    "layer_visibility": {"dominant": "Micro"},
                    "thresholds": {"detection": 0.42}, "overrides_applied": {},
                },
                "audit": {"clamped_fields": [], "rejected_fields": []},
            }

        async def detect_emergence(self, *args, **kwargs):
            return {
                "status": "ok", "contract_version": "1.0.0",
                "domain_profile": {"domain_name": "consumer_health", "version": "1.0.0"},
                "mode": "emergence", "layer_values": [0.3, 0.3, 0.3, 0.3],
                "result": {
                    "m_score": 0.3, "window_detected": False, "window_type": None,
                    "confidence": 0.0, "alignment_floor": 0.3,
                    "limiting_factor": None, "recommended_action": None,
                    "spatial_component": 0.3, "layer_attribution": {},
                    "layer_coupling": {"coherence": 1.0},
                    "thresholds": {"detection": 0.42}, "overrides_applied": {},
                },
                "audit": {"clamped_fields": [], "rejected_fields": []},
            }

    mcp = create_app(
        health_data_provider_override=_EmptyDataProvider(),
        mantic_client_override=_PassthroughMantic(),
    )
    client = Client(mcp)

    async def _check():
        async with client:
            result = await client.call_tool("personal_health_signal", {})
            text = str(result)
            # Should NOT get an escalation — just a normal LLM response
            assert "Safety escalation" not in text

    _run(_check())


def test_detect_escalation_triggers_unit():
    """Unit-test the _detect_escalation_triggers function directly."""
    from cip.domains.health.tools.personal_health_signals import _detect_escalation_triggers

    # All signals low with real data -> should trigger
    real_details = {
        "vital_stability": {"hr_signal": 0.1, "bp_signal": 0.05},
        "metabolic_balance": {"glucose_composite": 0.1},
        "activity_recovery": {"exercise_signal": 0.1},
        "preventive_readiness": {"screening_signal": 0.1},
    }
    triggers = _detect_escalation_triggers(
        layer_values=[0.1, 0.2, 0.15, 0.1],
        vitals_data={},
        signal_details=real_details,
    )
    assert "all_signals_below_0.3" in triggers

    # All signals low but from missing data -> should NOT trigger
    fallback_details = {
        "vital_stability": {"fallback": "no_vitals_data"},
        "metabolic_balance": {"fallback": "no_labs_or_biometrics"},
        "activity_recovery": {"fallback": "no_activity_data"},
        "preventive_readiness": {"fallback": "no_preventive_data"},
    }
    triggers = _detect_escalation_triggers(
        layer_values=[0.1, 0.2, 0.15, 0.1],
        vitals_data={},
        signal_details=fallback_details,
    )
    assert "all_signals_below_0.3" not in triggers

    # Even one fallback layer should suppress the trigger
    mixed_details = {
        "vital_stability": {"hr_signal": 0.1, "bp_signal": 0.05},
        "metabolic_balance": {"fallback": "no_labs_or_biometrics"},
        "activity_recovery": {"exercise_signal": 0.1},
        "preventive_readiness": {"screening_signal": 0.1},
    }
    triggers = _detect_escalation_triggers(
        layer_values=[0.1, 0.2, 0.15, 0.1],
        vitals_data={},
        signal_details=mixed_details,
    )
    assert "all_signals_below_0.3" not in triggers

    # Systolic trigger still works independently
    triggers = _detect_escalation_triggers(
        layer_values=[0.7, 0.6, 0.5, 0.8],
        vitals_data={"blood_pressure": {"systolic_avg": 195}},
        signal_details=real_details,
    )
    assert "systolic_over_180" in triggers
    assert "all_signals_below_0.3" not in triggers


def test_mantic_failure_falls_back_to_local_summary():
    """If cip-mantic-core is down/misconfigured, the tool should still return content."""

    class _FailingMantic:
        async def list_profiles(self):
            raise RuntimeError("down")

        async def detect_friction(self, *args, **kwargs):
            raise RuntimeError("down")

        async def detect_emergence(self, *args, **kwargs):
            raise RuntimeError("down")

    mcp = create_app(mantic_client_override=_FailingMantic())
    client = Client(mcp)

    async def _check():
        async with client:
            result = await client.call_tool("personal_health_signal", {})
            assert result

    _run(_check())
