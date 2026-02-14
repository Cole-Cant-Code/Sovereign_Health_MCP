"""Unit tests for the personal_health_signal MCP tool."""

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


@pytest.fixture
def client(mock_mantic_client):
    """Create an MCP client connected to the server with mock Mantic."""
    mcp = create_app(mantic_client_override=mock_mantic_client)
    return Client(mcp)


def test_tool_returns_content(client):
    """personal_health_signal should return non-empty LLM content."""
    async def _check():
        async with client:
            result = await client.call_tool("personal_health_signal", {})
            assert result
    _run(_check())


def test_tool_accepts_period(client):
    """Tool should accept a period parameter."""
    async def _check():
        async with client:
            result = await client.call_tool(
                "personal_health_signal", {"period": "last_90_days"}
            )
            assert result
    _run(_check())


def test_tool_appears_in_tool_list(client):
    """personal_health_signal should be discoverable."""
    async def _check():
        async with client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "personal_health_signal" in tool_names
    _run(_check())


def test_tool_accepts_tone_variant(client):
    """Tool should accept tone_variant parameter."""
    async def _check():
        async with client:
            result = await client.call_tool(
                "personal_health_signal", {"tone_variant": "clinical"}
            )
            assert result
    _run(_check())
