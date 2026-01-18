"""Tests for automation tracking functionality."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from ha_boss.core.database import AutomationExecution, AutomationServiceCall, Database
from ha_boss.monitoring.automation_tracker import AutomationTracker


@pytest.fixture
async def tracker(tmp_path):
    """Create automation tracker with test database."""
    db_path = tmp_path / "test_tracking.db"
    database = Database(str(db_path))
    await database.init_db()

    tracker = AutomationTracker(instance_id="test_instance", database=database)
    yield tracker

    await database.close()


@pytest.mark.asyncio
async def test_tracker_initialization(tracker):
    """Test tracker initializes correctly."""
    assert tracker.instance_id == "test_instance"
    assert tracker.database is not None


@pytest.mark.asyncio
async def test_record_execution_basic(tracker):
    """Test recording basic automation execution."""
    await tracker.record_execution(
        automation_id="automation.test_automation",
        trigger_type="state",
        success=True,
    )

    # Verify record was created
    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationExecution).where(
                AutomationExecution.automation_id == "automation.test_automation"
            )
        )
        execution = result.scalar_one()

    assert execution is not None
    assert execution.instance_id == "test_instance"
    assert execution.automation_id == "automation.test_automation"
    assert execution.trigger_type == "state"
    assert execution.success is True


@pytest.mark.asyncio
async def test_record_execution_with_duration(tracker):
    """Test recording execution with duration."""
    await tracker.record_execution(
        automation_id="automation.slow_automation",
        trigger_type="time",
        duration_ms=5500,
        success=True,
    )

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationExecution.duration_ms).where(
                AutomationExecution.automation_id == "automation.slow_automation"
            )
        )
        duration = result.scalar_one()

    assert duration == 5500


@pytest.mark.asyncio
async def test_record_execution_failure(tracker):
    """Test recording failed execution."""
    await tracker.record_execution(
        automation_id="automation.failing_automation",
        trigger_type="event",
        success=False,
        error_message="Entity not available",
    )

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationExecution).where(
                AutomationExecution.automation_id == "automation.failing_automation"
            )
        )
        execution = result.scalar_one()

    assert execution is not None
    assert execution.success is False
    assert execution.error_message == "Entity not available"


@pytest.mark.asyncio
async def test_record_service_call_basic(tracker):
    """Test recording basic service call."""
    await tracker.record_service_call(
        automation_id="automation.test_automation",
        service_name="light.turn_on",
        entity_id="light.bedroom",
        success=True,
    )

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationServiceCall).where(
                AutomationServiceCall.automation_id == "automation.test_automation"
            )
        )
        service_call = result.scalar_one()

    assert service_call is not None
    assert service_call.instance_id == "test_instance"
    assert service_call.automation_id == "automation.test_automation"
    assert service_call.service_name == "light.turn_on"
    assert service_call.entity_id == "light.bedroom"


@pytest.mark.asyncio
async def test_record_service_call_with_response_time(tracker):
    """Test recording service call with response time."""
    await tracker.record_service_call(
        automation_id="automation.test_automation",
        service_name="switch.turn_off",
        response_time_ms=150,
        success=True,
    )

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationServiceCall.response_time_ms).where(
                AutomationServiceCall.service_name == "switch.turn_off"
            )
        )
        response_time = result.scalar_one()

    assert response_time == 150


@pytest.mark.asyncio
async def test_record_multiple_executions(tracker):
    """Test recording multiple executions."""
    for _ in range(5):
        await tracker.record_execution(
            automation_id="automation.frequent_automation",
            trigger_type="state",
            success=True,
        )

    async with tracker.database.async_session() as session:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(AutomationExecution.id)).where(
                AutomationExecution.automation_id == "automation.frequent_automation"
            )
        )
        count = result.scalar()

    assert count == 5


@pytest.mark.asyncio
async def test_record_multiple_service_calls(tracker):
    """Test recording multiple service calls from same automation."""
    services = ["light.turn_on", "switch.turn_off", "scene.turn_on"]

    for service in services:
        await tracker.record_service_call(
            automation_id="automation.complex_automation",
            service_name=service,
            success=True,
        )

    async with tracker.database.async_session() as session:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(AutomationServiceCall.id)).where(
                AutomationServiceCall.automation_id == "automation.complex_automation"
            )
        )
        count = result.scalar()

    assert count == 3


@pytest.mark.asyncio
async def test_record_execution_error_handling(tracker):
    """Test that tracker handles database errors gracefully."""
    # Close database to cause errors
    await tracker.database.close()

    # Should not raise exception, just log error
    await tracker.record_execution(
        automation_id="automation.test",
        success=True,
    )

    # Reinitialize for cleanup
    await tracker.database.init_db()


@pytest.mark.asyncio
async def test_record_service_call_error_handling(tracker):
    """Test that tracker handles service call errors gracefully."""
    await tracker.database.close()

    # Should not raise exception
    await tracker.record_service_call(
        automation_id="automation.test",
        service_name="test.service",
        success=True,
    )

    await tracker.database.init_db()


@pytest.mark.asyncio
async def test_multi_instance_isolation(tmp_path):
    """Test that different instances track separately."""
    db_path = tmp_path / "test_multi_instance.db"
    database = Database(str(db_path))
    await database.init_db()

    tracker1 = AutomationTracker(instance_id="instance1", database=database)
    tracker2 = AutomationTracker(instance_id="instance2", database=database)

    # Record executions for different instances
    await tracker1.record_execution("automation.test", success=True)
    await tracker2.record_execution("automation.test", success=True)

    # Verify both instances recorded separately
    async with database.async_session() as session:
        result = await session.execute(
            select(AutomationExecution.instance_id)
            .where(AutomationExecution.automation_id == "automation.test")
            .order_by(AutomationExecution.instance_id)
        )
        instance_ids = result.scalars().all()

    assert len(instance_ids) == 2
    assert instance_ids[0] == "instance1"
    assert instance_ids[1] == "instance2"

    await database.close()


@pytest.mark.asyncio
async def test_execution_timestamp_recorded(tracker):
    """Test that execution timestamp is recorded correctly."""
    before = datetime.now(UTC)
    await tracker.record_execution("automation.test", success=True)
    after = datetime.now(UTC)

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationExecution.executed_at).where(
                AutomationExecution.automation_id == "automation.test"
            )
        )
        executed_at = result.scalar_one()

    # Timestamp should be between before and after
    # Handle both naive and aware datetimes
    if executed_at.tzinfo is None:
        executed_at = executed_at.replace(tzinfo=UTC)
    assert before <= executed_at <= after


@pytest.mark.asyncio
async def test_service_call_timestamp_recorded(tracker):
    """Test that service call timestamp is recorded correctly."""
    before = datetime.now(UTC)
    await tracker.record_service_call("automation.test", "test.service", success=True)
    after = datetime.now(UTC)

    async with tracker.database.async_session() as session:
        result = await session.execute(
            select(AutomationServiceCall.called_at).where(
                AutomationServiceCall.automation_id == "automation.test"
            )
        )
        called_at = result.scalar_one()

    # Handle both naive and aware datetimes
    if called_at.tzinfo is None:
        called_at = called_at.replace(tzinfo=UTC)
    assert before <= called_at <= after
