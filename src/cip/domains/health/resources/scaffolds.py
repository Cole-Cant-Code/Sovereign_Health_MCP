"""MCP Resources for health scaffold discovery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from cip.core.scaffold.registry import ScaffoldRegistry


def register_health_scaffold_resources(mcp: FastMCP, registry: ScaffoldRegistry) -> None:
    """Register health scaffold discovery resources on the MCP server."""

    @mcp.resource("scaffold://health/registry")
    def health_scaffold_registry_resource() -> str:
        """Discover all available health cognitive scaffolds."""
        scaffolds = registry.all()
        health_scaffolds = [s for s in scaffolds if s.domain == "personal_health"]
        return json.dumps(
            {
                "domain": "personal_health",
                "scaffold_count": len(health_scaffolds),
                "scaffolds": [
                    {
                        "id": s.id,
                        "display_name": s.display_name,
                        "description": s.description,
                        "applicability": {
                            "tools": s.applicability.tools,
                            "keywords": s.applicability.keywords,
                        },
                        "tone_variants": list(s.framing.tone_variants.keys()),
                        "output_formats": s.output_calibration.format_options,
                        "context_accepts": [f.field_name for f in s.context_accepts],
                        "context_exports": [f.field_name for f in s.context_exports],
                        "tags": s.tags,
                    }
                    for s in health_scaffolds
                ],
            },
            indent=2,
        )
