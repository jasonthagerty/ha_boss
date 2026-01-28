"""Tests for database management."""

from datetime import UTC, datetime, timedelta

import pytest

from ha_boss.core.database import (
    AutomationDesiredState,
    AutomationOutcomePattern,
    AutomationOutcomeValidation,
    Entity,
    HealingAction,
    HealthEvent,
    Integration,
    init_database,
)


@pytest.mark.asyncio
async def test_init_database(tmp_path):
    """Test database initialization."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    assert db.db_path == db_path
    assert db_path.exists()

    await db.close()


@pytest.mark.asyncio
async def test_create_entity(tmp_path):
    """Test creating and retrieving entity."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    entity_id = None
    async with db.async_session() as session:
        entity = Entity(
            instance_id="default",
            entity_id="sensor.test_temp",
            domain="sensor",
            friendly_name="Test Temperature",
            last_seen=datetime.now(UTC),
            last_state="22.5",
            is_monitored=True,
        )
        session.add(entity)
        await session.commit()
        entity_id = entity.id

    # Retrieve entity by primary key (autoincrement id)
    async with db.async_session() as session:
        result = await session.get(Entity, entity_id)
        assert result is not None
        assert result.instance_id == "default"
        assert result.entity_id == "sensor.test_temp"
        assert result.domain == "sensor"
        assert result.last_state == "22.5"

    await db.close()


@pytest.mark.asyncio
async def test_create_health_event(tmp_path):
    """Test creating health event."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    async with db.async_session() as session:
        event = HealthEvent(
            entity_id="sensor.test",
            event_type="unavailable",
            details={"reason": "connection_timeout"},
        )
        session.add(event)
        await session.commit()

        # Verify event was created
        assert event.id is not None
        assert event.event_type == "unavailable"

    await db.close()


@pytest.mark.asyncio
async def test_create_healing_action(tmp_path):
    """Test creating healing action."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    async with db.async_session() as session:
        action = HealingAction(
            entity_id="sensor.test",
            integration_id="integration_123",
            action="reload_integration",
            attempt_number=1,
            success=True,
            duration_seconds=2.5,
        )
        session.add(action)
        await session.commit()

        assert action.id is not None
        assert action.success is True

    await db.close()


@pytest.mark.asyncio
async def test_create_integration(tmp_path):
    """Test creating integration."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    integration_id = None
    async with db.async_session() as session:
        integration = Integration(
            instance_id="default",
            entry_id="abc123",
            domain="mqtt",
            title="MQTT Broker",
            source="user",
            disabled=False,
            consecutive_failures=0,
        )
        session.add(integration)
        await session.commit()
        integration_id = integration.id

    # Retrieve integration by primary key (autoincrement id)
    async with db.async_session() as session:
        result = await session.get(Integration, integration_id)
        assert result is not None
        assert result.instance_id == "default"
        assert result.entry_id == "abc123"
        assert result.domain == "mqtt"

    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_records(tmp_path):
    """Test cleanup of old records."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    # Create old and recent records
    old_timestamp = datetime.now(UTC) - timedelta(days=60)
    recent_timestamp = datetime.now(UTC) - timedelta(days=5)

    async with db.async_session() as session:
        # Old health event
        old_event = HealthEvent(
            entity_id="sensor.test",
            event_type="unavailable",
            timestamp=old_timestamp,
        )
        # Recent health event
        recent_event = HealthEvent(
            entity_id="sensor.test2",
            event_type="unavailable",
            timestamp=recent_timestamp,
        )
        session.add_all([old_event, recent_event])
        await session.commit()

    # Clean up records older than 30 days
    deleted = await db.cleanup_old_records(retention_days=30)

    assert deleted["health_events"] == 1

    # Verify only recent record remains
    async with db.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(HealthEvent))
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].entity_id == "sensor.test2"

    await db.close()


# Tests for Outcome Validation Models (Schema v7)


@pytest.mark.asyncio
async def test_create_automation_desired_state(tmp_path):
    """Test creating automation desired state."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    state_id = None
    async with db.async_session() as session:
        desired_state = AutomationDesiredState(
            instance_id="default",
            automation_id="automation.watch_apple_tv",
            entity_id="media_player.apple_tv",
            desired_state="playing",
            desired_attributes={"source": "Apple TV", "volume": 0.5},
            confidence=0.95,
            inference_method="ai_analysis",
        )
        session.add(desired_state)
        await session.commit()
        state_id = desired_state.id

    # Retrieve desired state
    async with db.async_session() as session:
        result = await session.get(AutomationDesiredState, state_id)
        assert result is not None
        assert result.instance_id == "default"
        assert result.automation_id == "automation.watch_apple_tv"
        assert result.entity_id == "media_player.apple_tv"
        assert result.desired_state == "playing"
        assert result.desired_attributes == {"source": "Apple TV", "volume": 0.5}
        assert result.confidence == 0.95
        assert result.inference_method == "ai_analysis"

    await db.close()


@pytest.mark.asyncio
async def test_create_automation_outcome_validation(tmp_path):
    """Test creating automation outcome validation."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    validation_id = None
    async with db.async_session() as session:
        validation = AutomationOutcomeValidation(
            instance_id="default",
            execution_id=123,
            entity_id="media_player.apple_tv",
            desired_state="playing",
            desired_attributes={"source": "Apple TV"},
            actual_state="off",
            actual_attributes=None,
            achieved=False,
            time_to_achievement_ms=None,
            user_description="TV didn't turn on",
        )
        session.add(validation)
        await session.commit()
        validation_id = validation.id

    # Retrieve validation
    async with db.async_session() as session:
        result = await session.get(AutomationOutcomeValidation, validation_id)
        assert result is not None
        assert result.instance_id == "default"
        assert result.execution_id == 123
        assert result.entity_id == "media_player.apple_tv"
        assert result.desired_state == "playing"
        assert result.actual_state == "off"
        assert result.achieved is False
        assert result.user_description == "TV didn't turn on"

    await db.close()


@pytest.mark.asyncio
async def test_create_automation_outcome_pattern(tmp_path):
    """Test creating automation outcome pattern."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    pattern_id = None
    async with db.async_session() as session:
        pattern = AutomationOutcomePattern(
            instance_id="default",
            automation_id="automation.watch_apple_tv",
            entity_id="light.living_room",
            observed_state="on",
            observed_attributes={"brightness": 20},
            occurrence_count=5,
        )
        session.add(pattern)
        await session.commit()
        pattern_id = pattern.id

    # Retrieve pattern
    async with db.async_session() as session:
        result = await session.get(AutomationOutcomePattern, pattern_id)
        assert result is not None
        assert result.instance_id == "default"
        assert result.automation_id == "automation.watch_apple_tv"
        assert result.entity_id == "light.living_room"
        assert result.observed_state == "on"
        assert result.observed_attributes == {"brightness": 20}
        assert result.occurrence_count == 5

    await db.close()


@pytest.mark.asyncio
async def test_automation_desired_state_unique_constraint(tmp_path):
    """Test unique constraint on automation_desired_states."""
    db_path = tmp_path / "test.db"
    db = await init_database(db_path)

    async with db.async_session() as session:
        # Create first desired state
        state1 = AutomationDesiredState(
            instance_id="default",
            automation_id="automation.test",
            entity_id="light.test",
            desired_state="on",
            confidence=0.9,
            inference_method="ai_analysis",
        )
        session.add(state1)
        await session.commit()

    # Try to create duplicate (should fail due to unique constraint)
    async with db.async_session() as session:
        state2 = AutomationDesiredState(
            instance_id="default",
            automation_id="automation.test",
            entity_id="light.test",
            desired_state="off",
            confidence=0.8,
            inference_method="user_annotated",
        )
        session.add(state2)

        # Expect IntegrityError due to unique constraint
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await session.commit()

    await db.close()
