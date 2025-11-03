"""Tests for notification manager."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import Config
from ha_boss.notifications.manager import (
    NotificationChannel,
    NotificationManager,
    create_notification_manager,
)
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)


@pytest.fixture
def mock_config() -> Config:
    """Create mock configuration."""
    config = MagicMock(spec=Config)
    config.is_dry_run = False
    config.notifications = MagicMock()
    config.notifications.on_healing_failure = True
    config.notifications.weekly_summary = True
    return config


@pytest.fixture
def mock_ha_client() -> AsyncMock:
    """Create mock Home Assistant client."""
    client = AsyncMock()
    client.create_persistent_notification = AsyncMock()
    client.call_service = AsyncMock()
    return client


@pytest.fixture
def notification_manager(mock_config: Config, mock_ha_client: AsyncMock) -> NotificationManager:
    """Create notification manager with mocks."""
    return NotificationManager(mock_config, mock_ha_client)


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_init_with_ha_client(self, mock_config: Config, mock_ha_client: AsyncMock) -> None:
        """Test initialization with HA client."""
        manager = NotificationManager(mock_config, mock_ha_client)

        assert manager.config == mock_config
        assert manager.ha_client == mock_ha_client
        assert manager._channels[NotificationChannel.HOME_ASSISTANT] is True
        assert manager._channels[NotificationChannel.CLI] is True

    def test_init_without_ha_client(self, mock_config: Config) -> None:
        """Test initialization without HA client."""
        manager = NotificationManager(mock_config, None)

        assert manager.ha_client is None
        assert manager._channels[NotificationChannel.HOME_ASSISTANT] is False
        assert manager._channels[NotificationChannel.CLI] is True

    def test_enable_channel(self, notification_manager: NotificationManager) -> None:
        """Test enabling a notification channel."""
        notification_manager.disable_channel(NotificationChannel.CLI)
        assert notification_manager._channels[NotificationChannel.CLI] is False

        notification_manager.enable_channel(NotificationChannel.CLI)
        assert notification_manager._channels[NotificationChannel.CLI] is True

    def test_enable_ha_channel_without_client(self, mock_config: Config) -> None:
        """Test enabling HA channel without client logs warning."""
        manager = NotificationManager(mock_config, None)

        with patch("ha_boss.notifications.manager.logger") as mock_logger:
            manager.enable_channel(NotificationChannel.HOME_ASSISTANT)
            mock_logger.warning.assert_called_once()

        assert manager._channels[NotificationChannel.HOME_ASSISTANT] is False

    def test_disable_channel(self, notification_manager: NotificationManager) -> None:
        """Test disabling a notification channel."""
        assert notification_manager._channels[NotificationChannel.CLI] is True

        notification_manager.disable_channel(NotificationChannel.CLI)
        assert notification_manager._channels[NotificationChannel.CLI] is False

    @pytest.mark.asyncio
    async def test_notify_to_home_assistant(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test sending notification to Home Assistant."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
            issue_type="unavailable",
        )

        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])

        mock_ha_client.create_persistent_notification.assert_called_once()
        call_args = mock_ha_client.create_persistent_notification.call_args
        assert "sensor.test" in call_args.kwargs["message"]
        assert call_args.kwargs["title"] == "HA Boss: Healing Failed"

    @pytest.mark.asyncio
    async def test_notify_to_cli(
        self, notification_manager: NotificationManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test sending notification to CLI."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
            issue_type="unavailable",
        )

        with caplog.at_level(logging.ERROR):
            await notification_manager.notify(context, channels=[NotificationChannel.CLI])

        assert "sensor.test" in caplog.text
        assert "Healing Failed" in caplog.text

    @pytest.mark.asyncio
    async def test_notify_severity_routing(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test automatic channel routing based on severity."""
        # ERROR should go to both HA and CLI
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        await notification_manager.notify(context)  # No channels specified

        # Should send to HA
        mock_ha_client.create_persistent_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_info_severity_routing(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that INFO severity only goes to CLI by default."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_SUCCESS,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.test",
        )

        await notification_manager.notify(context)  # No channels specified

        # Should NOT send to HA (INFO only goes to CLI by default)
        mock_ha_client.create_persistent_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_deduplication(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that duplicate notifications are not sent."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        # Send first notification
        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])
        assert mock_ha_client.create_persistent_notification.call_count == 1

        # Send same notification again
        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])
        # Should still be 1 (no duplicate sent)
        assert mock_ha_client.create_persistent_notification.call_count == 1

    @pytest.mark.asyncio
    async def test_notify_dry_run(
        self, mock_config: Config, mock_ha_client: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test notification in dry-run mode."""
        mock_config.is_dry_run = True
        manager = NotificationManager(mock_config, mock_ha_client)

        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        with caplog.at_level(logging.INFO):
            await manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])

        # Should not actually send
        mock_ha_client.create_persistent_notification.assert_not_called()
        # Should log dry-run message
        assert "[DRY RUN]" in caplog.text

    @pytest.mark.asyncio
    async def test_notify_disabled_channel_skipped(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that disabled channels are skipped."""
        notification_manager.disable_channel(NotificationChannel.HOME_ASSISTANT)

        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])

        # Should not send to disabled channel
        mock_ha_client.create_persistent_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_template_error_handled(
        self, notification_manager: NotificationManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that template rendering errors are handled gracefully."""
        # Create invalid context that will cause template error
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
        )

        with patch("ha_boss.notifications.manager.TemplateRegistry.render") as mock_render:
            mock_render.side_effect = ValueError("Template error")

            with caplog.at_level(logging.ERROR):
                await notification_manager.notify(
                    context, channels=[NotificationChannel.HOME_ASSISTANT]
                )

            assert "Failed to render" in caplog.text

    @pytest.mark.asyncio
    async def test_notify_channel_error_handled(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that channel send errors are handled gracefully."""
        mock_ha_client.create_persistent_notification.side_effect = Exception("Send error")

        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        # Should not raise exception
        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])

    @pytest.mark.asyncio
    async def test_dismiss(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test dismissing a notification."""
        notification_id = "test_notification_123"

        await notification_manager.dismiss(notification_id)

        mock_ha_client.call_service.assert_called_once_with(
            "persistent_notification",
            "dismiss",
            {"notification_id": notification_id},
        )

    @pytest.mark.asyncio
    async def test_dismiss_without_ha_client(self, mock_config: Config) -> None:
        """Test dismissing notification without HA client logs warning."""
        manager = NotificationManager(mock_config, None)

        with patch("ha_boss.notifications.manager.logger") as mock_logger:
            await manager.dismiss("test_id")
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_dry_run(
        self, mock_config: Config, mock_ha_client: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test dismiss in dry-run mode."""
        mock_config.is_dry_run = True
        manager = NotificationManager(mock_config, mock_ha_client)

        with caplog.at_level(logging.INFO):
            await manager.dismiss("test_id")

        mock_ha_client.call_service.assert_not_called()
        assert "[DRY RUN]" in caplog.text

    @pytest.mark.asyncio
    async def test_dismiss_removes_from_tracking(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that dismissing removes notification from tracking."""
        # Send a notification first
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )
        await notification_manager.notify(context, channels=[NotificationChannel.HOME_ASSISTANT])

        notification_id = "haboss_healing_failure_sensor_test"
        assert notification_id in notification_manager._sent_notifications

        # Dismiss it
        await notification_manager.dismiss(notification_id)

        assert notification_id not in notification_manager._sent_notifications

    @pytest.mark.asyncio
    async def test_dismiss_error_handled(
        self, notification_manager: NotificationManager, mock_ha_client: AsyncMock
    ) -> None:
        """Test that dismiss errors are handled gracefully."""
        mock_ha_client.call_service.side_effect = Exception("Dismiss error")

        # Should not raise exception
        await notification_manager.dismiss("test_id")

    @pytest.mark.asyncio
    async def test_dismiss_cli_channel_not_supported(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test that dismissing from CLI channel is not supported."""
        with patch("ha_boss.notifications.manager.logger") as mock_logger:
            await notification_manager.dismiss("test_id", channel=NotificationChannel.CLI)
            mock_logger.debug.assert_called()

    def test_generate_notification_id_with_entity(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test notification ID generation with entity ID."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.temperature",
        )

        notification_id = notification_manager._generate_notification_id(context)

        assert notification_id == "haboss_healing_failure_sensor_temperature"

    def test_generate_notification_id_with_integration_id(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test notification ID generation with integration ID."""
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_id="abc-123-def",
        )

        notification_id = notification_manager._generate_notification_id(context)

        assert notification_id == "haboss_circuit_breaker_abc_123_def"

    def test_generate_notification_id_with_integration_name(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test notification ID generation with integration name."""
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_name="Z-Wave JS",
        )

        notification_id = notification_manager._generate_notification_id(context)

        assert notification_id == "haboss_circuit_breaker_z-wave_js"

    def test_get_channels_for_severity_info(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test channel routing for INFO severity."""
        channels = notification_manager._get_channels_for_severity(NotificationSeverity.INFO)

        assert NotificationChannel.CLI in channels
        assert NotificationChannel.HOME_ASSISTANT not in channels

    def test_get_channels_for_severity_warning(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test channel routing for WARNING severity."""
        channels = notification_manager._get_channels_for_severity(NotificationSeverity.WARNING)

        assert NotificationChannel.CLI in channels
        assert NotificationChannel.HOME_ASSISTANT in channels

    def test_get_channels_for_severity_error(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test channel routing for ERROR severity."""
        channels = notification_manager._get_channels_for_severity(NotificationSeverity.ERROR)

        assert NotificationChannel.CLI in channels
        assert NotificationChannel.HOME_ASSISTANT in channels

    def test_get_channels_for_severity_critical(
        self, notification_manager: NotificationManager
    ) -> None:
        """Test channel routing for CRITICAL severity."""
        channels = notification_manager._get_channels_for_severity(NotificationSeverity.CRITICAL)

        assert NotificationChannel.CLI in channels
        assert NotificationChannel.HOME_ASSISTANT in channels

    def test_get_log_level_for_severity(self, notification_manager: NotificationManager) -> None:
        """Test log level mapping for severities."""
        assert (
            notification_manager._get_log_level_for_severity(NotificationSeverity.INFO)
            == logging.INFO
        )
        assert (
            notification_manager._get_log_level_for_severity(NotificationSeverity.WARNING)
            == logging.WARNING
        )
        assert (
            notification_manager._get_log_level_for_severity(NotificationSeverity.ERROR)
            == logging.ERROR
        )
        assert (
            notification_manager._get_log_level_for_severity(NotificationSeverity.CRITICAL)
            == logging.CRITICAL
        )

    def test_get_sent_notifications(self, notification_manager: NotificationManager) -> None:
        """Test getting sent notifications."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )
        notification_manager._sent_notifications["test_id"] = context

        sent = notification_manager.get_sent_notifications()

        assert "test_id" in sent
        assert sent["test_id"] == context
        # Ensure it's a copy
        assert sent is not notification_manager._sent_notifications

    def test_clear_sent_notifications(self, notification_manager: NotificationManager) -> None:
        """Test clearing sent notifications."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )
        notification_manager._sent_notifications["test_id"] = context

        notification_manager.clear_sent_notifications()

        assert len(notification_manager._sent_notifications) == 0


@pytest.mark.asyncio
async def test_create_notification_manager(mock_config: Config, mock_ha_client: AsyncMock) -> None:
    """Test notification manager factory function."""
    manager = await create_notification_manager(mock_config, mock_ha_client)

    assert isinstance(manager, NotificationManager)
    assert manager.config == mock_config
    assert manager.ha_client == mock_ha_client


@pytest.mark.asyncio
async def test_create_notification_manager_without_client(mock_config: Config) -> None:
    """Test notification manager factory without HA client."""
    manager = await create_notification_manager(mock_config, None)

    assert isinstance(manager, NotificationManager)
    assert manager.ha_client is None
