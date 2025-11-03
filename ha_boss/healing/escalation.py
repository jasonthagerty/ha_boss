"""Notification escalation for healing failures."""

import logging
from datetime import datetime
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.monitoring.health_monitor import HealthIssue
from ha_boss.notifications import (
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
    ) -> None:
        """Send notification about healing failure.

        Args:
            health_issue: Health issue that couldn't be healed
            error: Exception that caused healing to fail
            attempts: Number of healing attempts made
        """
        if not self.config.notifications.on_healing_failure:
            logger.debug("Healing failure notifications are disabled")
            return

        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id=health_issue.entity_id,
            issue_type=health_issue.issue_type,
            error=error,
            attempts=attempts,
            detected_at=health_issue.detected_at,
        )

        await self.notification_manager.notify(context)
        logger.info(f"Sent healing failure notification for {health_issue.entity_id}")

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

        # Send recovery notification
        context = NotificationContext(
            notification_type=NotificationType.RECOVERY,
            severity=NotificationSeverity.INFO,
            entity_id=entity_id,
            issue_type=previous_issue_type,
        )

        await self.notification_manager.notify(context)
        logger.info(f"Sent recovery notification for {entity_id}")

    async def notify_circuit_breaker_open(
        self,
        integration_name: str,
        failure_count: int,
        reset_time: datetime,
    ) -> None:
        """Send notification about circuit breaker opening.

        Args:
            integration_name: Integration that has circuit breaker open
            failure_count: Number of consecutive failures
            reset_time: When circuit breaker will reset
        """
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_name=integration_name,
            failure_count=failure_count,
            reset_time=reset_time,
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
