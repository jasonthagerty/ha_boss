"""Tests for notification escalation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig, NotificationsConfig
from ha_boss.core.exceptions import HealingFailedError
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.escalation import NotificationEscalator, create_notification_escalator
from ha_boss.monitoring.health_monitor import HealthIssue


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
async def test_escalator_creation(mock_config, mock_ha_client):
    """Test creating notification escalator via factory function."""
    escalator = await create_notification_escalator(mock_config, mock_ha_client)
    assert escalator is not None
    assert isinstance(escalator, NotificationEscalator)


@pytest.mark.asyncio
async def test_notify_healing_failure(escalator, sample_health_issue, mock_ha_client):
    """Test sending healing failure notification."""
    error = HealingFailedError("Integration reload failed")
    attempts = 3

    await escalator.notify_healing_failure(sample_health_issue, error, attempts)

    # Verify notification was sent
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args[1]["title"] == "HA Boss: Healing Failed"
    assert "sensor.test_sensor" in call_args[1]["message"]
    assert "unavailable" in call_args[1]["message"]
    assert str(attempts) in call_args[1]["message"]
    assert "haboss_healing_failure_sensor_test_sensor" == call_args[1]["notification_id"]


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
async def test_notify_recovery(escalator, mock_ha_client):
    """Test sending recovery notification."""
    await escalator.notify_recovery("sensor.test_sensor", "unavailable")

    # Verify notification was sent
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args[1]["title"] == "HA Boss: Entity Recovered"
    assert "sensor.test_sensor" in call_args[1]["message"]
    assert "unavailable" in call_args[1]["message"]
    assert "recovered" in call_args[1]["message"].lower()


@pytest.mark.asyncio
async def test_notify_recovery_dismisses_previous(escalator, mock_ha_client):
    """Test recovery notification dismisses previous failure notification."""
    # First send a failure notification
    issue = HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
    )
    await escalator.notify_healing_failure(issue, Exception("Test"), 1)

    # Track the notification
    assert "sensor.test_sensor" in escalator._sent_notifications

    # Now send recovery
    await escalator.notify_recovery("sensor.test_sensor", "unavailable")

    # Verify dismiss was called
    mock_ha_client.call_service.assert_called_once_with(
        "persistent_notification",
        "dismiss",
        {"notification_id": "haboss_healing_failure_sensor_test_sensor"},
    )

    # Verify entity removed from tracking
    assert "sensor.test_sensor" not in escalator._sent_notifications


@pytest.mark.asyncio
async def test_notify_circuit_breaker_open(escalator, mock_ha_client):
    """Test sending circuit breaker notification."""
    reset_time = datetime.now(UTC) + timedelta(minutes=5)

    await escalator.notify_circuit_breaker_open("Test Integration", 10, reset_time)

    # Verify notification was sent
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args[1]["title"] == "HA Boss: Circuit Breaker Opened"
    assert "Test Integration" in call_args[1]["message"]
    assert "10" in call_args[1]["message"]
    assert "auto-healing" in call_args[1]["message"].lower()


@pytest.mark.asyncio
async def test_notify_summary(escalator, mock_ha_client):
    """Test sending weekly summary notification."""
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

    await escalator.notify_summary(stats)

    # Verify notification was sent
    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args

    assert call_args[1]["title"] == "HA Boss: Weekly Summary"
    message = call_args[1]["message"]
    assert "100" in message
    assert "80" in message
    assert "20" in message
    assert "80.0%" in message
    assert "sensor.problem1" in message
    assert "sensor.problem2" in message


@pytest.mark.asyncio
async def test_notify_summary_disabled(disabled_notifications_config, mock_ha_client):
    """Test weekly summary respects config setting."""
    escalator = NotificationEscalator(disabled_notifications_config, mock_ha_client)
    stats = {"total_attempts": 0}

    await escalator.notify_summary(stats)

    # Verify notification was NOT sent
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_mode(dry_run_config, mock_ha_client):
    """Test notifications in dry-run mode."""
    escalator = NotificationEscalator(dry_run_config, mock_ha_client)

    issue = HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
    )

    await escalator.notify_healing_failure(issue, Exception("Test"), 1)

    # Verify notification was NOT sent (dry-run mode)
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_notification_error_handling(escalator, mock_ha_client):
    """Test graceful handling of notification errors."""
    # Make notification sending fail
    mock_ha_client.create_persistent_notification.side_effect = Exception("API Error")

    issue = HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
    )

    # Should not raise exception
    await escalator.notify_healing_failure(issue, Exception("Test"), 1)

    # Verify it tried to send
    mock_ha_client.create_persistent_notification.assert_called_once()


def test_format_time_ago():
    """Test time ago formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    # Just now
    now = datetime.now(UTC)
    assert escalator._format_time_ago(now) == "just now"

    # Minutes ago
    past = now - timedelta(minutes=5)
    result = escalator._format_time_ago(past)
    assert "5 minutes ago" in result

    # Hours ago
    past = now - timedelta(hours=2)
    result = escalator._format_time_ago(past)
    assert "2 hours ago" in result

    # Days ago
    past = now - timedelta(days=3)
    result = escalator._format_time_ago(past)
    assert "3 days ago" in result


def test_format_time_until():
    """Test time until formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    now = datetime.now(UTC)

    # Less than a minute
    future = now + timedelta(seconds=30)
    assert escalator._format_time_until(future) == "less than a minute"

    # Minutes
    future = now + timedelta(minutes=5)
    result = escalator._format_time_until(future)
    assert "5 minutes" in result or "4 minutes" in result  # Allow for timing variance

    # Hours
    future = now + timedelta(hours=2)
    result = escalator._format_time_until(future)
    assert "2 hours" in result or "1 hour" in result

    # Days
    future = now + timedelta(days=3)
    result = escalator._format_time_until(future)
    assert "3 days" in result or "2 days" in result


def test_format_healing_failure_message():
    """Test healing failure message formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    error = HealingFailedError("Integration reload failed")
    message = escalator._format_healing_failure_message(
        entity_id="sensor.test",
        issue_type="unavailable",
        error=error,
        attempts=3,
        detected_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    assert "sensor.test" in message
    assert "unavailable" in message
    assert "3" in message
    assert "Integration reload failed" in message
    assert "Action Required" in message


def test_format_recovery_message():
    """Test recovery message formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    message = escalator._format_recovery_message("sensor.test", "unavailable")

    assert "sensor.test" in message
    assert "unavailable" in message
    assert "recovered" in message.lower()
    assert "No further action" in message


def test_format_circuit_breaker_message():
    """Test circuit breaker message formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    reset_time = datetime.now(UTC) + timedelta(minutes=30)
    message = escalator._format_circuit_breaker_message("Test Integration", 10, reset_time)

    assert "Test Integration" in message
    assert "10" in message
    assert "auto-healing" in message.lower()
    assert "Action Required" in message


def test_format_summary_message():
    """Test summary message formatting."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    stats = {
        "total_attempts": 100,
        "successful": 80,
        "failed": 20,
        "success_rate": 80.0,
        "avg_duration_seconds": 2.5,
        "top_issues": [
            ("sensor.problem1", 5),
            ("sensor.problem2", 3),
            ("sensor.problem3", 2),
        ],
    }

    message = escalator._format_summary_message(stats)

    assert "100" in message
    assert "80" in message
    assert "20" in message
    assert "80.0%" in message
    assert "2.50s" in message
    assert "sensor.problem1" in message
    assert "sensor.problem2" in message
    assert "Most Common Issues" in message


def test_format_summary_message_no_top_issues():
    """Test summary message formatting without top issues."""
    escalator = NotificationEscalator(
        Config(
            home_assistant=HomeAssistantConfig(url="http://test", token="token"),
        ),
        AsyncMock(),
    )

    stats = {
        "total_attempts": 50,
        "successful": 50,
        "failed": 0,
        "success_rate": 100.0,
        "avg_duration_seconds": 1.0,
    }

    message = escalator._format_summary_message(stats)

    assert "50" in message
    assert "100.0%" in message
    assert "Most Common Issues" not in message
