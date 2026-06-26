"""Tests for notification escalation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig, NotificationsConfig
from ha_boss.core.exceptions import HealingFailedError
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.core.types import HealthIssue
from ha_boss.healing.escalation import NotificationEscalator, create_notification_escalator


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(
            on_healing_failure=True,
            weekly_summary=True,
        ),
        mode="production",
    )


@pytest.fixture
def disabled_notifications_config():
    """Create configuration with notifications disabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(
            on_healing_failure=False,
            weekly_summary=False,
        ),
        mode="production",
    )


@pytest.fixture
def dry_run_config():
    """Create dry-run configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(
            on_healing_failure=True,
            weekly_summary=True,
        ),
        mode="dry_run",
    )


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    client = AsyncMock(spec=HomeAssistantClient)
    client.create_persistent_notification = AsyncMock()
    client.call_service = AsyncMock()
    return client


@pytest.fixture
def escalator(mock_config, mock_ha_client):
    """Create NotificationEscalator instance."""
    return NotificationEscalator(mock_config, mock_ha_client)


@pytest.fixture
def sample_health_issue():
    """Create sample health issue."""
    return HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC) - timedelta(minutes=5),
        details={"state": "unavailable"},
    )


@pytest.mark.asyncio
async def test_notify_issue_detected_cloud_suppresses_mobile(issue_detect_config, mock_ha_client):
    """A cloud entity's issue notification omits the MOBILE channel."""
    from ha_boss.notifications import NotificationChannel

    escalator = NotificationEscalator(issue_detect_config, mock_ha_client)
    escalator.notification_manager.notify = AsyncMock()

    issue = HealthIssue(
        entity_id="media_player.lg_webos_tv",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
        is_cloud=True,
    )
    await escalator.notify_issue_detected(issue)

    channels = escalator.notification_manager.notify.call_args.kwargs.get("channels")
    assert channels is not None
    assert NotificationChannel.MOBILE not in channels
    assert NotificationChannel.HOME_ASSISTANT in channels


@pytest.mark.asyncio
async def test_notify_issue_detected_noncloud_uses_default_routing(
    issue_detect_config, mock_ha_client
):
    """A non-cloud entity uses default severity routing (channels=None → mobile allowed)."""
    escalator = NotificationEscalator(issue_detect_config, mock_ha_client)
    escalator.notification_manager.notify = AsyncMock()

    issue = HealthIssue(
        entity_id="binary_sensor.back_patio_motion",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
        is_cloud=False,
    )
    await escalator.notify_issue_detected(issue)

    assert escalator.notification_manager.notify.call_args.kwargs.get("channels") is None


@pytest.mark.asyncio
async def test_notify_issue_detected_cloud_keeps_mobile_when_not_suppressed(
    issue_detect_config, mock_ha_client
):
    """If suppress_mobile_push is off, cloud entities use default routing."""
    issue_detect_config.monitoring.cloud_handling.suppress_mobile_push = False
    escalator = NotificationEscalator(issue_detect_config, mock_ha_client)
    escalator.notification_manager.notify = AsyncMock()

    issue = HealthIssue(
        entity_id="media_player.lg_webos_tv",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
        is_cloud=True,
    )
    await escalator.notify_issue_detected(issue)

    assert escalator.notification_manager.notify.call_args.kwargs.get("channels") is None


@pytest.mark.asyncio
async def test_escalator_creation(mock_config, mock_ha_client):
    """Test creating notification escalator via factory function."""
    escalator = await create_notification_escalator(mock_config, mock_ha_client)
    assert escalator is not None
    assert isinstance(escalator, NotificationEscalator)
    assert escalator.notification_manager is not None


@pytest.mark.asyncio
async def test_notify_healing_failure(escalator, sample_health_issue, mock_ha_client):
    """Test sending healing failure notification."""
    error = HealingFailedError("Integration reload failed")
    attempts = 3

    await escalator.notify_healing_failure(sample_health_issue, error, attempts)

    # Verify notification was sent via NotificationManager
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args.kwargs["title"] == "HA Boss: Healing Failed"
    assert "sensor.test_sensor" in call_args.kwargs["message"]
    assert "unavailable" in call_args.kwargs["message"]
    assert str(attempts) in call_args.kwargs["message"]
    assert "HealingFailedError" in call_args.kwargs["message"]  # Exception type included


@pytest.mark.asyncio
async def test_notify_healing_failure_disabled(
    disabled_notifications_config, sample_health_issue, mock_ha_client
):
    """Test healing failure notification respects config setting."""
    escalator = NotificationEscalator(disabled_notifications_config, mock_ha_client)
    error = HealingFailedError("Test error")

    await escalator.notify_healing_failure(sample_health_issue, error, 1)

    # Verify notification was NOT sent
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_notify_recovery(escalator, mock_ha_client, caplog):
    """Test sending recovery notification."""
    import logging

    await escalator.notify_recovery("sensor.test_sensor", "unavailable")

    # Recovery notifications (INFO severity) go to CLI by default, not HA
    # They should appear in logs
    with caplog.at_level(logging.INFO):
        await escalator.notify_recovery("sensor.test_sensor", "unavailable")

    # Verify the notification was processed (logged to CLI)
    assert "recovered" in caplog.text.lower()
    assert "sensor.test_sensor" in caplog.text


@pytest.mark.asyncio
async def test_notify_recovery_dismisses_previous(escalator, sample_health_issue, mock_ha_client):
    """Test recovery notification dismisses previous failure notification."""
    # First send a failure notification
    await escalator.notify_healing_failure(sample_health_issue, Exception("Test"), 1)

    # Reset mock to clear the first call
    mock_ha_client.call_service.reset_mock()

    # Now send recovery
    await escalator.notify_recovery("sensor.test_sensor", "unavailable")

    # Verify both prior notifications are dismissed (healing failure + issue-detected)
    assert mock_ha_client.call_service.call_count == 2
    mock_ha_client.call_service.assert_any_call(
        "persistent_notification",
        "dismiss",
        {"notification_id": "haboss_healing_failure_sensor_test_sensor"},
    )


@pytest.mark.asyncio
async def test_notify_circuit_breaker_open(escalator, mock_ha_client):
    """Test sending circuit breaker notification."""
    reset_time = datetime.now(UTC) + timedelta(minutes=5)

    await escalator.notify_circuit_breaker_open("Test Integration", 10, reset_time)

    # Verify notification was sent
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args.kwargs["title"] == "HA Boss: Circuit Breaker Opened"
    assert "Test Integration" in call_args.kwargs["message"]
    assert "10" in call_args.kwargs["message"]
    assert "temporarily disabled" in call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_notify_summary(escalator, mock_ha_client, caplog):
    """Test sending weekly summary notification."""
    import logging

    stats = {
        "total_attempts": 100,
        "successful": 80,
        "failed": 20,
        "success_rate": 80.0,
        "avg_duration_seconds": 2.5,
        "top_issues": [
            ("sensor.problem1", 5),
            ("sensor.problem2", 3),
        ],
    }

    # Weekly summary notifications (INFO severity) go to CLI by default, not HA
    with caplog.at_level(logging.INFO):
        await escalator.notify_summary(stats)

    # Verify the notification was processed (logged to CLI)
    assert "Weekly Summary" in caplog.text
    assert "100" in caplog.text
    assert "sensor.problem1" in caplog.text


@pytest.mark.asyncio
async def test_notify_summary_disabled(disabled_notifications_config, mock_ha_client):
    """Test weekly summary respects config setting."""
    escalator = NotificationEscalator(disabled_notifications_config, mock_ha_client)
    stats = {"total_attempts": 0}

    await escalator.notify_summary(stats)

    # Verify notification was NOT sent
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_mode(dry_run_config, sample_health_issue, mock_ha_client):
    """Test notifications in dry-run mode."""
    escalator = NotificationEscalator(dry_run_config, mock_ha_client)

    await escalator.notify_healing_failure(sample_health_issue, Exception("Test"), 1)

    # In dry-run mode, notification should not be actually sent
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_notification_error_handling(escalator, sample_health_issue, mock_ha_client):
    """Test that notification errors are handled gracefully."""
    # Make notification fail
    mock_ha_client.create_persistent_notification.side_effect = Exception("Send failed")

    # Should not raise exception, but handle gracefully
    await escalator.notify_healing_failure(sample_health_issue, Exception("Test"), 1)

    # Verify attempt was made
    mock_ha_client.create_persistent_notification.assert_called_once()


@pytest.mark.asyncio
async def test_uses_notification_manager(mock_config, mock_ha_client):
    """Test that escalator uses NotificationManager internally."""
    escalator = NotificationEscalator(mock_config, mock_ha_client)

    # Verify NotificationManager is created
    assert hasattr(escalator, "notification_manager")
    assert escalator.notification_manager is not None


@pytest.fixture
def issue_detect_config():
    """Create config with monitor-and-notify (on_issue_detected) enabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(
            on_healing_failure=False,
            on_issue_detected=True,
            weekly_summary=False,
        ),
        mode="production",
    )


@pytest.mark.asyncio
async def test_notify_issue_detected_enabled(
    issue_detect_config, sample_health_issue, mock_ha_client
):
    """Test issue-detected notification is sent when enabled."""
    escalator = NotificationEscalator(issue_detect_config, mock_ha_client)

    await escalator.notify_issue_detected(sample_health_issue)

    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args
    assert "unavailable" in call_args.kwargs["title"]
    assert "sensor.test_sensor" in call_args.kwargs["message"]
    assert "unavailable" in call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_notify_issue_detected_disabled(escalator, sample_health_issue, mock_ha_client):
    """Test issue-detected notification is suppressed when flag is off (default)."""
    # Default mock_config leaves on_issue_detected at its default (False)
    await escalator.notify_issue_detected(sample_health_issue)

    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_notify_recovery_dismisses_issue_detected(escalator, mock_ha_client):
    """Test recovery dismisses a prior issue-detected notification."""
    await escalator.notify_recovery(
        entity_id="sensor.test_sensor", previous_issue_type="unavailable"
    )

    dismissed_ids = [
        call.args[2]["notification_id"]
        for call in mock_ha_client.call_service.call_args_list
        if call.args[:2] == ("persistent_notification", "dismiss")
    ]
    assert "haboss_issue_detected_sensor_test_sensor" in dismissed_ids


@pytest.mark.asyncio
async def test_dismiss_issue_detected_clears_without_recovery_notification(
    escalator, mock_ha_client
):
    """dismiss_issue_detected clears the issue-detected alert but sends NO recovery notification."""
    await escalator.dismiss_issue_detected("sensor.test_sensor")

    # The issue-detected notification is dismissed...
    dismissed_ids = [
        call.args[2]["notification_id"]
        for call in mock_ha_client.call_service.call_args_list
        if call.args[:2] == ("persistent_notification", "dismiss")
    ]
    assert dismissed_ids == ["haboss_issue_detected_sensor_test_sensor"]
    # ...and no RECOVERY (or any) notification is created.
    mock_ha_client.create_persistent_notification.assert_not_called()
