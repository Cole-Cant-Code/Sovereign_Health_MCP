"""Application settings loaded from environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """CIP Health server configuration."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Server
    # Default to loopback to avoid accidentally exposing a health MCP server
    # to your LAN/WAN. Opt into `0.0.0.0` explicitly when you intend remote access.
    cip_host: str = "127.0.0.1"
    cip_port: int = 8001
    cip_log_level: str = "info"
    # Additional explicit guard: if binding to non-loopback, refuse to start unless
    # this is set true (there is currently no auth layer).
    cip_allow_insecure_bind: bool = False

    # Inner LLM
    llm_provider: Literal["anthropic", "openai", "mock"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Mantic (cip-mantic-core MCP service)
    mantic_core_url: str = "http://127.0.0.1:8002/mcp"

    # Storage (health data bank)
    db_path: str = "~/.cip/health.db"

    # Privacy
    default_privacy_mode: str = "strict"

    # Connectors
    apple_health_export_path: str = ""

    # Encryption
    encryption_key: str = ""


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
