"""MCP Tool for personal health signal analysis (Mantic + privacy integration via MCP)."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.audit.logger import AuditLogger
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


# ---------------------------------------------------------------------------
# Safety helpers (deterministic, enforced before any LLM call)
# ---------------------------------------------------------------------------

_DETECTION_THRESHOLD_FALLBACK = 0.42


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _detect_escalation_triggers(
    *, layer_values: list[float], vitals_data: dict[str, Any]
) -> list[str]:
    """Return escalation trigger identifiers derived from raw data/signals."""
    triggers: list[str] = []

    # Trigger: all four signals are very low (system-wide risk)
    if len(layer_values) == 4 and all(isinstance(v, (int, float)) and v < 0.3 for v in layer_values):
        triggers.append("all_signals_below_0.3")

    # Trigger: very high systolic BP reading (vitals safety guardrail)
    systolic = _safe_float(
        (vitals_data.get("blood_pressure") or {}).get("systolic_avg")
        if isinstance(vitals_data, dict)
        else None
    )
    if systolic is not None and systolic > 180:
        triggers.append("systolic_over_180")

    return triggers


def _render_escalation_response(
    *, triggers: list[str], vitals_data: dict[str, Any], signals: dict[str, float]
) -> str:
    """Build a deterministic escalation response (no LLM)."""
    lines: list[str] = []
    lines.append("Safety escalation: please seek professional help")
    lines.append("")
    lines.append(
        "This tool detected one or more safety triggers in your health signals/vitals. "
        "This is not a diagnosis, but it is a strong reason to contact a qualified healthcare "
        "professional promptly."
    )

    systolic = _safe_float((vitals_data.get("blood_pressure") or {}).get("systolic_avg"))
    diastolic = _safe_float((vitals_data.get("blood_pressure") or {}).get("diastolic_avg"))

    lines.append("")
    lines.append("Detected triggers:")
    for t in triggers:
        if t == "systolic_over_180":
            extra = f" (systolic_avg={systolic:g} mmHg)" if systolic is not None else ""
            lines.append(f"- Very high systolic blood pressure (> 180 mmHg){extra}")
        elif t == "all_signals_below_0.3":
            lines.append("- All four computed health signals are very low (< 0.3)")
        else:
            lines.append(f"- {t}")

    lines.append("")
    lines.append("What to do now:")
    lines.append(
        "1. If you have severe symptoms (e.g., chest pain, trouble breathing, fainting, confusion), "
        "call local emergency services immediately."
    )
    lines.append(
        "2. Otherwise, contact your healthcare provider or an urgent care clinic promptly to review these readings."
    )
    lines.append(
        "3. If you can, re-check the measurement(s) under calm conditions (rest ~5 minutes, correct cuff fit/position) "
        "and share repeated readings with a clinician."
    )

    # Include the four signals (these are already consumer-friendly abstractions).
    if signals:
        lines.append("")
        lines.append("Current signal snapshot (0-1):")
        for name in LAYER_NAMES:
            if name in signals:
                lines.append(f"- {name}: {signals[name]:.4f}")

    lines.append("")
    lines.append("---")
    lines.append("Disclaimers:")
    lines.append(
        "- This is a personal health assessment, not medical advice. Consult a qualified healthcare provider for medical recommendations."
    )
    return "\n".join(lines)


def _local_mantic_summary_from_signals(layer_values: list[float]) -> dict[str, Any]:
    """Fallback Mantic-like summary when cip-mantic-core is unavailable."""
    if not layer_values:
        return {
            "friction_level": "moderate",
            "emergence_window": False,
            "limiting_factor": None,
            "dominant_layer": None,
            "coherence": None,
            "note": "mantic_unavailable",
        }

    lo = min(layer_values)
    hi = max(layer_values)
    signal_range = hi - lo
    coherence = max(0.0, min(1.0, 1.0 - signal_range))

    # Divergence severity is driven by spread; keep thresholds coarse.
    if signal_range < 0.25:
        friction_level = "low"
    elif signal_range < 0.5:
        friction_level = "moderate"
    else:
        friction_level = "high"

    limiting_factor = None
    if len(layer_values) == len(LAYER_NAMES):
        limiting_factor = LAYER_NAMES[layer_values.index(lo)]

    emergence_window = bool(
        coherence >= 0.7 and all(v >= _DETECTION_THRESHOLD_FALLBACK for v in layer_values)
    )

    return {
        "friction_level": friction_level,
        "emergence_window": emergence_window,
        "limiting_factor": limiting_factor,
        "dominant_layer": None,
        "coherence": round(coherence, 4),
        "note": "mantic_unavailable",
    }


_SIGNAL_CORE_PROFILE = "signal_core"
_SIGNAL_CORE_TO_HEALTH_LAYER: dict[str, str] = {
    "micro": "vital_stability",
    "meso": "activity_recovery",
    "macro": "metabolic_balance",
    "meta": "preventive_readiness",
}


def _extract_profile_names(resp: dict[str, Any]) -> set[str]:
    """Extract profile names from list_domain_profiles output (supports multiple shapes)."""
    raw = resp.get("profiles", [])
    names: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict) and isinstance(item.get("domain_name"), str):
                names.add(item["domain_name"])
    return names


def _mantic_layer_values_for_profile(profile_name: str, layer_values: list[float]) -> list[float]:
    """Reorder layer values to match the target Mantic profile's layer order."""
    if profile_name == _SIGNAL_CORE_PROFILE:
        # health order: [vital, metabolic, activity, preventive]
        # signal_core:  [micro, meso, macro, meta] -> [vital, activity, metabolic, preventive]
        if len(layer_values) == 4:
            return [layer_values[0], layer_values[2], layer_values[1], layer_values[3]]
    return layer_values


def _map_mantic_factor(profile_name: str, factor: str | None) -> str | None:
    """Map profile-specific factors (e.g. limiting_factor) back to health layer names."""
    if factor is None:
        return None
    if profile_name == _SIGNAL_CORE_PROFILE:
        return _SIGNAL_CORE_TO_HEALTH_LAYER.get(factor, factor)
    return factor


def register_personal_health_signal_tools(
    mcp: FastMCP,
    engine: ScaffoldEngine,
    llm_client: InnerLLMClient,
    health_data_provider: HealthDataProvider,
    mantic_client: ManticMCPClient,
    repository: HealthRepository | None = None,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Register personal health signal tools on the MCP server.

    These tools call cip-mantic-core via MCP for anomaly detection.
    When a repository is provided, analysis results are persisted to
    the encrypted health data bank.
    """

    # Cache profile listing to avoid a network round-trip on every tool call.
    _mantic_profiles_cache: set[str] | None = None

    async def _get_mantic_profiles() -> set[str]:
        nonlocal _mantic_profiles_cache
        if _mantic_profiles_cache is not None:
            return _mantic_profiles_cache
        try:
            resp = await mantic_client.list_profiles()
            _mantic_profiles_cache = _extract_profile_names(resp)
        except Exception:
            logger.exception("Failed to list cip-mantic-core profiles")
            _mantic_profiles_cache = set()
        return _mantic_profiles_cache

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
        start_time = time.monotonic()
        snapshot_id: str | None = None

        effective_privacy_mode = _validate_privacy_mode(privacy_mode)
        effective_store_mode = store_mode if store_mode in ("encrypted", "none") else "encrypted"
        if effective_privacy_mode == "strict":
            include_mantic_raw = False

        try:
            # -----------------------------------------------------------
            # 1. Gather data (5 async calls)
            # -----------------------------------------------------------
            vitals_data = await health_data_provider.get_vitals(period)
            lab_results = await health_data_provider.get_lab_results()
            activity_data = await health_data_provider.get_activity_data(period)
            preventive_care = await health_data_provider.get_preventive_care()
            biometrics = await health_data_provider.get_biometrics()

            # -----------------------------------------------------------
            # 2. Translate to Mantic signals (deterministic, no LLM)
            # -----------------------------------------------------------
            signals = translate_health_to_mantic(
                vitals_data=vitals_data,
                lab_results=lab_results,
                activity_data=activity_data,
                preventive_care=preventive_care,
                biometrics=biometrics,
            )
            layer_values = signals.as_layer_values()

            # -----------------------------------------------------------
            # 3. Deterministic safety escalation (before any LLM call)
            # -----------------------------------------------------------
            escalation_triggers = _detect_escalation_triggers(
                layer_values=layer_values, vitals_data=vitals_data
            )

            # Precompute deterministic signal snapshot for both LLM and deterministic responses.
            signal_snapshot = {
                name: round(value, 4) for name, value in zip(LAYER_NAMES, layer_values)
            }

            if escalation_triggers:
                # Skip Mantic + LLM; return deterministic escalation guidance.
                content = _render_escalation_response(
                    triggers=escalation_triggers,
                    vitals_data=vitals_data,
                    signals=signal_snapshot,
                )

                # Persist snapshot even on escalation (if storage enabled).
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
                            provenance=health_data_provider.get_provenance(),
                        )
                        snapshot_id = repository.save_snapshot(snapshot)
                        logger.info("Persisted health snapshot %s (escalation)", snapshot_id)
                    except Exception:
                        logger.exception("Failed to persist health snapshot — continuing")

                elapsed_ms = (time.monotonic() - start_time) * 1000
                if audit_logger is not None:
                    audit_logger.log_tool_call(
                        tool_name="personal_health_signal",
                        tool_input={"period": period, "privacy_mode": effective_privacy_mode},
                        privacy_mode=effective_privacy_mode,
                        llm_provider=llm_client.provider_name,
                        llm_disclosed=False,
                        snapshot_id=snapshot_id,
                        duration_ms=elapsed_ms,
                        # Keep metadata PHI-free.
                        metadata={"escalation_path": True},
                    )

                return content

            # -----------------------------------------------------------
            # 4. Run Mantic detection via cip-mantic-core (both modes)
            # -----------------------------------------------------------
            mantic_profile_used = PROFILE_NAME
            mantic_profile_fallback = False

            profiles = await _get_mantic_profiles()
            if profiles and PROFILE_NAME not in profiles and _SIGNAL_CORE_PROFILE in profiles:
                mantic_profile_used = _SIGNAL_CORE_PROFILE
                mantic_profile_fallback = True

            friction_result: dict[str, Any] = {}
            emergence_result: dict[str, Any] = {}
            mantic_summary: dict[str, Any] = {}

            try:
                mantic_layer_values = _mantic_layer_values_for_profile(
                    mantic_profile_used, layer_values
                )

                friction_envelope = await mantic_client.detect_friction(
                    profile_name=mantic_profile_used,
                    layer_values=mantic_layer_values,
                )
                friction_result = friction_envelope["result"]

                emergence_envelope = await mantic_client.detect_emergence(
                    profile_name=mantic_profile_used,
                    layer_values=mantic_layer_values,
                )
                emergence_result = emergence_envelope["result"]

                # -----------------------------------------------------------
                # 4b. Build structured Mantic summary
                # -----------------------------------------------------------
                coupling_data = friction_result.get("layer_coupling")
                # layer_coupling can be either:
                #   - dict  {"coherence": 0.78}           (cip-mantic-core ≥ 1.0)
                #   - list  [{"pair": [...], "delta": …}] (legacy / future)
                if isinstance(coupling_data, dict):
                    coherence_val = coupling_data.get("coherence")
                elif isinstance(coupling_data, list) and coupling_data:
                    first = coupling_data[0]
                    coherence_val = first.get("coherence") if isinstance(first, dict) else None
                else:
                    coherence_val = None

                limiting = _map_mantic_factor(
                    mantic_profile_used, emergence_result.get("limiting_factor")
                )

                mantic_summary = {
                    "friction_level": _friction_level_from_score(friction_result.get("m_score")),
                    "emergence_window": emergence_result.get("window_detected", False),
                    "limiting_factor": limiting,
                    "dominant_layer": (friction_result.get("layer_visibility") or {}).get("dominant"),
                    "coherence": coherence_val,
                }

            except Exception:
                # If Mantic is unavailable/misconfigured, fall back to a local
                # coherence/divergence summary and still provide an analysis.
                logger.exception("Mantic detection failed — falling back to local summary")
                mantic_summary = _local_mantic_summary_from_signals(layer_values)
                mantic_profile_used = "unavailable"
                mantic_profile_fallback = False

            # -----------------------------------------------------------
            # 5. Build full data_context
            # -----------------------------------------------------------
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
                "signals": signal_snapshot,
                "signal_details": signals.details,
                "mantic_summary": mantic_summary,
                "mantic_raw": {"friction": friction_result, "emergence": emergence_result},
                "mantic_profile": mantic_profile_used,
                "mantic_profile_fallback": mantic_profile_fallback,
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

            # -----------------------------------------------------------
            # 5b. Inject historical context (if snapshots exist)
            # -----------------------------------------------------------
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

            # -----------------------------------------------------------
            # 6. Select scaffold -> privacy filter -> apply -> invoke LLM
            # -----------------------------------------------------------
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

            # Apply privacy filter
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

            # -----------------------------------------------------------
            # 7. Persist snapshot to health data bank (if storage enabled)
            # -----------------------------------------------------------
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

            # -----------------------------------------------------------
            # 8. Audit log (success)
            # -----------------------------------------------------------
            elapsed_ms = (time.monotonic() - start_time) * 1000
            if audit_logger is not None:
                audit_logger.log_tool_call(
                    tool_name="personal_health_signal",
                    tool_input={"period": period, "privacy_mode": effective_privacy_mode},
                    privacy_mode=effective_privacy_mode,
                    llm_provider=llm_client.provider_name,
                    llm_disclosed=(llm_client.provider_name != "mock"),
                    snapshot_id=snapshot_id,
                    duration_ms=elapsed_ms,
                    metadata={
                        "mantic_profile": mantic_profile_used,
                        "mantic_profile_fallback": mantic_profile_fallback,
                    },
                )

            return response.content

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            if audit_logger is not None:
                audit_logger.log_tool_call(
                    tool_name="personal_health_signal",
                    tool_input={"period": period, "privacy_mode": effective_privacy_mode},
                    privacy_mode=effective_privacy_mode,
                    llm_provider=llm_client.provider_name,
                    llm_disclosed=False,
                    duration_ms=elapsed_ms,
                    status="failure",
                    error_type=type(exc).__name__,
                )
            raise
