"""Tests for ReliabilityAnalyzer."""

from datetime import UTC, datetime, timedelta

import pytest

from ha_boss.core.database import IntegrationReliability, init_database
from ha_boss.intelligence.reliability_analyzer import (
    FailureEvent,
    ReliabilityAnalyzer,
)


@pytest.fixture
async def test_database(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test_reliability.db"
    db = await init_database(db_path)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def analyzer(test_database):
    """Create analyzer instance."""
    return ReliabilityAnalyzer("default", test_database)


@pytest.fixture
async def sample_data(test_database):
    """Create sample reliability data for testing."""
    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        # Hue integration: 8 successes, 2 failures = 80% success rate (Good)
        for i in range(8):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=now - timedelta(hours=i),
                event_type="heal_success",
                entity_id=f"light.living_room_{i}",
            )
            session.add(event)

        for i in range(2):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=now - timedelta(hours=8 + i),
                event_type="heal_failure",
                entity_id=f"light.kitchen_{i}",
            )
            session.add(event)

        # ZWave integration: 1 success, 4 failures = 20% success rate (Poor)
        event = IntegrationReliability(
            integration_id="zwave_456",
            integration_domain="zwave",
            timestamp=now - timedelta(hours=1),
            event_type="heal_success",
        )
        session.add(event)

        for i in range(4):
            event = IntegrationReliability(
                integration_id="zwave_456",
                integration_domain="zwave",
                timestamp=now - timedelta(hours=2 + i),
                event_type="heal_failure",
            )
            session.add(event)

        # Met.no integration: All unavailable events, no healing attempts
        for i in range(5):
            event = IntegrationReliability(
                integration_id="met_789",
                integration_domain="met",
                timestamp=now - timedelta(hours=i),
                event_type="unavailable",
            )
            session.add(event)

        # MQTT integration: 19 successes, 1 failure = 95% success rate (Excellent)
        for i in range(19):
            event = IntegrationReliability(
                integration_id="mqtt_101",
                integration_domain="mqtt",
                timestamp=now - timedelta(hours=i),
                event_type="heal_success",
            )
            session.add(event)

        event = IntegrationReliability(
            integration_id="mqtt_101",
            integration_domain="mqtt",
            timestamp=now - timedelta(hours=20),
            event_type="heal_failure",
        )
        session.add(event)

        await session.commit()


@pytest.mark.asyncio
async def test_get_integration_metrics(analyzer, sample_data):
    """Test getting integration metrics."""
    metrics = await analyzer.get_integration_metrics(days=7)

    # Should have 4 integrations
    assert len(metrics) == 4

    # Should be sorted worst-first (zwave=20%, hue=80%, met=100%, mqtt=95%)
    assert metrics[0].integration_domain == "zwave"
    assert metrics[1].integration_domain == "hue"
    # met and mqtt both 95%+ could be either order


@pytest.mark.asyncio
async def test_success_rate_calculation(analyzer, sample_data):
    """Test success rate calculation (8 successes, 2 failures = 80%)."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="hue")

    assert len(metrics) == 1
    metric = metrics[0]

    assert metric.integration_domain == "hue"
    assert metric.heal_successes == 8
    assert metric.heal_failures == 2
    assert metric.success_rate == 0.80  # 8 / (8 + 2)


@pytest.mark.asyncio
async def test_reliability_score_excellent(analyzer, sample_data):
    """Test reliability score: Excellent (≥95%)."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="mqtt")

    metric = metrics[0]
    assert metric.success_rate == 0.95  # 19 / (19 + 1)
    assert metric.reliability_score == "Excellent"
    assert not metric.needs_attention


@pytest.mark.asyncio
async def test_reliability_score_good(analyzer, sample_data):
    """Test reliability score: Good (≥80%, <95%)."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="hue")

    metric = metrics[0]
    assert metric.success_rate == 0.80
    assert metric.reliability_score == "Good"
    assert not metric.needs_attention


@pytest.mark.asyncio
async def test_reliability_score_fair(test_database):
    """Test reliability score: Fair (≥60%, <80%)."""
    # Create data with 7 successes, 3 failures = 70%
    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        for i in range(7):
            event = IntegrationReliability(
                integration_id="test_123",
                integration_domain="test",
                timestamp=now - timedelta(hours=i),
                event_type="heal_success",
            )
            session.add(event)

        for i in range(3):
            event = IntegrationReliability(
                integration_id="test_123",
                integration_domain="test",
                timestamp=now - timedelta(hours=7 + i),
                event_type="heal_failure",
            )
            session.add(event)

        await session.commit()

    analyzer = ReliabilityAnalyzer("default", test_database)
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="test")

    metric = metrics[0]
    assert metric.success_rate == 0.7
    assert metric.reliability_score == "Fair"
    assert metric.needs_attention


@pytest.mark.asyncio
async def test_reliability_score_poor(analyzer, sample_data):
    """Test reliability score: Poor (<60%)."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="zwave")

    metric = metrics[0]
    assert metric.success_rate == 0.20  # 1 / (1 + 4)
    assert metric.reliability_score == "Poor"
    assert metric.needs_attention


@pytest.mark.asyncio
async def test_no_healing_attempts_defaults_to_100(analyzer, sample_data):
    """Test that integrations with no healing attempts have 100% success rate."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="met")

    metric = metrics[0]
    assert metric.heal_successes == 0
    assert metric.heal_failures == 0
    assert metric.success_rate == 1.0  # No attempts = 100%
    assert metric.reliability_score == "Excellent"


@pytest.mark.asyncio
async def test_get_failure_timeline(analyzer, sample_data):
    """Test getting failure timeline (chronological, only failures)."""
    failures = await analyzer.get_failure_timeline(days=7)

    # Should only have heal_failure and unavailable events
    for failure in failures:
        assert failure.event_type in ["heal_failure", "unavailable"]

    # Should be in chronological order (oldest first)
    for i in range(len(failures) - 1):
        assert failures[i].timestamp <= failures[i + 1].timestamp


@pytest.mark.asyncio
async def test_get_failure_timeline_filtered_by_domain(analyzer, sample_data):
    """Test filtering failure timeline by domain."""
    failures = await analyzer.get_failure_timeline(days=7, integration_domain="hue")

    # Should only have hue failures
    for failure in failures:
        assert failure.integration_domain == "hue"
        assert failure.event_type == "heal_failure"

    assert len(failures) == 2  # Hue has 2 failures


@pytest.mark.asyncio
async def test_get_failure_timeline_limit(analyzer, sample_data):
    """Test limiting failure timeline results."""
    failures = await analyzer.get_failure_timeline(days=7, limit=5)

    # Should not exceed limit
    assert len(failures) <= 5


@pytest.mark.asyncio
async def test_get_top_failing_integrations(analyzer, sample_data):
    """Test getting top failing integrations."""
    top_failing = await analyzer.get_top_failing_integrations(days=7, limit=2)

    # Should return worst 2
    assert len(top_failing) == 2

    # Worst should be first
    assert top_failing[0].integration_domain == "zwave"
    assert top_failing[0].success_rate == 0.20

    # Second worst
    assert top_failing[1].integration_domain == "hue"
    assert top_failing[1].success_rate == 0.80


@pytest.mark.asyncio
async def test_no_data_returns_empty_list(test_database):
    """Test that no data returns empty list, not crash."""
    analyzer = ReliabilityAnalyzer("default", test_database)

    # Query with no data in database
    metrics = await analyzer.get_integration_metrics(days=7)

    assert metrics == []
    assert isinstance(metrics, list)


@pytest.mark.asyncio
async def test_filter_by_domain(analyzer, sample_data):
    """Test filtering metrics by domain."""
    hue_metrics = await analyzer.get_integration_metrics(days=7, integration_domain="hue")

    assert len(hue_metrics) == 1
    assert hue_metrics[0].integration_domain == "hue"


@pytest.mark.asyncio
async def test_recommendations_poor_reliability(analyzer, sample_data):
    """Test recommendations for poor reliability integration."""
    recommendations = await analyzer.get_recommendations(integration_domain="zwave", days=7)

    # Should have critical warning
    assert any("CRITICAL" in rec for rec in recommendations)
    assert any("20.0%" in rec for rec in recommendations)


@pytest.mark.asyncio
async def test_recommendations_good_reliability(analyzer, sample_data):
    """Test recommendations for good reliability integration."""
    recommendations = await analyzer.get_recommendations(integration_domain="hue", days=7)

    # Should have positive message
    assert any("adequately" in rec or "performing" in rec for rec in recommendations)
    assert any("80.0%" in rec for rec in recommendations)


@pytest.mark.asyncio
async def test_recommendations_excellent_reliability(analyzer, sample_data):
    """Test recommendations for excellent reliability integration."""
    recommendations = await analyzer.get_recommendations(integration_domain="mqtt", days=7)

    # Should have positive message
    assert any("reliable" in rec for rec in recommendations)
    assert any("95.0%" in rec for rec in recommendations)


@pytest.mark.asyncio
async def test_recommendations_no_healing_with_unavailable(analyzer, sample_data):
    """Test recommendation when no healing attempts but unavailable events exist."""
    recommendations = await analyzer.get_recommendations(integration_domain="met", days=7)

    # Should suggest checking healing configuration
    assert any("healing" in rec.lower() for rec in recommendations)


@pytest.mark.asyncio
async def test_recommendations_no_data(test_database):
    """Test recommendations when no data exists."""
    analyzer = ReliabilityAnalyzer("default", test_database)
    recommendations = await analyzer.get_recommendations(integration_domain="nonexistent", days=7)

    assert len(recommendations) == 1
    assert "No data available" in recommendations[0]


@pytest.mark.asyncio
async def test_metric_properties(analyzer, sample_data):
    """Test ReliabilityMetric calculated properties."""
    metrics = await analyzer.get_integration_metrics(days=7, integration_domain="hue")
    metric = metrics[0]

    # Test heal_attempts property
    assert metric.heal_attempts == 10  # 8 successes + 2 failures

    # Test needs_attention property
    assert not metric.needs_attention  # 80% is ≥ 80%

    # Test reliability_score property
    assert metric.reliability_score == "Good"


@pytest.mark.asyncio
async def test_failure_event_dataclass():
    """Test FailureEvent dataclass creation."""
    now = datetime.now(UTC)

    event = FailureEvent(
        timestamp=now,
        integration_id="test_123",
        integration_domain="test",
        event_type="heal_failure",
        entity_id="light.test",
        details={"reason": "timeout"},
    )

    assert event.timestamp == now
    assert event.integration_id == "test_123"
    assert event.integration_domain == "test"
    assert event.event_type == "heal_failure"
    assert event.entity_id == "light.test"
    assert event.details == {"reason": "timeout"}


@pytest.mark.asyncio
async def test_date_range_filtering(test_database):
    """Test that date range filtering works correctly."""
    now = datetime.now(UTC)
    analyzer = ReliabilityAnalyzer("default", test_database)

    async with test_database.async_session() as session:
        # Old event (15 days ago)
        old_event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="test",
            timestamp=now - timedelta(days=15),
            event_type="heal_success",
        )
        session.add(old_event)

        # Recent event (3 days ago)
        recent_event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="test",
            timestamp=now - timedelta(days=3),
            event_type="heal_failure",
        )
        session.add(recent_event)

        await session.commit()

    # Query last 7 days - should only get recent event
    metrics = await analyzer.get_integration_metrics(days=7)

    assert len(metrics) == 1
    assert metrics[0].total_events == 1  # Only recent event


@pytest.mark.asyncio
async def test_multiple_integrations_same_domain(test_database):
    """Test handling multiple integration instances of same domain."""
    now = datetime.now(UTC)
    analyzer = ReliabilityAnalyzer("default", test_database)

    async with test_database.async_session() as session:
        # Two different hue bridges
        for integration_id in ["hue_bridge_1", "hue_bridge_2"]:
            for i in range(5):
                event = IntegrationReliability(
                    integration_id=integration_id,
                    integration_domain="hue",
                    timestamp=now - timedelta(hours=i),
                    event_type="heal_success",
                )
                session.add(event)

        await session.commit()

    # Should have separate metrics for each integration
    metrics = await analyzer.get_integration_metrics(days=7)

    assert len(metrics) == 2
    assert metrics[0].integration_id in ["hue_bridge_1", "hue_bridge_2"]
    assert metrics[1].integration_id in ["hue_bridge_1", "hue_bridge_2"]
    assert metrics[0].integration_id != metrics[1].integration_id
