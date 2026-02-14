"""Response parsing and guardrail enforcement for inner LLM output."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from cip.core.scaffold.models import Scaffold

logger = logging.getLogger(__name__)


@dataclass
class GuardrailCheck:
    """Result of checking a response against scaffold guardrails."""

    passed: bool
    flags: list[str] = field(default_factory=list)


def check_guardrails(content: str, scaffold: Scaffold) -> GuardrailCheck:
    """Check LLM response content against scaffold guardrails."""
    flags: list[str] = []
    content_lower = content.lower()

    for trigger in scaffold.guardrails.escalation_triggers:
        trigger_keywords = trigger.lower().split()
        matches = sum(1 for word in trigger_keywords if word in content_lower)
        if matches >= len(trigger_keywords) * 0.6:
            flags.append(f"escalation_trigger_detected: {trigger}")

    # Heuristic enforcement of "prohibited_actions". Scaffold-provided actions are
    # natural language, so we detect common unsafe patterns rather than attempting
    # to fully parse each action string.
    prohibited_indicators = {
        "making medical diagnoses": (
            "you have been diagnosed",
            "you are suffering from",
            "this is a sign of",
            "you have a condition",
        ),
        "prescribing treatments": (
            "take this medication",
            "stop taking your medication",
            "i prescribe",
            "you should take",
        ),
        "providing specific dietary plans": (
            "eat exactly",
            "your daily caloric intake should be",
            "follow this meal plan",
        ),
        "making disease predictions": (
            "you will develop",
            "you are at high risk of dying",
            "this will lead to",
            "guaranteed to cure",
        ),
    }

    for action, patterns in prohibited_indicators.items():
        for pattern in patterns:
            if pattern in content_lower:
                flags.append(
                    f"prohibited_pattern_detected: {action} ('{pattern}')"
                )

    passed = not any(f.startswith("prohibited_pattern") for f in flags)

    if flags:
        logger.warning("Guardrail flags for scaffold %s: %s", scaffold.id, flags)

    return GuardrailCheck(passed=passed, flags=flags)


def sanitize_content(content: str, guardrail_check: GuardrailCheck) -> str:
    """Remove or redact prohibited patterns from LLM output.

    If the guardrail check passed, return content unchanged.
    Otherwise, redact sentences containing prohibited phrases and
    return sanitized content.
    """
    if guardrail_check.passed:
        return content

    # Build list of prohibited phrases that were detected
    prohibited_phrases: list[str] = []
    for flag in guardrail_check.flags:
        if flag.startswith("prohibited_pattern_detected:"):
            # Extract the quoted pattern: "... ('phrase')"
            match = re.search(r"\('([^']+)'\)", flag)
            if match:
                prohibited_phrases.append(match.group(1))

    if not prohibited_phrases:
        return content

    # Redact sentences containing prohibited phrases
    sanitized = content
    for phrase in prohibited_phrases:
        # Replace sentences containing the phrase with a redaction note
        pattern = re.compile(
            r"[^.!?\n]*" + re.escape(phrase) + r"[^.!?\n]*[.!?]?",
            re.IGNORECASE,
        )
        sanitized = pattern.sub(
            "[Removed: contains prohibited health guidance]",
            sanitized,
        )

    return sanitized


def enforce_disclaimers(content: str, scaffold: Scaffold) -> tuple[str, list[str]]:
    """Ensure scaffold-required disclaimers appear in the final response.

    Returns: (possibly modified content, flags)
    """
    disclaimers = [d.strip() for d in scaffold.guardrails.disclaimers if d.strip()]
    if not disclaimers:
        return content, []

    def _norm(s: str) -> str:
        return " ".join(s.lower().split())

    content_norm = _norm(content)
    missing = [d for d in disclaimers if _norm(d) not in content_norm]
    if not missing:
        return content, []

    footer = "\n\n---\nDisclaimers:\n" + "\n".join(f"- {d}" for d in missing)
    return content + footer, [f"disclaimer_appended: {d}" for d in missing]


def extract_context_exports(
    content: str,
    scaffold: Scaffold,
    data_context: dict[str, Any],
) -> dict[str, Any]:
    """Extract cross-domain context export fields from the response.

    Strategy:
    1. If the field exists in data_context, use it directly (structured data).
    2. Otherwise, attempt to extract a value from the LLM content by looking
       for patterns like "field_name: value" or "field_name is value".
    3. If neither yields a result, skip the field (don't export garbage).
    """
    exports: dict[str, Any] = {}

    for export_field in scaffold.context_exports:
        field_name = export_field.field_name

        # Strategy 1: structured data from data_context
        if field_name in data_context:
            exports[field_name] = data_context[field_name]
            continue

        # Strategy 2: extract from LLM content via pattern matching
        extracted = _extract_field_from_content(
            content, field_name, export_field.type
        )
        if extracted is not None:
            exports[field_name] = extracted

    return exports


def _extract_field_from_content(
    content: str, field_name: str, field_type: str
) -> Any:
    """Try to extract a named field value from LLM output text.

    Looks for patterns like:
    - "heart_rate: 72 bpm"
    - "bmi: 25.5"
    - "risk_level: moderate"
    """
    # Normalize field name for pattern matching (e.g. heart_rate → heart rate)
    readable = field_name.replace("_", r"[\s_]")

    if field_type in ("number", "float", "int"):
        # Match: field_name: 1234.56 or field_name is 1234.56
        pattern = re.compile(
            readable + r"[\s:]+\$?([\d,]+\.?\d*)",
            re.IGNORECASE,
        )
        match = pattern.search(content)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                return None

    elif field_type in ("string", "str", "text"):
        pattern = re.compile(
            readable + r"[\s:]+([^\n.]+)",
            re.IGNORECASE,
        )
        match = pattern.search(content)
        if match:
            return match.group(1).strip()

    return None
