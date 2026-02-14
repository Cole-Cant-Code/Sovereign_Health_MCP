"""Tests that consumer_health.v1.yaml stays in sync with signal_models.py constants."""

from __future__ import annotations

from pathlib import Path

import yaml

from cip.domains.health.domain_logic.signal_models import (
    HEALTH_DOMAIN,
    HEALTH_WEIGHTS,
    LAYER_HIERARCHY,
    LAYER_NAMES,
    PROFILE_NAME,
)

def _find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError("Could not find project root (no pyproject.toml found)")


_PROFILE_PATH = (
    _find_project_root()
    / "src"
    / "cip"
    / "domains"
    / "health"
    / "profiles"
    / "consumer_health.v1.yaml"
)


def _load_profile() -> dict:
    text = _PROFILE_PATH.read_text()
    return yaml.safe_load(text)


class TestProfileSync:
    """Ensure the YAML profile matches the Python constants."""

    def test_profile_file_exists(self):
        assert _PROFILE_PATH.exists(), f"Profile YAML not found at {_PROFILE_PATH}"

    def test_domain_name_matches(self):
        profile = _load_profile()
        assert profile["domain_name"] == HEALTH_DOMAIN

    def test_profile_name_matches_domain(self):
        assert PROFILE_NAME == HEALTH_DOMAIN

    def test_layer_names_match(self):
        profile = _load_profile()
        assert profile["layer_names"] == LAYER_NAMES

    def test_weights_match(self):
        profile = _load_profile()
        assert profile["weights"] == HEALTH_WEIGHTS

    def test_weights_sum_to_one(self):
        profile = _load_profile()
        total = sum(profile["weights"])
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_hierarchy_matches(self):
        profile = _load_profile()
        assert profile["hierarchy"] == LAYER_HIERARCHY

    def test_layer_count_consistent(self):
        profile = _load_profile()
        assert len(profile["layer_names"]) == len(profile["weights"])

    def test_hierarchy_covers_all_layers(self):
        profile = _load_profile()
        hierarchy_layers = set(profile["hierarchy"].keys())
        layer_names = set(profile["layer_names"])
        assert hierarchy_layers == layer_names, (
            f"Hierarchy keys {hierarchy_layers} != layer names {layer_names}"
        )

    def test_version_is_semver(self):
        profile = _load_profile()
        version = profile["version"]
        parts = version.split(".")
        assert len(parts) == 3, f"Version '{version}' is not semver (expected X.Y.Z)"
        for part in parts:
            assert part.isdigit(), f"Version part '{part}' is not numeric"

    def test_has_required_fields(self):
        profile = _load_profile()
        required = [
            "domain_name",
            "version",
            "display_name",
            "description",
            "layer_names",
            "weights",
            "hierarchy",
            "thresholds",
            "temporal_allowlist",
        ]
        for field in required:
            assert field in profile, f"Missing required field: {field}"

    def test_thresholds_detection_is_positive(self):
        profile = _load_profile()
        threshold = profile["thresholds"]["detection"]
        assert 0 < threshold < 1, f"Detection threshold {threshold} not in (0, 1)"

    def test_temporal_allowlist_not_empty(self):
        profile = _load_profile()
        assert len(profile["temporal_allowlist"]) > 0

    def test_guardrails_present(self):
        profile = _load_profile()
        assert "guardrails" in profile
        guardrails = profile["guardrails"]
        assert "disclaimers" in guardrails
        assert "escalation_triggers" in guardrails
        assert len(guardrails["disclaimers"]) > 0
        assert len(guardrails["escalation_triggers"]) > 0
