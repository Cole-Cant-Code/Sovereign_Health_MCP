"""Tests for ManticMCPClient — MCP-to-MCP calls to cip-mantic-core."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest

from cip.core.mantic.client import (
    ManticClientError,
    ManticConnectionError,
    ManticDetectionError,
    ManticMCPClient,
    ManticResponseError,
)
from cip.core.mantic.models import ManticEnvelope


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@dataclass
class _TextBlock:
    """Mimics a fastmcp content block."""
    type: str = "text"
    text: str = ""


class MockMCPClient:
    """Fake fastmcp.Client for testing."""

    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses: dict[str, Any] = responses or {}
        self.last_tool: str | None = None
        self.last_args: dict[str, Any] | None = None
        self.call_count = 0
        self._raise_on_call: Exception | None = None

    def set_response(self, tool_name: str, response: dict) -> None:
        self.responses[tool_name] = response

    def raise_on_call(self, exc: Exception) -> None:
        self._raise_on_call = exc

    async def call_tool(self, tool_name: str, arguments: dict) -> list:
        self.last_tool = tool_name
        self.last_args = arguments
        self.call_count += 1

        if self._raise_on_call:
            raise self._raise_on_call

        data = self.responses.get(tool_name, {"status": "ok"})
        return [_TextBlock(text=json.dumps(data))]


# ------------------------------------------------------------------
# Sample envelopes (match observed cip-mantic-core responses)
# ------------------------------------------------------------------

FRICTION_ENVELOPE = {
    "status": "ok",
    "contract_version": "1.0.0",
    "domain_profile": {"domain_name": "consumer_health", "version": "1.0.0"},
    "mode": "friction",
    "layer_values": [0.7, 0.6, 0.5, 0.8],
    "result": {
        "alert": None,
        "severity": 0,
        "mismatch_score": 0.3,
        "m_score": 0.645,
        "spatial_component": 0.645,
        "layer_attribution": {
            "vital_stability": 0.27,
            "metabolic_balance": 0.28,
            "activity_recovery": 0.16,
            "preventive_readiness": 0.29,
        },
        "layer_visibility": {"dominant": "Micro"},
        "layer_coupling": {"coherence": 0.78},
        "thresholds": {"detection": 0.42},
        "overrides_applied": {},
    },
    "audit": {"clamped_fields": [], "rejected_fields": []},
}

EMERGENCE_ENVELOPE = {
    "status": "ok",
    "contract_version": "1.0.0",
    "domain_profile": {"domain_name": "consumer_health", "version": "1.0.0"},
    "mode": "emergence",
    "layer_values": [0.7, 0.6, 0.5, 0.8],
    "result": {
        "window_detected": True,
        "window_type": "FAVORABLE: Layers aligned above threshold",
        "confidence": 0.75,
        "alignment_floor": 0.5,
        "limiting_factor": "activity_recovery",
        "recommended_action": "Good alignment — proceed with awareness",
        "m_score": 0.645,
        "spatial_component": 0.645,
        "layer_attribution": {
            "vital_stability": 0.27,
            "metabolic_balance": 0.28,
            "activity_recovery": 0.16,
            "preventive_readiness": 0.29,
        },
        "layer_coupling": {"coherence": 0.78},
        "thresholds": {"detection": 0.42},
        "overrides_applied": {},
    },
    "audit": {"clamped_fields": [], "rejected_fields": []},
}


def _friction_mock() -> MockMCPClient:
    m = MockMCPClient()
    m.set_response("mantic_detect_friction", FRICTION_ENVELOPE)
    return m


def _emergence_mock() -> MockMCPClient:
    m = MockMCPClient()
    m.set_response("mantic_detect_emergence", EMERGENCE_ENVELOPE)
    return m


# ------------------------------------------------------------------
# Tests: Friction detection
# ------------------------------------------------------------------

class TestDetectFriction:
    """Test friction detection calls."""

    def test_calls_correct_tool(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert mock.last_tool == "mantic_detect_friction"

    def test_passes_profile_name(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert mock.last_args["profile_name"] == "consumer_health"

    def test_passes_layer_values(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        values = [0.7, 0.6, 0.5, 0.8]
        _run(client.detect_friction("consumer_health", values))
        assert mock.last_args["layer_values"] == values

    def test_passes_default_f_time(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert mock.last_args["f_time"] == 1.0

    def test_passes_custom_f_time(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8], f_time=1.5))
        assert mock.last_args["f_time"] == 1.5

    def test_omits_threshold_override_when_none(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "threshold_override" not in mock.last_args

    def test_passes_threshold_override(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_friction(
            "consumer_health", [0.7, 0.6, 0.5, 0.8], threshold_override=0.5
        ))
        assert mock.last_args["threshold_override"] == 0.5

    def test_returns_full_envelope(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert envelope["status"] == "ok"
        assert envelope["contract_version"] == "1.0.0"
        assert "result" in envelope

    def test_result_has_m_score(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "m_score" in envelope["result"]

    def test_result_has_layer_attribution(self):
        mock = _friction_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "layer_attribution" in envelope["result"]


# ------------------------------------------------------------------
# Tests: Emergence detection
# ------------------------------------------------------------------

class TestDetectEmergence:
    """Test emergence detection calls."""

    def test_calls_correct_tool(self):
        mock = _emergence_mock()
        client = ManticMCPClient(mock)
        _run(client.detect_emergence("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert mock.last_tool == "mantic_detect_emergence"

    def test_result_has_window_detected(self):
        mock = _emergence_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_emergence("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "window_detected" in envelope["result"]

    def test_result_has_alignment_floor(self):
        mock = _emergence_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_emergence("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "alignment_floor" in envelope["result"]

    def test_result_has_m_score(self):
        mock = _emergence_mock()
        client = ManticMCPClient(mock)
        envelope = _run(client.detect_emergence("consumer_health", [0.7, 0.6, 0.5, 0.8]))
        assert "m_score" in envelope["result"]


# ------------------------------------------------------------------
# Tests: Envelope parsing
# ------------------------------------------------------------------

class TestEnvelopeParsing:
    """Test ManticEnvelope model parsing."""

    def test_parse_friction_envelope(self):
        env = ManticEnvelope.from_dict(FRICTION_ENVELOPE)
        assert env.ok
        assert env.mode == "friction"
        assert env.contract_version == "1.0.0"

    def test_parse_emergence_envelope(self):
        env = ManticEnvelope.from_dict(EMERGENCE_ENVELOPE)
        assert env.ok
        assert env.mode == "emergence"

    def test_as_friction_extracts_m_score(self):
        env = ManticEnvelope.from_dict(FRICTION_ENVELOPE)
        friction = env.as_friction()
        assert friction.m_score == 0.645

    def test_as_friction_extracts_attribution(self):
        env = ManticEnvelope.from_dict(FRICTION_ENVELOPE)
        friction = env.as_friction()
        assert "vital_stability" in friction.layer_attribution

    def test_as_emergence_extracts_window(self):
        env = ManticEnvelope.from_dict(EMERGENCE_ENVELOPE)
        emergence = env.as_emergence()
        assert emergence.window_detected is True
        assert emergence.alignment_floor == 0.5

    def test_as_emergence_extracts_limiting_factor(self):
        env = ManticEnvelope.from_dict(EMERGENCE_ENVELOPE)
        emergence = env.as_emergence()
        assert emergence.limiting_factor == "activity_recovery"

    def test_ok_false_on_error(self):
        env = ManticEnvelope.from_dict({"status": "error", "error": "bad"})
        assert not env.ok

    def test_from_dict_handles_missing_fields(self):
        env = ManticEnvelope.from_dict({})
        assert env.status == "unknown"
        assert env.result == {}


# ------------------------------------------------------------------
# Tests: Health check
# ------------------------------------------------------------------

class TestHealthCheck:
    """Test health_check tool call."""

    def test_calls_health_check_tool(self):
        mock = MockMCPClient()
        mock.set_response("health_check", {"status": "ok", "server": "CIP Mantic Core"})
        client = ManticMCPClient(mock)
        result = _run(client.health_check())
        assert mock.last_tool == "health_check"
        assert result["status"] == "ok"


# ------------------------------------------------------------------
# Tests: Error handling
# ------------------------------------------------------------------

class TestErrorHandling:
    """Test error scenarios."""

    def test_connection_error_wraps_exception(self):
        mock = MockMCPClient()
        mock.raise_on_call(ConnectionError("refused"))
        client = ManticMCPClient(mock)
        with pytest.raises(ManticConnectionError, match="cip-mantic-core"):
            _run(client.detect_friction("consumer_health", [0.5, 0.5, 0.5, 0.5]))

    def test_empty_response_raises(self):
        mock = MockMCPClient()

        async def empty_call(*args, **kwargs):
            return []

        mock.call_tool = empty_call
        client = ManticMCPClient(mock)
        with pytest.raises(ManticResponseError, match="Empty response"):
            _run(client.detect_friction("consumer_health", [0.5, 0.5, 0.5, 0.5]))

    def test_error_status_raises(self):
        mock = MockMCPClient()
        mock.set_response(
            "mantic_detect_friction",
            {"status": "error", "error": "unknown_profile"},
        )
        client = ManticMCPClient(mock)
        with pytest.raises(ManticDetectionError, match="unknown_profile"):
            _run(client.detect_friction("bad_profile", [0.5, 0.5, 0.5, 0.5]))

    def test_invalid_json_raises(self):
        mock = MockMCPClient()

        async def bad_json_call(*args, **kwargs):
            return [_TextBlock(text="not json at all")]

        mock.call_tool = bad_json_call
        client = ManticMCPClient(mock)
        with pytest.raises(ManticResponseError, match="Invalid JSON"):
            _run(client.detect_friction("consumer_health", [0.5, 0.5, 0.5, 0.5]))

    def test_all_errors_inherit_base(self):
        """All custom exceptions are ManticClientError."""
        assert issubclass(ManticConnectionError, ManticClientError)
        assert issubclass(ManticResponseError, ManticClientError)
        assert issubclass(ManticDetectionError, ManticClientError)
