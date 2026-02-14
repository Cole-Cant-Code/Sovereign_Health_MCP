"""Scaffold registry — in-memory index for loaded scaffolds."""

from __future__ import annotations

import logging

from cip.core.scaffold.models import Scaffold

logger = logging.getLogger(__name__)


class ScaffoldRegistry:
    """In-memory registry of all loaded scaffold definitions."""

    def __init__(self) -> None:
        self._scaffolds: dict[str, Scaffold] = {}
        self._by_tool: dict[str, list[str]] = {}
        self._by_tag: dict[str, list[str]] = {}

    def register(self, scaffold: Scaffold) -> None:
        """Add a scaffold to all indexes."""
        if scaffold.id in self._scaffolds:
            raise ValueError(f"Duplicate scaffold id registered: {scaffold.id!r}")
        self._scaffolds[scaffold.id] = scaffold

        for tool in scaffold.applicability.tools:
            ids = self._by_tool.setdefault(tool, [])
            if scaffold.id not in ids:
                ids.append(scaffold.id)

        for tag in scaffold.tags:
            ids = self._by_tag.setdefault(tag, [])
            if scaffold.id not in ids:
                ids.append(scaffold.id)

    def get(self, scaffold_id: str) -> Scaffold | None:
        """Look up a scaffold by ID."""
        return self._scaffolds.get(scaffold_id)

    def find_by_tool(self, tool_name: str) -> list[Scaffold]:
        """Find scaffolds applicable to a given tool name."""
        ids = self._by_tool.get(tool_name, [])
        return [self._scaffolds[sid] for sid in ids]

    def find_by_tag(self, tag: str) -> list[Scaffold]:
        """Find scaffolds with a given tag."""
        ids = self._by_tag.get(tag, [])
        return [self._scaffolds[sid] for sid in ids]

    def all(self) -> list[Scaffold]:
        """Return all registered scaffolds."""
        return list(self._scaffolds.values())
