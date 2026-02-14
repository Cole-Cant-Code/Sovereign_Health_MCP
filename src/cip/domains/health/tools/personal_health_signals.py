"""MCP Tool for personal health signal analysis (Mantic + privacy integration via MCP)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.llm.client import InnerLLMClient
    from cip.core.mantic.client import ManticMCPClient
    from cip.core.scaffold.engine import ScaffoldEngine
    from cip.core.storage.repository import HealthRepository
    from cip.domains.health.connectors import HealthDataProvider

from cip.core.privacy.policy import PrivacyMode, build_llm_data_context
from cip.domains.health.domain_logic.signal_models import (
    LAYER_NAMES,
    PROFILE_NAME,
)
from cip.domains.health.domain_logic.signal_translator import (
    translate_health_to_mantic,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_privacy_mode(value: str | None) -> PrivacyMode:
    """Validate and default the privacy_mode parameter."""
    if value in (None, ""):
        return "strict"
    if value not in ("strict", "standard", "explicit"):
        raise ValueError("privacy_mode must be one of: strict | standard | explicit")
    return value  # type: ignore[return-value]


def _friction_level_from_score(m_score: float | None) -> str:
    """Map a raw Mantic M-score to a human-readable friction level."""
    if m_score is None:
        return "moderate"
    if m_score < 0.4:
        return "low"
    if m_score < 0.7:
        return "moderate"
    return "high"


def _compute_exports(
    *, signals: dict[str, float], mantic_summary: dict[str, Any]
) -> dict[str, Any]:
    """Build deterministic context exports for cross-domain sharing."""
    if not signals:
        return {}

    strongest = max(signals.items(), key=lambda kv: kv[1])[0]
    weakest = min(signals.items(), key=lambda kv: kv[1])[0]

    risk = ""
    opportunity = ""

    if mantic_summary.get("friction_level") == "high":
        risk = f"High divergence detected; weakest area is '{weakest}'."
    elif mantic_summary.get("coherence") is not None and mantic_summary["coherence"] < 0.6:
        risk = f"Signals are mismatched; weakest area is '{weakest}'."
    elif mantic_summary.get("limiting_factor"):
        risk = f"Primary limiting factor: '{mantic_summary['limiting_factor']}'."

    if mantic_summary.get("emergence_window"):
        opportunity = "Signals are aligned enough to safely set a new health goal."

    return {
        "health_signal_summary": {
            "signals": signals,
            "strongest": strongest,
            "weakest": weakest,
        },
        "primary_health_risk": risk,
        "primary_health_opportunity": opportunity,
    }


def register_personal_health_signal_tools(
    mcp: FastMCP,
    engine: ScaffoldEngine,
    llm_client: InnerLLMClient,
    health_data_provider: HealthDataProvider,
    mantic_client: ManticMCPClient,
    repository: HealthRepository | None = None,
) -> None:
    """Register personal health signal tools on the MCP server.

    These tools call cip-mantic-core via MCP for anomaly detection.
    When a repository is provided, analysis results are persisted to
    the encrypted health data bank.
    """

    @mcp.tool
    async def personal_health_signal(
        ctx: Context,
        period: str = "last_30_days",
        scaffold_id: str | None = None,
        tone_variant: str | None = None,
        output_format: str | None = None,
        cross_domain_context: str | None = None,
        privacy_mode: str | None = None,
        store_mode: str | None = None,
        include_mantic_raw: bool = False,
    ) -> str:
        """Assess overall personal health using multi-factor signal analysis.

        Translates your vitals, lab results, activity patterns, and preventive
        care status into quantitative health signals, then detects divergences
        (where one area is strong but another is weak) and alignment windows
        (where everything is healthy enough to set new goals).

        Args:
            period: Time period to analyze (e.g., 'last_30_days', 'last_90_days').
            scaffold_id: Optional scaffold override.
            tone_variant: Optional tone override (clinical, reassuring, action_oriented).
            output_format: Optional format override.
            cross_domain_context: Optional JSON string with context from other domains.
            privacy_mode: Controls what data reaches the LLM prompt.
                'strict' (default) — only signal scores + safe Mantic summary.
                'standard' — adds friendly vitals (HR, BP, HRV, sleep, exercise, BMI).
                'explicit' — full data context reaches the LLM.
            store_mode: Controls snapshot persistence.
                'encrypted' (default) — persist to health data bank.
                'none' — do not persist this analysis.
            include_mantic_raw: Include raw Mantic outputs in explicit mode.
                Forced to False when privacy_mode is 'strict'.
        """
        effective_privacy_mode = _validate_privacy_mode(privacy_mode)
        effective_store_mode = store_mode if store_mode in ("encrypted", "none") else "encrypted"
        if effective_privacy_mode == "strict":
            include_mantic_raw = False
        # ---------------------------------------------------------------
        # 1. Gather data (5 async calls)
        # ---------------------------------------------------------------
        vitals_data = await health_data_provider.get_vitals(period)
        lab_results = await health_data_provider.get_lab_results()
        activity_data = await health_data_provider.get_activity_data(period)
        preventive_care = await health_data_provider.get_preventive_care()
        biometrics = await health_data_provider.get_biometrics()

        # ---------------------------------------------------------------
        # 2. Translate to Mantic signals (deterministic, no LLM)
        # ---------------------------------------------------------------
        signals = translate_health_to_mantic(
            vitals_data=vitals_data,
            lab_results=lab_results,
            activity_data=activity_data,
            preventive_care=preventive_care,
            biometrics=biometrics,
        )
        layer_values = signals.as_layer_values()

        # ---------------------------------------------------------------
        # 3. Run Mantic detection via cip-mantic-core (both modes)
        # ---------------------------------------------------------------
        friction_envelope = await mantic_client.detect_friction(
            profile_name=PROFILE_NAME,
            layer_values=layer_values,
        )
        friction_result = friction_envelope["result"]

        emergence_envelope = await mantic_client.detect_emergence(
            profile_name=PROFILE_NAME,
            layer_values=layer_values,
        )
        emergence_result = emergence_envelope["result"]

        # ---------------------------------------------------------------
        # 3b. Build structured Mantic summary (for scaffold routing + LLM)
        # ---------------------------------------------------------------
        coupling_list = friction_result.get("layer_coupling")
        mantic_summary: dict[str, Any] = {
            "friction_level": _friction_level_from_score(friction_result.get("m_score")),
            "emergence_window": emergence_result.get("window_detected", False),
            "limiting_factor": emergence_result.get("limiting_factor"),
            "dominant_layer": (friction_result.get("layer_visibility") or {}).get("dominant"),
            "coherence": (
                coupling_list[0].get("coherence")
                if isinstance(coupling_list, list) and coupling_list
                else None
            ),
        }

        # ---------------------------------------------------------------
        # 4. Build full data_context (all metrics — privacy filter applied later)
        # ---------------------------------------------------------------
        data_context: dict[str, Any] = {
            "period": period,
            "resting_heart_rate": vitals_data.get("resting_heart_rate", {}).get("current_bpm"),
            "blood_pressure_systolic": vitals_data.get("blood_pressure", {}).get("systolic_avg"),
            "blood_pressure_diastolic": vitals_data.get("blood_pressure", {}).get("diastolic_avg"),
            "hrv_ms": vitals_data.get("hrv", {}).get("avg_ms"),
            "exercise_sessions_per_week": activity_data.get("exercise", {}).get(
                "sessions_per_week"
            ),
            "sleep_duration_hours": activity_data.get("sleep", {}).get("avg_duration_hours"),
            "bmi": biometrics.get("bmi"),
            "lab_count": len(lab_results),
            "signals": {
                name: round(value, 4)
                for name, value in zip(LAYER_NAMES, layer_values)
            },
            "signal_details": signals.details,
            "mantic_summary": mantic_summary,
            "mantic_raw": {"friction": friction_result, "emergence": emergence_result},
            "friction": {
                "m_score": friction_result.get("m_score"),
                "detected": friction_result.get("alert") is not None,
                "layer_attribution": friction_result.get("layer_attribution"),
                "layer_coupling": friction_result.get("layer_coupling"),
                "layer_visibility": friction_result.get("layer_visibility"),
            },
            "emergence": {
                "m_score": emergence_result.get("m_score"),
                "detected": emergence_result.get("window_detected", False),
                "window_type": emergence_result.get("window_type"),
                "alignment_floor": emergence_result.get("alignment_floor"),
                "layer_attribution": emergence_result.get("layer_attribution"),
                "layer_coupling": emergence_result.get("layer_coupling"),
            },
            **health_data_provider.get_provenance(),
        }

        # Deterministic context exports (for cross-domain sharing)
        data_context.update(
            _compute_exports(signals=data_context["signals"], mantic_summary=mantic_summary)
        )

        # ---------------------------------------------------------------
        # 4b. Inject historical context (if snapshots exist)
        # ---------------------------------------------------------------
        if repository is not None:
            try:
                snapshot_count = repository.count_snapshots()
                if snapshot_count > 1:
                    from cip.domains.health.domain_logic.trend_analyzer import TrendAnalyzer

                    trend_analyzer = TrendAnalyzer(repository)
                    signal_trends = {}
                    for sname in LAYER_NAMES:
                        signal_trends[sname] = trend_analyzer.compute_signal_trend(sname)
                    divergences = trend_analyzer.detect_divergence_patterns()

                    data_context["historical"] = {
                        "snapshots_available": snapshot_count,
                        "signal_trends": signal_trends,
                        "divergence_patterns": divergences,
                    }
                    logger.info(
                        "Injected historical context: %d snapshots, %d divergences",
                        snapshot_count, len(divergences),
                    )
            except Exception:
                logger.exception("Failed to compute historical context — continuing without it")

        # ---------------------------------------------------------------
        # 5. Select scaffold -> privacy filter -> apply -> invoke LLM
        # ---------------------------------------------------------------
        tool_context = {"mantic_summary": mantic_summary}
        scaffold = engine.select(
            tool_name="personal_health_signal",
            user_input=period,
            caller_scaffold_id=scaffold_id,
            tool_context=tool_context,
        )

        xd_context = None
        if cross_domain_context:
            try:
                xd_context = json.loads(cross_domain_context)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Invalid cross_domain_context JSON, ignoring input"
                )

        # Apply privacy filter — only the filtered context reaches the LLM prompt
        llm_data_context = build_llm_data_context(
            full_data_context=data_context,
            privacy_mode=effective_privacy_mode,
            include_mantic_raw=include_mantic_raw,
        )

        assembled = engine.apply(
            scaffold=scaffold,
            user_query=f"Assess my personal health for {period}",
            data_context=llm_data_context,
            cross_domain_context=xd_context,
            tone_variant=tone_variant,
            output_format=output_format,
        )

        response = await llm_client.invoke(
            assembled_prompt=assembled,
            scaffold=scaffold,
            data_context=llm_data_context,
        )

        if response.guardrail_flags:
            logger.warning(
                "Guardrail flags on personal_health_signal: %s",
                response.guardrail_flags,
            )

        # ---------------------------------------------------------------
        # 6. Persist snapshot to health data bank (if storage enabled)
        # ---------------------------------------------------------------
        if repository is not None and effective_store_mode != "none":
            try:
                from datetime import datetime, timezone

                from cip.core.storage.models import HealthSnapshot

                snapshot = HealthSnapshot(
                    id="",  # auto-generated UUID
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source=health_data_provider.data_source,
                    period=period,
                    vitals_data=vitals_data,
                    labs_data=lab_results,
                    activity_data=activity_data,
                    preventive_data=preventive_care,
                    biometrics_data=biometrics,
                    vital_stability=layer_values[0],
                    metabolic_balance=layer_values[1],
                    activity_recovery=layer_values[2],
                    preventive_readiness=layer_values[3],
                    friction_m_score=friction_result.get("m_score"),
                    friction_detected=friction_result.get("alert") is not None,
                    emergence_m_score=emergence_result.get("m_score"),
                    emergence_detected=emergence_result.get("window_detected", False),
                    emergence_window_type=emergence_result.get("window_type"),
                    provenance=health_data_provider.get_provenance(),
                )
                snapshot_id = repository.save_snapshot(snapshot)
                logger.info("Persisted health snapshot %s", snapshot_id)
            except Exception:
                logger.exception("Failed to persist health snapshot — continuing")

        return response.content
