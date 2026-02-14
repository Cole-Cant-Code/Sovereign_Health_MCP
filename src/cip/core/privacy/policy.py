"""Privacy policy for controlling what data is exposed to the inner LLM.

The inner LLM should generally operate on:
- deterministic signal scores (0-1)
- a safe Mantic summary (levels, limiting factor, coherence)
- a small set of user-friendly metrics (optionally coarsened)

Raw health records should be stored (optionally, encrypted) but not placed into prompts
unless the user explicitly opts in.
"""

from __future__ import annotations

from typing import Any, Literal

PrivacyMode = Literal["strict", "standard", "explicit"]


def _round_floats(obj: Any, ndigits: int = 2) -> Any:
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits=ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits=ndigits) for v in obj]
    return obj


def build_llm_data_context(
    *,
    full_data_context: dict[str, Any],
    privacy_mode: PrivacyMode,
    include_mantic_raw: bool,
) -> dict[str, Any]:
    """Build the minimized data_context that will be rendered into the LLM prompt."""
    period = full_data_context.get("period")
    signals = full_data_context.get("signals", {})
    mantic_summary = full_data_context.get("mantic_summary", {})
    provenance = {
        "data_source": full_data_context.get("data_source"),
        "data_source_note": full_data_context.get("data_source_note"),
    }

    base: dict[str, Any] = {
        "period": period,
        "signals": _round_floats(signals, ndigits=4),
        "mantic": mantic_summary,
        "provenance": {k: v for k, v in provenance.items() if v},
    }

    if privacy_mode == "strict":
        # No raw vitals/labs/activity; no raw Mantic outputs.
        return base

    if privacy_mode == "standard":
        # Include a small set of user-friendly metrics (still not raw lab panels).
        base.update(
            {
                "resting_heart_rate_bpm": full_data_context.get("resting_heart_rate"),
                "blood_pressure": {
                    "systolic_avg": full_data_context.get("blood_pressure_systolic"),
                    "diastolic_avg": full_data_context.get("blood_pressure_diastolic"),
                },
                "hrv_ms": full_data_context.get("hrv_ms"),
                "sleep_duration_hours": full_data_context.get("sleep_duration_hours"),
                "exercise_sessions_per_week": full_data_context.get("exercise_sessions_per_week"),
                "bmi": full_data_context.get("bmi"),
                "lab_count": full_data_context.get("lab_count"),
            }
        )
        return _round_floats(base, ndigits=2)

    # explicit
    # Allow essentially everything the tool computed, with optional raw Mantic outputs.
    explicit_ctx = dict(full_data_context)
    if not include_mantic_raw:
        explicit_ctx.pop("mantic_raw", None)
    return explicit_ctx
