"""Notification escalation for healing failures."""

import logging
from datetime import datetime
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.exceptions import HealingFailedError
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.monitoring.health_monitor import HealthIssue

logger = logging.getLogger(__name__)


class NotificationEscalator:
    """Handles notification escalation when healing fails.

    Creates persistent notifications in Home Assistant UI to alert users
    about issues that require manual intervention.
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
        self.ha_client = ha_client

        # Track sent notifications to avoid spam
        # entity_id -> notification_id
        self._sent_notifications: dict[str, str] = {}

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

        entity_id = health_issue.entity_id
        issue_type = health_issue.issue_type

        # Format message
        message = self._format_healing_failure_message(
            entity_id=entity_id,
            issue_type=issue_type,
            error=error,
            attempts=attempts,
            detected_at=health_issue.detected_at,
        )

        # Create notification
        notification_id = f"haboss_healing_failure_{entity_id.replace('.', '_')}"
        await self._send_notification(
            title="HA Boss: Healing Failed",
            message=message,
            notification_id=notification_id,
        )

        # Track sent notification
        self._sent_notifications[entity_id] = notification_id

        logger.info(f"Sent healing failure notification for {entity_id}")

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
        # Format message
        message = self._format_recovery_message(
            entity_id=entity_id,
            previous_issue_type=previous_issue_type,
        )

        # Dismiss previous failure notification if it exists
        if entity_id in self._sent_notifications:
            old_notification_id = self._sent_notifications[entity_id]
            try:
                await self.ha_client.call_service(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": old_notification_id},
                )
                logger.debug(f"Dismissed previous notification for {entity_id}")
            except Exception as e:
                logger.warning(f"Failed to dismiss notification: {e}")

            del self._sent_notifications[entity_id]

        # Send recovery notification
        notification_id = f"haboss_recovery_{entity_id.replace('.', '_')}"
        await self._send_notification(
            title="HA Boss: Entity Recovered",
            message=message,
            notification_id=notification_id,
        )

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
        message = self._format_circuit_breaker_message(
            integration_name=integration_name,
            failure_count=failure_count,
            reset_time=reset_time,
        )

        notification_id = f"haboss_circuit_breaker_{integration_name.replace(' ', '_').lower()}"
        await self._send_notification(
            title="HA Boss: Circuit Breaker Opened",
            message=message,
            notification_id=notification_id,
        )

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

        message = self._format_summary_message(stats)

        notification_id = f"haboss_weekly_summary_{datetime.now().strftime('%Y%m%d')}"
        await self._send_notification(
            title="HA Boss: Weekly Summary",
            message=message,
            notification_id=notification_id,
        )

        logger.info("Sent weekly summary notification")

    async def _send_notification(
        self,
        title: str,
        message: str,
        notification_id: str,
    ) -> None:
        """Send persistent notification to Home Assistant.

        Args:
            title: Notification title
            message: Notification message
            notification_id: Unique notification ID
        """
        if self.config.is_dry_run:
            logger.info(f"[DRY RUN] Would send notification: {title}")
            logger.debug(f"[DRY RUN] Message: {message}")
            return

        try:
            await self.ha_client.create_persistent_notification(
                message=message,
                title=title,
                notification_id=notification_id,
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}", exc_info=True)

    def _format_healing_failure_message(
        self,
        entity_id: str,
        issue_type: str,
        error: Exception,
        attempts: int,
        detected_at: datetime,
    ) -> str:
        """Format healing failure message.

        Args:
            entity_id: Entity that failed to heal
            issue_type: Type of issue
            error: Exception that caused failure
            attempts: Number of attempts
            detected_at: When issue was detected

        Returns:
            Formatted message
        """
        time_ago = self._format_time_ago(detected_at)

        lines = [
            f"**Entity:** `{entity_id}`",
            f"**Issue:** {issue_type}",
            f"**Detected:** {time_ago}",
            f"**Attempts:** {attempts}",
            "",
        ]

        # Add error details
        if isinstance(error, HealingFailedError):
            lines.append(f"**Reason:** {error}")
        else:
            lines.append(f"**Error:** {type(error).__name__}: {error}")

        lines.extend(
            [
                "",
                "**Action Required:**",
                "Please investigate and fix the integration manually.",
                "",
                "HA Boss will retry automatically when conditions allow.",
            ]
        )

        return "\n".join(lines)

    def _format_recovery_message(
        self,
        entity_id: str,
        previous_issue_type: str,
    ) -> str:
        """Format recovery message.

        Args:
            entity_id: Entity that recovered
            previous_issue_type: Previous issue type

        Returns:
            Formatted message
        """
        lines = [
            f"**Entity:** `{entity_id}`",
            f"**Previous Issue:** {previous_issue_type}",
            "",
            "The entity has recovered and is now reporting normally.",
            "",
            "No further action needed.",
        ]

        return "\n".join(lines)

    def _format_circuit_breaker_message(
        self,
        integration_name: str,
        failure_count: int,
        reset_time: datetime,
    ) -> str:
        """Format circuit breaker message.

        Args:
            integration_name: Integration name
            failure_count: Number of failures
            reset_time: When circuit breaker resets

        Returns:
            Formatted message
        """
        reset_in = self._format_time_until(reset_time)

        lines = [
            f"**Integration:** {integration_name}",
            f"**Consecutive Failures:** {failure_count}",
            f"**Reset In:** {reset_in}",
            "",
            "Auto-healing has been temporarily disabled for this integration",
            "due to repeated failures.",
            "",
            "**Action Required:**",
            "1. Check Home Assistant logs for error details",
            "2. Fix the integration configuration",
            "3. Manually reload the integration",
            "",
            f"Automatic healing will resume at {reset_time.strftime('%H:%M:%S')}.",
        ]

        return "\n".join(lines)

    def _format_summary_message(
        self,
        stats: dict[str, Any],
    ) -> str:
        """Format weekly summary message.

        Args:
            stats: Summary statistics

        Returns:
            Formatted message
        """
        lines = [
            "**Weekly Healing Summary**",
            "",
            f"**Total Attempts:** {stats.get('total_attempts', 0)}",
            f"**Successful:** {stats.get('successful', 0)}",
            f"**Failed:** {stats.get('failed', 0)}",
            f"**Success Rate:** {stats.get('success_rate', 0):.1f}%",
            f"**Avg Duration:** {stats.get('avg_duration_seconds', 0):.2f}s",
            "",
        ]

        # Add top issues if available
        if "top_issues" in stats:
            lines.append("**Most Common Issues:**")
            for entity_id, count in stats["top_issues"][:5]:
                lines.append(f"- `{entity_id}`: {count} times")
            lines.append("")

        lines.append("Keep up the good work maintaining your Home Assistant instance!")

        return "\n".join(lines)

    def _format_time_ago(self, dt: datetime) -> str:
        """Format datetime as time ago string.

        Args:
            dt: Datetime to format

        Returns:
            Human-readable time ago string
        """
        from datetime import UTC

        now = datetime.now(UTC)
        delta = now - dt

        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = delta.days
            return f"{days} day{'s' if days != 1 else ''} ago"

    def _format_time_until(self, dt: datetime) -> str:
        """Format datetime as time until string.

        Args:
            dt: Datetime to format

        Returns:
            Human-readable time until string
        """
        from datetime import UTC

        now = datetime.now(UTC)
        delta = dt - now

        if delta.total_seconds() < 60:
            return "less than a minute"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days} day{'s' if days != 1 else ''}"


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
