"""Service management tools for HA Boss MCP server."""


from fastmcp import FastMCP

from ha_boss_mcp.clients.db_reader import DBReader
from ha_boss_mcp.clients.haboss_api import HABossAPIClient
from ha_boss_mcp.models import ComponentHealth, ConfigSummary, HealthCheck


async def register_tools(mcp: FastMCP, api_client: HABossAPIClient, db_reader: DBReader) -> None:
    """Register service management tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        api_client: HA Boss API client
        db_reader: Database reader client
    """

    @mcp.tool()
    async def health_check() -> HealthCheck:
        """Get comprehensive HA Boss service health check.

        Performs tier-based health assessment of all 22 HA Boss components across
        5 priority tiers. This is the most thorough way to verify HA Boss is
        functioning correctly and identify any degraded components.

        **Health Tiers (Critical to Optional):**
        1. **Tier 1 - Critical**: Core service, HA REST API, database, configuration
        2. **Tier 2 - Essential**: WebSocket connection, state tracker, integrations
        3. **Tier 3 - Operational**: Health monitor, events, history, notifications
        4. **Tier 4 - Healing**: Healing manager, circuit breakers, persistence
        5. **Tier 5 - Intelligence**: Ollama LLM, Claude API (graceful degradation)

        **Component Status:**
        - healthy: Component fully operational
        - degraded: Component working with reduced functionality
        - unhealthy: Component failed or unavailable
        - unknown: Status cannot be determined

        **Overall Status:**
        - healthy: All critical/essential components healthy
        - degraded: Some operational/healing components degraded
        - unhealthy: Critical/essential components failed

        Use this for:
        - Verifying HA Boss is running correctly
        - Diagnosing service issues
        - Monitoring deployment health
        - Identifying which specific components have problems

        Returns:
            Health check result with component breakdown

        Example:
            health_check()
        """
        # Use API for comprehensive health check
        health_data = await api_client.get_health_check()

        components = [
            ComponentHealth(
                component=comp["component"],
                status=comp["status"],
                message=comp.get("message"),
                tier=comp.get("tier", 3),
            )
            for comp in health_data.get("components", [])
        ]

        return HealthCheck(
            overall_status=health_data.get("overall_status", "unknown"),
            timestamp=health_data.get("timestamp", ""),
            components=components,
        )

    @mcp.tool()
    async def get_config() -> ConfigSummary:
        """Get sanitized HA Boss configuration summary.

        Returns high-level configuration settings without exposing secrets
        (API keys, tokens, passwords are excluded). This is useful for:
        - Understanding current HA Boss configuration
        - Verifying settings without accessing config files
        - Debugging configuration issues
        - Documenting deployment settings

        **Information Included:**
        - Number of monitored entities
        - Auto-healing enabled/disabled
        - Healing parameters (max attempts, grace period)
        - API and LLM feature enablement

        **Security:**
        All sensitive values (tokens, API keys, passwords) are automatically
        excluded from the response. Only configuration parameters are returned.

        Returns:
            Sanitized configuration summary

        Example:
            get_config()
        """
        # Use API to get configuration (already sanitized by HA Boss)
        status_data = await api_client.get_service_status()

        # Also get entity count from database
        entity_count = await db_reader.count_entities(monitored_only=True)

        # Extract config from status response (HA Boss includes config summary)
        config_data = status_data.get("config", {})

        return ConfigSummary(
            monitored_entities_count=entity_count,
            auto_healing_enabled=config_data.get("auto_healing_enabled", True),
            healing_max_attempts=config_data.get("healing_max_attempts", 3),
            grace_period_seconds=config_data.get("grace_period_seconds", 300),
            api_enabled=config_data.get("api_enabled", True),
            llm_enabled=config_data.get("llm_enabled", False),
        )
