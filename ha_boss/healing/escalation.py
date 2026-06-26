"""Notification escalation for healing failures."""

import logging
from datetime import datetime
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
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
    """Handles notification escalation when healing fails.

    Wraps NotificationManager to provide healing-specific notification interface.
    Acts as a facade for the notification system with domain-specific methods.
    """

    def __init__(
        self,
        config: Config,
        ha_client: HomeAssistantClient,
    ) -> None:
        """Initialize notification escalator.

        Args:
            config: HA Boss configuration
            ha_client: Home Assistant API client
        """
        self.config = config
        self.notification_manager = NotificationManager(config, ha_client)

    async def notify_healing_failure(
        self,
        health_issue: HealthIssue,
        error: Exception,
        attempts: int,
        healing_stats: dict[str, Any] | None = None,
        integration_info: dict[str, Any] | None = None,
    ) -> None:
        """Send notification about healing failure.

        Args:
            health_issue: Health issue that couldn't be healed
            error: Exception that caused healing to fail
            attempts: Number of healing attempts made
            healing_stats: Optional historical healing statistics
            integration_info: Optional integration details
        """
        if not self.config.notifications.on_healing_failure:
            logger.debug("Healing failure notifications are disabled")
            return

        extra: dict[str, Any] | None = None

        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id=health_issue.entity_id,
            issue_type=health_issue.issue_type,
            error=error,
            attempts=attempts,
            detected_at=health_issue.detected_at,
            extra=extra,
        )

        await self.notification_manager.notify(context)
        logger.info(f"Sent healing failure notification for {health_issue.entity_id}")

    async def notify_issue_detected(
        self,
        health_issue: HealthIssue,
    ) -> None:
        """Send notification about a detected issue without attempting to heal.

        Used for monitor-and-notify operation, where HA Boss reports problems
        (e.g. a stuck or offline sensor) without reloading integrations.

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
        # cannot heal — keep them off mobile push to avoid noise; HA/CLI still get it.
        channels = None
        if health_issue.is_cloud and self.config.monitoring.cloud_handling.suppress_mobile_push:
            channels = [NotificationChannel.CLI, NotificationChannel.HOME_ASSISTANT]
            logger.debug(
                f"Cloud entity {health_issue.entity_id}: suppressing mobile push " "(HA/CLI only)"
            )

        await self.notification_manager.notify(context, channels=channels)
        logger.info(f"Sent issue-detected notification for {health_issue.entity_id}")

    async def notify_recovery(
        self,
        entity_id: str,
        previous_issue_type: str,
    ) -> None:
        """Send notification about entity recovery.

        Args:
            entity_id: Entity that recovered
            previous_issue_type: Type of issue it recovered from
        """
        # Dismiss previous failure notification if it exists
        notification_id = f"haboss_healing_failure_{entity_id.replace('.', '_')}"
        await self.notification_manager.dismiss(notification_id)

        # Dismiss previous issue-detected notification if it exists
        issue_notification_id = f"haboss_issue_detected_{entity_id.replace('.', '_')}"
        await self.notification_manager.dismiss(issue_notification_id)

        # Send recovery notification
        context = NotificationContext(
            notification_type=NotificationType.RECOVERY,
            severity=NotificationSeverity.INFO,
            entity_id=entity_id,
            issue_type=previous_issue_type,
        )

        await self.notification_manager.notify(context)
        logger.info(f"Sent recovery notification for {entity_id}")

    async def dismiss_issue_detected(self, entity_id: str) -> None:
        """Clear a prior issue-detected notification without sending a recovery alert.

        Used by monitor-and-notify mode on recovery: it dismisses the
        issue-detected notification (and re-arms its mobile push) but does NOT
        emit a RECOVERY notification, so a user who only enabled
        ``on_issue_detected`` is not sent recovery alerts they did not configure.

        Args:
            entity_id: Entity that recovered.
        """
        issue_notification_id = f"haboss_issue_detected_{entity_id.replace('.', '_')}"
        await self.notification_manager.dismiss(issue_notification_id)
        logger.debug(f"Cleared issue-detected notification for {entity_id}")

    async def notify_circuit_breaker_open(
        self,
        integration_name: str,
        failure_count: int,
        reset_time: datetime,
        healing_stats: dict[str, Any] | None = None,
    ) -> None:
        """Send notification about circuit breaker opening.

        Args:
            integration_name: Integration that has circuit breaker open
            failure_count: Number of consecutive failures
            reset_time: When circuit breaker will reset
            healing_stats: Optional historical healing statistics
        """
        extra: dict[str, Any] | None = None

        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_name=integration_name,
            failure_count=failure_count,
            reset_time=reset_time,
            extra=extra,
        )

        await self.notification_manager.notify(context)
        logger.info(f"Sent circuit breaker notification for {integration_name}")

    async def notify_summary(
        self,
        stats: dict[str, Any],
    ) -> None:
        """Send weekly summary notification.

        Args:
            stats: Summary statistics
        """
        if not self.config.notifications.weekly_summary:
            logger.debug("Weekly summary notifications are disabled")
            return

        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats=stats,
        )

        await self.notification_manager.notify(context)
        logger.info("Sent weekly summary notification")


async def create_notification_escalator(
    config: Config,
    ha_client: HomeAssistantClient,
) -> NotificationEscalator:
    """Create a notification escalator.

    Args:
        config: HA Boss configuration
        ha_client: Home Assistant API client

    Returns:
        Initialized notification escalator
    """
    return NotificationEscalator(config, ha_client)
