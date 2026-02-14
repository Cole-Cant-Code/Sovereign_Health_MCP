"""Scaffold YAML validator — ensures scaffold definitions are well-formed."""

from __future__ import annotations

import logging
from pathlib import Path

from cip.core.scaffold.loader import load_scaffold_file
from cip.core.scaffold.models import Scaffold

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["id", "version", "domain", "display_name", "description"]


def validate_scaffold_file(
    path: Path, *, project_root: Path | None = None
) -> tuple[Scaffold | None, list[str]]:
    """Validate a single scaffold YAML file.

    Returns: (scaffold_or_none, errors)
    """
    errors: list[str] = []

    display_path: str
    if project_root:
        try:
            display_path = str(path.relative_to(project_root))
        except ValueError:
            display_path = str(path)
    else:
        display_path = str(path)

    try:
        scaffold = load_scaffold_file(path)
    except Exception as exc:
        return None, [f"{display_path}: Failed to load — {exc}"]

    for field_name in REQUIRED_FIELDS:
        value = getattr(scaffold, field_name, None)
        if not value:
            errors.append(f"{display_path}: Missing or empty required field '{field_name}'")

    # Applicability should define at least one tool or keyword.
    if not scaffold.applicability.tools and not scaffold.applicability.keywords:
        errors.append(f"{display_path}: Applicability has no tools or keywords")

    # Required disclaimers.
    if not scaffold.guardrails.disclaimers:
        errors.append(f"{display_path}: No guardrail disclaimers defined")

    # Reasoning framework should have steps.
    steps = scaffold.reasoning_framework.get("steps", [])
    if not steps:
        errors.append(f"{display_path}: Reasoning framework has no steps")

    # Version format check (semver-ish).
    if scaffold.version and not all(c.isdigit() or c == "." for c in scaffold.version):
        errors.append(
            f"{display_path}: Version '{scaffold.version}' doesn't look like a version number"
        )

    # Filename should start with the scaffold id (supports suffixes like `.v1.yaml`).
    name = path.name
    if not (name == f"{scaffold.id}.yaml" or name.startswith(f"{scaffold.id}.")):
        errors.append(
            f"{display_path}: Filename '{name}' should match scaffold id '{scaffold.id}' "
            f"(expected '{scaffold.id}.*.yaml')"
        )

    return scaffold, errors


def validate_scaffold_directory(
    directory: str | Path, *, project_root: Path | None = None
) -> tuple[int, list[str]]:
    """Validate all scaffold YAML files in a directory (recursively).

    Returns: (scaffold_count, errors)
    """
    directory = Path(directory)
    if not directory.is_dir():
        return 0, [f"Scaffold directory not found: {directory}"]

    yaml_files = sorted(p for p in directory.rglob("*.yaml") if not p.name.startswith("_"))
    if not yaml_files:
        return 0, [f"No scaffold YAML files found in {directory}"]

    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    loaded = 0

    for path in yaml_files:
        scaffold, file_errors = validate_scaffold_file(path, project_root=project_root)
        if file_errors:
            errors.extend(file_errors)
            continue

        assert scaffold is not None  # for type checkers
        loaded += 1

        # Duplicate ID detection.
        if scaffold.id in seen_ids:
            if project_root:
                try:
                    here = str(path.relative_to(project_root))
                except ValueError:
                    here = str(path)
                try:
                    there = str(seen_ids[scaffold.id].relative_to(project_root))
                except ValueError:
                    there = str(seen_ids[scaffold.id])
            else:
                here = str(path)
                there = str(seen_ids[scaffold.id])
            errors.append(
                f"{here}: Duplicate ID '{scaffold.id}' — already defined in {there}"
            )
        else:
            seen_ids[scaffold.id] = path

    return loaded, errors


def validate_scaffolds(directory: str | Path) -> tuple[int, int]:
    """Backwards-compatible API: returns (scaffold_count, error_count)."""
    count, errors = validate_scaffold_directory(directory)
    for err in errors:
        logger.error("%s", err)
    return count, len(errors)
