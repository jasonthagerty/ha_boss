"""Tests for health_monitor module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from ha_boss.core.config import Config, MonitoringConfig, HomeAssistantConfig
from ha_boss.core.database import Database
from ha_boss.core.exceptions import DatabaseError
from ha_boss.monitoring.health_monitor import (
    HealthIssue,
    HealthMonitor,
    create_health_monitor,
)
from ha_boss.monitoring.state_tracker import EntityState, StateTracker


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration."""
    config = MagicMock(spec=Config)
    config.monitoring = MonitoringConfig(
        include=[],
        exclude=["sensor.time*", "sensor.date*"],
        grace_period_seconds=300,  # 5 minutes
        stale_threshold_seconds=3600,  # 1 hour
    )
    config.home_assistant = MagicMock(spec=HomeAssistantConfig)
    return config


@pytest.fixture
async def mock_database() -> Database:
    """Create a mock database."""
    db = MagicMock(spec=Database)
    db.async_session = MagicMock()
    return db


@pytest.fixture
async def mock_state_tracker() -> StateTracker:
    """Create a mock state tracker."""
    tracker = MagicMock(spec=StateTracker)
    tracker.get_all_states = AsyncMock(return_value={})
    tracker.get_state = AsyncMock(return_value=None)
    return tracker


@pytest.fixture
async def health_monitor(
    mock_config: Config, mock_database: Database, mock_state_tracker: StateTracker
) -> HealthMonitor:
    """Create a health monitor instance."""
    return HealthMonitor(mock_config, mock_database, mock_state_tracker)


class TestHealthIssue:
    """Tests for HealthIssue class."""

    def test_health_issue_initialization(self) -> None:
        """Test HealthIssue initialization."""
        now = datetime.utcnow()
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=now,
            details={"state": "unavailable"},
        )

        assert issue.entity_id == "sensor.test"
        assert issue.issue_type == "unavailable"
        assert issue.detected_at == now
        assert issue.details == {"state": "unavailable"}

    def test_health_issue_repr(self) -> None:
        """Test HealthIssue string representation."""
        now = datetime.utcnow()
        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=now,
        )

        repr_str = repr(issue)
        assert "sensor.test" in repr_str
        assert "unavailable" in repr_str


class TestHealthMonitorDetection:
    """Tests for issue detection logic."""

    def test_detect_unavailable(self, health_monitor: HealthMonitor) -> None:
        """Test detection of unavailable entity."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.utcnow(),
        )

        issue_type = health_monitor._detect_issue_type(entity_state)
        assert issue_type == "unavailable"

    def test_detect_unknown(self, health_monitor: HealthMonitor) -> None:
        """Test detection of unknown entity."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unknown",
            last_updated=datetime.utcnow(),
        )

        issue_type = health_monitor._detect_issue_type(entity_state)
        assert issue_type == "unknown"

    def test_detect_stale(self, health_monitor: HealthMonitor) -> None:
        """Test detection of stale entity."""
        # Entity not updated for 2 hours (threshold is 1 hour)
        old_time = datetime.utcnow() - timedelta(hours=2)
        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=old_time,
        )

        issue_type = health_monitor._detect_issue_type(entity_state)
        assert issue_type == "stale"

    def test_detect_healthy(self, health_monitor: HealthMonitor) -> None:
        """Test detection when entity is healthy."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
        )

        issue_type = health_monitor._detect_issue_type(entity_state)
        assert issue_type is None


class TestHealthMonitorGracePeriod:
    """Tests for grace period handling."""

    @pytest.mark.asyncio
    async def test_grace_period_not_elapsed(self, health_monitor: HealthMonitor) -> None:
        """Test that issue is not reported during grace period."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.utcnow(),
        )

        callback = AsyncMock()
        health_monitor.on_issue_detected = callback

        with patch.object(health_monitor, "_persist_health_event", new_callable=AsyncMock):
            # First check - starts tracking
            await health_monitor._handle_detected_issue(entity_state, "unavailable")
            callback.assert_not_called()

            # Second check - still in grace period
            await health_monitor._handle_detected_issue(entity_state, "unavailable")
            callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_period_elapsed(self, health_monitor: HealthMonitor) -> None:
        """Test that issue is reported after grace period."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.utcnow(),
        )

        callback = AsyncMock()
        health_monitor.on_issue_detected = callback

        # Simulate issue detected 10 minutes ago (grace period is 5 minutes)
        past_time = datetime.utcnow() - timedelta(minutes=10)
        health_monitor._issue_tracker["sensor.test"] = ("unavailable", past_time)

        with patch.object(health_monitor, "_persist_health_event", new_callable=AsyncMock):
            await health_monitor._handle_detected_issue(entity_state, "unavailable")

            # Should report issue now
            callback.assert_called_once()
            assert "sensor.test" in health_monitor._reported_issues

    @pytest.mark.asyncio
    async def test_grace_period_reset_on_type_change(self, health_monitor: HealthMonitor) -> None:
        """Test grace period resets when issue type changes."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unknown",
            last_updated=datetime.utcnow(),
        )

        # Start tracking unavailable
        past_time = datetime.utcnow() - timedelta(minutes=10)
        health_monitor._issue_tracker["sensor.test"] = ("unavailable", past_time)

        callback = AsyncMock()
        health_monitor.on_issue_detected = callback

        with patch.object(health_monitor, "_persist_health_event", new_callable=AsyncMock):
            # Now detect unknown (different type)
            await health_monitor._handle_detected_issue(entity_state, "unknown")

            # Should NOT report because grace period reset
            callback.assert_not_called()

            # Should be tracking new issue type with current time
            assert health_monitor._issue_tracker["sensor.test"][0] == "unknown"


class TestHealthMonitorRecovery:
    """Tests for entity recovery handling."""

    @pytest.mark.asyncio
    async def test_recovery_during_grace_period(self, health_monitor: HealthMonitor) -> None:
        """Test recovery during grace period (no report)."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
        )

        # Track issue that hasn't been reported yet
        health_monitor._issue_tracker["sensor.test"] = ("unavailable", datetime.utcnow())

        with patch.object(
            health_monitor, "_persist_health_event", new_callable=AsyncMock
        ) as mock_persist:
            await health_monitor._handle_recovery(entity_state)

            # Should remove from tracking
            assert "sensor.test" not in health_monitor._issue_tracker

            # Should NOT persist recovery event
            mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_after_reporting(self, health_monitor: HealthMonitor) -> None:
        """Test recovery after issue was reported."""
        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
        )

        # Track reported issue
        past_time = datetime.utcnow() - timedelta(minutes=10)
        health_monitor._issue_tracker["sensor.test"] = ("unavailable", past_time)
        health_monitor._reported_issues.add("sensor.test")

        with patch.object(
            health_monitor, "_persist_health_event", new_callable=AsyncMock
        ) as mock_persist:
            await health_monitor._handle_recovery(entity_state)

            # Should remove from both trackers
            assert "sensor.test" not in health_monitor._issue_tracker
            assert "sensor.test" not in health_monitor._reported_issues

            # Should persist recovery event
            mock_persist.assert_called_once()
            issue = mock_persist.call_args[0][0]
            assert issue.issue_type == "recovered"
            assert issue.entity_id == "sensor.test"


class TestHealthMonitorFiltering:
    """Tests for entity include/exclude filtering."""

    def test_should_monitor_no_patterns(self, health_monitor: HealthMonitor) -> None:
        """Test monitoring with no include/exclude patterns."""
        health_monitor.config.monitoring.include = []
        health_monitor.config.monitoring.exclude = []

        assert health_monitor._should_monitor_entity("sensor.temperature") is True
        assert health_monitor._should_monitor_entity("binary_sensor.door") is True

    def test_should_monitor_exclude_pattern(self, health_monitor: HealthMonitor) -> None:
        """Test exclude patterns."""
        health_monitor.config.monitoring.include = []
        health_monitor.config.monitoring.exclude = ["sensor.time*", "sensor.date*"]

        assert health_monitor._should_monitor_entity("sensor.temperature") is True
        assert health_monitor._should_monitor_entity("sensor.time") is False
        assert health_monitor._should_monitor_entity("sensor.date_today") is False

    def test_should_monitor_include_pattern(self, health_monitor: HealthMonitor) -> None:
        """Test include patterns."""
        health_monitor.config.monitoring.include = ["sensor.*", "binary_sensor.*"]
        health_monitor.config.monitoring.exclude = []

        assert health_monitor._should_monitor_entity("sensor.temperature") is True
        assert health_monitor._should_monitor_entity("binary_sensor.door") is True
        assert health_monitor._should_monitor_entity("light.bedroom") is False

    def test_should_monitor_include_and_exclude(self, health_monitor: HealthMonitor) -> None:
        """Test include and exclude patterns together."""
        health_monitor.config.monitoring.include = ["sensor.*"]
        health_monitor.config.monitoring.exclude = ["sensor.time*"]

        assert health_monitor._should_monitor_entity("sensor.temperature") is True
        assert health_monitor._should_monitor_entity("sensor.time") is False
        assert health_monitor._should_monitor_entity("light.bedroom") is False


class TestHealthMonitorPersistence:
    """Tests for database persistence."""

    @pytest.mark.asyncio
    async def test_persist_health_event(
        self, health_monitor: HealthMonitor, mock_database: Database
    ) -> None:
        """Test persisting health event to database."""
        # Mock session
        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.utcnow(),
        )

        await health_monitor._persist_health_event(issue)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_health_event_database_error(
        self, health_monitor: HealthMonitor, mock_database: Database
    ) -> None:
        """Test handling database error during persist."""
        # Mock session to raise error
        mock_session = MagicMock()
        mock_session.add = MagicMock(side_effect=Exception("Database error"))
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        issue = HealthIssue(
            entity_id="sensor.test",
            issue_type="unavailable",
            detected_at=datetime.utcnow(),
        )

        with pytest.raises(DatabaseError):
            await health_monitor._persist_health_event(issue)


class TestHealthMonitorLifecycle:
    """Tests for monitor start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_monitor(self, health_monitor: HealthMonitor) -> None:
        """Test starting health monitor."""
        with patch.object(health_monitor, "_monitor_loop", new_callable=AsyncMock):
            await health_monitor.start()

            assert health_monitor._running is True
            assert health_monitor._monitor_task is not None

    @pytest.mark.asyncio
    async def test_stop_monitor(self, health_monitor: HealthMonitor) -> None:
        """Test stopping health monitor."""
        # Start monitor first
        with patch.object(health_monitor, "_monitor_loop", new_callable=AsyncMock):
            await health_monitor.start()

        # Now stop it
        await health_monitor.stop()

        assert health_monitor._running is False

    @pytest.mark.asyncio
    async def test_check_entity_now(
        self, health_monitor: HealthMonitor, mock_state_tracker: StateTracker
    ) -> None:
        """Test manual entity health check."""
        # Mock an unavailable entity
        entity_state = EntityState(
            entity_id="sensor.test",
            state="unavailable",
            last_updated=datetime.utcnow(),
        )
        mock_state_tracker.get_state = AsyncMock(return_value=entity_state)

        issue = await health_monitor.check_entity_now("sensor.test")

        assert issue is not None
        assert issue.entity_id == "sensor.test"
        assert issue.issue_type == "unavailable"

    @pytest.mark.asyncio
    async def test_check_entity_now_healthy(
        self, health_monitor: HealthMonitor, mock_state_tracker: StateTracker
    ) -> None:
        """Test manual check of healthy entity."""
        # Mock a healthy entity
        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
        )
        mock_state_tracker.get_state = AsyncMock(return_value=entity_state)

        issue = await health_monitor.check_entity_now("sensor.test")

        assert issue is None

    @pytest.mark.asyncio
    async def test_check_entity_now_nonexistent(
        self, health_monitor: HealthMonitor, mock_state_tracker: StateTracker
    ) -> None:
        """Test manual check of non-existent entity."""
        mock_state_tracker.get_state = AsyncMock(return_value=None)

        issue = await health_monitor.check_entity_now("sensor.nonexistent")

        assert issue is None


class TestCreateHealthMonitor:
    """Tests for create_health_monitor factory function."""

    @pytest.mark.asyncio
    async def test_create_health_monitor(
        self,
        mock_config: Config,
        mock_database: Database,
        mock_state_tracker: StateTracker,
    ) -> None:
        """Test creating and starting health monitor."""
        with patch.object(HealthMonitor, "_monitor_loop", new_callable=AsyncMock):
            monitor = await create_health_monitor(mock_config, mock_database, mock_state_tracker)

            assert isinstance(monitor, HealthMonitor)
            assert monitor._running is True

    @pytest.mark.asyncio
    async def test_create_health_monitor_with_callback(
        self,
        mock_config: Config,
        mock_database: Database,
        mock_state_tracker: StateTracker,
    ) -> None:
        """Test creating health monitor with callback."""
        callback = AsyncMock()

        with patch.object(HealthMonitor, "_monitor_loop", new_callable=AsyncMock):
            monitor = await create_health_monitor(
                mock_config, mock_database, mock_state_tracker, on_issue_detected=callback
            )

            assert monitor.on_issue_detected == callback
