"""MCP tools for longitudinal health trend analysis.

These tools query the health data bank for historical patterns,
trends, and divergences across stored snapshots.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.audit.logger import AuditLogger
    from cip.core.llm.client import InnerLLMClient
    from cip.core.scaffold.engine import ScaffoldEngine
    from cip.domains.health.domain_logic.trend_analyzer import TrendAnalyzer

logger = logging.getLogger(__name__)


def register_health_trend_tools(
    mcp: FastMCP,
    engine: ScaffoldEngine,
    llm_client: InnerLLMClient,
    trend_analyzer: TrendAnalyzer,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Register longitudinal health trend analysis tools on the MCP server."""

    @mcp.tool
    async def health_trend_analysis(
        ctx: Context,
        days: int = 90,
        scaffold_id: str | None = None,
        tone_variant: str | None = None,
    ) -> str:
        """Analyze trends in your health signals over time.

        Requires at least 2 stored health snapshots. Computes trend direction,
        volatility, and detects divergence patterns (signals moving in opposite
        directions that may need attention).

        Args:
            days: Number of days to analyze (default: 90).
            scaffold_id: Optional scaffold override.
            tone_variant: Optional tone override.
        """
        start_time = time.monotonic()
        summary = trend_analyzer.get_snapshot_summary()

        if summary["snapshots_available"] < 2:
            return json.dumps({
                "status": "insufficient_data",
                "snapshots_available": summary["snapshots_available"],
                "message": (
                    "At least 2 health snapshots are needed for trend analysis. "
                    "Run a personal health signal assessment to create snapshots."
                ),
            })

        # Compute trends for all 4 signals
        signal_names = [
            "vital_stability",
            "metabolic_balance",
            "activity_recovery",
            "preventive_readiness",
        ]
        signal_trends = {}
        for name in signal_names:
            signal_trends[name] = trend_analyzer.compute_signal_trend(name, days=days)

        # Detect divergence patterns
        divergences = trend_analyzer.detect_divergence_patterns(days=days)

        data_context = {
            "analysis_period_days": days,
            "snapshots_available": summary["snapshots_available"],
            "oldest_snapshot": summary.get("oldest_timestamp"),
            "latest_snapshot": summary.get("latest_timestamp"),
            "signal_trends": signal_trends,
            "divergence_patterns": divergences,
            "divergence_count": len(divergences),
        }

        # Use scaffold for LLM interpretation
        scaffold = engine.select(
            tool_name="health_trend_analysis",
            user_input=f"trend analysis over {days} days",
            caller_scaffold_id=scaffold_id,
        )

        assembled = engine.apply(
            scaffold=scaffold,
            user_query=f"Analyze my health trends over the last {days} days",
            data_context=data_context,
            tone_variant=tone_variant,
        )

        response = await llm_client.invoke(
            assembled_prompt=assembled,
            scaffold=scaffold,
            data_context=data_context,
        )

        # Audit log
        elapsed_ms = (time.monotonic() - start_time) * 1000
        if audit_logger is not None:
            audit_logger.log_tool_call(
                tool_name="health_trend_analysis",
                tool_input={"days": days},
                llm_provider=llm_client.provider_name,
                llm_disclosed=(llm_client.provider_name != "mock"),
                duration_ms=elapsed_ms,
            )

        return response.content

    @mcp.tool
    async def lab_trend(
        ctx: Context,
        test_name: str,
        limit: int = 10,
    ) -> str:
        """Show the trend for a specific lab test over time.

        Args:
            test_name: Name of the lab test (e.g., 'Fasting Glucose', 'LDL Cholesterol').
            limit: Maximum number of historical readings to include.
        """
        start_time = time.monotonic()
        trend = trend_analyzer.compute_lab_trend(test_name, limit=limit)

        if audit_logger is not None:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            audit_logger.log_tool_call(
                tool_name="lab_trend",
                tool_input={"test_name": test_name, "limit": limit},
                llm_disclosed=False,
                duration_ms=elapsed_ms,
            )

        return json.dumps(trend, indent=2)
