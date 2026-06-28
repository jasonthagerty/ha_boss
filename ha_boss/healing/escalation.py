"""Notification escalation facade for HA Boss."""

import logging

from ha_boss.core.config import Config
from ha_boss.core.types import HealthIssue
from ha_boss.notifications import (
    NotificationChannel,
    NotificationContext,
    NotificationManager,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)


class NotificationEscalator:
    """Facade over a shared NotificationManager with domain-specific methods.

    Accepts the NotificationManager created by the service so that dedup state
    (``_sent_mobile_notifications``) is shared between the escalator and the
    action-handler that processes mobile Ack taps.  Creating a private manager
    inside the escalator would break re-alerting after an Ack.
    """

    def __init__(
        self,
        config: Config,
        notification_manager: NotificationManager,
    ) -> None:
        self.config = config
        self.notification_manager = notification_manager

    async def notify_issue_detected(
        self,
        health_issue: HealthIssue,
    ) -> None:
        """Send notification about a detected issue.

        Args:
            health_issue: Health issue that was detected
        """
        if not self.config.notifications.on_issue_detected:
            logger.debug("Issue-detected notifications are disabled")
            return

        context = NotificationContext(
            notification_type=NotificationType.ISSUE_DETECTED,
            severity=NotificationSeverity.WARNING,
            entity_id=health_issue.entity_id,
            friendly_name=health_issue.friendly_name,
            issue_type=health_issue.issue_type,
            detected_at=health_issue.detected_at,
        )

        # Cloud (internet-dependent) entities flap on external availability we
        # cannot fix — keep them off mobile push; HA/CLI still fire.
        channels = None
        if health_issue.is_cloud and self.config.monitoring.cloud_handling.suppress_mobile_push:
            channels = [NotificationChannel.CLI, NotificationChannel.HOME_ASSISTANT]
            logger.debug(
                f"Cloud entity {health_issue.entity_id}: suppressing mobile push (HA/CLI only)"
            )

        await self.notification_manager.notify(context, channels=channels)
        logger.info(f"Sent issue-detected notification for {health_issue.entity_id}")

    async def notify_connection_error(self, error: str | None = None) -> None:
        """Send notification about a persistent WebSocket connection failure.

        Fired when the WebSocket has been disconnected for longer than
        config.websocket.reconnect_notify_after_seconds.

        Args:
            error: Optional description of the connection error.
        """
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
            error=error,
        )
        await self.notification_manager.notify(context)
        logger.info("Sent connection-error notification")

    async def dismiss_issue_detected(self, entity_id: str) -> None:
        """Clear a prior issue-detected notification without sending a recovery alert.

        Used by monitor-and-notify mode on recovery: dismisses the
        issue-detected notification (and re-arms its mobile push) but does NOT
        emit a recovery notification, so users who only enabled
        ``on_issue_detected`` are not sent alerts they did not configure.

        Args:
            entity_id: Entity that recovered.
        """
        issue_notification_id = f"haboss_issue_detected_{entity_id.replace('.', '_')}"
        await self.notification_manager.dismiss(issue_notification_id)
        logger.debug(f"Cleared issue-detected notification for {entity_id}")


async def create_notification_escalator(
    config: Config,
    notification_manager: NotificationManager,
) -> NotificationEscalator:
    """Create a notification escalator backed by a shared NotificationManager.

    Args:
        config: HA Boss configuration
        notification_manager: Shared NotificationManager (must be the same
            instance used by the service's action handler so dedup state is shared).

    Returns:
        Initialized notification escalator
    """
    return NotificationEscalator(config, notification_manager)
