"""CIP server entry point — ``python -m cip.core.server.main``."""

from __future__ import annotations

import logging
from ipaddress import ip_address

from cip.core.config.settings import get_settings
from cip.core.server.app import create_app


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def run() -> None:
    """Start the CIP MCP server with Streamable HTTP transport."""
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.cip_log_level.upper(), logging.INFO))

    logger = logging.getLogger(__name__)
    if not settings.cip_allow_insecure_bind and not _is_loopback_host(settings.cip_host):
        raise RuntimeError(
            "Refusing to bind CIP server to a non-loopback host without an auth layer. "
            "Set CIP_ALLOW_INSECURE_BIND=true to override (unsafe)."
        )
    logger.info(
        "Starting CIP Personal Health server on %s:%d",
        settings.cip_host,
        settings.cip_port,
    )

    mcp = create_app()
    mcp.run(
        transport="streamable-http",
        host=settings.cip_host,
        port=settings.cip_port,
    )


if __name__ == "__main__":
    run()
