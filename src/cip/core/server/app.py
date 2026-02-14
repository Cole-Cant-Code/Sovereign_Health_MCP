"""CIP Personal Health MCP Server — application factory.

This module provides:
- create_app() for testability (integration tests create fresh server instances)
- Module-level `mcp` variable for FastMCP discovery (fastmcp.json points here)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastmcp import FastMCP

from cip.core.config.settings import get_settings
from cip.core.llm.client import InnerLLMClient
from cip.core.llm.provider import create_provider
from cip.core.mantic.client import ManticMCPClient
from cip.core.scaffold.engine import ScaffoldEngine
from cip.core.scaffold.loader import load_scaffold_directory
from cip.core.scaffold.registry import ScaffoldRegistry
from cip.core.storage.database import HealthDatabase
from cip.core.storage.encryption import EncryptionError, FieldEncryptor
from cip.core.storage.repository import HealthRepository
from cip.domains.health.connectors import HealthDataProvider
from cip.domains.health.connectors.providers import MockHealthDataProvider
from cip.domains.health.prompts.health_prompts import register_health_prompts
from cip.domains.health.resources.scaffolds import register_health_scaffold_resources
from cip.domains.health.tools.personal_health_signals import (
    register_personal_health_signal_tools,
)

logger = logging.getLogger(__name__)

# Scaffold YAML definitions live under src/cip/domains/health/scaffolds/
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent.parent / "domains" / "health" / "scaffolds"


def create_app(
    *,
    health_data_provider_override: HealthDataProvider | None = None,
    mantic_client_override: ManticMCPClient | None = None,
    repository_override: HealthRepository | None = None,
) -> FastMCP:
    """Create and configure the CIP Health MCP server.

    This is the main application factory. It:
    1. Creates the FastMCP server instance
    2. Initializes the scaffold registry and engine
    3. Creates the inner LLM client
    4. Creates the Mantic MCP client (for cip-mantic-core)
    5. Initializes the health data provider (mock for now)
    6. Initializes the encrypted storage layer (health data bank)
    7. Registers all tools, resources, and prompts
    """
    settings = get_settings()

    # --- Server instance ---
    server = FastMCP(
        "CIP Personal Health",
        instructions=(
            "Consumer Intelligence Protocol — Personal Health domain server. "
            "Provides scaffold-driven health signal analysis, wellness assessments, "
            "and plain-language health guidance through MCP tools "
            "powered by an inner specialist LLM."
        ),
    )

    # --- Initialize scaffold system ---
    registry = ScaffoldRegistry()
    scaffold_count = load_scaffold_directory(_SCAFFOLD_DIR, registry)
    logger.info("Loaded %d scaffolds from %s", scaffold_count, _SCAFFOLD_DIR)

    engine = ScaffoldEngine(registry)

    # --- Initialize inner LLM ---
    if settings.llm_provider == "mock":
        provider_name = "mock"
        api_key = ""
        model = ""
    elif settings.llm_provider == "anthropic":
        api_key = settings.anthropic_api_key
        model = settings.anthropic_model
        provider_name = "anthropic" if api_key else "mock"
    elif settings.llm_provider == "openai":
        api_key = settings.openai_api_key
        model = settings.openai_model
        provider_name = "openai" if api_key else "mock"
    else:  # pragma: no cover
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")

    if provider_name == "mock" and settings.llm_provider != "mock":
        logger.warning(
            "No API key configured for provider '%s'; falling back to mock provider",
            settings.llm_provider,
        )

    provider = create_provider(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
    )
    llm_client = InnerLLMClient(provider=provider)

    # --- Initialize Mantic MCP client (cip-mantic-core) ---
    if mantic_client_override is not None:
        mantic_client = mantic_client_override
    else:
        from fastmcp import Client as MCPClient

        mantic_mcp = MCPClient(settings.mantic_core_url)
        mantic_client = ManticMCPClient(mantic_mcp)
        logger.info("Mantic client configured for %s", settings.mantic_core_url)

    # --- Initialize health data provider ---
    if health_data_provider_override is not None:
        health_provider = health_data_provider_override
    else:
        health_provider = MockHealthDataProvider()
        logger.info("Using mock health data provider")

    # --- Initialize encrypted storage (health data bank) ---
    repository: HealthRepository | None = None
    if repository_override is not None:
        repository = repository_override
    elif settings.encryption_key:
        try:
            encryptor = FieldEncryptor(settings.encryption_key)
            health_db = HealthDatabase(settings.db_path)
            health_db.initialize()
            repository = HealthRepository(health_db, encryptor)
            logger.info(
                "Health data bank initialized: %s (schema v%d)",
                settings.db_path,
                health_db.get_schema_version(),
            )
        except EncryptionError as exc:
            logger.error("Failed to initialize storage: %s", exc)
            logger.warning("Continuing without persistence — data will not be stored")
    else:
        logger.info(
            "No ENCRYPTION_KEY configured — running without persistence. "
            "Set ENCRYPTION_KEY to enable the health data bank."
        )

    # --- Register tools ---
    @server.tool
    def health_check() -> dict:
        """Check server health and return basic status information."""
        status = {
            "status": "ok",
            "server": "CIP Personal Health",
            "version": "0.1.0",
            "scaffolds_loaded": scaffold_count,
            "mantic_core_url": settings.mantic_core_url,
            "storage_enabled": repository is not None,
        }
        if repository is not None:
            status["snapshots_stored"] = repository.count_snapshots()
        return status

    # --- Register Mantic health signal tools (MCP-to-MCP via cip-mantic-core) ---
    register_personal_health_signal_tools(
        server, engine, llm_client, health_provider, mantic_client, repository
    )
    logger.info("Personal health signal tools registered (MCP-to-MCP via cip-mantic-core)")

    # --- Register manual entry tools (requires storage) ---
    if repository is not None:
        from cip.domains.health.tools.manual_entry_tools import register_manual_entry_tools

        register_manual_entry_tools(server, repository)
        logger.info("Manual entry tools registered")

        # --- Register longitudinal trend tools (requires storage) ---
        from cip.domains.health.domain_logic.trend_analyzer import TrendAnalyzer
        from cip.domains.health.tools.health_trend_tools import register_health_trend_tools

        trend_analyzer = TrendAnalyzer(repository)
        register_health_trend_tools(server, engine, llm_client, trend_analyzer)
        logger.info("Health trend analysis tools registered")

    # --- Register resources ---
    register_health_scaffold_resources(server, registry)

    # --- Register prompts ---
    register_health_prompts(server)

    return server


# Module-level instance for FastMCP discovery (fastmcp.json: "server": "...app.py:mcp").
# Lazy: only created when this module is loaded directly (not when tests import create_app).
def __getattr__(name: str):
    if name == "mcp":
        global mcp  # noqa: PLW0603
        mcp = create_app()
        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
