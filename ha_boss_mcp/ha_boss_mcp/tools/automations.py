"""MCP tools for automation analysis and usage tracking.

Provides tools to:
- Analyze automations for optimization suggestions
- View automation execution history
- Get usage statistics for automations
"""

import logging
from typing import TYPE_CHECKING

from ha_boss_mcp.models import (
    AutomationAnalysis,
    AutomationExecution,
    AutomationInfo,
    AutomationServiceCall,
    UsageStatistics,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from ha_boss_mcp.clients.db_reader import DBReader
    from ha_boss_mcp.clients.haboss_api import HABossAPIClient

logger = logging.getLogger(__name__)


def register_tools(
    mcp: "FastMCP",
    api_client: "HABossAPIClient",
    db_reader: "DBReader",
) -> None:
    """Register automation tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        api_client: HA Boss API client
        db_reader: Database reader for direct queries
    """

    @mcp.tool()
    async def analyze_automation(
        automation_id: str,
        include_ai: bool = True,
        include_usage: bool = False,
        days: int = 30,
    ) -> AutomationAnalysis:
        """Analyze an automation for optimization suggestions.

        Performs static analysis and optionally AI-powered analysis to identify
        potential improvements, anti-patterns, and optimization opportunities.

        When include_usage is True, also analyzes execution history to provide
        usage-based recommendations (e.g., high failure rate, slow execution).

        Args:
            automation_id: Automation entity ID (e.g., "automation.bedroom_lights")
            include_ai: Include AI-powered analysis (requires LLM configuration)
            include_usage: Include usage-based analysis from execution history
            days: Days of usage data to analyze (1-90, default: 30)

        Returns:
            Analysis result with suggestions, complexity score, and optional usage stats
        """
        logger.info(f"Analyzing automation: {automation_id}")

        response = await api_client.analyze_automation(
            automation_id=automation_id,
            include_ai=include_ai,
            include_usage=include_usage,
            days=days,
        )

        # Get usage stats from database if requested
        usage_stats = None
        if include_usage:
            try:
                stats = await db_reader.get_automation_usage_stats(
                    automation_id=automation_id,
                    days=days,
                )
                usage_stats = UsageStatistics(**stats)
            except Exception as e:
                logger.warning(f"Failed to get usage stats from database: {e}")

        return AutomationAnalysis(
            automation_id=response.get("automation_id", automation_id),
            alias=response.get("alias"),
            analysis=response.get("analysis", "No analysis available"),
            suggestions=response.get("suggestions", []),
            complexity_score=response.get("complexity_score"),
            usage_stats=usage_stats,
        )

    @mcp.tool()
    async def get_automation_executions(
        automation_id: str | None = None,
        days: int = 7,
        limit: int = 100,
    ) -> list[AutomationExecution]:
        """Get automation execution history.

        Retrieves records of automation executions including success/failure status,
        trigger type, and execution duration.

        Args:
            automation_id: Optional automation ID filter (returns all if not specified)
            days: Days of history to retrieve (1-90, default: 7)
            limit: Maximum executions to return (1-1000, default: 100)

        Returns:
            List of execution records ordered by most recent first
        """
        logger.info(f"Getting automation executions: {automation_id or 'all'}, {days} days")

        executions = await db_reader.get_automation_executions(
            automation_id=automation_id,
            days=days,
            limit=limit,
        )

        return [AutomationExecution(**ex) for ex in executions]

    @mcp.tool()
    async def get_automation_service_calls(
        automation_id: str | None = None,
        days: int = 7,
        limit: int = 100,
    ) -> list[AutomationServiceCall]:
        """Get service calls made by automations.

        Retrieves records of service calls triggered by automations, including
        which services were called, target entities, and response times.

        Args:
            automation_id: Optional automation ID filter (returns all if not specified)
            days: Days of history to retrieve (1-90, default: 7)
            limit: Maximum service calls to return (1-1000, default: 100)

        Returns:
            List of service call records ordered by most recent first
        """
        logger.info(f"Getting automation service calls: {automation_id or 'all'}, {days} days")

        calls = await db_reader.get_automation_service_calls(
            automation_id=automation_id,
            days=days,
            limit=limit,
        )

        return [AutomationServiceCall(**call) for call in calls]

    @mcp.tool()
    async def get_automation_usage_stats(
        automation_id: str,
        days: int = 30,
    ) -> UsageStatistics:
        """Get aggregated usage statistics for an automation.

        Provides summary metrics including execution count, failure rate,
        average duration, service call volume, and trigger patterns.

        Useful for identifying:
        - High-frequency automations that may need optimization
        - Automations with high failure rates
        - Slow-executing automations
        - Inactive automations that may be candidates for removal

        Args:
            automation_id: Automation entity ID (e.g., "automation.bedroom_lights")
            days: Days of data to analyze (1-90, default: 30)

        Returns:
            Aggregated usage statistics
        """
        logger.info(f"Getting usage stats for: {automation_id}, {days} days")

        stats = await db_reader.get_automation_usage_stats(
            automation_id=automation_id,
            days=days,
        )

        return UsageStatistics(**stats)

    @mcp.tool()
    async def list_automations() -> list[AutomationInfo]:
        """List all automations from Home Assistant.

        Retrieves basic information about all automation entities including
        their current state and last trigger time.

        Returns:
            List of automation entities with basic info
        """
        logger.info("Listing all automations")

        try:
            automations = await api_client.list_automations()

            return [
                AutomationInfo(
                    automation_id=auto.get("entity_id", ""),
                    alias=auto.get("attributes", {}).get("friendly_name"),
                    state=auto.get("state", "unknown"),
                    last_triggered=auto.get("attributes", {}).get("last_triggered"),
                )
                for auto in automations
            ]
        except Exception as e:
            logger.error(f"Failed to list automations: {e}")
            return []

    logger.info("Registered 5 automation tools")
