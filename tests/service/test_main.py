"""Tests for main service orchestration.

Tests verify multi-instance service architecture with:
- Per-instance component dicts (ha_clients, state_trackers, health_monitors, etc.)
- Per-instance statistics (health_checks_performed, healings_attempted, etc.)
- Backward-compatible properties that access default instance
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from ha_boss.core.config import Config
from ha_boss.core.types import HealthIssue
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
        # Component dicts should be empty before start()
        assert service.ha_clients == {}
        assert service.websocket_clients == {}
        assert service.state_trackers == {}

    def test_service_has_config(self, service: HABossService, mock_config: Config) -> None:
        """Test that service has configuration."""
        assert service.config == mock_config
        assert service.config.mode == "testing"

    def test_initial_statistics(self, service: HABossService) -> None:
        """Test that statistics are initialized as empty dicts."""
        assert service.health_checks_performed == {}
        assert service.healings_attempted == {}
        assert service.healings_succeeded == {}
        assert service.healings_failed == {}


class TestHABossServiceStart:
    """Test service startup."""

    @pytest.mark.asyncio
    async def test_start_initializes_components(
        self, service: HABossService, mock_config: Config
    ) -> None:
        """Test that start() initializes all components for default instance."""
        # Mock all component initializations
        with (
            patch("ha_boss.service.main.Database") as mock_db_class,
            patch("ha_boss.core.ha_client.HomeAssistantClient") as mock_ha_client_class,
            patch("ha_boss.service.main.IntegrationDiscovery") as mock_integration_discovery,
            patch(
                "ha_boss.discovery.entity_discovery.EntityDiscoveryService"
            ) as mock_entity_discovery,
            patch("ha_boss.service.main.StateTracker") as mock_state_tracker,
            patch("ha_boss.service.main.HealthMonitor") as mock_health_monitor,
            patch("ha_boss.service.main.HealingManager"),
            patch("ha_boss.service.main.NotificationEscalator"),
            patch("ha_boss.service.main.NotificationManager"),
            patch("ha_boss.service.main.WebSocketClient") as mock_websocket_client,
        ):
            # Set up mocks
            mock_db = AsyncMock()
            mock_db.init_db = AsyncMock()
            mock_db.validate_version = AsyncMock(
                return_value=(True, "Database version v1 is current")
            )
            mock_db_class.return_value = mock_db

            mock_client = AsyncMock()
            mock_client.get_states = AsyncMock(return_value=[])
            mock_ha_client_class.return_value = mock_client

            mock_discovery = AsyncMock()
            mock_discovery.discover_all = AsyncMock(return_value={})
            mock_integration_discovery.return_value = mock_discovery

            # Entity discovery mock that calls get_states during refresh
            async def mock_discover_and_refresh(trigger_type, trigger_source):
                # Simulate EntityDiscoveryService calling get_states
                await mock_client.get_states()
                return {
                    "automations_found": 0,
                    "scenes_found": 0,
                    "scripts_found": 0,
                    "entities_discovered": 0,
                }

            mock_entity_disc = AsyncMock()
            mock_entity_disc.discover_and_refresh = mock_discover_and_refresh
            mock_entity_disc._monitored_set = set()
            mock_entity_disc._auto_discovered_entities = set()
            mock_entity_discovery.return_value = mock_entity_disc

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

            # Verify default instance exists in component dicts
            assert "default" in service.ha_clients
            assert "default" in service.websocket_clients
            assert "default" in service.state_trackers
            assert "default" in service.health_monitors
            assert "default" in service.healing_managers

            # Verify backward-compatible properties work
            assert service.ha_client is not None
            assert service.websocket_client is not None
            assert service.state_tracker is not None
            assert service.health_monitor is not None
            assert service.healing_manager is not None

            # Verify initializations were called
            mock_db.init_db.assert_called_once()
            # get_states is called 3 times: connection test, initial snapshot, entity discovery
            assert mock_client.get_states.call_count == 3
            # Note: StateTracker.initialize() is no longer called in multi-instance architecture
            mock_monitor.start.assert_called_once()
            # WebSocket now uses start() instead of connect() for initialization
            mock_ws.start.assert_called_once()

            # Verify statistics initialized for default instance
            assert "default" in service.health_checks_performed
            assert service.health_checks_performed["default"] == 0

    @pytest.mark.asyncio
    async def test_start_handles_connection_errors(self, service: HABossService) -> None:
        """Test that start() handles connection errors gracefully."""
        with (
            patch("ha_boss.service.main.Database") as mock_db_class,
            patch("ha_boss.core.ha_client.HomeAssistantClient") as mock_ha_client_class,
        ):
            mock_db = AsyncMock()
            mock_db.init_db = AsyncMock()
            mock_db.validate_version = AsyncMock(
                return_value=(True, "Database version v1 is current")
            )
            mock_db_class.return_value = mock_db

            mock_client = AsyncMock()
            mock_client.get_states = AsyncMock(side_effect=Exception("Connection failed"))
            mock_ha_client_class.return_value = mock_client

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
        """Test that stop() cleans up all per-instance components."""
        # Set up service as if it's running with default instance
        service.state = ServiceState.RUNNING
        service.database = AsyncMock()
        service.database.close = AsyncMock()

        # Add components for default instance
        mock_ha_client = AsyncMock()
        mock_ha_client.close = AsyncMock()
        service.ha_clients["default"] = mock_ha_client

        mock_health_monitor = AsyncMock()
        mock_health_monitor.stop = AsyncMock()
        service.health_monitors["default"] = mock_health_monitor

        mock_websocket = AsyncMock()
        mock_websocket.stop = AsyncMock()
        service.websocket_clients["default"] = mock_websocket

        await service.stop()

        # Verify cleanup
        assert service.state == ServiceState.STOPPED
        service.database.close.assert_called_once()
        mock_ha_client.close.assert_called_once()
        mock_health_monitor.stop.assert_called_once()
        mock_websocket.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, service: HABossService) -> None:
        """Test that stop() when not running does nothing."""
        assert service.state == ServiceState.STOPPED

        await service.stop()

        assert service.state == ServiceState.STOPPED


class TestHABossServiceCallbacks:
    """Test service callback handlers."""

    @pytest.mark.asyncio
    async def test_on_state_updated_triggers_health_check(self, service: HABossService) -> None:
        """Test that state updates trigger health checks."""
        # Set up mocks for default instance
        service.ha_clients["default"] = AsyncMock()

        mock_health_monitor = AsyncMock()
        mock_health_monitor.check_entity_now = AsyncMock(return_value=None)
        service.health_monitors["default"] = mock_health_monitor

        # Create state
        new_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.now(UTC),
        )

        # Call with instance_id parameter
        await service._on_state_updated("default", new_state, None)

        # Verify health check was called
        mock_health_monitor.check_entity_now.assert_called_once_with("sensor.test")

    @pytest.mark.asyncio
    async def test_on_health_issue_triggers_healing(self, service: HABossService) -> None:
        """Test that health issues trigger healing."""
        # Set up mocks for default instance
        service.config.healing.enabled = True
        service.healings_attempted["default"] = 0
        service.healings_succeeded["default"] = 0
        service.healings_failed["default"] = 0

        mock_healing_manager = AsyncMock()
        mock_healing_manager.heal = AsyncMock(return_value=True)
        service.healing_managers["default"] = mock_healing_manager

        mock_escalation = AsyncMock()
        service.escalation_managers["default"] = mock_escalation

        # Create health issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue("default", issue)

        # Verify healing was attempted
        mock_healing_manager.heal.assert_called_once_with(issue)
        assert service.healings_attempted["default"] == 1
        assert service.healings_succeeded["default"] == 1

    @pytest.mark.asyncio
    async def test_on_health_issue_escalates_on_failure(self, service: HABossService) -> None:
        """Test that healing failures are escalated."""
        # Set up mocks for default instance
        service.config.healing.enabled = True
        service.healings_attempted["default"] = 0
        service.healings_succeeded["default"] = 0
        service.healings_failed["default"] = 0

        mock_healing_manager = AsyncMock()
        mock_healing_manager.heal = AsyncMock(return_value=False)
        service.healing_managers["default"] = mock_healing_manager

        mock_escalation = AsyncMock()
        mock_escalation.notify_healing_failure = AsyncMock()
        service.escalation_managers["default"] = mock_escalation

        # Create health issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue("default", issue)

        # Verify escalation was called
        mock_escalation.notify_healing_failure.assert_called_once()
        assert service.healings_attempted["default"] == 1
        assert service.healings_succeeded["default"] == 0
        assert service.healings_failed["default"] == 1

    @pytest.mark.asyncio
    async def test_on_health_issue_skips_recovery_events(self, service: HABossService) -> None:
        """Test that recovery events don't trigger healing."""
        # Set up mocks for default instance
        mock_healing_manager = AsyncMock()
        mock_healing_manager.heal_entity = AsyncMock()
        service.healing_managers["default"] = mock_healing_manager

        # Create recovery issue
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="recovered",
            detected_at=datetime.now(UTC),
        )

        await service._on_health_issue("default", issue)

        # Verify healing was NOT called
        mock_healing_manager.heal_entity.assert_not_called()


class TestHABossServiceStatus:
    """Test service status reporting."""

    def test_get_status_when_stopped(self, service: HABossService) -> None:
        """Test status when service is stopped."""
        status = service.get_status()

        assert status["state"] == ServiceState.STOPPED
        assert status["mode"] == "testing"
        assert status["uptime_seconds"] == 0
        assert status["start_time"] is None
        assert status["instance_count"] == 0
        assert status["instances"] == {}
        assert status["statistics"]["health_checks_performed"] == 0

    def test_get_status_when_running(self, service: HABossService) -> None:
        """Test status when service is running with default instance."""
        service.state = ServiceState.RUNNING
        service.start_time = datetime.now(UTC)

        # Set up default instance with mock components
        mock_ws = AsyncMock()
        mock_ws.is_connected = lambda: True
        service.websocket_clients["default"] = mock_ws
        service.ha_clients["default"] = AsyncMock()

        # Set per-instance statistics
        service.health_checks_performed["default"] = 10
        service.healings_attempted["default"] = 5
        service.healings_succeeded["default"] = 4
        service.healings_failed["default"] = 1

        status = service.get_status()

        assert status["state"] == ServiceState.RUNNING
        assert status["uptime_seconds"] > 0
        assert status["start_time"] is not None
        assert status["instance_count"] == 1
        assert "default" in status["instances"]
        assert status["statistics"]["health_checks_performed"] == 10
        assert status["statistics"]["healings_attempted"] == 5
        assert status["statistics"]["healings_succeeded"] == 4
        assert status["statistics"]["healing_success_rate"] == 80.0
        assert status["instances"]["default"]["websocket_connected"] is True

    @pytest.mark.asyncio
    async def test_state_tracker_callback_integration(self, service: HABossService) -> None:
        """Test that StateTracker actually calls _on_state_updated callback."""
        # Set up service components for default instance
        service.ha_clients["default"] = AsyncMock()

        # Create real StateTracker with callback
        from ha_boss.core.database import Database

        test_db = Database(":memory:")
        await test_db.init_db()

        # Track callback invocations
        callback_called = False
        callback_args = None

        async def track_callback(
            instance_id: str, new_state: EntityState, old_state: EntityState | None
        ) -> None:
            nonlocal callback_called, callback_args
            callback_called = True
            callback_args = (instance_id, new_state, old_state)

        # Replace _on_state_updated with tracking version
        service._on_state_updated = track_callback

        # Create StateTracker with callback wrapper
        from ha_boss.monitoring.state_tracker import StateTracker

        async def on_state_updated_wrapper(
            new_state: EntityState, old_state: EntityState | None
        ) -> None:
            await service._on_state_updated("default", new_state, old_state)

        state_tracker = StateTracker(
            database=test_db,
            instance_id="default",
            on_state_updated=on_state_updated_wrapper,
        )

        # Simulate state update (WebSocket event format)
        state_data = {
            "entity_id": "sensor.test",
            "new_state": {
                "state": "unavailable",
                "last_changed": datetime.now(UTC).isoformat(),
                "last_updated": datetime.now(UTC).isoformat(),
                "attributes": {},
            },
        }

        await state_tracker.update_state(state_data)

        # Verify callback was called
        assert callback_called, "Callback should have been invoked"
        assert callback_args is not None
        assert callback_args[0] == "default"
        assert callback_args[1].entity_id == "sensor.test"

        await test_db.close()
