"""Consumer health signal models and domain constants for Mantic integration."""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Domain constants (used by signal_translator and the MCP tool)
# ---------------------------------------------------------------------------

LAYER_NAMES = [
    "vital_stability",
    "metabolic_balance",
    "activity_recovery",
    "preventive_readiness",
]

# Weights encode consumer health theory:
#   metabolic_balance (0.30) — most structural predictor of long-term health
#   vital_stability & preventive_readiness (0.25) — important, one real-time, one structural
#   activity_recovery (0.20) — important but most volatile day-to-day
HEALTH_WEIGHTS = [0.25, 0.30, 0.20, 0.25]

# Domain name for generic_detect (cannot collide with Mantic's 7 reserved domains)
HEALTH_DOMAIN = "consumer_health"

# Profile name registered with cip-mantic-core (matches consumer_health.v1.yaml)
PROFILE_NAME = "consumer_health"

# Layer hierarchy for Mantic's introspection system
LAYER_HIERARCHY = {
    "vital_stability": "Micro",
    "metabolic_balance": "Macro",
    "activity_recovery": "Meso",
    "preventive_readiness": "Meso",
}

# ---------------------------------------------------------------------------
# Fallback values for missing data
# ---------------------------------------------------------------------------

FALLBACK_NO_DATA = 0.3          # Missing data entirely -> pessimistic default
FALLBACK_PARTIAL_DATA = 0.5     # Some data missing -> neutral assumption
FALLBACK_NO_LABS = 0.4          # No lab results -> cautious default
FALLBACK_GOOD_DEFAULT = 0.7     # No conditions/medications = assumed healthy


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class HealthSignals:
    """Translated consumer health signals, ready for Mantic kernel input."""

    vital_stability: float         # 0-1: physiological signal stability
    metabolic_balance: float       # 0-1: metabolic health indicators
    activity_recovery: float       # 0-1: exercise/sleep/recovery balance
    preventive_readiness: float    # 0-1: preventive care engagement
    details: dict = field(default_factory=dict)

    def as_layer_values(self) -> list[float]:
        """Return values in LAYER_NAMES order for generic_detect."""
        return [
            self.vital_stability,
            self.metabolic_balance,
            self.activity_recovery,
            self.preventive_readiness,
        ]
