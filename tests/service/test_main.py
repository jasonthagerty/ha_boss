"""Tests for main service orchestration."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import Config
from ha_boss.monitoring.health_monitor import HealthIssue
from ha_boss.monitoring.state_tracker import EntityState
from ha_boss.service.main import HABossService, ServiceState


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration for testing."""
    return Config(
        home_assistant={"url": "http://localhost:8123", "token": "test_token"},
        monitoring={
            "grace_period_seconds": 300,
            "stale_threshold_seconds": 3600,
            "snapshot_interval_seconds": 300,
        },
        healing={
            "enabled": True,
            "max_attempts": 3,
            "cooldown_seconds": 300,
            "circuit_breaker_threshold": 10,
            "circuit_breaker_reset_seconds": 3600,
        },
        notifications={"on_healing_failure": True, "weekly_summary": False},
        database={"path": ":memory:", "retention_days": 30},
        mode="testing",
    )


@pytest.fixture
def service(mock_config: Config) -> HABossService:
    """Create a HABossService instance for testing."""
    return HABossService(mock_config)


class TestHABossServiceInitialization:
    """Test service initialization."""

    def test_service_creation(self, service: HABossService) -> None:
        """Test that service can be created."""
        assert service.state == ServiceState.STOPPED
        assert service.database is None
        assert service.ha_client is None
        assert service.websocket_client is None

    def test_service_has_config(self, service: HABossService, mock_config: Config) -> None:
        """Test that service has configuration."""
        assert service.config == mock_config
        assert service.config.mode == "testing"

    def test_initial_statistics(self, service: HABossService) -> None:
        """Test that statistics are initialized to zero."""
        assert service.health_checks_performed == 0
        assert service.healings_attempted == 0
        assert service.healings_succeeded == 0


class TestHABossServiceStart:
    """Test service startup."""

    @pytest.mark.asyncio
    async def test_start_initializes_components(
        self, service: HABossService, mock_config: Config
    ) -> None:
        """Test that start() initializes all components."""
        # Mock all component initializations
        with (
            patch("ha_boss.service.main.Database") as mock_db_class,
            patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
            patch("ha_boss.service.main.IntegrationDiscovery") as mock_integration_discovery,
            patch("ha_boss.service.main.StateTracker") as mock_state_tracker,
            patch("ha_boss.service.main.HealthMonitor") as mock_health_monitor,
            patch("ha_boss.service.main.HealingManager") as mock_healing_manager,
            patch("ha_boss.service.main.NotificationEscalator") as mock_escalation_manager,
            patch("ha_boss.service.main.NotificationManager") as mock_notification_manager,
            patch("ha_boss.service.main.WebSocketClient") as mock_websocket_client,
        ):
            # Set up mocks
            mock_db = AsyncMock()
            mock_db.init_db = AsyncMock()
            mock_db_class.return_value = mock_db

            mock_client = AsyncMock()
            mock_client.get_states = AsyncMock(return_value=[])
            # create_ha_client is async, so return the client wrapped in a coroutine
            async def mock_create_client(config):
                return mock_client
            mock_ha_client.side_effect = mock_create_client

            mock_discovery = AsyncMock()
            mock_discovery.discover_all = AsyncMock(return_value={})
            mock_integration_discovery.return_value = mock_discovery

            mock_tracker = AsyncMock()
            mock_tracker.initialize = AsyncMock()
            mock_state_tracker.return_value = mock_tracker

            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock()
            mock_health_monitor.return_value = mock_monitor

            mock_ws = AsyncMock()
            mock_ws.connect = AsyncMock()
            mock_ws.subscribe_to_state_changes = AsyncMock()
            mock_ws.start = AsyncMock()
            mock_websocket_client.return_value = mock_ws

            # Mock background task creation
            with patch("asyncio.create_task", return_value=AsyncMock()):
                await service.start()

            # Verify state
            assert service.state == ServiceState.RUNNING
            assert service.database is not None
            assert service.ha_client is not None
            assert service.websocket_client is not None
            assert service.state_tracker is not None
            assert service.health_monitor is not None
            assert service.healing_manager is not None

            # Verify initializations were called
            mock_db.init_db.assert_called_once()
            # get_states is called twice: once to test connection, once to get initial snapshot
            assert mock_client.get_states.call_count == 2
            mock_tracker.initialize.assert_called_once()
            mock_monitor.start.assert_called_once()
            mock_ws.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handles_connection_errors(
        self, service: HABossService
    ) -> None:
        """Test that start() handles connection errors gracefully."""
        with (
            patch("ha_boss.service.main.Database") as mock_db_class,
            patch("ha_boss.service.main.create_ha_client") as mock_ha_client,
        ):
            mock_db = AsyncMock()
            mock_db.init_db = AsyncMock()
            mock_db_class.return_value = mock_db

            mock_client = AsyncMock()
            mock_client.get_states = AsyncMock(
                side_effect=Exception("Connection failed")
            )
            # create_ha_client is async
            async def mock_create_client(config):
                return mock_client
            mock_ha_client.side_effect = mock_create_client

            with pytest.raises(Exception, match="Connection failed"):
                await service.start()

            # Verify state is ERROR
            assert service.state == ServiceState.ERROR

    @pytest.mark.asyncio
    async def test_start_idempotent(self, service: HABossService) -> None:
        """Test that calling start() when already started does nothing."""
        service.state = ServiceState.RUNNING

        await service.start()

        # Should not change state
        assert service.state == ServiceState.RUNNING


class TestHABossServiceStop:
    """Test service shutdown."""

    @pytest.mark.asyncio
    async def test_stop_cleans_up_components(self, service: HABossService) -> None:
        """Test that stop() cleans up all components."""
        # Set up service as if it's running
        service.state = ServiceState.RUNNING
        service.database = AsyncMock()
        service.database.close = AsyncMock()
        service.ha_client = AsyncMock()
        service.ha_client.close = AsyncMock()
        service.health_monitor = AsyncMock()
        service.health_monitor.stop = AsyncMock()
        service.websocket_client = AsyncMock()
        service.websocket_client.stop = AsyncMock()

        await service.stop()

        # Verify cleanup
        assert service.state == ServiceState.STOPPED
        service.database.close.assert_called_once()
        service.ha_client.close.assert_called_once()
        service.health_monitor.stop.assert_called_once()
        service.websocket_client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, service: HABossService) -> None:
        """Test that stop() when not running does nothing."""
        assert service.state == ServiceState.STOPPED

        await service.stop()

        assert service.state == ServiceState.STOPPED


class TestHABossServiceCallbacks:
    """Test service callback handlers."""

    @pytest.mark.asyncio
    async def test_on_state_updated_triggers_health_check(
        self, service: HABossService
    ) -> None:
        """Test that state updates trigger health checks."""
        # Set up mocks
        service.health_monitor = AsyncMock()
        service.health_monitor.check_entity = AsyncMock(return_value=[])

        # Create state
        new_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.now(UTC),
        )

        await service._on_state_updated(new_state, None)

        # Verify health check was called
        service.health_monitor.check_entity.assert_called_once_with("sensor.test")

    @pytest.mark.asyncio
    async def test_on_health_issue_triggers_healing(self, service: HABossService) -> None:
        """Test that health issues trigger healing."""
        # Set up mocks
        service.config.healing.enabled = True
        service.healing_manager = AsyncMock()
        service.healing_manager.heal_entity = AsyncMock(return_value=True)
        service.escalation_manager = AsyncMock()

        # Create health issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue(issue)

        # Verify healing was attempted
        service.healing_manager.heal_entity.assert_called_once_with("sensor.test")
        assert service.healings_attempted == 1
        assert service.healings_succeeded == 1

    @pytest.mark.asyncio
    async def test_on_health_issue_escalates_on_failure(
        self, service: HABossService
    ) -> None:
        """Test that healing failures are escalated."""
        # Set up mocks
        service.config.healing.enabled = True
        service.healing_manager = AsyncMock()
        service.healing_manager.heal_entity = AsyncMock(return_value=False)
        service.escalation_manager = AsyncMock()
        service.escalation_manager.notify_healing_failure = AsyncMock()

        # Create health issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue(issue)

        # Verify escalation was called
        service.escalation_manager.notify_healing_failure.assert_called_once()
        assert service.healings_attempted == 1
        assert service.healings_succeeded == 0

    @pytest.mark.asyncio
    async def test_on_health_issue_skips_recovery_events(
        self, service: HABossService
    ) -> None:
        """Test that recovery events don't trigger healing."""
        # Set up mocks
        service.healing_manager = AsyncMock()
        service.healing_manager.heal_entity = AsyncMock()

        # Create recovery issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="recovered",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue(issue)

        # Verify healing was NOT called
        service.healing_manager.heal_entity.assert_not_called()


class TestHABossServiceStatus:
    """Test service status reporting."""

    def test_get_status_when_stopped(self, service: HABossService) -> None:
        """Test status when service is stopped."""
        status = service.get_status()

        assert status["state"] == ServiceState.STOPPED
        assert status["mode"] == "testing"
        assert status["uptime_seconds"] == 0
        assert status["start_time"] is None
        assert status["websocket_connected"] is False
        assert status["statistics"]["health_checks_performed"] == 0

    def test_get_status_when_running(self, service: HABossService) -> None:
        """Test status when service is running."""
        service.state = ServiceState.RUNNING
        service.start_time = datetime.now(UTC)
        service.health_checks_performed = 10
        service.healings_attempted = 5
        service.healings_succeeded = 4

        status = service.get_status()

        assert status["state"] == ServiceState.RUNNING
        assert status["uptime_seconds"] > 0
        assert status["start_time"] is not None
        assert status["statistics"]["health_checks_performed"] == 10
        assert status["statistics"]["healings_attempted"] == 5
        assert status["statistics"]["healings_succeeded"] == 4
        assert status["statistics"]["healing_success_rate"] == 80.0
