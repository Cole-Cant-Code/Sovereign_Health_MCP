"""MCP client for cip-mantic-core anomaly detection service.

This replaces direct ``from mantic_thinking.tools.generic_detect import detect``
with MCP-to-MCP calls via fastmcp.Client.  The cip-mantic-core server handles
profile routing, governance, and audit trails.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cip.core.mantic.models import ManticEnvelope

logger = logging.getLogger(__name__)


class ManticMCPClient:
    """Client for the cip-mantic-core MCP server.

    Wraps friction and emergence detection into simple async methods
    that return the full Mantic envelope (including audit trail).

    Usage::

        from fastmcp import Client
        mcp = Client("http://127.0.0.1:8002/mcp")
        mantic = ManticMCPClient(mcp)

        envelope = await mantic.detect_friction("consumer_health", [0.7, 0.6, 0.5, 0.8])
        result = envelope["result"]
    """

    def __init__(self, mcp_client: Any) -> None:
        """Initialise with a connected fastmcp.Client (or compatible)."""
        self._client = mcp_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_friction(
        self,
        profile_name: str,
        layer_values: list[float],
        *,
        f_time: float = 1.0,
        threshold_override: float | None = None,
        interaction_mode: str = "dynamic",
    ) -> dict[str, Any]:
        """Run friction (divergence) detection via cip-mantic-core.

        Returns the full envelope dict.  Callers typically read
        ``envelope["result"]`` which has the same keys as the old
        ``generic_detect(mode="friction")`` return value.
        """
        args: dict[str, Any] = {
            "profile_name": profile_name,
            "layer_values": layer_values,
            "f_time": f_time,
            "interaction_mode": interaction_mode,
        }
        if threshold_override is not None:
            args["threshold_override"] = threshold_override

        return await self._call_tool("mantic_detect_friction", args)

    async def detect_emergence(
        self,
        profile_name: str,
        layer_values: list[float],
        *,
        f_time: float = 1.0,
        threshold_override: float | None = None,
        interaction_mode: str = "dynamic",
    ) -> dict[str, Any]:
        """Run emergence (alignment) detection via cip-mantic-core.

        Returns the full envelope dict.  Callers typically read
        ``envelope["result"]`` which has the same keys as the old
        ``generic_detect(mode="emergence")`` return value.
        """
        args: dict[str, Any] = {
            "profile_name": profile_name,
            "layer_values": layer_values,
            "f_time": f_time,
            "interaction_mode": interaction_mode,
        }
        if threshold_override is not None:
            args["threshold_override"] = threshold_override

        return await self._call_tool("mantic_detect_emergence", args)

    async def health_check(self) -> dict[str, Any]:
        """Verify cip-mantic-core is reachable and report status."""
        return await self._call_tool("health_check", {})

    async def list_profiles(self) -> dict[str, Any]:
        """List all registered domain profiles."""
        return await self._call_tool("list_domain_profiles", {})

    def parse_envelope(self, raw: dict[str, Any]) -> ManticEnvelope:
        """Parse a raw dict into a typed ManticEnvelope."""
        return ManticEnvelope.from_dict(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool on cip-mantic-core and return the parsed response.

        fastmcp.Client.call_tool returns a list of content blocks.
        We expect a single content block containing JSON, but we accept:
        - text blocks containing JSON
        - json/data blocks (already parsed dicts in some transports)
        """
        logger.debug("Calling cip-mantic-core tool %s", tool_name)

        try:
            result = await self._client.call_tool(tool_name, arguments)
        except Exception:
            logger.exception("Failed to call cip-mantic-core tool %s", tool_name)
            raise ManticConnectionError(
                f"Failed to call cip-mantic-core tool '{tool_name}'. "
                "Is the cip-mantic-core server running?"
            ) from None

        if not result:
            raise ManticResponseError(f"Empty response from {tool_name}")

        payload = _extract_payload(result)
        if payload is None:
            raise ManticResponseError(
                f"No usable content in response from {tool_name}"
            )

        if isinstance(payload, str):
            try:
                parsed: Any = json.loads(payload)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ManticResponseError(
                    f"Invalid JSON from {tool_name}: {exc}"
                ) from exc
        else:
            parsed = payload

        if not isinstance(parsed, dict):
            raise ManticResponseError(
                f"Expected JSON object from {tool_name}, got {type(parsed).__name__}"
            )

        if parsed.get("status") == "error":
            error_msg = _format_error(parsed.get("error"))
            raise ManticDetectionError(
                f"cip-mantic-core returned error: {error_msg}"
            )

        # Detection tools must return a Mantic envelope with a 'result' object.
        if tool_name.startswith("mantic_detect"):
            if parsed.get("status") != "ok":
                raise ManticResponseError(
                    f"Unexpected status from {tool_name}: {parsed.get('status')!r}"
                )
            if "result" not in parsed or not isinstance(parsed.get("result"), dict):
                raise ManticResponseError(
                    f"Missing or invalid 'result' in response from {tool_name}"
                )

        return parsed


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------

class ManticClientError(Exception):
    """Base exception for ManticMCPClient errors."""


class ManticConnectionError(ManticClientError):
    """Could not reach cip-mantic-core."""


class ManticResponseError(ManticClientError):
    """Response from cip-mantic-core was unexpected."""


class ManticDetectionError(ManticClientError):
    """cip-mantic-core returned an error status."""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_text(result: Any) -> str | None:
    """Extract text from a fastmcp tool result.

    fastmcp.Client.call_tool can return:
    - A list of content blocks (each with .type and .text)
    - A single content block
    - A raw string (in some mock scenarios)
    """
    if isinstance(result, str):
        return result

    if isinstance(result, list):
        for block in result:
            if hasattr(block, "text"):
                return block.text
            if isinstance(block, str):
                return block
        return None

    if hasattr(result, "text"):
        return result.text

    return None


def _extract_payload(result: Any) -> Any | None:
    """Extract a usable payload from a fastmcp tool result.

    Some transports return:
    - list[ContentBlock] where ContentBlock.type is 'text' and ContentBlock.text contains JSON
    - list[ContentBlock] where ContentBlock.type is 'json' and ContentBlock.data is already a dict
    - a single ContentBlock
    - a raw string
    - an already-parsed dict (in certain mocks)
    """
    if isinstance(result, (dict, list)) and not isinstance(result, str):
        # dict: already parsed payload
        if isinstance(result, dict):
            return result

        # list: prefer JSON/data blocks, then text blocks
        if isinstance(result, list):
            for block in result:
                payload = _payload_from_block(block, prefer_json=True)
                if payload is not None:
                    return payload
            for block in result:
                payload = _payload_from_block(block, prefer_json=False)
                if payload is not None:
                    return payload
            return None

    if isinstance(result, str):
        return result

    # Single content block object
    payload = _payload_from_block(result, prefer_json=True)
    if payload is not None:
        return payload
    return _payload_from_block(result, prefer_json=False)


def _payload_from_block(block: Any, *, prefer_json: bool) -> Any | None:
    """Extract payload from a single content block."""
    # Dict-like blocks
    if isinstance(block, dict):
        if prefer_json:
            if "data" in block:
                return block["data"]
            if "json" in block:
                return block["json"]
        if "text" in block:
            return block["text"]
        return None

    # Objects with attributes
    if prefer_json:
        if getattr(block, "type", None) == "json":
            for attr in ("data", "json"):
                if hasattr(block, attr):
                    return getattr(block, attr)
        for attr in ("data", "json"):
            if hasattr(block, attr):
                return getattr(block, attr)

    if hasattr(block, "text"):
        return block.text

    if isinstance(block, str):
        return block

    return None


def _format_error(error: Any) -> str:
    """Format an error payload from cip-mantic-core into a human-readable string."""
    if error is None:
        return "Unknown error"
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        # Common pattern: {"code": "...", "message": "..."}
        msg = error.get("message") or error.get("code")
        return msg if isinstance(msg, str) and msg else str(error)
    return str(error)
