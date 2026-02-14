"""MCP tools for health data management (deletion, purge, retention).

These tools implement the user's right to delete their health data,
as required by HIPAA and good data stewardship practice. All deletions
are audit-logged.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from cip.core.audit.logger import AuditLogger
    from cip.core.storage.repository import HealthRepository

logger = logging.getLogger(__name__)


def register_data_management_tools(
    mcp: FastMCP,
    repository: HealthRepository,
    audit_logger: AuditLogger | None = None,
) -> None:
    """Register data management tools on the MCP server."""

    @mcp.tool
    async def delete_health_snapshot(
        ctx: Context,
        snapshot_id: str,
    ) -> str:
        """Delete a specific health snapshot and its associated data.

        This permanently removes the snapshot, including encrypted raw data,
        denormalized lab results, and vital readings.

        Args:
            snapshot_id: The UUID of the snapshot to delete.
        """
        start_time = time.monotonic()
        deleted = repository.delete_snapshot(snapshot_id)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        if deleted:
            if audit_logger is not None:
                audit_logger.log_data_delete(
                    tool_name="delete_health_snapshot",
                    snapshot_id=snapshot_id,
                    count=1,
                )
            logger.info("Deleted health snapshot %s", snapshot_id)
            return json.dumps({
                "status": "deleted",
                "snapshot_id": snapshot_id,
                "duration_ms": round(elapsed_ms, 1),
            })
        else:
            return json.dumps({
                "status": "not_found",
                "snapshot_id": snapshot_id,
                "message": "No snapshot found with that ID.",
            })

    @mcp.tool
    async def purge_old_data(
        ctx: Context,
        older_than_days: int = 365,
    ) -> str:
        """Delete all health snapshots older than a specified number of days.

        This is a bulk deletion for data retention compliance. All associated
        lab results and vital readings are also removed.

        Args:
            older_than_days: Delete data older than this many days (default: 365).
        """
        if older_than_days < 1:
            return json.dumps({
                "status": "error",
                "message": "older_than_days must be at least 1.",
            })

        start_time = time.monotonic()
        count = repository.purge_before_days(older_than_days)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        if audit_logger is not None and count > 0:
            audit_logger.log_data_delete(
                tool_name="purge_old_data",
                count=count,
                metadata={"older_than_days": older_than_days},
            )

        return json.dumps({
            "status": "purged",
            "snapshots_deleted": count,
            "older_than_days": older_than_days,
            "duration_ms": round(elapsed_ms, 1),
        })

    @mcp.tool
    async def delete_all_health_data(
        ctx: Context,
        confirm: str = "",
    ) -> str:
        """Permanently delete ALL stored health data.

        This is a destructive operation that removes every snapshot, lab result,
        vital reading, and data source record. It cannot be undone.

        Args:
            confirm: Must be exactly 'DELETE_ALL' to proceed. Safety gate.
        """
        if confirm != "DELETE_ALL":
            return json.dumps({
                "status": "cancelled",
                "message": (
                    "To delete all health data, call this tool with "
                    "confirm='DELETE_ALL'. This action cannot be undone."
                ),
            })

        start_time = time.monotonic()
        count = repository.delete_all_data()
        elapsed_ms = (time.monotonic() - start_time) * 1000

        if audit_logger is not None:
            audit_logger.log_data_delete(
                tool_name="delete_all_health_data",
                count=count,
                metadata={"confirmed": True},
            )

        logger.warning("ALL health data deleted: %d snapshots removed", count)
        return json.dumps({
            "status": "all_deleted",
            "snapshots_deleted": count,
            "duration_ms": round(elapsed_ms, 1),
            "message": "All health data has been permanently deleted.",
        })
