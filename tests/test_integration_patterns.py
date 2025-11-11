"""Integration tests for pattern collection during service operation."""


import pytest

from ha_boss.core.config import Config, DatabaseConfig, HomeAssistantConfig, IntelligenceConfig
from ha_boss.core.database import Database, IntegrationReliability
from ha_boss.intelligence.pattern_collector import PatternCollector


@pytest.fixture
async def test_database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_patterns.db"
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def test_config():
    """Create test configuration with pattern collection enabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://test:8123",
            token="test_token",
        ),
        database=DatabaseConfig(
            path=":memory:",
            retention_days=30,
        ),
        intelligence=IntelligenceConfig(
            pattern_collection_enabled=True,
        ),
        mode="testing",
    )


@pytest.fixture
def test_config_disabled():
    """Create test configuration with pattern collection disabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://test:8123",
            token="test_token",
        ),
        database=DatabaseConfig(
            path=":memory:",
            retention_days=30,
        ),
        intelligence=IntelligenceConfig(
            pattern_collection_enabled=False,
        ),
        mode="testing",
    )


@pytest.mark.asyncio
async def test_pattern_collector_initialized_when_enabled(test_config, test_database):
    """Test that PatternCollector is initialized when enabled in config."""
    # Create pattern collector directly
    pattern_collector = PatternCollector(config=test_config, database=test_database)

    # Pattern collector should be initialized
    assert pattern_collector is not None
    assert isinstance(pattern_collector, PatternCollector)


@pytest.mark.asyncio
async def test_pattern_collector_not_initialized_when_disabled(test_config_disabled, test_database):
    """Test that PatternCollector respects disabled config."""
    pattern_collector = PatternCollector(config=test_config_disabled, database=test_database)

    # Try to record an event - should be no-op when disabled
    initial_count = pattern_collector.get_event_count()

    await pattern_collector.record_entity_unavailable(
        integration_id="test",
        integration_domain="test",
        entity_id="sensor.test",
    )

    # Event count should not increase when disabled
    assert pattern_collector.get_event_count() == initial_count


@pytest.mark.asyncio
async def test_unavailable_event_recorded(test_database):
    """Test that unavailable events are recorded in database."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Record unavailable event
    await pattern_collector.record_entity_unavailable(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test",
        details={"reason": "timeout"},
    )

    # Verify record was created
    async with test_database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.entity_id == "sensor.test"
        assert event.integration_id == "test_integration"
        assert event.integration_domain == "test"
        assert event.event_type == "unavailable"


@pytest.mark.asyncio
async def test_healing_success_recorded(test_database):
    """Test that successful healing attempts are recorded."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Record successful healing
    await pattern_collector.record_healing_attempt(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test",
        success=True,
        details={"issue_type": "unavailable"},
    )

    # Verify record was created
    async with test_database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.entity_id == "sensor.test"
        assert event.integration_domain == "test"
        assert event.event_type == "heal_success"


@pytest.mark.asyncio
async def test_healing_failure_recorded(test_database):
    """Test that failed healing attempts are recorded."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Record failed healing
    await pattern_collector.record_healing_attempt(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test",
        success=False,
        details={"issue_type": "unavailable", "max_attempts": 3},
    )

    # Verify record was created
    async with test_database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.entity_id == "sensor.test"
        assert event.integration_domain == "test"
        assert event.event_type == "heal_failure"


@pytest.mark.asyncio
async def test_pattern_collection_without_integration_info(test_database):
    """Test that pattern collection works when integration info is unavailable."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Record event without integration info
    await pattern_collector.record_entity_unavailable(
        integration_id=None,
        integration_domain=None,
        entity_id="sensor.unknown",
    )

    # Verify record was created
    async with test_database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.entity_id == "sensor.unknown"
        # PatternCollector fills in defaults when integration info is missing
        assert event.integration_id == "domain_sensor"
        assert event.integration_domain == "sensor"
        assert event.event_type == "unavailable"


@pytest.mark.asyncio
async def test_multiple_events_recorded(test_database):
    """Test that multiple pattern events are recorded correctly."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Record multiple events
    await pattern_collector.record_entity_unavailable(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test1",
    )

    await pattern_collector.record_healing_attempt(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test1",
        success=True,
    )

    await pattern_collector.record_entity_unavailable(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test2",
    )

    await pattern_collector.record_healing_attempt(
        integration_id="test_integration",
        integration_domain="test",
        entity_id="sensor.test2",
        success=False,
    )

    # Verify all records were created
    async with test_database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(IntegrationReliability))
        events = result.scalars().all()

        assert len(events) == 4
        event_types = [event.event_type for event in events]
        assert "unavailable" in event_types
        assert "heal_success" in event_types
        assert "heal_failure" in event_types


@pytest.mark.asyncio
async def test_pattern_collection_gracefully_handles_errors(test_database):
    """Test that pattern collection gracefully handles database errors."""
    config = Config(
        home_assistant=HomeAssistantConfig(url="http://test:8123", token="test_token"),
        database=DatabaseConfig(path=str(test_database.db_path), retention_days=30),
        intelligence=IntelligenceConfig(pattern_collection_enabled=True),
        mode="testing",
    )

    pattern_collector = PatternCollector(config=config, database=test_database)

    # Close the database to simulate an error
    await test_database.close()

    # Try to record an event - should not raise exception
    try:
        await pattern_collector.record_entity_unavailable(
            integration_id="test",
            integration_domain="test",
            entity_id="sensor.test",
        )
        # If we get here, the error was handled gracefully
        assert True
    except Exception as e:
        # This should not happen - errors should be caught internally
        pytest.fail(f"PatternCollector did not handle error gracefully: {e}")
