"""MCP Prompts — pre-built interaction templates for health user journeys."""

from __future__ import annotations

from fastmcp import FastMCP


def register_health_prompts(mcp: FastMCP) -> None:
    """Register health domain MCP prompts."""

    @mcp.prompt()
    def health_check_prompt() -> str:
        """Prompt template for a comprehensive personal health assessment."""
        return """I'd like a comprehensive personal health check. Please analyze:

1. My vital signs and their trends
2. My lab results and metabolic health
3. My exercise and sleep patterns
4. My preventive care status (screenings, vaccinations)
5. Specific, prioritized actions I can take this month

Please be honest but encouraging. I want realistic advice I can actually follow."""

    @mcp.prompt()
    def wellness_review_prompt(time_period: str = "last month") -> str:
        """Prompt template for reviewing wellness metrics over a period."""
        return f"""Let's review my wellness metrics for {time_period}. I'd like to:

1. See how my vitals have trended
2. Check my exercise consistency and sleep quality
3. Identify any areas that need attention
4. Get specific action items for improvement

Please analyze my health data and give me actionable insights."""
