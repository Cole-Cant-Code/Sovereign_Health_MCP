"""Shared test fixtures for CIP Health tests."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Test hermeticity
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _force_hermetic_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

# Allow running tests without `pip install -e .` by making `src/` importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from cip.core.scaffold.engine import ScaffoldEngine  # noqa: E402
from cip.core.scaffold.models import (  # noqa: E402
    Scaffold,
    ScaffoldApplicability,
    ScaffoldFraming,
    ScaffoldGuardrails,
    ScaffoldOutputCalibration,
)
from cip.core.scaffold.registry import ScaffoldRegistry  # noqa: E402


def make_test_scaffold(
    id: str = "test_scaffold",
    tools: list[str] | None = None,
    keywords: list[str] | None = None,
) -> Scaffold:
    """Create a test scaffold with sensible defaults."""
    return Scaffold(
        id=id,
        version="1.0.0",
        domain="personal_health",
        display_name=f"Test: {id}",
        description=f"Test scaffold {id}",
        applicability=ScaffoldApplicability(
            tools=tools or ["default_tool"],
            keywords=keywords or ["default"],
            intent_signals=[],
        ),
        framing=ScaffoldFraming(
            role="Test analyst",
            perspective="Test perspective",
            tone="neutral",
            tone_variants={"formal": "Very formal", "casual": "Very casual"},
        ),
        reasoning_framework={"steps": ["Analyze data", "Draw conclusions"]},
        domain_knowledge_activation=["General health knowledge"],
        output_calibration=ScaffoldOutputCalibration(
            format="structured_narrative",
            format_options=["structured_narrative", "bullet_points"],
            max_length_guidance="200-400 words",
            must_include=["health summary"],
            never_include=["medical diagnoses"],
        ),
        guardrails=ScaffoldGuardrails(
            disclaimers=["Not medical advice."],
            escalation_triggers=["emergency"],
            prohibited_actions=["diagnose conditions"],
        ),
        context_accepts=[],
        context_exports=[],
        tags=["test"],
    )


@pytest.fixture
def registry() -> ScaffoldRegistry:
    """Create a registry with test scaffolds (neutral + risk + growth)."""
    reg = ScaffoldRegistry()
    reg.register(make_test_scaffold(
        id="personal_health_signal",
        tools=["personal_health_signal"],
        keywords=["health", "wellness", "vitals", "signals"],
    ))
    reg.register(make_test_scaffold(
        id="personal_health_signal.risk",
        tools=["personal_health_signal"],
        keywords=["health", "risk"],
    ))
    reg.register(make_test_scaffold(
        id="personal_health_signal.growth",
        tools=["personal_health_signal"],
        keywords=["health", "growth"],
    ))
    return reg


@pytest.fixture
def engine(registry: ScaffoldRegistry) -> ScaffoldEngine:
    """Create a scaffold engine with test registry."""
    return ScaffoldEngine(registry)


# ---------------------------------------------------------------------------
# Mock Mantic MCP client
# ---------------------------------------------------------------------------

# Sample envelopes matching cip-mantic-core response format
_FRICTION_ENVELOPE: dict[str, Any] = {
    "status": "ok",
    "contract_version": "1.0.0",
    "domain_profile": "consumer_health",
    "mode": "friction",
    "layer_values": [0.7, 0.55, 0.65, 0.5],
    "result": {
        "m_score": 0.3842,
        "alert": None,
        "severity": None,
        "mismatch_score": 0.15,
        "layer_attribution": {
            "vital_stability": 0.175,
            "metabolic_balance": 0.165,
            "activity_recovery": 0.13,
            "preventive_readiness": 0.125,
        },
        "layer_coupling": [
            {"pair": ["vital_stability", "metabolic_balance"], "delta": 0.15}
        ],
        "layer_visibility": {
            "vital_stability": "visible",
            "metabolic_balance": "visible",
            "activity_recovery": "visible",
            "preventive_readiness": "visible",
        },
    },
    "audit": {"detection_ms": 1.2, "f_time": 1.0},
}

_EMERGENCE_ENVELOPE: dict[str, Any] = {
    "status": "ok",
    "contract_version": "1.0.0",
    "domain_profile": "consumer_health",
    "mode": "emergence",
    "layer_values": [0.7, 0.55, 0.65, 0.5],
    "result": {
        "m_score": 0.6025,
        "window_detected": False,
        "window_type": None,
        "confidence": 0.0,
        "alignment_floor": 0.5,
        "limiting_factor": "preventive_readiness",
        "recommended_action": None,
        "layer_attribution": {
            "vital_stability": 0.175,
            "metabolic_balance": 0.165,
            "activity_recovery": 0.13,
            "preventive_readiness": 0.125,
        },
        "layer_coupling": [
            {"pair": ["vital_stability", "metabolic_balance"], "delta": 0.15}
        ],
    },
    "audit": {"detection_ms": 0.8, "f_time": 1.0},
}


@dataclass
class _TextBlock:
    """Mimics fastmcp content block structure."""

    type: str
    text: str


class MockMCPClient:
    """Mock fastmcp.Client that returns canned Mantic envelopes.

    Suitable for injecting into ManticMCPClient for unit and integration tests
    without needing a running cip-mantic-core server.
    """

    def __init__(
        self,
        friction_envelope: dict[str, Any] | None = None,
        emergence_envelope: dict[str, Any] | None = None,
    ) -> None:
        self._friction = friction_envelope or _FRICTION_ENVELOPE
        self._emergence = emergence_envelope or _EMERGENCE_ENVELOPE
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> list[Any]:
        self.calls.append((tool_name, arguments))
        if tool_name == "mantic_detect_friction":
            payload = self._friction
        elif tool_name == "mantic_detect_emergence":
            payload = self._emergence
        elif tool_name == "health_check":
            payload = {"status": "ok", "profiles_loaded": 1}
        elif tool_name == "list_domain_profiles":
            payload = {"profiles": ["consumer_health"]}
        else:
            payload = {"error": f"Unknown tool: {tool_name}"}
        return [_TextBlock(type="text", text=json.dumps(payload))]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_mcp_client() -> MockMCPClient:
    """Create a MockMCPClient with default envelopes."""
    return MockMCPClient()


@pytest.fixture
def mock_mantic_client(mock_mcp_client: MockMCPClient):
    """Create a ManticMCPClient backed by MockMCPClient."""
    from cip.core.mantic.client import ManticMCPClient

    return ManticMCPClient(mock_mcp_client)


# ---------------------------------------------------------------------------
# In-memory storage fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def health_db():
    """Create an in-memory HealthDatabase for testing."""
    from cip.core.storage.database import HealthDatabase

    db = HealthDatabase(":memory:")
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def field_encryptor():
    """Create a FieldEncryptor with a test key."""
    from cryptography.fernet import Fernet

    from cip.core.storage.encryption import FieldEncryptor

    return FieldEncryptor(Fernet.generate_key().decode())


@pytest.fixture
def health_repository(health_db, field_encryptor):
    """Create a HealthRepository backed by in-memory SQLite."""
    from cip.core.storage.repository import HealthRepository

    return HealthRepository(health_db, field_encryptor)


@pytest.fixture
def audit_logger(health_db):
    """Create an AuditLogger backed by in-memory SQLite."""
    from cip.core.audit.logger import AuditLogger

    return AuditLogger(health_db)
