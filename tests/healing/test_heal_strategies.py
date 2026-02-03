"""Tests for healing strategies and auto-healing manager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from ha_boss.core.config import Config, HealingConfig, HomeAssistantConfig
from ha_boss.core.database import HealingAction, Integration, init_database
from ha_boss.core.exceptions import (
    CircuitBreakerOpenError,
    HealingFailedError,
    IntegrationNotFoundError,
)
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.heal_strategies import HealingManager, create_healing_manager
from ha_boss.healing.integration_manager import IntegrationDiscovery
from ha_boss.core.types import HealthIssue


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        healing=HealingConfig(
            enabled=True,
            max_attempts=3,
            cooldown_seconds=60,
            circuit_breaker_threshold=5,
            circuit_breaker_reset_seconds=300,
        ),
        mode="production",
    )


@pytest.fixture
def dry_run_config():
    """Create dry-run mode configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        healing=HealingConfig(
            enabled=True,
            max_attempts=3,
            cooldown_seconds=60,
            circuit_breaker_threshold=5,
            circuit_breaker_reset_seconds=300,
        ),
        mode="dry_run",
    )


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db = await init_database(tmp_path / "test.db")
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    client = AsyncMock(spec=HomeAssistantClient)
    client.instance_id = "default"
    client.reload_integration = AsyncMock()
    return client


@pytest.fixture
def mock_integration_discovery():
    """Create mock integration discovery."""
    discovery = AsyncMock(spec=IntegrationDiscovery)
    discovery.get_integration_for_entity = lambda entity_id: "test_integration_123"
    discovery.get_integration_details = lambda entry_id: {
        "entry_id": entry_id,
        "domain": "test_domain",
        "title": "Test Integration",
        "source": "test",
    }
    return discovery


@pytest.fixture
def healing_manager(mock_config, database, mock_ha_client, mock_integration_discovery):
    """Create HealingManager instance."""
    return HealingManager(
        mock_config,
        database,
        mock_ha_client,
        mock_integration_discovery,
    )


@pytest.fixture
def sample_health_issue():
    """Create sample health issue."""
    return HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
        details={"state": "unavailable"},
    )


@pytest.mark.asyncio
async def test_healing_manager_creation(
    mock_config, database, mock_ha_client, mock_integration_discovery
):
    """Test creating healing manager via factory function."""
    manager = await create_healing_manager(
        mock_config, database, mock_ha_client, mock_integration_discovery
    )
    assert manager is not None
    assert isinstance(manager, HealingManager)


@pytest.mark.asyncio
async def test_successful_healing(healing_manager, sample_health_issue, mock_ha_client):
    """Test successful healing attempt."""
    # Perform healing
    result = await healing_manager.heal(sample_health_issue)

    # Verify success
    assert result is True

    # Verify HA client was called
    mock_ha_client.reload_integration.assert_called_once_with("test_integration_123")

    # Verify database record
    async with healing_manager.database.async_session() as session:
        result_db = await session.execute(select(HealingAction))
        actions = result_db.scalars().all()
        assert len(actions) == 1
        assert actions[0].entity_id == "sensor.test_sensor"
        assert actions[0].integration_id == "test_integration_123"
        assert actions[0].success is True
        assert actions[0].attempt_number == 1


@pytest.mark.asyncio
async def test_failed_healing(healing_manager, sample_health_issue, mock_ha_client):
    """Test failed healing attempt."""
    # Make reload_integration raise exception
    mock_ha_client.reload_integration.side_effect = Exception("Reload failed")

    # Attempt healing
    with pytest.raises(HealingFailedError):
        await healing_manager.heal(sample_health_issue)

    # Verify database record
    async with healing_manager.database.async_session() as session:
        result_db = await session.execute(select(HealingAction))
        actions = result_db.scalars().all()
        assert len(actions) == 1
        assert actions[0].success is False
        assert actions[0].error == "Reload failed"


@pytest.mark.asyncio
async def test_integration_not_found(healing_manager, sample_health_issue):
    """Test healing when integration cannot be found."""
    # Configure discovery to return None
    healing_manager.integration_discovery.get_integration_for_entity = lambda _: None

    # Attempt healing
    with pytest.raises(IntegrationNotFoundError) as exc_info:
        await healing_manager.heal(sample_health_issue)

    assert "Cannot find integration" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cooldown_enforcement(healing_manager, sample_health_issue, mock_ha_client):
    """Test cooldown prevents rapid retries."""
    # First attempt - should succeed
    await healing_manager.heal(sample_health_issue)

    # Immediate second attempt - should fail due to cooldown
    with pytest.raises(HealingFailedError) as exc_info:
        await healing_manager.heal(sample_health_issue)

    assert "Cooldown active" in str(exc_info.value)

    # Verify only one reload was attempted
    assert mock_ha_client.reload_integration.call_count == 1


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold(
    healing_manager, sample_health_issue, database, mock_ha_client
):
    """Test circuit breaker opens after threshold failures."""
    # Make all attempts fail
    mock_ha_client.reload_integration.side_effect = Exception("Always fails")

    # Create integration in database
    async with database.async_session() as session:
        integration = Integration(
            entry_id="test_integration_123",
            domain="test_domain",
            title="Test Integration",
            is_discovered=True,
        )
        session.add(integration)
        await session.commit()

    # Attempt healing multiple times (should fail each time)
    for _ in range(healing_manager.config.healing.circuit_breaker_threshold):
        # Reset cooldown to allow retries
        healing_manager._last_attempt.clear()

        with pytest.raises(HealingFailedError):
            await healing_manager.heal(sample_health_issue)

    # Verify circuit breaker is now open
    async with database.async_session() as session:
        result = await session.execute(
            select(Integration).where(Integration.entry_id == "test_integration_123")
        )
        integration = result.scalar_one()
        assert integration.circuit_breaker_open_until is not None
        # SQLite doesn't preserve timezone, so add UTC if naive
        cb_until = integration.circuit_breaker_open_until
        if cb_until.tzinfo is None:
            cb_until = cb_until.replace(tzinfo=UTC)
        assert cb_until > datetime.now(UTC)
        assert (
            integration.consecutive_failures
            >= healing_manager.config.healing.circuit_breaker_threshold
        )

    # Next attempt should fail immediately with CircuitBreakerOpenError
    healing_manager._last_attempt.clear()
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await healing_manager.heal(sample_health_issue)

    assert "Circuit breaker is open" in str(exc_info.value)


@pytest.mark.asyncio
async def test_circuit_breaker_resets_after_timeout(healing_manager, sample_health_issue, database):
    """Test circuit breaker resets after timeout expires."""
    # Create integration with expired circuit breaker
    past_time = datetime.now(UTC) - timedelta(seconds=10)
    async with database.async_session() as session:
        integration = Integration(
            entry_id="test_integration_123",
            domain="test_domain",
            title="Test Integration",
            is_discovered=True,
            consecutive_failures=10,
            circuit_breaker_open_until=past_time,  # Already expired
        )
        session.add(integration)
        await session.commit()

    # Attempt healing - should succeed (circuit breaker reset)
    result = await healing_manager.heal(sample_health_issue)
    assert result is True

    # Verify circuit breaker was reset
    async with database.async_session() as session:
        result_db = await session.execute(
            select(Integration).where(Integration.entry_id == "test_integration_123")
        )
        integration = result_db.scalar_one()
        assert integration.circuit_breaker_open_until is None


@pytest.mark.asyncio
async def test_dry_run_mode(dry_run_config, database, mock_ha_client, mock_integration_discovery):
    """Test healing in dry-run mode."""
    manager = HealingManager(
        dry_run_config,
        database,
        mock_ha_client,
        mock_integration_discovery,
    )

    issue = HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
    )

    # Perform healing in dry-run mode
    result = await manager.heal(issue)

    # Should succeed
    assert result is True

    # Verify HA client was NOT called
    mock_ha_client.reload_integration.assert_not_called()

    # Verify database record was still created
    async with database.async_session() as session:
        result_db = await session.execute(select(HealingAction))
        actions = result_db.scalars().all()
        assert len(actions) == 1
        assert actions[0].success is True


@pytest.mark.asyncio
async def test_attempt_number_increments(healing_manager, sample_health_issue, mock_ha_client):
    """Test attempt number increments for multiple attempts."""
    # First attempt
    await healing_manager.heal(sample_health_issue)

    # Reset cooldown
    healing_manager._last_attempt.clear()

    # Second attempt
    await healing_manager.heal(sample_health_issue)

    # Verify attempt numbers in database
    async with healing_manager.database.async_session() as session:
        result = await session.execute(select(HealingAction).order_by(HealingAction.timestamp))
        actions = result.scalars().all()
        assert len(actions) == 2
        assert actions[0].attempt_number == 1
        assert actions[1].attempt_number == 2


@pytest.mark.asyncio
async def test_success_resets_failure_count(
    healing_manager, sample_health_issue, database, mock_ha_client
):
    """Test successful healing resets failure count."""
    # Create integration with failures
    async with database.async_session() as session:
        integration = Integration(
            entry_id="test_integration_123",
            domain="test_domain",
            title="Test Integration",
            is_discovered=True,
            consecutive_failures=3,
        )
        session.add(integration)
        await session.commit()

    # Successful healing
    await healing_manager.heal(sample_health_issue)

    # Verify failure count was reset
    async with database.async_session() as session:
        result = await session.execute(
            select(Integration).where(Integration.entry_id == "test_integration_123")
        )
        integration = result.scalar_one()
        assert integration.consecutive_failures == 0
        assert integration.last_successful_reload is not None


@pytest.mark.asyncio
async def test_can_heal_checks(healing_manager, database):
    """Test can_heal method."""
    # Entity with no integration - cannot heal
    healing_manager.integration_discovery.get_integration_for_entity = lambda _: None
    can_heal, reason = await healing_manager.can_heal("sensor.unknown")
    assert can_heal is False
    assert "not found" in reason.lower()

    # Entity with integration - can heal
    healing_manager.integration_discovery.get_integration_for_entity = (
        lambda _: "test_integration_123"
    )
    can_heal, reason = await healing_manager.can_heal("sensor.test_sensor")
    assert can_heal is True
    assert "Can heal" in reason

    # Entity with cooldown - cannot heal
    healing_manager._last_attempt["test_integration_123"] = datetime.now(UTC)
    can_heal, reason = await healing_manager.can_heal("sensor.test_sensor")
    assert can_heal is False
    assert "Cooldown" in reason

    # Entity with open circuit breaker - cannot heal
    healing_manager._last_attempt.clear()
    future_time = datetime.now(UTC) + timedelta(seconds=300)
    async with database.async_session() as session:
        integration = Integration(
            entry_id="test_integration_123",
            domain="test_domain",
            title="Test Integration",
            is_discovered=True,
            circuit_breaker_open_until=future_time,
        )
        session.add(integration)
        await session.commit()

    can_heal, reason = await healing_manager.can_heal("sensor.test_sensor")
    assert can_heal is False
    assert "Circuit breaker is open" in reason


@pytest.mark.asyncio
async def test_get_healing_stats(healing_manager, sample_health_issue, mock_ha_client):
    """Test getting healing statistics."""
    # Initially no stats
    stats = await healing_manager.get_healing_stats()
    assert stats["total_attempts"] == 0

    # Perform successful healing
    await healing_manager.heal(sample_health_issue)

    # Check stats
    stats = await healing_manager.get_healing_stats()
    assert stats["total_attempts"] == 1
    assert stats["successful"] == 1
    assert stats["failed"] == 0
    assert stats["success_rate"] == 100.0

    # Perform failed healing
    healing_manager._last_attempt.clear()
    mock_ha_client.reload_integration.side_effect = Exception("Failed")
    with pytest.raises(HealingFailedError):
        await healing_manager.heal(sample_health_issue)

    # Check updated stats
    stats = await healing_manager.get_healing_stats()
    assert stats["total_attempts"] == 2
    assert stats["successful"] == 1
    assert stats["failed"] == 1
    assert stats["success_rate"] == 50.0

    # Check entity-specific stats
    stats = await healing_manager.get_healing_stats(entity_id="sensor.test_sensor")
    assert stats["total_attempts"] == 2

    stats = await healing_manager.get_healing_stats(entity_id="sensor.other")
    assert stats["total_attempts"] == 0


@pytest.mark.asyncio
async def test_healing_duration_recorded(healing_manager, sample_health_issue):
    """Test that healing duration is recorded."""
    await healing_manager.heal(sample_health_issue)

    async with healing_manager.database.async_session() as session:
        result = await session.execute(select(HealingAction))
        action = result.scalar_one()
        assert action.duration_seconds is not None
        assert action.duration_seconds >= 0
