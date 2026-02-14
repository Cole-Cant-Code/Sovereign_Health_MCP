"""LLM provider protocol — abstract interface for inner LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    """Response from an LLM provider."""

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: float


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract interface for inner LLM calls."""

    async def generate(
        self,
        system_message: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> ProviderResponse: ...


def create_provider(
    provider_name: str,
    api_key: str = "",
    model: str = "",
) -> LLMProvider:
    """Factory function to create an LLM provider by name.

    Args:
        provider_name: "anthropic", "openai", or "mock"
        api_key: API key for the provider.
        model: Model identifier override.

    Returns:
        An LLMProvider instance.
    """
    if provider_name == "anthropic":
        from cip.core.llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model or "claude-sonnet-4-20250514")
    elif provider_name == "openai":
        from cip.core.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o")
    elif provider_name == "mock":
        from cip.core.llm.providers.mock import MockProvider

        return MockProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
