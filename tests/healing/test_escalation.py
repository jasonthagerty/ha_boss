"""Tests for notification escalation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig, NotificationsConfig
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.core.types import HealthIssue
from ha_boss.healing.escalation import NotificationEscalator, create_notification_escalator
from ha_boss.notifications.manager import NotificationManager


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        mode="production",
    )


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    client = AsyncMock(spec=HomeAssistantClient)
    client.create_persistent_notification = AsyncMock()
    client.call_service = AsyncMock()
    return client


@pytest.fixture
def notification_manager(mock_config, mock_ha_client):
    """Shared NotificationManager (mirrors production wiring)."""
    return NotificationManager(mock_config, mock_ha_client)


@pytest.fixture
def escalator(mock_config, notification_manager):
    """Create NotificationEscalator backed by the shared manager."""
    return NotificationEscalator(mock_config, notification_manager)


@pytest.fixture
def sample_health_issue():
    """Create sample health issue."""
    return HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC) - timedelta(minutes=5),
        details={"state": "unavailable"},
    )


@pytest.fixture
def issue_detect_config():
    """Create config with monitor-and-notify (on_issue_detected) enabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(on_issue_detected=True),
        mode="production",
    )


@pytest.mark.asyncio
async def test_notify_issue_detected_cloud_suppresses_mobile(issue_detect_config, mock_ha_client):
    """A cloud entity's issue notification omits the MOBILE channel."""
    from ha_boss.notifications import NotificationChannel

    nm = NotificationManager(issue_detect_config, mock_ha_client)
    escalator = NotificationEscalator(issue_detect_config, nm)
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
    nm = NotificationManager(issue_detect_config, mock_ha_client)
    escalator = NotificationEscalator(issue_detect_config, nm)
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
    nm = NotificationManager(issue_detect_config, mock_ha_client)
    escalator = NotificationEscalator(issue_detect_config, nm)
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
    nm = NotificationManager(mock_config, mock_ha_client)
    escalator = await create_notification_escalator(mock_config, nm)
    assert escalator is not None
    assert isinstance(escalator, NotificationEscalator)
    assert escalator.notification_manager is nm


@pytest.mark.asyncio
async def test_uses_shared_notification_manager(mock_config, mock_ha_client):
    """Escalator uses the notification_manager passed in, not a private copy."""
    nm = NotificationManager(mock_config, mock_ha_client)
    escalator = NotificationEscalator(mock_config, nm)
    assert escalator.notification_manager is nm


@pytest.mark.asyncio
async def test_notify_issue_detected_enabled(
    issue_detect_config, sample_health_issue, mock_ha_client
):
    """Test issue-detected notification is sent when enabled."""
    nm = NotificationManager(issue_detect_config, mock_ha_client)
    escalator = NotificationEscalator(issue_detect_config, nm)

    await escalator.notify_issue_detected(sample_health_issue)

    mock_ha_client.create_persistent_notification.assert_called_once()
    call_args = mock_ha_client.create_persistent_notification.call_args
    assert "unavailable" in call_args.kwargs["title"]
    assert "sensor.test_sensor" in call_args.kwargs["message"]
    assert "unavailable" in call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_notify_issue_detected_disabled(mock_ha_client, sample_health_issue):
    """Test issue-detected notification is suppressed when flag is explicitly off."""
    config = Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        notifications=NotificationsConfig(on_issue_detected=False),
        mode="production",
    )
    nm = NotificationManager(config, mock_ha_client)
    escalator = NotificationEscalator(config, nm)
    await escalator.notify_issue_detected(sample_health_issue)

    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_issue_detected_clears_without_recovery_notification(
    escalator, mock_ha_client
):
    """dismiss_issue_detected clears the issue-detected alert but sends NO recovery notification."""
    await escalator.dismiss_issue_detected("sensor.test_sensor")

    dismissed_ids = [
        call.args[2]["notification_id"]
        for call in mock_ha_client.call_service.call_args_list
        if call.args[:2] == ("persistent_notification", "dismiss")
    ]
    assert dismissed_ids == ["haboss_issue_detected_sensor_test_sensor"]
    mock_ha_client.create_persistent_notification.assert_not_called()


@pytest.mark.asyncio
async def test_ack_clears_shared_manager_dedup(mock_config, mock_ha_client):
    """Acknowledging a mobile push via the shared manager re-arms the escalator's dedup.

    This is the P4 regression test: if escalator and service action-handler use
    different NotificationManager instances, the escalator won't re-push after an Ack.
    """
    nm = NotificationManager(mock_config, mock_ha_client)
    notification_id = "haboss_issue_detected_sensor_test_sensor"

    # Simulate mobile dedup state being set (as if we just sent the push)
    nm._sent_mobile_notifications[notification_id] = object()  # type: ignore[assignment]

    # Service action-handler calls dismiss() on the SAME manager when Ack arrives
    await nm.dismiss(notification_id)

    # Dedup entry must be cleared so the escalator can re-push on the next cycle
    assert notification_id not in nm._sent_mobile_notifications


@pytest.mark.asyncio
async def test_notify_connection_error_sends_ha_notification(escalator, mock_ha_client):
    """notify_connection_error sends a persistent notification to HA."""
    await escalator.notify_connection_error("Lost connection after 30 minutes")

    mock_ha_client.create_persistent_notification.assert_called_once()
    call_kwargs = mock_ha_client.create_persistent_notification.call_args
    title = call_kwargs.kwargs.get("title") or call_kwargs.args[1]
    assert "Connection" in title or "connection" in title


@pytest.mark.asyncio
async def test_notify_connection_error_no_error_message(escalator, mock_ha_client):
    """notify_connection_error works without an explicit error string."""
    await escalator.notify_connection_error()

    mock_ha_client.create_persistent_notification.assert_called_once()
