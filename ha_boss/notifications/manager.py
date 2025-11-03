"""Notification manager for routing alerts to various channels."""

import logging
from enum import Enum

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    TemplateRegistry,
)

logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    """Notification delivery channels."""

    HOME_ASSISTANT = "home_assistant"  # HA persistent notifications
    CLI = "cli"  # CLI/stdout via logging (for Docker logs)


class NotificationManager:
    """Manages notification routing to multiple channels.

    Features:
    - Multiple channels: HA persistent notifications, CLI/stdout
    - Severity-based routing
    - Template-based message generation
    - Deduplication to avoid spam
    - Dry-run mode support
    """

    def __init__(
        self,
        config: Config,
        ha_client: HomeAssistantClient | None = None,
    ) -> None:
        """Initialize notification manager.

        Args:
            config: HA Boss configuration
            ha_client: Optional Home Assistant API client (required for HA notifications)
        """
        self.config = config
        self.ha_client = ha_client

        # Track sent HA notifications to avoid spam
        # notification_id -> context
        self._sent_notifications: dict[str, NotificationContext] = {}

        # Channel enablement
        self._channels: dict[NotificationChannel, bool] = {
            NotificationChannel.HOME_ASSISTANT: ha_client is not None,
            NotificationChannel.CLI: True,  # Always available
        }

    def enable_channel(self, channel: NotificationChannel) -> None:
        """Enable a notification channel.

        Args:
            channel: Channel to enable
        """
        if channel == NotificationChannel.HOME_ASSISTANT and self.ha_client is None:
            logger.warning("Cannot enable HOME_ASSISTANT channel: ha_client is None")
            return

        self._channels[channel] = True
        logger.info(f"Enabled notification channel: {channel}")

    def disable_channel(self, channel: NotificationChannel) -> None:
        """Disable a notification channel.

        Args:
            channel: Channel to disable
        """
        self._channels[channel] = False
        logger.info(f"Disabled notification channel: {channel}")

    async def notify(
        self,
        context: NotificationContext,
        channels: list[NotificationChannel] | None = None,
    ) -> None:
        """Send notification to specified channels.

        Args:
            context: Notification context
            channels: Optional list of channels to send to. If None, routes based on severity.
        """
        # Determine channels to use
        if channels is None:
            channels = self._get_channels_for_severity(context.severity)

        # Render message using template
        try:
            title, message = TemplateRegistry.render(context)
        except Exception as e:
            logger.error(f"Failed to render notification template: {e}", exc_info=True)
            return

        # Send to each enabled channel
        for channel in channels:
            if not self._channels.get(channel, False):
                logger.debug(f"Channel {channel} is disabled, skipping")
                continue

            try:
                if channel == NotificationChannel.HOME_ASSISTANT:
                    await self._send_to_home_assistant(title, message, context)
                elif channel == NotificationChannel.CLI:
                    await self._send_to_cli(title, message, context)
            except Exception as e:
                logger.error(f"Failed to send notification to {channel}: {e}", exc_info=True)

    async def dismiss(
        self,
        notification_id: str,
        channel: NotificationChannel = NotificationChannel.HOME_ASSISTANT,
    ) -> None:
        """Dismiss a previous notification.

        Args:
            notification_id: Notification ID to dismiss
            channel: Channel to dismiss from (only HA supported)
        """
        if channel != NotificationChannel.HOME_ASSISTANT:
            logger.debug(f"Dismiss not supported for channel: {channel}")
            return

        if self.ha_client is None:
            logger.warning("Cannot dismiss notification: ha_client is None")
            return

        if self.config.is_dry_run:
            logger.info(f"[DRY RUN] Would dismiss notification: {notification_id}")
            return

        try:
            await self.ha_client.call_service(
                "persistent_notification",
                "dismiss",
                {"notification_id": notification_id},
            )
            logger.debug(f"Dismissed notification: {notification_id}")

            # Remove from tracking
            if notification_id in self._sent_notifications:
                del self._sent_notifications[notification_id]

        except Exception as e:
            logger.warning(f"Failed to dismiss notification {notification_id}: {e}")

    async def _send_to_home_assistant(
        self,
        title: str,
        message: str,
        context: NotificationContext,
    ) -> None:
        """Send notification to Home Assistant persistent notifications.

        Args:
            title: Notification title
            message: Notification message
            context: Notification context
        """
        if self.ha_client is None:
            logger.warning("Cannot send HA notification: ha_client is None")
            return

        # Generate notification ID
        notification_id = self._generate_notification_id(context)

        # Check if we should send (deduplication)
        if notification_id in self._sent_notifications:
            logger.debug(f"Notification {notification_id} already sent, skipping")
            return

        if self.config.is_dry_run:
            logger.info(f"[DRY RUN] Would send HA notification: {title}")
            logger.debug(f"[DRY RUN] Message: {message}")
            return

        try:
            await self.ha_client.create_persistent_notification(
                message=message,
                title=title,
                notification_id=notification_id,
            )

            # Track sent notification
            self._sent_notifications[notification_id] = context

            logger.info(f"Sent HA notification: {notification_id}")

        except Exception as e:
            logger.error(f"Failed to send HA notification: {e}", exc_info=True)
            raise

    async def _send_to_cli(
        self,
        title: str,
        message: str,
        context: NotificationContext,
    ) -> None:
        """Send notification to CLI/stdout via logging.

        Args:
            title: Notification title
            message: Notification message
            context: Notification context
        """
        # Map severity to log level
        log_level = self._get_log_level_for_severity(context.severity)

        # Format for CLI output
        cli_message = f"{title}\n{message}"

        # Log with appropriate level
        logger.log(log_level, cli_message)

    def _generate_notification_id(self, context: NotificationContext) -> str:
        """Generate unique notification ID for tracking.

        Args:
            context: Notification context

        Returns:
            Notification ID string
        """
        from datetime import UTC, datetime

        # Base ID on notification type
        base_id = f"haboss_{context.notification_type.value}"

        # Add entity-specific suffix if available
        if context.entity_id:
            entity_suffix = context.entity_id.replace(".", "_")
            base_id = f"{base_id}_{entity_suffix}"
        elif context.integration_id:
            integration_suffix = context.integration_id.replace("-", "_")
            base_id = f"{base_id}_{integration_suffix}"
        elif context.integration_name:
            name_suffix = context.integration_name.replace(" ", "_").lower()
            base_id = f"{base_id}_{name_suffix}"
        else:
            # For generic notifications without specific entity/integration,
            # add timestamp to prevent collisions
            timestamp_suffix = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            base_id = f"{base_id}_{timestamp_suffix}"

        return base_id

    def _get_channels_for_severity(
        self,
        severity: NotificationSeverity,
    ) -> list[NotificationChannel]:
        """Determine which channels to use based on severity.

        Args:
            severity: Notification severity

        Returns:
            List of channels to send to
        """
        # Default routing: CLI for all, HA for warnings and above
        channels = [NotificationChannel.CLI]

        if severity in (
            NotificationSeverity.WARNING,
            NotificationSeverity.ERROR,
            NotificationSeverity.CRITICAL,
        ):
            channels.append(NotificationChannel.HOME_ASSISTANT)

        return channels

    def _get_log_level_for_severity(self, severity: NotificationSeverity) -> int:
        """Map notification severity to logging level.

        Args:
            severity: Notification severity

        Returns:
            Logging level integer
        """
        mapping = {
            NotificationSeverity.INFO: logging.INFO,
            NotificationSeverity.WARNING: logging.WARNING,
            NotificationSeverity.ERROR: logging.ERROR,
            NotificationSeverity.CRITICAL: logging.CRITICAL,
        }
        return mapping.get(severity, logging.INFO)

    def get_sent_notifications(self) -> dict[str, NotificationContext]:
        """Get all sent notifications.

        Returns:
            Dictionary of notification_id -> context
        """
        return self._sent_notifications.copy()

    def clear_sent_notifications(self) -> None:
        """Clear tracking of sent notifications."""
        self._sent_notifications.clear()
        logger.debug("Cleared sent notifications tracking")


async def create_notification_manager(
    config: Config,
    ha_client: HomeAssistantClient | None = None,
) -> NotificationManager:
    """Create a notification manager.

    Args:
        config: HA Boss configuration
        ha_client: Optional Home Assistant API client

    Returns:
        Initialized notification manager
    """
    manager = NotificationManager(config, ha_client)
    logger.info("Created notification manager")
    return manager
