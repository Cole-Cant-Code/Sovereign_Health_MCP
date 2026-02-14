"""Inner LLM client — the bridge between scaffolds and LLM calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cip.core.llm.provider import LLMProvider, ProviderResponse
from cip.core.llm.response import (
    check_guardrails,
    enforce_disclaimers,
    extract_context_exports,
    sanitize_content,
)
from cip.core.llm.system_prompt import build_full_system_prompt
from cip.core.scaffold.models import AssembledPrompt, Scaffold

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured response from the inner specialist LLM."""

    content: str
    scaffold_id: str
    scaffold_version: str
    guardrail_flags: list[str] = field(default_factory=list)
    context_exports: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


class InnerLLMClient:
    """Invokes the inner specialist LLM with scaffold-assembled prompts."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def invoke(
        self,
        assembled_prompt: AssembledPrompt,
        scaffold: Scaffold,
        data_context: dict[str, Any] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Call the inner specialist LLM with an assembled scaffold prompt."""
        full_system = build_full_system_prompt(assembled_prompt.system_message)

        provider_response: ProviderResponse = await self.provider.generate(
            system_message=full_system,
            user_message=assembled_prompt.user_message,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        logger.info(
            "Inner LLM call: scaffold=%s, model=%s, tokens=%d+%d, latency=%.0fms",
            scaffold.id,
            provider_response.model,
            provider_response.input_tokens,
            provider_response.output_tokens,
            provider_response.latency_ms,
        )

        guardrail_check = check_guardrails(provider_response.content, scaffold)

        # Enforce guardrails: sanitize prohibited content before returning.
        content = sanitize_content(provider_response.content, guardrail_check)
        if not guardrail_check.passed:
            logger.warning(
                "Guardrails enforced on scaffold %s: %d prohibited patterns redacted",
                scaffold.id,
                len([f for f in guardrail_check.flags if "prohibited" in f]),
            )

        # Ensure scaffold-required disclaimers appear in the final output.
        content, disclaimer_flags = enforce_disclaimers(content, scaffold)

        # Deterministic provenance for callers: if tools provided provenance fields in
        # data_context, append a short footer so clients don't rely on the LLM to mention it.
        if data_context:
            source = data_context.get("data_source")
            note = data_context.get("data_source_note")
            if source and "Data source:" not in content:
                footer_lines = ["", "", "---", f"Data source: {source}"]
                if note:
                    footer_lines.append(f"Note: {note}")
                content += "\n".join(footer_lines)

        context_exports = extract_context_exports(
            content=content,
            scaffold=scaffold,
            data_context=data_context or {},
        )

        return LLMResponse(
            content=content,
            scaffold_id=scaffold.id,
            scaffold_version=scaffold.version,
            guardrail_flags=guardrail_check.flags + disclaimer_flags,
            context_exports=context_exports,
            usage={
                "input_tokens": provider_response.input_tokens,
                "output_tokens": provider_response.output_tokens,
            },
        )
