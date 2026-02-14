"""Integration tests for the CIP Health MCP server."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from cip.core.server.app import create_app


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio required)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# personal_health_signal is always registered (MCP-to-MCP, no optional dep)
ALL_EXPECTED_TOOLS = [
    "health_check",
    "personal_health_signal",
]


@pytest.fixture
def client(mock_mantic_client):
    """Create an MCP client connected to the server with mock Mantic."""
    mcp = create_app(mantic_client_override=mock_mantic_client)
    return Client(mcp)


def test_server_starts_and_lists_tools(client):
    """Server should start and expose all registered tools."""
    async def _check():
        async with client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            for expected in ALL_EXPECTED_TOOLS:
                assert expected in tool_names, f"Missing tool: {expected}"
    _run(_check())


def test_health_check_returns_ok(client):
    """health_check tool should return status ok."""
    async def _check():
        async with client:
            result = await client.call_tool("health_check", {})
            assert "ok" in str(result)
    _run(_check())


def test_health_check_includes_mantic_url(client):
    """health_check should report the Mantic core URL."""
    async def _check():
        async with client:
            result = await client.call_tool("health_check", {})
            result_text = str(result)
            assert "mantic_core_url" in result_text
    _run(_check())
