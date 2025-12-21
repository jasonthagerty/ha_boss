"""Monitoring tools for HA Boss MCP server."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ha_boss_mcp.clients.db_reader import DBReader
from ha_boss_mcp.clients.haboss_api import HABossAPIClient
from ha_boss_mcp.models import EntityHistoryEntry, EntityState, ServiceStatus


async def register_tools(mcp: FastMCP, api_client: HABossAPIClient, db_reader: DBReader) -> None:
    """Register monitoring tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        api_client: HA Boss API client
        db_reader: Database reader client
    """

    @mcp.tool()
    async def get_service_status() -> ServiceStatus:
        """Get HA Boss service status and uptime information.

        Returns comprehensive service status including:
        - Overall service health (running, degraded, unhealthy)
        - Service uptime in seconds
        - Total monitored entities count
        - Healing statistics (total attempts and successes)

        This is useful for checking if HA Boss is operating normally and
        getting a quick overview of its monitoring and healing activity.

        Returns:
            Service status with uptime and statistics
        """
        status_data = await api_client.get_service_status()

        return ServiceStatus(
            status=status_data.get("status", "unknown"),
            uptime_seconds=status_data.get("uptime_seconds", 0.0),
            total_entities=status_data.get("total_entities", 0),
            total_healing_attempts=status_data.get("total_healing_attempts", 0),
            successful_healings=status_data.get("successful_healings", 0),
        )

    @mcp.tool()
    async def list_entities(
        limit: Annotated[
            int, Field(description="Maximum entities to return (1-1000)", ge=1, le=1000)
        ] = 100,
        offset: Annotated[int, Field(description="Pagination offset", ge=0)] = 0,
    ) -> list[EntityState]:
        """List all Home Assistant entities being monitored by HA Boss.

        Returns paginated list of entities with their current states, domains,
        friendly names, and associated integrations. Use this for:
        - Discovery: Find all available entities
        - Bulk health checks: See state of multiple entities at once
        - Integration mapping: Identify which entities belong to which integrations

        The list is sorted alphabetically by entity_id for consistent pagination.

        Args:
            limit: Maximum number of entities to return (default: 100)
            offset: Skip this many entities for pagination (default: 0)

        Returns:
            List of entity states with metadata

        Example:
            To get first 50 entities: list_entities(limit=50, offset=0)
            To get next 50 entities: list_entities(limit=50, offset=50)
        """
        # Use database for performance (read-only query)
        entities_data = await db_reader.list_entities(
            limit=limit, offset=offset, monitored_only=True
        )

        return [
            EntityState(
                entity_id=entity["entity_id"],
                domain=entity["domain"],
                state=entity.get("last_state"),
                friendly_name=entity.get("friendly_name"),
                integration_id=entity.get("integration_id"),
                last_updated=entity["last_seen"],
            )
            for entity in entities_data
        ]

    @mcp.tool()
    async def get_entity_state(
        entity_id: Annotated[
            str,
            Field(
                description="Entity ID to query (e.g., 'sensor.living_room_temperature', 'light.bedroom')"
            ),
        ],
    ) -> EntityState:
        """Get current state and metadata for a specific Home Assistant entity.

        Retrieves detailed information about a single entity including:
        - Current state value (e.g., "23.5" for temperature sensor, "on" for light)
        - Domain (sensor, light, switch, etc.)
        - Human-friendly name
        - Associated integration
        - Last update timestamp

        This is useful for:
        - Checking specific entity health
        - Monitoring critical devices
        - Debugging entity state issues
        - Understanding entity relationships

        Args:
            entity_id: Full entity ID (format: domain.object_id)

        Returns:
            Entity state with full metadata

        Raises:
            ValueError: If entity_id not found in database

        Example:
            get_entity_state("sensor.bedroom_temperature")
            get_entity_state("light.living_room_ceiling")
        """
        # Use database for performance (read-only query)
        entity_data = await db_reader.get_entity(entity_id)

        if not entity_data:
            raise ValueError(f"Entity '{entity_id}' not found")

        return EntityState(
            entity_id=entity_data["entity_id"],
            domain=entity_data["domain"],
            state=entity_data.get("last_state"),
            friendly_name=entity_data.get("friendly_name"),
            integration_id=entity_data.get("integration_id"),
            last_updated=entity_data["last_seen"],
        )

    @mcp.tool()
    async def get_entity_history(
        entity_id: Annotated[str, Field(description="Entity ID to get history for")],
        hours: Annotated[
            int,
            Field(
                description="Hours of history to retrieve (1-168 for 1 week)",
                ge=1,
                le=168,
            ),
        ] = 24,
    ) -> list[EntityHistoryEntry]:
        """Get state change history for a Home Assistant entity.

        Retrieves chronological list of state changes for the specified entity
        over the given time period. This is useful for:
        - Analyzing state transition patterns
        - Debugging intermittent issues
        - Understanding entity behavior over time
        - Identifying when problems started

        History entries are ordered newest to oldest (most recent first).

        Args:
            entity_id: Entity ID to query
            hours: How many hours of history to retrieve (default: 24)

        Returns:
            List of state changes with timestamps

        Example:
            # Get last 24 hours of changes
            get_entity_history("sensor.temperature", hours=24)

            # Get full week of history
            get_entity_history("light.bedroom", hours=168)
        """
        # Use database for performance (read-only query)
        history_data = await db_reader.get_entity_history(entity_id, hours=hours, limit=1000)

        return [
            EntityHistoryEntry(
                old_state=entry.get("old_state"),
                new_state=entry["new_state"],
                timestamp=entry["timestamp"],
            )
            for entry in history_data
        ]
