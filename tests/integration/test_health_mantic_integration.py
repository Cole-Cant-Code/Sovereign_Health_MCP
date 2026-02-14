"""Integration tests: Mantic MCP-to-MCP + health signal translation E2E.

These tests use a MockMCPClient (from conftest) to verify the full pipeline:
mock data → signal translation → Mantic detection (via MCP) → envelope parsing.
No running cip-mantic-core server required.
"""

from __future__ import annotations

import asyncio

import pytest

from cip.core.mantic.client import ManticMCPClient
from cip.domains.health.connectors.mock_data import (
    get_mock_activity_data,
    get_mock_biometrics,
    get_mock_lab_results,
    get_mock_preventive_care,
    get_mock_vitals_data,
)
from cip.domains.health.domain_logic.signal_models import (
    LAYER_NAMES,
    PROFILE_NAME,
)
from cip.domains.health.domain_logic.signal_translator import (
    translate_health_to_mantic,
)


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio required)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSignalTranslationDeterminism:
    def test_same_inputs_same_signals(self):
        a = translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        ).as_layer_values()
        b = translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        ).as_layer_values()
        assert a == b

    def test_signal_values_in_expected_range(self):
        values = translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        ).as_layer_values()
        for v in values:
            assert 0.0 <= v <= 1.0, f"Signal value {v} out of [0, 1] range"


class TestManticMCPDetection:
    """Test Mantic detection via MCP client (mock transport)."""

    def _signals(self):
        return translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        ).as_layer_values()

    def test_friction_via_mcp_returns_envelope(self, mock_mantic_client):
        vals = self._signals()
        envelope = _run(mock_mantic_client.detect_friction(
            profile_name=PROFILE_NAME,
            layer_values=vals,
        ))
        assert envelope["status"] == "ok"
        assert "result" in envelope
        result = envelope["result"]
        assert "m_score" in result
        assert "layer_attribution" in result

    def test_emergence_via_mcp_returns_envelope(self, mock_mantic_client):
        vals = self._signals()
        envelope = _run(mock_mantic_client.detect_emergence(
            profile_name=PROFILE_NAME,
            layer_values=vals,
        ))
        assert envelope["status"] == "ok"
        assert "result" in envelope
        result = envelope["result"]
        assert "m_score" in result
        assert "window_detected" in result
        assert "alignment_floor" in result

    def test_friction_result_has_expected_keys(self, mock_mantic_client):
        envelope = _run(mock_mantic_client.detect_friction(
            profile_name=PROFILE_NAME,
            layer_values=self._signals(),
        ))
        result = envelope["result"]
        for key in ("m_score", "alert", "layer_attribution", "layer_coupling"):
            assert key in result, f"Missing key in friction result: {key}"

    def test_emergence_result_has_expected_keys(self, mock_mantic_client):
        envelope = _run(mock_mantic_client.detect_emergence(
            profile_name=PROFILE_NAME,
            layer_values=self._signals(),
        ))
        result = envelope["result"]
        for key in ("m_score", "window_detected", "alignment_floor", "layer_attribution"):
            assert key in result, f"Missing key in emergence result: {key}"


class TestFullFlowE2E:
    """Full pipeline: mock data → translation → MCP Mantic detection → envelope."""

    def test_full_flow_data_to_output(self, mock_mantic_client):
        signals = translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        )
        vals = signals.as_layer_values()

        friction = _run(mock_mantic_client.detect_friction(
            profile_name=PROFILE_NAME,
            layer_values=vals,
        ))
        emergence = _run(mock_mantic_client.detect_emergence(
            profile_name=PROFILE_NAME,
            layer_values=vals,
        ))

        assert isinstance(friction["result"]["m_score"], float)
        assert isinstance(emergence["result"]["m_score"], float)
        assert 0.0 <= friction["result"]["m_score"] <= 1.0
        assert 0.0 <= emergence["result"]["m_score"] <= 1.0

    def test_mcp_client_records_correct_tool_calls(self, mock_mcp_client):
        """Verify the MCP client calls the correct cip-mantic-core tools."""
        client = ManticMCPClient(mock_mcp_client)
        vals = translate_health_to_mantic(
            get_mock_vitals_data(), get_mock_lab_results(),
            get_mock_activity_data(), get_mock_preventive_care(),
            get_mock_biometrics(),
        ).as_layer_values()

        _run(client.detect_friction(profile_name=PROFILE_NAME, layer_values=vals))
        _run(client.detect_emergence(profile_name=PROFILE_NAME, layer_values=vals))

        tool_names = [call[0] for call in mock_mcp_client.calls]
        assert "mantic_detect_friction" in tool_names
        assert "mantic_detect_emergence" in tool_names

    def test_profile_name_passed_to_mantic(self, mock_mcp_client):
        """Verify profile_name is correctly passed in MCP tool arguments."""
        client = ManticMCPClient(mock_mcp_client)
        vals = [0.7, 0.55, 0.65, 0.5]

        _run(client.detect_friction(profile_name=PROFILE_NAME, layer_values=vals))

        _, args = mock_mcp_client.calls[0]
        assert args["profile_name"] == PROFILE_NAME
        assert args["layer_values"] == vals
