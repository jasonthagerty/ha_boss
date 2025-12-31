"""Weekly summary report generator for HA Boss."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ha_boss.core.config import Config
from ha_boss.core.database import (
    Database,
    IntegrationReliability,
    PatternInsight,
)
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity
from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer, ReliabilityMetric
from ha_boss.notifications.manager import NotificationChannel, NotificationManager
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)


@dataclass
class IntegrationTrend:
    """Trend data for a single integration."""

    domain: str
    current_rate: float
    previous_rate: float | None
    trend: str  # "improved", "degraded", "stable", "new"
    change_percent: float | None


@dataclass
class WeeklySummary:
    """Weekly summary report data."""

    period_start: datetime
    period_end: datetime
    total_integrations: int
    total_healing_attempts: int
    successful_healings: int
    failed_healings: int
    overall_success_rate: float

    # Top performers (highest reliability)
    top_performers: list[ReliabilityMetric] = field(default_factory=list)

    # Needs attention (lowest reliability)
    needs_attention: list[ReliabilityMetric] = field(default_factory=list)

    # Trends compared to previous week
    trends: list[IntegrationTrend] = field(default_factory=list)
    improved_count: int = 0
    degraded_count: int = 0
    stable_count: int = 0

    # AI-generated content
    ai_summary: str | None = None
    ai_recommendations: str | None = None

    # Comparison with previous week
    previous_success_rate: float | None = None
    success_rate_change: float | None = None


class WeeklySummaryGenerator:
    """Generate weekly AI-powered summary reports.

    Aggregates weekly pattern data, identifies trends, and generates
    natural language summaries using the LLM router.
    """

    def __init__(
        self,
        instance_id: str,
        config: Config,
        database: Database,
        llm_router: LLMRouter | None = None,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        """Initialize weekly summary generator.

        Args:
            instance_id: Home Assistant instance identifier
            config: HA Boss configuration
            database: Database instance
            llm_router: Optional LLM router for AI summaries
            notification_manager: Optional notification manager for delivery
        """
        self.instance_id = instance_id
        self.config = config
        self.database = database
        self.llm_router = llm_router
        self.notification_manager = notification_manager
        self.reliability_analyzer = ReliabilityAnalyzer(instance_id, database)

    async def generate_summary(
        self,
        period_end: datetime | None = None,
    ) -> WeeklySummary:
        """Generate weekly summary report.

        Args:
            period_end: End of the period to analyze (default: now)

        Returns:
            WeeklySummary with aggregated data and AI analysis
        """
        if period_end is None:
            period_end = datetime.now(UTC)

        period_start = period_end - timedelta(days=7)

        logger.info(f"Generating weekly summary for {period_start.date()} to {period_end.date()}")

        # Get current week metrics
        current_metrics = await self.reliability_analyzer.get_integration_metrics(days=7)

        # Get previous week metrics for comparison
        previous_metrics = await self._get_previous_week_metrics(period_start)

        # Calculate overall statistics
        total_healing_attempts = sum(m.heal_attempts for m in current_metrics)
        successful_healings = sum(m.heal_successes for m in current_metrics)
        failed_healings = sum(m.heal_failures for m in current_metrics)

        if total_healing_attempts > 0:
            overall_success_rate = successful_healings / total_healing_attempts
        else:
            overall_success_rate = 1.0

        # Sort by success rate (best first for top performers)
        sorted_by_best = sorted(current_metrics, key=lambda m: m.success_rate, reverse=True)
        # Sort by success rate (worst first for needs attention)
        sorted_by_worst = sorted(current_metrics, key=lambda m: m.success_rate)

        # Top 3 performers
        top_performers = [m for m in sorted_by_best[:3] if m.heal_attempts > 0]

        # Top 3 needing attention (with healing attempts and issues)
        needs_attention = [m for m in sorted_by_worst[:3] if m.needs_attention]

        # Calculate trends
        trends = self._calculate_trends(current_metrics, previous_metrics)
        improved_count = sum(1 for t in trends if t.trend == "improved")
        degraded_count = sum(1 for t in trends if t.trend == "degraded")
        stable_count = sum(1 for t in trends if t.trend == "stable")

        # Calculate previous week's overall success rate
        previous_success_rate = None
        success_rate_change = None
        if previous_metrics:
            prev_attempts = sum(m.heal_attempts for m in previous_metrics)
            prev_successes = sum(m.heal_successes for m in previous_metrics)
            if prev_attempts > 0:
                previous_success_rate = prev_successes / prev_attempts
                success_rate_change = (overall_success_rate - previous_success_rate) * 100

        # Create summary
        summary = WeeklySummary(
            period_start=period_start,
            period_end=period_end,
            total_integrations=len(current_metrics),
            total_healing_attempts=total_healing_attempts,
            successful_healings=successful_healings,
            failed_healings=failed_healings,
            overall_success_rate=overall_success_rate,
            top_performers=top_performers,
            needs_attention=needs_attention,
            trends=trends,
            improved_count=improved_count,
            degraded_count=degraded_count,
            stable_count=stable_count,
            previous_success_rate=previous_success_rate,
            success_rate_change=success_rate_change,
        )

        # Generate AI summary if LLM router available
        if self.llm_router and self.config.notifications.ai_enhanced:
            import asyncio

            # Run AI generation in parallel for better performance
            summary.ai_summary, summary.ai_recommendations = await asyncio.gather(
                self._generate_ai_summary(summary),
                self._generate_ai_recommendations(summary),
            )

        logger.info(
            f"Weekly summary generated: {total_healing_attempts} heals, "
            f"{overall_success_rate:.1%} success rate"
        )

        return summary

    async def _get_previous_week_metrics(
        self,
        current_period_start: datetime,
    ) -> list[ReliabilityMetric]:
        """Get metrics for the previous week.

        Args:
            current_period_start: Start of current period

        Returns:
            List of metrics from previous week
        """
        # Previous week is 7-14 days ago
        prev_start = current_period_start - timedelta(days=7)

        async with self.database.async_session() as session:
            # Query for previous week's data
            query = select(IntegrationReliability).where(
                IntegrationReliability.instance_id == self.instance_id,
                IntegrationReliability.timestamp >= prev_start,
                IntegrationReliability.timestamp < current_period_start,
            )
            result = await session.execute(query)
            events = result.scalars().all()

            if not events:
                return []

            # Aggregate by integration
            metrics_by_domain: dict[str, dict[str, Any]] = {}
            for event in events:
                domain = event.integration_domain
                if domain not in metrics_by_domain:
                    metrics_by_domain[domain] = {
                        "integration_id": event.integration_id,
                        "heal_successes": 0,
                        "heal_failures": 0,
                        "unavailable_events": 0,
                        "total_events": 0,
                    }

                metrics_by_domain[domain]["total_events"] += 1
                if event.event_type == "heal_success":
                    metrics_by_domain[domain]["heal_successes"] += 1
                elif event.event_type == "heal_failure":
                    metrics_by_domain[domain]["heal_failures"] += 1
                elif event.event_type == "unavailable":
                    metrics_by_domain[domain]["unavailable_events"] += 1

            # Convert to ReliabilityMetric objects
            metrics = []
            for domain, data in metrics_by_domain.items():
                heal_attempts = data["heal_successes"] + data["heal_failures"]
                if heal_attempts > 0:
                    success_rate = data["heal_successes"] / heal_attempts
                else:
                    success_rate = 1.0

                metric = ReliabilityMetric(
                    integration_id=data["integration_id"],
                    integration_domain=domain,
                    total_events=data["total_events"],
                    heal_successes=data["heal_successes"],
                    heal_failures=data["heal_failures"],
                    unavailable_events=data["unavailable_events"],
                    success_rate=success_rate,
                    period_start=prev_start,
                    period_end=current_period_start,
                )
                metrics.append(metric)

            return metrics

    def _calculate_trends(
        self,
        current: list[ReliabilityMetric],
        previous: list[ReliabilityMetric],
    ) -> list[IntegrationTrend]:
        """Calculate trends between current and previous weeks.

        Args:
            current: Current week metrics
            previous: Previous week metrics

        Returns:
            List of trends for each integration
        """
        trends = []

        # Create lookup for previous metrics
        prev_lookup = {m.integration_domain: m.success_rate for m in previous}

        for metric in current:
            domain = metric.integration_domain
            current_rate = metric.success_rate
            previous_rate = prev_lookup.get(domain)

            if previous_rate is None:
                # New integration
                trend = IntegrationTrend(
                    domain=domain,
                    current_rate=current_rate,
                    previous_rate=None,
                    trend="new",
                    change_percent=None,
                )
            else:
                # Calculate change
                change = current_rate - previous_rate
                change_percent = change * 100

                # Determine trend (5% threshold for significance)
                if change > 0.05:
                    trend_label = "improved"
                elif change < -0.05:
                    trend_label = "degraded"
                else:
                    trend_label = "stable"

                trend = IntegrationTrend(
                    domain=domain,
                    current_rate=current_rate,
                    previous_rate=previous_rate,
                    trend=trend_label,
                    change_percent=change_percent,
                )

            trends.append(trend)

        return trends

    async def _generate_ai_summary(self, summary: WeeklySummary) -> str | None:
        """Generate AI-powered natural language summary.

        Args:
            summary: Summary data to analyze

        Returns:
            AI-generated summary text, or None if generation failed
        """
        if not self.llm_router:
            return None

        # Build prompt with summary data
        prompt = self._build_summary_prompt(summary)

        system_prompt = """You are an AI assistant that analyzes Home Assistant integration
health data and generates concise, actionable summaries. Keep your response brief (2-3 sentences)
and focus on the most important insights. Use a friendly but professional tone."""

        try:
            result = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.MODERATE,
                max_tokens=200,
                temperature=0.7,
                system_prompt=system_prompt,
            )
            return result
        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            return None

    async def _generate_ai_recommendations(self, summary: WeeklySummary) -> str | None:
        """Generate AI-powered recommendations.

        Args:
            summary: Summary data to analyze

        Returns:
            AI-generated recommendations, or None if generation failed
        """
        if not self.llm_router or not summary.needs_attention:
            return None

        # Build prompt for recommendations
        prompt = self._build_recommendations_prompt(summary)

        system_prompt = """You are an AI assistant that provides specific, actionable
recommendations for improving Home Assistant integration reliability. Be concise and
prioritize the most impactful actions. Format as a brief bulleted list (2-3 items)."""

        try:
            result = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.MODERATE,
                max_tokens=200,
                temperature=0.5,
                system_prompt=system_prompt,
            )
            return result
        except Exception as e:
            logger.warning(f"Failed to generate AI recommendations: {e}")
            return None

    def _build_summary_prompt(self, summary: WeeklySummary) -> str:
        """Build prompt for AI summary generation.

        Args:
            summary: Summary data

        Returns:
            Formatted prompt string
        """
        lines = [
            f"Analyze this Home Assistant weekly health report (Week of {summary.period_start.strftime('%b %d')} - {summary.period_end.strftime('%b %d')}):",
            "",
            f"- Total integrations monitored: {summary.total_integrations}",
            f"- Healing attempts: {summary.total_healing_attempts}",
            f"- Success rate: {summary.overall_success_rate:.1%}",
        ]

        if summary.success_rate_change is not None:
            direction = "up" if summary.success_rate_change > 0 else "down"
            lines.append(
                f"- Change from last week: {direction} {abs(summary.success_rate_change):.1f}%"
            )

        if summary.top_performers:
            lines.append("")
            lines.append("Top performers:")
            for m in summary.top_performers:
                lines.append(f"- {m.integration_domain}: {m.success_rate:.1%}")

        if summary.needs_attention:
            lines.append("")
            lines.append("Needs attention:")
            for m in summary.needs_attention:
                lines.append(f"- {m.integration_domain}: {m.success_rate:.1%}")

        lines.append("")
        lines.append(
            f"Trends: {summary.improved_count} improved, {summary.degraded_count} degraded, {summary.stable_count} stable"
        )
        lines.append("")
        lines.append("Provide a brief (2-3 sentence) summary of the overall system health.")

        return "\n".join(lines)

    def _build_recommendations_prompt(self, summary: WeeklySummary) -> str:
        """Build prompt for AI recommendations generation.

        Args:
            summary: Summary data

        Returns:
            Formatted prompt string
        """
        lines = [
            "Based on this week's Home Assistant integration data, provide specific recommendations:",
            "",
        ]

        for metric in summary.needs_attention:
            lines.append(f"- {metric.integration_domain}: {metric.success_rate:.1%} success rate")
            lines.append(
                f"  ({metric.heal_failures} failures, {metric.unavailable_events} unavailable events)"
            )

        # Add trend context
        degraded = [t for t in summary.trends if t.trend == "degraded"]
        if degraded:
            lines.append("")
            lines.append("Recently degraded:")
            for t in degraded[:3]:
                if t.change_percent:
                    lines.append(f"- {t.domain}: down {abs(t.change_percent):.1f}%")

        lines.append("")
        lines.append("Provide 2-3 specific, actionable recommendations to improve reliability.")

        return "\n".join(lines)

    async def send_notification(self, summary: WeeklySummary) -> None:
        """Send summary as Home Assistant persistent notification.

        Args:
            summary: Summary to send
        """
        if not self.notification_manager:
            logger.warning("Cannot send notification: notification_manager not available")
            return

        # Build stats dictionary for template
        stats: dict[str, Any] = {
            "total_attempts": summary.total_healing_attempts,
            "successful": summary.successful_healings,
            "failed": summary.failed_healings,
            "success_rate": summary.overall_success_rate * 100,
            "avg_duration_seconds": 0,  # TODO: Add duration tracking
        }

        # Add top issues if we have needs_attention
        if summary.needs_attention:
            stats["top_issues"] = [
                (m.integration_domain, m.heal_failures) for m in summary.needs_attention
            ]

        # Create enhanced message with AI content
        extra: dict[str, Any] = {}
        if summary.ai_summary:
            extra["ai_summary"] = summary.ai_summary
        if summary.ai_recommendations:
            extra["ai_recommendations"] = summary.ai_recommendations

        # Add trend summary
        extra["trends"] = {
            "improved": summary.improved_count,
            "degraded": summary.degraded_count,
            "stable": summary.stable_count,
        }

        # Add comparison data
        if summary.success_rate_change is not None:
            extra["rate_change"] = summary.success_rate_change

        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats=stats,
            extra=extra,
        )

        # Send notification
        await self.notification_manager.notify(
            context,
            channels=[
                NotificationChannel.HOME_ASSISTANT,
                NotificationChannel.CLI,
            ],
        )

        logger.info("Weekly summary notification sent")

    async def store_in_database(self, summary: WeeklySummary) -> None:
        """Store weekly summary in pattern_insights table.

        Args:
            summary: Summary to store
        """
        async with self.database.async_session() as session:
            # Serialize summary data
            data = {
                "total_integrations": summary.total_integrations,
                "total_healing_attempts": summary.total_healing_attempts,
                "successful_healings": summary.successful_healings,
                "failed_healings": summary.failed_healings,
                "overall_success_rate": summary.overall_success_rate,
                "improved_count": summary.improved_count,
                "degraded_count": summary.degraded_count,
                "stable_count": summary.stable_count,
                "top_performers": [
                    {
                        "domain": m.integration_domain,
                        "success_rate": m.success_rate,
                        "heal_successes": m.heal_successes,
                    }
                    for m in summary.top_performers
                ],
                "needs_attention": [
                    {
                        "domain": m.integration_domain,
                        "success_rate": m.success_rate,
                        "heal_failures": m.heal_failures,
                    }
                    for m in summary.needs_attention
                ],
                "trends": [
                    {
                        "domain": t.domain,
                        "current_rate": t.current_rate,
                        "previous_rate": t.previous_rate,
                        "trend": t.trend,
                        "change_percent": t.change_percent,
                    }
                    for t in summary.trends
                ],
            }

            # Add AI content if available
            if summary.ai_summary:
                data["ai_summary"] = summary.ai_summary
            if summary.ai_recommendations:
                data["ai_recommendations"] = summary.ai_recommendations

            # Add comparison data
            if summary.previous_success_rate is not None:
                data["previous_success_rate"] = summary.previous_success_rate
            if summary.success_rate_change is not None:
                data["success_rate_change"] = summary.success_rate_change

            # Create pattern insight record
            insight = PatternInsight(
                insight_type="weekly_summary",
                period="weekly",
                period_start=summary.period_start,
                data=data,
            )

            session.add(insight)
            await session.commit()

            logger.info(f"Weekly summary stored in database for {summary.period_start.date()}")

    async def generate_and_send(self) -> WeeklySummary:
        """Generate weekly summary, send notification, and store in database.

        This is the main entry point for scheduled execution.

        Returns:
            Generated WeeklySummary
        """
        # Generate summary
        summary = await self.generate_summary()

        # Store in database
        await self.store_in_database(summary)

        # Send notification if enabled
        if self.config.notifications.weekly_summary:
            await self.send_notification(summary)

        return summary

    def format_report(self, summary: WeeklySummary) -> str:
        """Format summary as human-readable report text.

        Args:
            summary: Summary to format

        Returns:
            Formatted report string
        """
        lines = [
            "Weekly Health Summary",
            f"Week of {summary.period_start.strftime('%b %d')} - {summary.period_end.strftime('%b %d, %Y')}",
            "",
            "Overview:",
            f"This week, HA Boss monitored {summary.total_integrations} integrations and performed "
            f"{summary.total_healing_attempts} healing actions with a {summary.overall_success_rate:.0%} success rate.",
        ]

        # Add comparison with previous week
        if summary.success_rate_change is not None:
            if summary.success_rate_change > 0:
                lines.append(
                    f"Overall system health improved {summary.success_rate_change:.1f}% compared to last week."
                )
            elif summary.success_rate_change < 0:
                lines.append(
                    f"Overall system health decreased {abs(summary.success_rate_change):.1f}% compared to last week."
                )
            else:
                lines.append("Overall system health remained stable compared to last week.")

        # Top performers
        if summary.top_performers:
            lines.extend(["", "Top Performers:"])
            for m in summary.top_performers:
                trend_info = ""
                for t in summary.trends:
                    if (
                        t.domain == m.integration_domain
                        and t.trend == "improved"
                        and t.change_percent
                    ):
                        trend_info = f" (improved from {t.previous_rate:.0%} last week)"
                        break
                lines.append(
                    f"  {m.integration_domain}: {m.success_rate:.0%} reliability{trend_info}"
                )

        # Needs attention
        if summary.needs_attention:
            lines.extend(["", "Needs Attention:"])
            for m in summary.needs_attention:
                trend_info = ""
                for t in summary.trends:
                    if (
                        t.domain == m.integration_domain
                        and t.trend == "degraded"
                        and t.change_percent
                    ):
                        trend_info = f" (degraded from {t.previous_rate:.0%} last week)"
                        break
                lines.append(
                    f"  {m.integration_domain}: {m.success_rate:.0%} reliability{trend_info}"
                )

        # Trends
        lines.extend(
            [
                "",
                "Trends:",
                f"  {summary.improved_count} integrations improved, "
                f"{summary.degraded_count} degraded, "
                f"{summary.stable_count} stable",
            ]
        )

        # AI content
        if summary.ai_summary:
            lines.extend(["", "AI Analysis:", summary.ai_summary])

        if summary.ai_recommendations:
            lines.extend(["", "Recommendations:", summary.ai_recommendations])

        return "\n".join(lines)
