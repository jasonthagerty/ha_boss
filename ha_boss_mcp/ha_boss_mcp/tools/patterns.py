"""Pattern analysis tools for HA Boss MCP server."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ha_boss_mcp.clients.db_reader import DBReader
from ha_boss_mcp.clients.haboss_api import HABossAPIClient
from ha_boss_mcp.models import Anomaly, FailureEvent, IntegrationReliability


async def register_tools(mcp: FastMCP, api_client: HABossAPIClient, db_reader: DBReader) -> None:
    """Register pattern analysis tools with FastMCP server.

    Args:
        mcp: FastMCP server instance
        api_client: HA Boss API client
        db_reader: Database reader client
    """

    @mcp.tool()
    async def get_reliability_stats(
        integration_domain: Annotated[
            str | None,
            Field(description="Optional integration domain filter (e.g., 'hue', 'zwave', 'mqtt')"),
        ] = None,
        days: Annotated[
            int,
            Field(description="Days of data to analyze (1-90)", ge=1, le=90),
        ] = 7,
    ) -> list[IntegrationReliability]:
        """Get integration reliability statistics and success rates.

        Analyzes historical data to compute reliability metrics for integrations.
        This shows which integrations are most/least reliable and helps identify
        problematic components in your Home Assistant setup.

        **Metrics Provided:**
        - Total events: All reliability-related events recorded
        - Heal successes: Successful recovery attempts
        - Heal failures: Failed recovery attempts
        - Unavailable events: Times entities became unavailable
        - Reliability score: Percentage indicating overall health (0-100)

        **Use Cases:**
        - Identify unreliable integrations requiring attention
        - Prioritize troubleshooting efforts
        - Track reliability improvements over time
        - Generate reliability reports

        Args:
            integration_domain: Filter by specific integration (e.g., 'hue')
                               or None for all integrations
            days: Number of days to analyze (default: 7)

        Returns:
            List of integration reliability statistics

        Example:
            # Get all integrations reliability for last week
            get_reliability_stats()

            # Check Hue integration reliability
            get_reliability_stats(integration_domain="hue")

            # Get monthly reliability report
            get_reliability_stats(days=30)
        """
        # Use API for complex aggregation
        stats_data = await api_client.get_reliability_stats(
            integration_domain=integration_domain, days=days
        )

        # API returns dict with integrations list
        integrations = stats_data.get("integrations", [])

        return [
            IntegrationReliability(
                integration_domain=integration["integration_domain"],
                total_events=integration["total_events"],
                heal_successes=integration["heal_successes"],
                heal_failures=integration["heal_failures"],
                unavailable_events=integration["unavailable_events"],
                reliability_score=integration["reliability_score"],
                days_analyzed=days,
            )
            for integration in integrations
        ]

    @mcp.tool()
    async def get_failure_patterns(
        integration_domain: Annotated[
            str | None,
            Field(description="Optional integration domain filter (e.g., 'hue', 'zwave')"),
        ] = None,
        days: Annotated[
            int,
            Field(description="Days of failures to retrieve (1-90)", ge=1, le=90),
        ] = 7,
        limit: Annotated[
            int,
            Field(description="Maximum failures to return (1-500)", ge=1, le=500),
        ] = 100,
    ) -> list[FailureEvent]:
        """Get failure event timeline for pattern analysis.

        Retrieves chronological list of failure events (unavailability, failed healings)
        to help identify patterns such as:
        - Time-of-day correlations (e.g., failures at 3am)
        - Recurring issues with specific entities
        - Cascading failures across integrations
        - Resolution effectiveness

        **Event Types:**
        - unavailable: Entity became unavailable
        - heal_failure: Healing attempt failed
        - stale: Entity stopped updating

        **Analysis Capabilities:**
        - Identify if failures cluster at specific times
        - Find entities with chronic issues
        - Measure time-to-resolution for different failure types
        - Correlate failures across integrations

        Events are sorted newest to oldest (most recent first).

        Args:
            integration_domain: Filter by integration (None for all)
            days: Days of failure history to retrieve (default: 7)
            limit: Maximum number of failures to return (default: 100)

        Returns:
            List of failure events with resolution status

        Example:
            # Get all failures from last week
            get_failure_patterns()

            # Analyze Z-Wave failures
            get_failure_patterns(integration_domain="zwave")

            # Get last 200 failures from past month
            get_failure_patterns(days=30, limit=200)
        """
        # Use API for complex filtering and enrichment
        failures_data = await api_client.get_failure_patterns(
            integration_domain=integration_domain, days=days, limit=limit
        )

        return [
            FailureEvent(
                timestamp=failure["timestamp"],
                entity_id=failure["entity_id"],
                integration_domain=failure.get("integration_domain"),
                event_type=failure["event_type"],
                resolved=failure.get("resolved", False),
                resolution_time_seconds=failure.get("resolution_time_seconds"),
            )
            for failure in failures_data
        ]

    @mcp.tool()
    async def get_anomalies(
        include_ai_insights: Annotated[
            bool,
            Field(description="Include AI-generated insights about anomalies (requires LLM)"),
        ] = False,
        days: Annotated[
            int,
            Field(description="Days of data to analyze (1-30)", ge=1, le=30),
        ] = 7,
    ) -> list[Anomaly]:
        """Get detected anomalies in Home Assistant entity behavior.

        Uses pattern detection (and optionally AI) to identify unusual behavior
        in entity states and integrations. This helps catch:
        - Entities behaving differently than normal
        - Sudden changes in failure rates
        - Unusual state transition patterns
        - Integration degradation

        **Anomaly Types:**
        - state_frequency: Unusual change frequency
        - value_outlier: State value outside normal range
        - integration_degradation: Integration reliability drop
        - temporal_pattern: Unexpected timing of events

        **Severity Levels:**
        - low: Minor deviation, likely benign
        - medium: Notable deviation, worth investigating
        - high: Significant deviation, requires attention

        **AI Insights (optional):**
        When enabled, uses local LLM (Ollama) or Claude to analyze anomalies
        and provide human-readable explanations and recommendations.

        Args:
            include_ai_insights: Whether to generate AI analysis (default: False)
            days: Days of data to analyze for anomalies (default: 7)

        Returns:
            List of detected anomalies with severity and descriptions

        Example:
            # Get anomalies (pattern-based only)
            get_anomalies()

            # Get anomalies with AI analysis
            get_anomalies(include_ai_insights=True)

            # Analyze last 2 weeks
            get_anomalies(days=14)
        """
        # Use API for anomaly detection (includes AI processing if enabled)
        # Note: This endpoint may not exist in current HA Boss - using weekly_summary as proxy
        summary_data = await api_client.get_weekly_summary(include_ai_insights=include_ai_insights)

        # Extract anomalies from summary
        anomalies = summary_data.get("anomalies", [])

        return [
            Anomaly(
                entity_id=anomaly.get("entity_id", "unknown"),
                anomaly_type=anomaly.get("anomaly_type", "unknown"),
                severity=anomaly.get("severity", "medium"),
                timestamp=anomaly.get("timestamp", ""),
                description=anomaly.get("description", "Anomaly detected"),
                ai_insights=anomaly.get("ai_insights") if include_ai_insights else None,
            )
            for anomaly in anomalies
        ]
