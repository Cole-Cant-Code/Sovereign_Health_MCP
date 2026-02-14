"""Unit tests for Mantic-driven scaffold routing in ScaffoldEngine.

Tests the context-aware routing added to engine.select() that chooses
risk/growth/neutral scaffolds based on Mantic detection summaries.
"""

from __future__ import annotations

import pytest

from cip.core.scaffold.engine import ScaffoldEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mantic_summary(
    *,
    friction_level: str = "moderate",
    emergence_window: bool = False,
    coherence: float | None = 0.75,
    limiting_factor: str | None = None,
    dominant_layer: str | None = None,
) -> dict:
    """Create a mantic_summary dict for testing scaffold routing."""
    return {
        "friction_level": friction_level,
        "emergence_window": emergence_window,
        "limiting_factor": limiting_factor,
        "dominant_layer": dominant_layer,
        "coherence": coherence,
    }


# ---------------------------------------------------------------------------
# Growth scaffold routing
# ---------------------------------------------------------------------------

class TestGrowthRouting:
    def test_select_returns_growth_when_emergence_window(self, engine: ScaffoldEngine):
        """emergence_window=True should route to growth scaffold."""
        summary = _make_mantic_summary(emergence_window=True)
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal.growth"

    def test_emergence_takes_priority_over_high_friction(self, engine: ScaffoldEngine):
        """When both emergence and high friction, emergence wins (checked first)."""
        summary = _make_mantic_summary(
            emergence_window=True,
            friction_level="high",
        )
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal.growth"


# ---------------------------------------------------------------------------
# Risk scaffold routing
# ---------------------------------------------------------------------------

class TestRiskRouting:
    def test_select_returns_risk_when_high_friction(self, engine: ScaffoldEngine):
        """friction_level='high' should route to risk scaffold."""
        summary = _make_mantic_summary(friction_level="high")
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal.risk"

    def test_select_returns_risk_when_low_coherence(self, engine: ScaffoldEngine):
        """coherence < 0.6 should route to risk scaffold."""
        summary = _make_mantic_summary(coherence=0.4)
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal.risk"

    def test_coherence_boundary_at_06(self, engine: ScaffoldEngine):
        """coherence exactly 0.6 should NOT trigger risk routing."""
        summary = _make_mantic_summary(coherence=0.6)
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        # Should fall through to neutral
        assert scaffold.id == "personal_health_signal"

    def test_coherence_none_does_not_trigger_risk(self, engine: ScaffoldEngine):
        """coherence=None (missing data) should NOT trigger risk routing."""
        summary = _make_mantic_summary(coherence=None)
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal"


# ---------------------------------------------------------------------------
# Neutral (default) routing
# ---------------------------------------------------------------------------

class TestNeutralRouting:
    def test_select_returns_neutral_when_normal(self, engine: ScaffoldEngine):
        """Normal mantic summary should route to neutral scaffold."""
        summary = _make_mantic_summary()
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        assert scaffold.id == "personal_health_signal"

    def test_select_returns_neutral_when_no_tool_context(self, engine: ScaffoldEngine):
        """No tool_context should fall through to neutral."""
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
        )
        assert scaffold.id == "personal_health_signal"

    def test_select_returns_neutral_when_tool_context_empty(self, engine: ScaffoldEngine):
        """Empty tool_context should fall through to neutral."""
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={},
        )
        assert scaffold.id == "personal_health_signal"


# ---------------------------------------------------------------------------
# Override behavior
# ---------------------------------------------------------------------------

class TestScaffoldOverrides:
    def test_explicit_scaffold_id_overrides_routing(self, engine: ScaffoldEngine):
        """caller_scaffold_id should bypass Mantic-driven routing entirely."""
        summary = _make_mantic_summary(emergence_window=True)
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            caller_scaffold_id="personal_health_signal.risk",
            tool_context={"mantic_summary": summary},
        )
        # When caller_scaffold_id is set, Mantic routing is skipped.
        # It should use the matcher which should find the risk scaffold by ID.
        assert scaffold.id == "personal_health_signal.risk"

    def test_different_tool_name_skips_mantic_routing(self, engine: ScaffoldEngine):
        """Mantic routing only applies to 'personal_health_signal' tool.

        For a different tool name, the Mantic routing block is skipped
        even if tool_context has emergence_window=True. It falls through
        to match_scaffold → default scaffold.
        """
        summary = _make_mantic_summary(emergence_window=True)
        # The tool_name is something else entirely.
        # Since no scaffold matches "other_tool", it falls to the default.
        scaffold = engine.select(
            tool_name="other_tool",
            user_input="last_30_days",
            tool_context={"mantic_summary": summary},
        )
        # Falls to DEFAULT_SCAFFOLD_ID = "personal_health_signal"
        assert scaffold.id == "personal_health_signal"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_malformed_mantic_summary_falls_through(self, engine: ScaffoldEngine):
        """Non-dict mantic_summary should not crash, just fall through."""
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"mantic_summary": "not_a_dict"},
        )
        assert scaffold.id == "personal_health_signal"

    def test_tool_context_without_mantic_summary(self, engine: ScaffoldEngine):
        """tool_context without mantic_summary key falls through cleanly."""
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input="last_30_days",
            tool_context={"something_else": True},
        )
        assert scaffold.id == "personal_health_signal"
