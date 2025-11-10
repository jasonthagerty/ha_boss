"""Tests for Phase 2 pattern collection database models."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from ha_boss.core.database import (
    Database,
    IntegrationMetrics,
    IntegrationReliability,
    PatternInsight,
    init_database,
)


@pytest.fixture
async def test_database(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test_patterns.db"
    db = await init_database(db_path)
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_integration_reliability_creation(test_database):
    """Test creating IntegrationReliability record."""
    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="hue",
            timestamp=now,
            event_type="heal_success",
            entity_id="light.living_room",
            details={"reason": "scheduled_check"},
        )
        session.add(event)
        await session.commit()

        # Verify it was saved
        assert event.id is not None
        assert event.integration_id == "test_123"
        assert event.integration_domain == "hue"
        assert event.event_type == "heal_success"
        assert event.entity_id == "light.living_room"
        assert event.details == {"reason": "scheduled_check"}
        assert event.created_at is not None


@pytest.mark.asyncio
async def test_integration_reliability_event_types(test_database):
    """Test all three event types for IntegrationReliability."""
    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        # Test heal_success
        success_event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="zwave",
            timestamp=now,
            event_type="heal_success",
        )
        session.add(success_event)

        # Test heal_failure
        failure_event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="zwave",
            timestamp=now,
            event_type="heal_failure",
        )
        session.add(failure_event)

        # Test unavailable
        unavailable_event = IntegrationReliability(
            integration_id="test_123",
            integration_domain="zwave",
            timestamp=now,
            event_type="unavailable",
        )
        session.add(unavailable_event)

        await session.commit()

        # Verify all saved
        assert success_event.id is not None
        assert failure_event.id is not None
        assert unavailable_event.id is not None


@pytest.mark.asyncio
async def test_integration_reliability_query_by_domain(test_database):
    """Test querying IntegrationReliability by domain."""
    from sqlalchemy import select

    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        # Add events for different domains
        hue_event = IntegrationReliability(
            integration_id="hue_123",
            integration_domain="hue",
            timestamp=now,
            event_type="heal_success",
        )
        zwave_event = IntegrationReliability(
            integration_id="zwave_456",
            integration_domain="zwave",
            timestamp=now,
            event_type="heal_failure",
        )
        session.add_all([hue_event, zwave_event])
        await session.commit()

        # Query for hue events only
        result = await session.execute(
            select(IntegrationReliability).where(
                IntegrationReliability.integration_domain == "hue"
            )
        )
        events = result.scalars().all()

        assert len(events) == 1
        assert events[0].integration_domain == "hue"
        assert events[0].event_type == "heal_success"


@pytest.mark.asyncio
async def test_integration_metrics_creation(test_database):
    """Test creating IntegrationMetrics record."""
    period_start = datetime.now(UTC) - timedelta(days=7)
    period_end = datetime.now(UTC)

    async with test_database.async_session() as session:
        metrics = IntegrationMetrics(
            integration_id="test_123",
            integration_domain="hue",
            period_start=period_start,
            period_end=period_end,
            total_events=20,
            heal_successes=18,
            heal_failures=2,
            unavailable_events=5,
            success_rate=0.90,
        )
        session.add(metrics)
        await session.commit()

        # Verify
        assert metrics.id is not None
        assert metrics.total_events == 20
        assert metrics.heal_successes == 18
        assert metrics.heal_failures == 2
        assert metrics.success_rate == 0.90


@pytest.mark.asyncio
async def test_integration_metrics_success_rate_calculation(test_database):
    """Test success rate calculation in IntegrationMetrics."""
    period_start = datetime.now(UTC) - timedelta(days=1)
    period_end = datetime.now(UTC)

    async with test_database.async_session() as session:
        # 8 successes, 2 failures = 80% success rate
        metrics = IntegrationMetrics(
            integration_id="test_123",
            integration_domain="test",
            period_start=period_start,
            period_end=period_end,
            total_events=10,
            heal_successes=8,
            heal_failures=2,
            unavailable_events=0,
        )
        # Calculate success rate
        heal_attempts = metrics.heal_successes + metrics.heal_failures
        if heal_attempts > 0:
            metrics.success_rate = metrics.heal_successes / heal_attempts

        session.add(metrics)
        await session.commit()

        assert metrics.success_rate == 0.8


@pytest.mark.asyncio
async def test_integration_metrics_query_by_period(test_database):
    """Test querying IntegrationMetrics by time period."""
    from sqlalchemy import select

    now = datetime.now(UTC)
    old_period = now - timedelta(days=30)
    recent_period = now - timedelta(days=7)

    async with test_database.async_session() as session:
        # Old metrics
        old_metrics = IntegrationMetrics(
            integration_id="test_123",
            integration_domain="hue",
            period_start=old_period,
            period_end=old_period + timedelta(days=1),
            total_events=10,
            heal_successes=8,
            heal_failures=2,
            unavailable_events=0,
            success_rate=0.8,
        )
        # Recent metrics
        recent_metrics = IntegrationMetrics(
            integration_id="test_123",
            integration_domain="hue",
            period_start=recent_period,
            period_end=recent_period + timedelta(days=1),
            total_events=15,
            heal_successes=14,
            heal_failures=1,
            unavailable_events=2,
            success_rate=0.93,
        )
        session.add_all([old_metrics, recent_metrics])
        await session.commit()

        # Query for metrics in last 14 days
        cutoff = now - timedelta(days=14)
        result = await session.execute(
            select(IntegrationMetrics).where(
                IntegrationMetrics.period_start >= cutoff
            )
        )
        metrics = result.scalars().all()

        assert len(metrics) == 1
        assert metrics[0].success_rate == 0.93


@pytest.mark.asyncio
async def test_pattern_insight_creation(test_database):
    """Test creating PatternInsight record."""
    period_start = datetime.now(UTC) - timedelta(days=1)

    async with test_database.async_session() as session:
        insight = PatternInsight(
            insight_type="top_failures",
            period="daily",
            period_start=period_start,
            data={
                "top_failures": [
                    {"integration": "met", "failures": 10},
                    {"integration": "zwave", "failures": 5},
                ],
                "total_failures": 15,
            },
        )
        session.add(insight)
        await session.commit()

        # Verify
        assert insight.id is not None
        assert insight.insight_type == "top_failures"
        assert insight.period == "daily"
        assert "top_failures" in insight.data
        assert len(insight.data["top_failures"]) == 2


@pytest.mark.asyncio
async def test_pattern_insight_json_serialization(test_database):
    """Test that PatternInsight correctly handles complex JSON data."""
    period_start = datetime.now(UTC)

    async with test_database.async_session() as session:
        complex_data = {
            "analysis": "time_of_day_patterns",
            "patterns": [
                {"hour": 3, "failures": 12, "reason": "scheduled_updates"},
                {"hour": 14, "failures": 5, "reason": "peak_usage"},
            ],
            "metadata": {
                "confidence": 0.85,
                "sample_size": 100,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        }

        insight = PatternInsight(
            insight_type="time_of_day",
            period="weekly",
            period_start=period_start,
            data=complex_data,
        )
        session.add(insight)
        await session.commit()

        # Verify JSON roundtrip
        assert insight.data["analysis"] == "time_of_day_patterns"
        assert len(insight.data["patterns"]) == 2
        assert insight.data["metadata"]["confidence"] == 0.85


@pytest.mark.asyncio
async def test_pattern_insight_query_by_type(test_database):
    """Test querying PatternInsight by insight_type."""
    from sqlalchemy import select

    period_start = datetime.now(UTC)

    async with test_database.async_session() as session:
        # Create different insight types
        failure_insight = PatternInsight(
            insight_type="top_failures",
            period="daily",
            period_start=period_start,
            data={"failures": []},
        )
        time_insight = PatternInsight(
            insight_type="time_of_day",
            period="daily",
            period_start=period_start,
            data={"patterns": []},
        )
        session.add_all([failure_insight, time_insight])
        await session.commit()

        # Query for specific type
        result = await session.execute(
            select(PatternInsight).where(
                PatternInsight.insight_type == "top_failures"
            )
        )
        insights = result.scalars().all()

        assert len(insights) == 1
        assert insights[0].insight_type == "top_failures"


@pytest.mark.asyncio
async def test_all_pattern_models_created(test_database):
    """Test that all pattern collection tables are created."""
    from sqlalchemy import inspect

    # Get inspector and table names within connection context
    async with test_database.engine.connect() as conn:
        def get_tables(sync_conn):
            inspector = inspect(sync_conn)
            return inspector.get_table_names()

        tables = await conn.run_sync(get_tables)

    # Verify all three tables exist
    assert "integration_reliability" in tables
    assert "integration_metrics" in tables
    assert "pattern_insights" in tables


@pytest.mark.asyncio
async def test_integration_reliability_indexes(test_database):
    """Test that IntegrationReliability has proper indexes."""
    from sqlalchemy import inspect

    async with test_database.engine.connect() as conn:
        def get_indexes(sync_conn):
            inspector = inspect(sync_conn)
            return inspector.get_indexes("integration_reliability")

        indexes = await conn.run_sync(get_indexes)

    index_columns = [idx["column_names"][0] for idx in indexes if len(idx["column_names"]) == 1]

    # Verify key indexes exist
    assert "integration_id" in index_columns
    assert "integration_domain" in index_columns
    assert "timestamp" in index_columns
    assert "event_type" in index_columns
