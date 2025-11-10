# Issue #28: Implement Integration Reliability Tracking

## 📋 Overview

Implement queries and calculations for integration reliability metrics to answer: "Which integrations are unreliable?"

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P1
**Effort**: 3 hours

## 🎯 Objective

Create `ReliabilityAnalyzer` that:
- Calculates success rates per integration
- Identifies top failing integrations
- Provides failure timelines
- Generates reliability scores (Excellent/Good/Fair/Poor)

## 🏗️ Implementation

### File: `ha_boss/intelligence/reliability_analyzer.py`

```python
"""Integration reliability analysis and metrics."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ha_boss.core.database import Database, IntegrationReliability

logger = logging.getLogger(__name__)


class ReliabilityMetric:
    """Represents integration reliability metrics."""

    def __init__(
        self,
        integration_id: str,
        integration_domain: str,
        total_events: int,
        heal_successes: int,
        heal_failures: int,
        unavailable_events: int,
        success_rate: float,
        period_start: datetime,
        period_end: datetime,
    ):
        self.integration_id = integration_id
        self.integration_domain = integration_domain
        self.total_events = total_events
        self.heal_successes = heal_successes
        self.heal_failures = heal_failures
        self.unavailable_events = unavailable_events
        self.success_rate = success_rate
        self.period_start = period_start
        self.period_end = period_end

    @property
    def reliability_score(self) -> str:
        """Human-readable reliability score."""
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
        """Whether this integration needs attention."""
        return self.success_rate < 0.80 or self.heal_failures > 5


class ReliabilityAnalyzer:
    """Analyzes integration reliability patterns."""

    def __init__(self, database: Database):
        self.database = database

    async def get_integration_metrics(
        self,
        integration_domain: str | None = None,
        days: int = 7,
    ) -> list[ReliabilityMetric]:
        """Get reliability metrics for integrations.

        Args:
            integration_domain: Filter by domain (None = all)
            days: Number of days to analyze

        Returns:
            List of reliability metrics, sorted by success rate (worst first)
        """
        period_start = datetime.now(UTC) - timedelta(days=days)
        period_end = datetime.now(UTC)

        async with self.database.session() as session:
            # Build query to aggregate events
            query = select(
                IntegrationReliability.integration_id,
                IntegrationReliability.integration_domain,
                func.count().label("total_events"),
                func.sum(
                    func.case(
                        (IntegrationReliability.event_type == "heal_success", 1),
                        else_=0
                    )
                ).label("heal_successes"),
                func.sum(
                    func.case(
                        (IntegrationReliability.event_type == "heal_failure", 1),
                        else_=0
                    )
                ).label("heal_failures"),
                func.sum(
                    func.case(
                        (IntegrationReliability.event_type == "unavailable", 1),
                        else_=0
                    )
                ).label("unavailable_events"),
            ).where(
                IntegrationReliability.timestamp >= period_start
            ).group_by(
                IntegrationReliability.integration_id,
                IntegrationReliability.integration_domain
            )

            # Filter by domain if specified
            if integration_domain:
                query = query.where(
                    IntegrationReliability.integration_domain == integration_domain
                )

            result = await session.execute(query)
            rows = result.all()

            # Build metrics
            metrics = []
            for row in rows:
                heal_attempts = row.heal_successes + row.heal_failures
                success_rate = (
                    row.heal_successes / heal_attempts if heal_attempts > 0 else 1.0
                )

                metrics.append(
                    ReliabilityMetric(
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
                )

            # Sort by success rate (worst first) for easy identification
            metrics.sort(key=lambda m: m.success_rate)

            return metrics

    async def get_failure_timeline(
        self,
        integration_domain: str,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Get timeline of failures for an integration.

        Args:
            integration_domain: Integration to analyze
            days: Number of days

        Returns:
            List of failure events with timestamps
        """
        period_start = datetime.now(UTC) - timedelta(days=days)

        async with self.database.session() as session:
            query = select(IntegrationReliability).where(
                IntegrationReliability.integration_domain == integration_domain,
                IntegrationReliability.timestamp >= period_start,
                IntegrationReliability.event_type.in_(["heal_failure", "unavailable"])
            ).order_by(IntegrationReliability.timestamp.desc())

            result = await session.execute(query)
            events = result.scalars().all()

            return [
                {
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "entity_id": event.entity_id,
                    "details": event.details,
                }
                for event in events
            ]

    async def get_top_failing_integrations(
        self,
        limit: int = 5,
        days: int = 7,
    ) -> list[ReliabilityMetric]:
        """Get top failing integrations.

        Args:
            limit: Number of integrations to return
            days: Number of days to analyze

        Returns:
            Top N failing integrations
        """
        all_metrics = await self.get_integration_metrics(days=days)

        # Filter to only those with failures
        failing = [m for m in all_metrics if m.heal_failures > 0]

        # Return top N worst
        return failing[:limit]

    async def get_recommendations(
        self,
        integration_domain: str,
        days: int = 7,
    ) -> list[str]:
        """Get actionable recommendations for an integration.

        Args:
            integration_domain: Integration to analyze
            days: Number of days

        Returns:
            List of recommendation strings
        """
        metrics_list = await self.get_integration_metrics(integration_domain, days)

        if not metrics_list:
            return ["No data available for this integration"]

        metric = metrics_list[0]
        recommendations = []

        if metric.success_rate < 0.50:
            recommendations.append(
                f"🔴 Critical: {integration_domain} has very poor reliability ({metric.success_rate*100:.0f}%)"
            )
            recommendations.append("Check Home Assistant logs immediately")
            recommendations.append("Consider reconfiguring or replacing this integration")

        elif metric.success_rate < 0.80:
            recommendations.append(
                f"⚠️  {integration_domain} reliability is below target ({metric.success_rate*100:.0f}%)"
            )
            recommendations.append("Review integration configuration")
            recommendations.append("Check for firmware updates")

        if metric.unavailable_events > metric.heal_failures * 2:
            recommendations.append("Integration frequently goes unavailable")
            recommendations.append("Check network connectivity and power")

        if not recommendations:
            recommendations.append(f"✓ {integration_domain} is performing well")

        return recommendations
```

## ✅ Acceptance Criteria

- [ ] `ReliabilityAnalyzer` class implemented
- [ ] Calculate success rates per integration
- [ ] Query top failing integrations
- [ ] Get failure timeline with details
- [ ] Generate actionable recommendations
- [ ] Handle edge cases (no data, single event)
- [ ] Performance: Query 10k+ events in < 100ms
- [ ] Unit tests with test database
- [ ] Type hints on all methods

## 🧪 Testing

Create `tests/intelligence/test_reliability_analyzer.py`:

```python
@pytest.mark.asyncio
async def test_get_integration_metrics():
    """Test getting reliability metrics."""
    # Populate test database with events
    # Call get_integration_metrics()
    # Verify metrics calculated correctly

@pytest.mark.asyncio
async def test_success_rate_calculation():
    """Test success rate calculation."""
    # 8 successes, 2 failures = 80%
    # Verify correct calculation

@pytest.mark.asyncio
async def test_reliability_score():
    """Test reliability score labels."""
    # >= 95% = Excellent
    # >= 80% = Good
    # >= 60% = Fair
    # < 60% = Poor

@pytest.mark.asyncio
async def test_failure_timeline():
    """Test getting failure timeline."""
    # Add multiple failures at different times
    # Verify returned in chronological order
    # Verify only failures returned (not successes)

@pytest.mark.asyncio
async def test_top_failing_integrations():
    """Test getting top N failing integrations."""
    # Add events for multiple integrations
    # Call get_top_failing_integrations(limit=3)
    # Verify returns worst 3

@pytest.mark.asyncio
async def test_no_data():
    """Test handling when no data exists."""
    # Empty database
    # Should return empty list, not crash

@pytest.mark.asyncio
async def test_filter_by_domain():
    """Test filtering metrics by integration domain."""
    # Add events for multiple integrations
    # Query for specific domain
    # Verify only that domain returned

@pytest.mark.asyncio
async def test_recommendations():
    """Test generating recommendations."""
    # Test different scenarios:
    # - Poor reliability → critical warning
    # - Medium reliability → suggestions
    # - Good reliability → positive message
```

## 📝 Implementation Notes

1. **SQL Aggregation**: Use SQLAlchemy's `func.sum()` and `func.case()` for efficient counting

2. **Success Rate**: Handle division by zero (no healing attempts = 100%)

3. **Sorting**: Always sort worst-first for easy identification

4. **Performance**:
   - Use indexes on timestamp and integration_domain
   - Limit result sets with `days` parameter
   - Consider caching for frequently accessed metrics

5. **Recommendations**:
   - Use thresholds to categorize severity
   - Provide actionable next steps
   - Link to documentation where relevant

## 🔗 Dependencies

- **Requires**: #26 (database schema), #27 (pattern collector for data)
- **Blocks**: #29 (CLI reports use this analyzer)

---

**Labels**: `phase-2`, `intelligence`, `analytics`, `P1`
