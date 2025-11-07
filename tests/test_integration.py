"""Integration tests for HA Boss service orchestration.

These tests verify the complete service flow with minimal mocking,
ensuring all components work together correctly.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import Config
from ha_boss.service.main import HABossService, ServiceState


@pytest.fixture
def integration_config() -> Config:
    """Create a configuration for integration testing."""
    return Config(
        home_assistant={"url": "http://test-ha:8123", "token": "test_token"},
        monitoring={
            "grace_period_seconds": 5,  # Short for testing
            "stale_threshold_seconds": 60,
            "snapshot_interval_seconds": 60,  # Minimum allowed
        },
        healing={
            "enabled": True,
            "max_attempts": 2,
            "cooldown_seconds": 5,
            "circuit_breaker_threshold": 5,
            "circuit_breaker_reset_seconds": 60,
        },
        notifications={"on_healing_failure": True, "weekly_summary": False},
        database={"path": ":memory:", "retention_days": 30},
        mode="testing",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_full_startup_and_shutdown(integration_config: Config) -> None:
    """Test complete service lifecycle: startup -> running -> shutdown."""
    # Mock external dependencies
    with (
        patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
        patch("ha_boss.service.main.WebSocketClient") as mock_ws_class,
    ):
        # Set up HA client mock
        mock_client = AsyncMock()
        mock_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.test1",
                    "state": "20.5",
                    "last_updated": datetime.now(UTC).isoformat(),
                    "attributes": {"unit_of_measurement": "°C"},
                },
                {
                    "entity_id": "sensor.test2",
                    "state": "available",
                    "last_updated": datetime.now(UTC).isoformat(),
                    "attributes": {},
                },
            ]
        )
        mock_client.close = AsyncMock()
        mock_ha_client.return_value = mock_client

        # Set up WebSocket mock
        mock_ws = AsyncMock()
        mock_ws.connect = AsyncMock()
        mock_ws.subscribe_to_state_changes = AsyncMock()
        mock_ws.start = AsyncMock()
        mock_ws.stop = AsyncMock()
        mock_ws._ws = MagicMock()  # Simulate connected socket
        mock_ws_class.return_value = mock_ws

        # Create service
        service = HABossService(integration_config)

        # Mock background tasks to not run indefinitely
        with patch("asyncio.create_task", return_value=AsyncMock()):
            # Start service
            await service.start()

        # Verify service is running
        assert service.state == ServiceState.RUNNING
        assert service.database is not None
        assert service.ha_client is not None
        assert service.websocket_client is not None
        assert service.state_tracker is not None
        assert service.health_monitor is not None
        assert service.healing_manager is not None

        # Verify state tracker was initialized with entities
        assert len(service.state_tracker._cache) == 2
        assert "sensor.test1" in service.state_tracker._cache
        assert "sensor.test2" in service.state_tracker._cache

        # Get status
        status = service.get_status()
        assert status["state"] == ServiceState.RUNNING
        assert status["websocket_connected"] is True

        # Stop service
        await service.stop()

        # Verify cleanup
        assert service.state == ServiceState.STOPPED
        mock_ws.stop.assert_called_once()
        mock_client.close.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_handles_ha_unavailable(integration_config: Config) -> None:
    """Test service handles Home Assistant being unavailable."""
    with patch("ha_boss.service.main.create_ha_client") as mock_ha_client:
        # Simulate HA being unavailable
        mock_client = AsyncMock()
        mock_client.get_states = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        mock_ha_client.return_value = mock_client

        service = HABossService(integration_config)

        # Service start should fail
        with pytest.raises(Exception, match="Connection refused"):
            await service.start()

        # Verify state
        assert service.state == ServiceState.ERROR


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_state_update_flow(integration_config: Config) -> None:
    """Test the flow: WebSocket event -> State update -> Health check."""
    with (
        patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
        patch("ha_boss.service.main.WebSocketClient") as mock_ws_class,
    ):
        # Set up mocks
        mock_client = AsyncMock()
        mock_client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.test",
                    "state": "available",
                    "last_updated": datetime.now(UTC).isoformat(),
                    "attributes": {},
                }
            ]
        )
        mock_client.close = AsyncMock()
        mock_ha_client.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.connect = AsyncMock()
        mock_ws.subscribe_to_state_changes = AsyncMock()
        mock_ws.start = AsyncMock()
        mock_ws.stop = AsyncMock()
        mock_ws._ws = MagicMock()
        mock_ws_class.return_value = mock_ws

        # Create and start service
        service = HABossService(integration_config)

        with patch("asyncio.create_task", return_value=AsyncMock()):
            await service.start()

        # Simulate WebSocket state change event
        state_change_event = {
            "data": {
                "new_state": {
                    "entity_id": "sensor.test",
                    "state": "unavailable",
                    "last_updated": datetime.now(UTC).isoformat(),
                    "attributes": {},
                }
            }
        }

        # Process the event
        await service._on_websocket_state_changed(state_change_event)

        # Verify state tracker was updated
        entity_state = service.state_tracker.get_state("sensor.test")
        assert entity_state is not None
        assert entity_state.state == "unavailable"

        # Clean up
        await service.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_healing_flow(integration_config: Config) -> None:
    """Test the complete healing flow: Issue detection -> Healing -> Notification."""
    with (
        patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
        patch("ha_boss.service.main.WebSocketClient") as mock_ws_class,
    ):
        # Set up mocks
        mock_client = AsyncMock()
        mock_client.get_states = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client.call_service = AsyncMock(return_value=True)
        mock_ha_client.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.connect = AsyncMock()
        mock_ws.subscribe_to_state_changes = AsyncMock()
        mock_ws.start = AsyncMock()
        mock_ws.stop = AsyncMock()
        mock_ws._ws = MagicMock()
        mock_ws_class.return_value = mock_ws

        # Create and start service
        service = HABossService(integration_config)

        with patch("asyncio.create_task", return_value=AsyncMock()):
            await service.start()

        # Simulate a health issue
        from ha_boss.monitoring.health_monitor import HealthIssue

        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.now(UTC),
        )

        # Mock healing manager to simulate successful heal
        service.healing_manager.heal_entity = AsyncMock(return_value=True)

        # Trigger health issue callback
        await service._on_health_issue(issue)

        # Verify healing was attempted
        assert service.healings_attempted == 1
        assert service.healings_succeeded == 1
        service.healing_manager.heal_entity.assert_called_once_with("sensor.test")

        # Clean up
        await service.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_graceful_shutdown_on_signal(integration_config: Config) -> None:
    """Test service responds to shutdown signals gracefully."""
    with (
        patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
        patch("ha_boss.service.main.WebSocketClient") as mock_ws_class,
    ):
        # Set up minimal mocks
        mock_client = AsyncMock()
        mock_client.get_states = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_ha_client.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.connect = AsyncMock()
        mock_ws.subscribe_to_state_changes = AsyncMock()
        mock_ws.start = AsyncMock()
        mock_ws.stop = AsyncMock()
        mock_ws._ws = MagicMock()
        mock_ws_class.return_value = mock_ws

        service = HABossService(integration_config)

        with patch("asyncio.create_task", return_value=AsyncMock()):
            await service.start()

        assert service.state == ServiceState.RUNNING

        # Simulate shutdown
        service._shutdown_event.set()
        await service.stop()

        # Verify clean shutdown
        assert service.state == ServiceState.STOPPED
        mock_ws.stop.assert_called_once()
        mock_client.close.assert_called_once()
