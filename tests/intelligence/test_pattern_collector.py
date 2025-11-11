"""Tests for PatternCollector service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from ha_boss.core.config import Config, HomeAssistantConfig, IntelligenceConfig
from ha_boss.core.database import IntegrationReliability, init_database
from ha_boss.intelligence.pattern_collector import PatternCollector


@pytest.fixture
def mock_config():
    """Create mock configuration with pattern collection enabled."""
    config = Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
    )
    return config


@pytest.fixture
def mock_config_disabled():
    """Create mock configuration with pattern collection disabled."""
    config = Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        intelligence=IntelligenceConfig(pattern_collection_enabled=False),
    )
    return config


@pytest.fixture
async def test_database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_patterns.db"
    db = await init_database(db_path)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def pattern_collector(mock_config, test_database):
    """Create PatternCollector instance."""
    return PatternCollector(mock_config, test_database)


@pytest.fixture
def pattern_collector_disabled(mock_config_disabled, test_database):
    """Create PatternCollector instance with collection disabled."""
    return PatternCollector(mock_config_disabled, test_database)


@pytest.mark.asyncio
async def test_record_healing_success(pattern_collector, test_database):
    """Test recording a successful healing attempt."""
    await pattern_collector.record_healing_attempt(
        integration_id="test_123",
        integration_domain="hue",
        entity_id="light.living_room",
        success=True,
        details={"reason": "entity_unavailable", "attempt": 1},
    )

    # Verify recorded in database
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.integration_id == "test_123"
        assert event.integration_domain == "hue"
        assert event.entity_id == "light.living_room"
        assert event.event_type == "heal_success"
        assert event.details["reason"] == "entity_unavailable"

    # Verify event count incremented
    assert pattern_collector.get_event_count() == 1


@pytest.mark.asyncio
async def test_record_healing_failure(pattern_collector, test_database):
    """Test recording a failed healing attempt."""
    await pattern_collector.record_healing_attempt(
        integration_id="test_456",
        integration_domain="zwave_js",
        entity_id="sensor.temperature",
        success=False,
        details={"error": "Integration reload failed", "attempt": 3},
    )

    # Verify recorded in database
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.integration_id == "test_456"
        assert event.integration_domain == "zwave_js"
        assert event.entity_id == "sensor.temperature"
        assert event.event_type == "heal_failure"
        assert event.details["error"] == "Integration reload failed"

    assert pattern_collector.get_event_count() == 1


@pytest.mark.asyncio
async def test_record_entity_unavailable(pattern_collector, test_database):
    """Test recording an entity unavailable event."""
    await pattern_collector.record_entity_unavailable(
        integration_id="test_789",
        integration_domain="met",
        entity_id="weather.home",
        details={"state": "unavailable", "last_seen": "2024-01-01T00:00:00Z"},
    )

    # Verify recorded in database
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.integration_id == "test_789"
        assert event.integration_domain == "met"
        assert event.entity_id == "weather.home"
        assert event.event_type == "unavailable"

    assert pattern_collector.get_event_count() == 1


@pytest.mark.asyncio
async def test_record_entity_unavailable_missing_integration_info(pattern_collector, test_database):
    """Test recording unavailable event when integration info is missing."""
    await pattern_collector.record_entity_unavailable(
        integration_id=None,
        integration_domain=None,
        entity_id="sensor.unknown",
        details={"state": "unavailable"},
    )

    # Verify fallback to entity domain
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.integration_id == "domain_sensor"
        assert event.integration_domain == "sensor"
        assert event.entity_id == "sensor.unknown"
        assert event.event_type == "unavailable"


@pytest.mark.asyncio
async def test_pattern_collection_disabled(pattern_collector_disabled, test_database):
    """Test that collection is skipped when disabled."""
    await pattern_collector_disabled.record_healing_attempt(
        integration_id="test_123",
        integration_domain="hue",
        entity_id="light.living_room",
        success=True,
    )

    await pattern_collector_disabled.record_entity_unavailable(
        integration_id="test_456",
        integration_domain="zwave",
        entity_id="sensor.temp",
    )

    # Verify nothing recorded
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()
        assert len(events) == 0

    # Event count should not increment
    assert pattern_collector_disabled.get_event_count() == 0


@pytest.mark.asyncio
async def test_graceful_error_handling_healing(pattern_collector):
    """Test that database errors don't crash during healing attempt recording."""
    # Mock database session to raise an exception
    with patch.object(
        pattern_collector.database, "async_session", side_effect=Exception("Database error")
    ):
        # Should not raise, just log
        await pattern_collector.record_healing_attempt(
            integration_id="test_123",
            integration_domain="hue",
            entity_id="light.test",
            success=True,
        )

    # Event count should not increment on error
    assert pattern_collector.get_event_count() == 0


@pytest.mark.asyncio
async def test_graceful_error_handling_unavailable(pattern_collector):
    """Test that database errors don't crash during unavailable event recording."""
    # Mock database session to raise an exception
    with patch.object(
        pattern_collector.database, "async_session", side_effect=Exception("Database error")
    ):
        # Should not raise, just log
        await pattern_collector.record_entity_unavailable(
            integration_id="test_456",
            integration_domain="zwave",
            entity_id="sensor.test",
        )

    # Event count should not increment on error
    assert pattern_collector.get_event_count() == 0


@pytest.mark.asyncio
async def test_record_multiple_events(pattern_collector, test_database):
    """Test recording multiple events of different types."""
    # Record success
    await pattern_collector.record_healing_attempt(
        integration_id="test_1",
        integration_domain="hue",
        entity_id="light.room1",
        success=True,
    )

    # Record failure
    await pattern_collector.record_healing_attempt(
        integration_id="test_1",
        integration_domain="hue",
        entity_id="light.room2",
        success=False,
    )

    # Record unavailable
    await pattern_collector.record_entity_unavailable(
        integration_id="test_1",
        integration_domain="hue",
        entity_id="light.room3",
    )

    # Verify all recorded
    async with test_database.async_session() as session:
        result = await session.execute(
            select(IntegrationReliability).order_by(IntegrationReliability.id)
        )
        events = result.scalars().all()

        assert len(events) == 3
        assert events[0].event_type == "heal_success"
        assert events[1].event_type == "heal_failure"
        assert events[2].event_type == "unavailable"

    assert pattern_collector.get_event_count() == 3


@pytest.mark.asyncio
async def test_timestamps_recorded(pattern_collector, test_database):
    """Test that timestamps are properly recorded."""
    before = datetime.now(UTC)

    await pattern_collector.record_healing_attempt(
        integration_id="test_123",
        integration_domain="hue",
        entity_id="light.test",
        success=True,
    )

    after = datetime.now(UTC)

    # Verify timestamp is between before and after
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        event = result.scalars().first()

        # SQLite stores timestamps as naive, so make comparison timezone-naive
        assert event.timestamp >= before.replace(tzinfo=None)
        assert event.timestamp <= after.replace(tzinfo=None)
        assert event.created_at >= before.replace(tzinfo=None)
        assert event.created_at <= after.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_optional_details(pattern_collector, test_database):
    """Test recording events without optional details."""
    await pattern_collector.record_healing_attempt(
        integration_id="test_123",
        integration_domain="hue",
        entity_id="light.test",
        success=True,
        details=None,
    )

    # Verify recorded with None details
    async with test_database.async_session() as session:
        result = await session.execute(select(IntegrationReliability))
        event = result.scalars().first()

        assert event.details is None
