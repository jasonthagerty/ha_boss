"""Reliability analysis for integration health patterns."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import case, func, select

from ha_boss.core.database import Database, IntegrationReliability

logger = logging.getLogger(__name__)

ReliabilityScore = Literal["Excellent", "Good", "Fair", "Poor"]


@dataclass
class ReliabilityMetric:
    """Integration reliability metrics."""

    integration_id: str
    integration_domain: str
    total_events: int
    heal_successes: int
    heal_failures: int
    unavailable_events: int
    success_rate: float
    period_start: datetime
    period_end: datetime

    @property
    def reliability_score(self) -> ReliabilityScore:
        """Get reliability score label based on success rate.

        Returns:
            "Excellent" (≥95%), "Good" (≥80%), "Fair" (≥60%), or "Poor" (<60%)
        """
        if self.success_rate >= 0.95:
            return "Excellent"
        elif self.success_rate >= 0.80:
            return "Good"
        elif self.success_rate >= 0.60:
            return "Fair"
        else:
            return "Poor"

    @property
    def needs_attention(self) -> bool:
        """Check if integration needs attention (success rate < 80%)."""
        return self.success_rate < 0.80

    @property
    def heal_attempts(self) -> int:
        """Total healing attempts (successes + failures)."""
        return self.heal_successes + self.heal_failures


@dataclass
class FailureEvent:
    """A single failure event with details."""

    timestamp: datetime
    integration_id: str
    integration_domain: str
    event_type: str  # heal_failure or unavailable
    entity_id: str | None
    details: dict | None


class ReliabilityAnalyzer:
    """Analyze integration reliability patterns."""

    def __init__(self, database: Database) -> None:
        """Initialize analyzer.

        Args:
            database: Database instance for queries
        """
        self.database = database

    async def get_integration_metrics(
        self,
        days: int = 7,
        integration_domain: str | None = None,
    ) -> list[ReliabilityMetric]:
        """Get reliability metrics for integrations.

        Args:
            days: Number of days to analyze (default: 7)
            integration_domain: Optional domain filter (e.g., "hue", "zwave")

        Returns:
            List of ReliabilityMetric objects, sorted by worst success rate first
        """
        period_start = datetime.now(UTC) - timedelta(days=days)
        period_end = datetime.now(UTC)

        async with self.database.async_session() as session:
            # Build query to aggregate events per integration
            query = (
                select(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                    func.count(IntegrationReliability.id).label("total_events"),
                    func.sum(
                        case(
                            (IntegrationReliability.event_type == "heal_success", 1),
                            else_=0,
                        )
                    ).label("heal_successes"),
                    func.sum(
                        case(
                            (IntegrationReliability.event_type == "heal_failure", 1),
                            else_=0,
                        )
                    ).label("heal_failures"),
                    func.sum(
                        case(
                            (IntegrationReliability.event_type == "unavailable", 1),
                            else_=0,
                        )
                    ).label("unavailable_events"),
                )
                .where(IntegrationReliability.timestamp >= period_start)
                .group_by(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                )
            )

            # Add domain filter if specified
            if integration_domain:
                query = query.where(IntegrationReliability.integration_domain == integration_domain)

            result = await session.execute(query)
            rows = result.all()

            # Convert to ReliabilityMetric objects
            metrics = []
            for row in rows:
                heal_attempts = row.heal_successes + row.heal_failures
                # Calculate success rate (handle division by zero)
                if heal_attempts > 0:
                    success_rate = row.heal_successes / heal_attempts
                else:
                    # No healing attempts = 100% (no failures)
                    success_rate = 1.0

                metric = ReliabilityMetric(
                    integration_id=row.integration_id,
                    integration_domain=row.integration_domain,
                    total_events=row.total_events,
                    heal_successes=row.heal_successes,
                    heal_failures=row.heal_failures,
                    unavailable_events=row.unavailable_events,
                    success_rate=success_rate,
                    period_start=period_start,
                    period_end=period_end,
                )
                metrics.append(metric)

            # Sort by worst success rate first (ascending)
            metrics.sort(key=lambda m: m.success_rate)

            return metrics

    async def get_failure_timeline(
        self,
        integration_domain: str | None = None,
        days: int = 7,
        limit: int = 100,
    ) -> list[FailureEvent]:
        """Get timeline of failure events.

        Args:
            integration_domain: Optional domain filter
            days: Number of days to look back
            limit: Maximum number of events to return

        Returns:
            List of FailureEvent objects in chronological order (oldest first)
        """
        period_start = datetime.now(UTC) - timedelta(days=days)

        async with self.database.async_session() as session:
            # Query for failure events only
            query = (
                select(IntegrationReliability)
                .where(IntegrationReliability.timestamp >= period_start)
                .where(IntegrationReliability.event_type.in_(["heal_failure", "unavailable"]))
                .order_by(IntegrationReliability.timestamp.asc())
                .limit(limit)
            )

            # Add domain filter if specified
            if integration_domain:
                query = query.where(IntegrationReliability.integration_domain == integration_domain)

            result = await session.execute(query)
            events = result.scalars().all()

            # Convert to FailureEvent objects
            return [
                FailureEvent(
                    timestamp=event.timestamp,
                    integration_id=event.integration_id,
                    integration_domain=event.integration_domain,
                    event_type=event.event_type,
                    entity_id=event.entity_id,
                    details=event.details,
                )
                for event in events
            ]

    async def get_top_failing_integrations(
        self,
        days: int = 7,
        limit: int = 10,
    ) -> list[ReliabilityMetric]:
        """Get top N integrations with worst reliability.

        Args:
            days: Number of days to analyze
            limit: Number of integrations to return

        Returns:
            List of top failing integrations, worst first
        """
        all_metrics = await self.get_integration_metrics(days=days)

        # Already sorted worst-first, just limit
        return all_metrics[:limit]

    async def get_recommendations(
        self,
        integration_domain: str,
        days: int = 7,
    ) -> list[str]:
        """Generate actionable recommendations for an integration.

        Args:
            integration_domain: Integration domain to analyze
            days: Number of days to analyze

        Returns:
            List of recommendation strings
        """
        metrics = await self.get_integration_metrics(
            days=days, integration_domain=integration_domain
        )

        if not metrics:
            return ["No data available for this integration in the specified period"]

        metric = metrics[0]  # Should only be one for specific domain
        recommendations = []

        # Severity-based recommendations
        if metric.reliability_score == "Poor":
            recommendations.append(
                f"⚠️ CRITICAL: {metric.integration_domain} has {metric.success_rate:.1%} success rate"
            )
            recommendations.append(
                "Consider checking integration configuration and network connectivity"
            )
            if metric.unavailable_events > 10:
                recommendations.append(
                    f"High unavailable events ({metric.unavailable_events}) - check device connectivity"
                )
        elif metric.reliability_score == "Fair":
            recommendations.append(
                f"⚡ WARNING: {metric.integration_domain} has {metric.success_rate:.1%} success rate"
            )
            recommendations.append("Review recent failures for patterns")
        elif metric.reliability_score == "Good":
            recommendations.append(
                f"✓ {metric.integration_domain} is performing adequately ({metric.success_rate:.1%})"
            )
            if metric.heal_failures > 0:
                recommendations.append("Monitor for any increasing failure trends")
        else:  # Excellent
            recommendations.append(
                f"✓ {metric.integration_domain} is highly reliable ({metric.success_rate:.1%})"
            )

        # Specific recommendations based on failure patterns
        if metric.heal_failures > metric.heal_successes:
            recommendations.append(
                "More heal failures than successes - integration may need manual intervention"
            )

        if metric.heal_attempts == 0 and metric.unavailable_events > 0:
            recommendations.append(
                "No healing attempts despite unavailable events - check healing configuration"
            )

        return recommendations
