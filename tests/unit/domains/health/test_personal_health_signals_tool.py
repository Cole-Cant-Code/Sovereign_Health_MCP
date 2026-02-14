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
