"""MCP tools for viewing the audit trail.

These tools expose the PHI-free audit log, allowing the user to review
data access events and LLM disclosure history. No health data is
contained in the audit trail by design — only hashed input references.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.audit.logger import AuditLogger

logger = logging.getLogger(__name__)


def register_audit_tools(
    mcp: FastMCP,
    audit_logger: AuditLogger,
) -> None:
    """Register audit trail tools on the MCP server."""

    @mcp.tool
    async def audit_summary(
        ctx: Context,
        days: int = 30,
    ) -> str:
        """View recent data access events and LLM disclosure counts.

        The audit trail is PHI-free by design: it records which tools were
        used, when, and whether health data was sent to an external LLM,
        but never stores raw health data.

        Args:
            days: Number of days to look back (default: 30).
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        total_events = audit_logger.count_events(since=since)
        disclosure_count = audit_logger.count_disclosures(since=since)
        recent_events = audit_logger.get_events(since=since, limit=20)

        # Simplify events for display (strip internal IDs)
        display_events = []
        for event in recent_events:
            display_events.append({
                "timestamp": event.get("timestamp"),
                "action": event.get("action"),
                "tool_name": event.get("tool_name"),
                "privacy_mode": event.get("privacy_mode"),
                "llm_provider": event.get("llm_provider"),
                "llm_disclosed": bool(event.get("llm_disclosed")),
                "status": event.get("status"),
                "duration_ms": event.get("duration_ms"),
            })

        return json.dumps({
            "status": "ok",
            "period_days": days,
            "total_events": total_events,
            "llm_disclosures": disclosure_count,
            "recent_events": display_events,
            "note": (
                "This audit trail contains no health data. "
                "It tracks tool usage and whether data was sent to external LLMs."
            ),
        }, indent=2)
