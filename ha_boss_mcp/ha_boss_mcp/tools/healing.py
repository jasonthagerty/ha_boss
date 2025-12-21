"""Healing tools for HA Boss MCP server."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ha_boss_mcp.clients.db_reader import DBReader
from ha_boss_mcp.clients.haboss_api import HABossAPIClient
from ha_boss_mcp.models import HealingAction, HealingResult, HealingStats


async def register_tools(mcp: FastMCP, api_client: HABossAPIClient, db_reader: DBReader) -> None:
    """Register healing tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        api_client: HA Boss API client
        db_reader: Database reader client
    """

    @mcp.tool()
    async def trigger_healing(
        entity_id: Annotated[
            str,
            Field(description="Entity ID to heal (e.g., 'sensor.temperature', 'light.bedroom')"),
        ],
        dry_run: Annotated[
            bool,
            Field(description="Test without executing (default: True for safety)"),
        ] = True,
    ) -> HealingResult:
        """Trigger healing for a Home Assistant entity (reloads associated integration).

        When an entity becomes unavailable or unresponsive, healing attempts to
        restore it by reloading its parent integration. This is HA Boss's core
        auto-healing capability, exposed for manual triggering.

        **Safety Features:**
        - Circuit breakers: Prevents excessive reload attempts
        - Cooldown periods: Spaces out retry attempts
        - Dry-run mode: Test before executing (enabled by default)

        **What happens during healing:**
        1. Identifies the integration associated with the entity
        2. Calls Home Assistant's reload_config_entry service
        3. Waits for confirmation
        4. Records success/failure in database

        **Use Cases:**
        - Manual recovery of failed integrations
        - Testing auto-healing behavior
        - Proactive maintenance before issues escalate

        Args:
            entity_id: Full entity ID to heal
            dry_run: If True, simulates healing without executing (default: True)

        Returns:
            Healing result with success status and details

        Example:
            # Test healing (safe, won't execute)
            trigger_healing("sensor.living_room_temp", dry_run=True)

            # Actually execute healing
            trigger_healing("sensor.living_room_temp", dry_run=False)
        """
        # Use API for write operations
        result_data = await api_client.trigger_healing(entity_id, dry_run=dry_run)

        return HealingResult(
            entity_id=result_data.get("entity_id", entity_id),
            action=result_data.get("action", "reload_integration"),
            success=result_data.get("success", False),
            dry_run=dry_run,
            message=result_data.get("message", "Healing completed"),
            duration_seconds=result_data.get("duration_seconds"),
        )

    @mcp.tool()
    async def get_healing_history(
        entity_id: Annotated[
            str | None,
            Field(description="Optional entity ID filter (leave empty for all)"),
        ] = None,
        days: Annotated[
            int,
            Field(description="Days of history to retrieve (1-90)", ge=1, le=90),
        ] = 7,
        limit: Annotated[
            int,
            Field(description="Maximum actions to return (1-500)", ge=1, le=500),
        ] = 50,
    ) -> list[HealingAction]:
        """Get recent healing actions and their outcomes.

        Retrieves chronological history of healing attempts made by HA Boss,
        including both successful and failed actions. This is useful for:
        - Analyzing healing effectiveness
        - Identifying problematic integrations
        - Debugging repeated failures
        - Understanding system reliability

        **Information Included:**
        - Entity and integration targeted
        - Action type (e.g., reload_integration)
        - Success/failure status
        - Error messages for failures
        - Execution duration
        - Attempt number (for tracking retries)

        History is sorted newest to oldest (most recent first).

        Args:
            entity_id: Optional filter for specific entity (default: all entities)
            days: How many days of history to retrieve (default: 7)
            limit: Maximum number of actions to return (default: 50)

        Returns:
            List of healing actions with full details

        Example:
            # Get all healing in last 7 days
            get_healing_history()

            # Get healing for specific entity
            get_healing_history(entity_id="sensor.bedroom_temp")

            # Get last 30 days, up to 100 actions
            get_healing_history(days=30, limit=100)
        """
        # Use database for read operations
        actions_data = await db_reader.get_healing_actions(
            entity_id=entity_id, days=days, limit=limit
        )

        return [
            HealingAction(
                id=action["id"],
                entity_id=action["entity_id"],
                integration_id=action.get("integration_id"),
                action=action["action"],
                timestamp=action["timestamp"],
                success=bool(action["success"]),
                error=action.get("error"),
                duration_seconds=action.get("duration_seconds"),
            )
            for action in actions_data
        ]

    @mcp.tool()
    async def get_healing_stats(
        days: Annotated[
            int,
            Field(description="Days of data to analyze (1-90)", ge=1, le=90),
        ] = 7,
    ) -> HealingStats:
        """Get healing statistics and success/failure metrics.

        Provides aggregated statistics about HA Boss's healing effectiveness
        over the specified time period. Key metrics include:
        - Total healing attempts
        - Successful vs failed attempts
        - Overall success rate percentage

        This is useful for:
        - Measuring system reliability
        - Evaluating auto-healing effectiveness
        - Identifying if success rate is degrading
        - Reporting to stakeholders

        Args:
            days: How many days of data to analyze (default: 7)

        Returns:
            Healing statistics with success rates

        Example:
            # Get last week's healing stats
            get_healing_stats(days=7)

            # Get monthly healing performance
            get_healing_stats(days=30)
        """
        # Use database for aggregation
        stats_data = await db_reader.get_healing_stats(days=days)

        return HealingStats(
            total_attempts=stats_data["total_attempts"],
            successful_attempts=stats_data["successful_attempts"],
            failed_attempts=stats_data["failed_attempts"],
            success_rate=stats_data["success_rate"],
            days=days,
        )
