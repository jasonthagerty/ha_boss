"""Pattern-based anomaly detection for integration failures."""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import func, select

from ha_boss.core.database import Database, IntegrationReliability
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


class AnomalyType(Enum):
    """Types of anomalies that can be detected."""

    UNUSUAL_FAILURE_RATE = "unusual_failure_rate"
    TIME_CORRELATION = "time_correlation"
    INTEGRATION_CORRELATION = "integration_correlation"


@dataclass
class Anomaly:
    """Detected anomaly with details and AI explanation."""

    type: AnomalyType
    integration_domain: str
    severity: float  # 0.0-1.0
    description: str
    detected_at: datetime
    ai_explanation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def severity_label(self) -> str:
        """Get human-readable severity label."""
        if self.severity >= 0.8:
            return "Critical"
        elif self.severity >= 0.6:
            return "High"
        elif self.severity >= 0.4:
            return "Medium"
        else:
            return "Low"


@dataclass
class FailureStats:
    """Statistics for failure analysis."""

    integration_domain: str
    integration_id: str
    failure_count: int
    period_hours: int
    timestamps: list[datetime] = field(default_factory=list)


class AnomalyDetector:
    """Detect anomalies in integration failure patterns.

    Uses statistical analysis and AI to identify unusual patterns
    and provide actionable explanations.
    """

    def __init__(
        self,
        database: Database,
        llm_router: LLMRouter | None = None,
        sensitivity_threshold: float = 2.0,
    ) -> None:
        """Initialize anomaly detector.

        Args:
            database: Database instance for pattern queries
            llm_router: Optional LLM router for AI explanations
            sensitivity_threshold: Standard deviations for anomaly detection (default: 2.0)
        """
        self.database = database
        self.llm_router = llm_router
        self.sensitivity_threshold = sensitivity_threshold

    async def detect_anomalies(self, hours: int = 24) -> list[Anomaly]:
        """Scan for anomalies in recent patterns.

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            List of detected anomalies, sorted by severity (highest first)
        """
        anomalies: list[Anomaly] = []

        # Run all detection methods
        failure_rate_anomalies = await self.check_unusual_failure_rate(hours=hours)
        anomalies.extend(failure_rate_anomalies)

        time_correlation_anomalies = await self.check_time_correlations(hours=hours)
        anomalies.extend(time_correlation_anomalies)

        integration_correlation_anomalies = await self.check_integration_correlations(hours=hours)
        anomalies.extend(integration_correlation_anomalies)

        # Generate AI explanations for high-severity anomalies
        if self.llm_router:
            for anomaly in anomalies:
                if anomaly.severity >= 0.6:  # Only for high/critical
                    explanation = await self._generate_ai_explanation(anomaly)
                    if explanation:
                        anomaly.ai_explanation = explanation

        # Sort by severity (highest first)
        anomalies.sort(key=lambda a: a.severity, reverse=True)

        return anomalies

    async def check_unusual_failure_rate(self, hours: int = 24) -> list[Anomaly]:
        """Detect integrations with unusual failure rates.

        Uses statistical analysis to find integrations with failure rates
        that exceed the mean by more than the sensitivity threshold
        (default: 2 standard deviations).

        Args:
            hours: Number of hours to analyze

        Returns:
            List of anomalies for unusual failure rates
        """
        anomalies: list[Anomaly] = []
        period_start = datetime.now(UTC) - timedelta(hours=hours)

        async with self.database.async_session() as session:
            # Get failure counts per integration for the recent period
            recent_query = (
                select(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                    func.count(IntegrationReliability.id).label("failure_count"),
                )
                .where(IntegrationReliability.timestamp >= period_start)
                .where(IntegrationReliability.event_type.in_(["heal_failure", "unavailable"]))
                .group_by(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                )
            )

            result = await session.execute(recent_query)
            recent_failures = result.all()

            if not recent_failures:
                return anomalies

            # Get historical baseline (last 30 days, excluding current period)
            baseline_start = datetime.now(UTC) - timedelta(days=30)
            baseline_end = period_start

            baseline_query = (
                select(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                    func.count(IntegrationReliability.id).label("failure_count"),
                )
                .where(IntegrationReliability.timestamp >= baseline_start)
                .where(IntegrationReliability.timestamp < baseline_end)
                .where(IntegrationReliability.event_type.in_(["heal_failure", "unavailable"]))
                .group_by(
                    IntegrationReliability.integration_id,
                    IntegrationReliability.integration_domain,
                )
            )

            result = await session.execute(baseline_query)
            baseline_failures = {row.integration_id: row for row in result.all()}

            # Calculate statistics and detect anomalies
            for recent in recent_failures:
                baseline = baseline_failures.get(recent.integration_id)

                # Calculate expected failure rate (failures per hour in baseline)
                if baseline:
                    baseline_hours = (baseline_end - baseline_start).total_seconds() / 3600
                    baseline_rate = (
                        baseline.failure_count / baseline_hours if baseline_hours > 0 else 0
                    )
                else:
                    # No baseline data - use 0 as expected
                    baseline_rate = 0

                # Calculate current rate
                current_rate = recent.failure_count / hours

                # Skip if no significant activity
                if current_rate == 0 and baseline_rate == 0:
                    continue

                # Calculate deviation from baseline
                # Use simple comparison for now (can add proper std dev with more data points)
                if baseline_rate > 0:
                    rate_increase = current_rate / baseline_rate
                else:
                    # No baseline - any failures are potentially anomalous
                    rate_increase = current_rate * 10 if current_rate > 0 else 0

                # Check if increase exceeds threshold
                if rate_increase >= self.sensitivity_threshold:
                    # Calculate severity based on increase magnitude
                    severity = min(1.0, rate_increase / 10)  # Cap at 1.0

                    # Build description
                    if baseline_rate > 0:
                        pct_increase = (rate_increase - 1) * 100
                        description = (
                            f"{recent.integration_domain} has {recent.failure_count} failures "
                            f"in the past {hours} hours ({pct_increase:.0f}% increase from normal rate)"
                        )
                    else:
                        description = (
                            f"{recent.integration_domain} has {recent.failure_count} failures "
                            f"in the past {hours} hours (normally has no failures)"
                        )

                    anomaly = Anomaly(
                        type=AnomalyType.UNUSUAL_FAILURE_RATE,
                        integration_domain=recent.integration_domain,
                        severity=severity,
                        description=description,
                        detected_at=datetime.now(UTC),
                        details={
                            "integration_id": recent.integration_id,
                            "failure_count": recent.failure_count,
                            "period_hours": hours,
                            "current_rate": current_rate,
                            "baseline_rate": baseline_rate,
                            "rate_increase": rate_increase,
                        },
                    )
                    anomalies.append(anomaly)

        return anomalies

    async def check_time_correlations(self, hours: int = 24) -> list[Anomaly]:
        """Detect time-of-day patterns in failures.

        Identifies if failures cluster around specific hours,
        suggesting time-based triggers.

        Args:
            hours: Number of hours to analyze

        Returns:
            List of anomalies for time correlations
        """
        anomalies: list[Anomaly] = []
        period_start = datetime.now(UTC) - timedelta(hours=hours)

        async with self.database.async_session() as session:
            # Get all failures in the period with timestamps
            query = (
                select(IntegrationReliability)
                .where(IntegrationReliability.timestamp >= period_start)
                .where(IntegrationReliability.event_type.in_(["heal_failure", "unavailable"]))
                .order_by(IntegrationReliability.timestamp)
            )

            result = await session.execute(query)
            events = result.scalars().all()

            if not events:
                return anomalies

            # Group failures by integration and analyze time patterns
            integration_events: dict[str, list[datetime]] = {}
            for event in events:
                if event.integration_domain not in integration_events:
                    integration_events[event.integration_domain] = []
                integration_events[event.integration_domain].append(event.timestamp)

            # Analyze each integration's time distribution
            for domain, timestamps in integration_events.items():
                if len(timestamps) < 3:  # Need at least 3 events for pattern
                    continue

                # Extract hours from timestamps
                hours_list = [ts.hour for ts in timestamps]

                # Calculate hour clustering
                hour_counts: dict[int, int] = {}
                for hour in hours_list:
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1

                # Find the most common hour
                max_hour = max(hour_counts, key=lambda h: hour_counts[h])
                max_count = hour_counts[max_hour]

                # Check if failures are concentrated (>60% in same 2-hour window)
                window_count = sum(
                    hour_counts.get(h, 0)
                    for h in range((max_hour - 1) % 24, (max_hour + 2) % 24)
                    if h in hour_counts or ((max_hour - 1) % 24 <= h <= (max_hour + 1) % 24)
                )

                # More precise window calculation
                window_hours = [(max_hour - 1) % 24, max_hour, (max_hour + 1) % 24]
                window_count = sum(hour_counts.get(h, 0) for h in window_hours)

                concentration = window_count / len(timestamps)

                if concentration >= 0.6:  # 60%+ failures in 3-hour window
                    # Calculate severity based on concentration and count
                    severity = min(1.0, concentration * (len(timestamps) / 10))

                    # Format hour range for display
                    start_hour = (max_hour - 1) % 24
                    end_hour = (max_hour + 1) % 24
                    hour_range = f"{start_hour:02d}:00-{end_hour:02d}:00"

                    description = (
                        f"{domain} failures cluster around {hour_range} "
                        f"({concentration:.0%} of {len(timestamps)} failures)"
                    )

                    anomaly = Anomaly(
                        type=AnomalyType.TIME_CORRELATION,
                        integration_domain=domain,
                        severity=severity,
                        description=description,
                        detected_at=datetime.now(UTC),
                        details={
                            "peak_hour": max_hour,
                            "hour_range": hour_range,
                            "window_count": window_count,
                            "total_failures": len(timestamps),
                            "concentration": concentration,
                            "hour_distribution": hour_counts,
                        },
                    )
                    anomalies.append(anomaly)

        return anomalies

    async def check_integration_correlations(self, hours: int = 24) -> list[Anomaly]:
        """Detect correlations between integration failures.

        Identifies integrations that fail together, suggesting
        shared dependencies or cascading failures.

        Args:
            hours: Number of hours to analyze

        Returns:
            List of anomalies for integration correlations
        """
        anomalies: list[Anomaly] = []
        period_start = datetime.now(UTC) - timedelta(hours=hours)

        async with self.database.async_session() as session:
            # Get all failures with timestamps
            query = (
                select(IntegrationReliability)
                .where(IntegrationReliability.timestamp >= period_start)
                .where(IntegrationReliability.event_type.in_(["heal_failure", "unavailable"]))
                .order_by(IntegrationReliability.timestamp)
            )

            result = await session.execute(query)
            events = result.scalars().all()

            if len(events) < 4:  # Need events to find correlations
                return anomalies

            # Group failures by time windows (5-minute buckets)
            time_buckets: dict[int, set[str]] = {}
            bucket_size_seconds = 300  # 5 minutes

            for event in events:
                # Calculate bucket index
                bucket = int(event.timestamp.timestamp() / bucket_size_seconds)
                if bucket not in time_buckets:
                    time_buckets[bucket] = set()
                time_buckets[bucket].add(event.integration_domain)

            # Find co-occurring integrations
            co_occurrences: dict[tuple[str, str], int] = {}
            integration_counts: dict[str, int] = {}

            for bucket, integrations in time_buckets.items():
                # Count each integration
                for integration in integrations:
                    integration_counts[integration] = integration_counts.get(integration, 0) + 1

                # Count pairs that fail together
                integrations_list = sorted(integrations)
                for i, int1 in enumerate(integrations_list):
                    for int2 in integrations_list[i + 1 :]:
                        pair = (int1, int2)
                        co_occurrences[pair] = co_occurrences.get(pair, 0) + 1

            # Identify significant correlations
            for pair, co_count in co_occurrences.items():
                int1, int2 = pair
                count1 = integration_counts[int1]
                count2 = integration_counts[int2]

                # Calculate correlation strength (Jaccard similarity)
                # co_count / (count1 + count2 - co_count)
                union_count = count1 + count2 - co_count
                if union_count > 0:
                    correlation = co_count / union_count
                else:
                    correlation = 0

                # Need at least 50% correlation and minimum occurrences
                if correlation >= 0.5 and co_count >= 2:
                    # Severity based on correlation strength and frequency
                    severity = min(1.0, correlation * (co_count / 5))

                    description = (
                        f"{int1} and {int2} fail together {co_count} times "
                        f"({correlation:.0%} correlation)"
                    )

                    # Create anomaly (report once for the pair)
                    anomaly = Anomaly(
                        type=AnomalyType.INTEGRATION_CORRELATION,
                        integration_domain=f"{int1}+{int2}",  # Composite name
                        severity=severity,
                        description=description,
                        detected_at=datetime.now(UTC),
                        details={
                            "integration_1": int1,
                            "integration_2": int2,
                            "co_occurrence_count": co_count,
                            "int1_total": count1,
                            "int2_total": count2,
                            "correlation": correlation,
                        },
                    )
                    anomalies.append(anomaly)

        return anomalies

    async def _generate_ai_explanation(self, anomaly: Anomaly) -> str | None:
        """Generate AI explanation for an anomaly.

        Args:
            anomaly: The anomaly to explain

        Returns:
            AI-generated explanation or None if generation fails
        """
        if not self.llm_router:
            return None

        try:
            # Build context-aware prompt based on anomaly type
            prompt = self._build_explanation_prompt(anomaly)

            response = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.SIMPLE,
                max_tokens=200,
                temperature=0.3,
                system_prompt=self._get_system_prompt(),
            )

            return response

        except Exception as e:
            logger.warning(
                f"Failed to generate AI explanation for {anomaly.integration_domain}: {e}"
            )
            return None

    def _build_explanation_prompt(self, anomaly: Anomaly) -> str:
        """Build prompt for AI explanation generation.

        Args:
            anomaly: The anomaly to explain

        Returns:
            Prompt string
        """
        parts = [
            f"Anomaly Type: {anomaly.type.value}",
            f"Integration: {anomaly.integration_domain}",
            f"Severity: {anomaly.severity_label}",
            f"Description: {anomaly.description}",
        ]

        # Add type-specific details
        if anomaly.type == AnomalyType.UNUSUAL_FAILURE_RATE:
            if "rate_increase" in anomaly.details:
                parts.append(f"Rate increase: {anomaly.details['rate_increase']:.1f}x normal")
            if "failure_count" in anomaly.details:
                parts.append(f"Recent failures: {anomaly.details['failure_count']}")

        elif anomaly.type == AnomalyType.TIME_CORRELATION:
            if "hour_range" in anomaly.details:
                parts.append(f"Peak failure time: {anomaly.details['hour_range']}")
            if "concentration" in anomaly.details:
                parts.append(f"Time concentration: {anomaly.details['concentration']:.0%}")

        elif anomaly.type == AnomalyType.INTEGRATION_CORRELATION:
            if "correlation" in anomaly.details:
                parts.append(f"Correlation strength: {anomaly.details['correlation']:.0%}")

        prompt = "\n".join(parts)
        prompt += "\n\nProvide a brief explanation of likely causes and 2-3 actionable suggestions."

        return prompt

    def _get_system_prompt(self) -> str:
        """Get system prompt for AI explanations.

        Returns:
            System prompt string
        """
        return """You are a Home Assistant expert analyzing integration failure patterns.
Provide concise, actionable explanations for the detected anomaly.

Focus on:
1. Most likely cause based on the pattern
2. Specific steps to investigate
3. Potential fixes or mitigations

Be practical and specific to Home Assistant integrations.
Keep your response brief (3-4 sentences max)."""


async def create_anomaly_detector(
    database: Database,
    llm_router: LLMRouter | None = None,
    sensitivity_threshold: float = 2.0,
) -> AnomalyDetector:
    """Create an anomaly detector.

    Args:
        database: Database instance
        llm_router: Optional LLM router for AI explanations
        sensitivity_threshold: Standard deviations for anomaly detection

    Returns:
        Initialized anomaly detector
    """
    return AnomalyDetector(database, llm_router, sensitivity_threshold)
