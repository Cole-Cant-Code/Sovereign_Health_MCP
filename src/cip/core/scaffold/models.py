"""Data models for cognitive scaffolds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScaffoldApplicability:
    """Defines when a scaffold should be selected."""

    tools: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    intent_signals: list[str] = field(default_factory=list)


@dataclass
class ScaffoldFraming:
    """The cognitive framing the inner LLM adopts."""

    role: str = ""
    perspective: str = ""
    tone: str = ""
    tone_variants: dict[str, str] = field(default_factory=dict)


@dataclass
class ScaffoldOutputCalibration:
    """Controls the shape and content of LLM output."""

    format: str = "structured_narrative"
    format_options: list[str] = field(default_factory=lambda: ["structured_narrative"])
    max_length_guidance: str = ""
    must_include: list[str] = field(default_factory=list)
    never_include: list[str] = field(default_factory=list)


@dataclass
class ScaffoldGuardrails:
    """Safety boundaries for the inner LLM."""

    disclaimers: list[str] = field(default_factory=list)
    escalation_triggers: list[str] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=list)


@dataclass
class ContextField:
    """A single cross-domain context field definition."""

    field_name: str
    type: str
    description: str


@dataclass
class Scaffold:
    """A complete cognitive scaffold — a reasoning framework for the inner LLM."""

    id: str
    version: str
    domain: str
    display_name: str
    description: str
    applicability: ScaffoldApplicability
    framing: ScaffoldFraming
    reasoning_framework: dict[str, Any]
    domain_knowledge_activation: list[str]
    output_calibration: ScaffoldOutputCalibration
    guardrails: ScaffoldGuardrails
    context_accepts: list[ContextField] = field(default_factory=list)
    context_exports: list[ContextField] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class AssembledPrompt:
    """The final prompt sent to the inner LLM after scaffold application."""

    system_message: str
    user_message: str
    metadata: dict[str, Any] = field(default_factory=dict)
