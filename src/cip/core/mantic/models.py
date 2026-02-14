"""Response models for cip-mantic-core MCP service."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrictionResult:
    """Parsed friction detection result from cip-mantic-core."""

    m_score: float
    alert: str | None
    severity: float
    mismatch_score: float
    layer_attribution: dict[str, float]
    layer_coupling: dict
    layer_visibility: dict | None
    thresholds: dict = field(default_factory=dict)
    overrides_applied: dict = field(default_factory=dict)


@dataclass
class EmergenceResult:
    """Parsed emergence detection result from cip-mantic-core."""

    m_score: float
    window_detected: bool
    window_type: str | None
    confidence: float
    alignment_floor: float
    limiting_factor: str | None
    recommended_action: str | None
    layer_attribution: dict[str, float]
    layer_coupling: dict
    thresholds: dict = field(default_factory=dict)
    overrides_applied: dict = field(default_factory=dict)


@dataclass
class ManticEnvelope:
    """Full response envelope from cip-mantic-core detect calls."""

    status: str
    contract_version: str
    domain_profile: dict
    mode: str
    layer_values: list[float]
    result: dict
    audit: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ManticEnvelope:
        """Parse a raw dict response from the MCP tool call."""
        return cls(
            status=data.get("status", "unknown"),
            contract_version=data.get("contract_version", ""),
            domain_profile=data.get("domain_profile", {}),
            mode=data.get("mode", ""),
            layer_values=data.get("layer_values", []),
            result=data.get("result", {}),
            audit=data.get("audit", {}),
        )

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_friction(self) -> FrictionResult:
        """Extract a typed FrictionResult from the envelope."""
        r = self.result
        return FrictionResult(
            m_score=r.get("m_score", 0.0),
            alert=r.get("alert"),
            severity=r.get("severity", 0.0),
            mismatch_score=r.get("mismatch_score", 0.0),
            layer_attribution=r.get("layer_attribution", {}),
            layer_coupling=r.get("layer_coupling", {}),
            layer_visibility=r.get("layer_visibility"),
            thresholds=r.get("thresholds", {}),
            overrides_applied=r.get("overrides_applied", {}),
        )

    def as_emergence(self) -> EmergenceResult:
        """Extract a typed EmergenceResult from the envelope."""
        r = self.result
        return EmergenceResult(
            m_score=r.get("m_score", 0.0),
            window_detected=r.get("window_detected", False),
            window_type=r.get("window_type"),
            confidence=r.get("confidence", 0.0),
            alignment_floor=r.get("alignment_floor", 0.0),
            limiting_factor=r.get("limiting_factor"),
            recommended_action=r.get("recommended_action"),
            layer_attribution=r.get("layer_attribution", {}),
            layer_coupling=r.get("layer_coupling", {}),
            thresholds=r.get("thresholds", {}),
            overrides_applied=r.get("overrides_applied", {}),
        )
