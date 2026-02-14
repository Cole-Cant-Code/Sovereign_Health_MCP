"""Scaffold engine — orchestrates selection and application of scaffolds."""

from __future__ import annotations

import logging
from typing import Any

from cip.core.scaffold.matcher import match_scaffold
from cip.core.scaffold.models import AssembledPrompt, Scaffold
from cip.core.scaffold.registry import ScaffoldRegistry
from cip.core.scaffold.renderer import render_scaffold

logger = logging.getLogger(__name__)

DEFAULT_SCAFFOLD_ID = "personal_health_signal"


class ScaffoldNotFoundError(Exception):
    """Raised when no scaffold can be selected for a request."""


class ScaffoldEngine:
    """Selects the right scaffold and assembles it into an LLM prompt.

    This is the core of the Negotiated Expertise Pattern.
    """

    def __init__(self, registry: ScaffoldRegistry) -> None:
        self.registry = registry

    def select(
        self,
        tool_name: str,
        user_input: str = "",
        caller_scaffold_id: str | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> Scaffold:
        """Select the best scaffold for this invocation.

        Raises ScaffoldNotFoundError if no scaffold matches and no default exists.
        """
        # Context-aware routing for health: prefer specialized scaffolds when a
        # deterministic detector (Mantic) indicates a risk window or growth window.
        if tool_context and tool_name == "personal_health_signal" and not caller_scaffold_id:
            ms = tool_context.get("mantic_summary") if isinstance(tool_context, dict) else None
            if isinstance(ms, dict):
                if ms.get("emergence_window") is True:
                    growth = self.registry.get("personal_health_signal.growth")
                    if growth:
                        return growth
                coherence = ms.get("coherence")
                friction_level = ms.get("friction_level")
                if friction_level == "high" or (
                    isinstance(coherence, (int, float)) and coherence < 0.6
                ):
                    risk = self.registry.get("personal_health_signal.risk")
                    if risk:
                        return risk

        scaffold = match_scaffold(
            registry=self.registry,
            tool_name=tool_name,
            user_input=user_input,
            caller_scaffold_id=caller_scaffold_id,
        )

        if scaffold:
            return scaffold

        # Fall back to domain default
        default = self.registry.get(DEFAULT_SCAFFOLD_ID)
        if default:
            logger.info("Using default scaffold: %s", DEFAULT_SCAFFOLD_ID)
            return default

        raise ScaffoldNotFoundError(
            f"No scaffold found for tool='{tool_name}', input='{user_input[:50]}', "
            f"and no default scaffold '{DEFAULT_SCAFFOLD_ID}' exists"
        )

    def apply(
        self,
        scaffold: Scaffold,
        user_query: str,
        data_context: dict[str, Any],
        cross_domain_context: dict[str, Any] | None = None,
        tone_variant: str | None = None,
        output_format: str | None = None,
    ) -> AssembledPrompt:
        """Combine scaffold + user query + data into a complete LLM prompt."""
        return render_scaffold(
            scaffold=scaffold,
            user_query=user_query,
            data_context=data_context,
            cross_domain_context=cross_domain_context,
            tone_variant=tone_variant,
            output_format=output_format,
        )
