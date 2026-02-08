"""Notification message templates for various alert types."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class NotificationType(StrEnum):
    """Types of notifications that can be sent."""

    HEALING_FAILURE = "healing_failure"
    HEALING_SUCCESS = "healing_success"
    CIRCUIT_BREAKER = "circuit_breaker"
    CONNECTION_ERROR = "connection_error"
    WEEKLY_SUMMARY = "weekly_summary"
    RECOVERY = "recovery"
    ANOMALY_DETECTED = "anomaly_detected"


class NotificationSeverity(StrEnum):
    """Severity levels for notifications."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class NotificationContext:
    """Context data for rendering notification templates.

    Attributes:
        notification_type: Type of notification
        severity: Notification severity level
        entity_id: Optional entity ID related to the notification
        integration_name: Optional integration name
        integration_id: Optional integration entry ID
        issue_type: Optional issue type (e.g., "unavailable", "stale")
        error: Optional error message or exception
        attempts: Optional number of attempts made
        detected_at: Optional datetime when issue was detected
        failure_count: Optional consecutive failure count
        reset_time: Optional reset time for circuit breaker
        stats: Optional statistics dictionary
        extra: Additional context-specific data
    """

    notification_type: NotificationType
    severity: NotificationSeverity
    entity_id: str | None = None
    integration_name: str | None = None
    integration_id: str | None = None
    issue_type: str | None = None
    error: str | Exception | None = None
    attempts: int | None = None
    detected_at: datetime | None = None
    failure_count: int | None = None
    reset_time: datetime | None = None
    stats: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class NotificationTemplate:
    """Base class for notification templates."""

    @staticmethod
    def format_time_ago(dt: datetime) -> str:
        """Format datetime as time ago string.

        Args:
            dt: Datetime to format

        Returns:
            Human-readable time ago string
        """
        now = datetime.now(UTC)
        # Handle naive datetimes by adding UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

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

    @staticmethod
    def format_time_until(dt: datetime) -> str:
        """Format datetime as time until string.

        Args:
            dt: Datetime to format

        Returns:
            Human-readable time until string
        """
        now = datetime.now(UTC)
        # Handle naive datetimes by adding UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

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

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render notification title and message.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        raise NotImplementedError("Subclasses must implement render()")


class HealingFailureTemplate(NotificationTemplate):
    """Template for healing failure notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render healing failure notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Healing Failed"

        lines = [
            f"**Entity:** `{context.entity_id}`",
            f"**Issue:** {context.issue_type or 'Unknown'}",
        ]

        if context.detected_at:
            time_ago = HealingFailureTemplate.format_time_ago(context.detected_at)
            lines.append(f"**Detected:** {time_ago}")

        if context.attempts:
            lines.append(f"**Attempts:** {context.attempts}")

        lines.append("")

        # Add error details
        if context.error:
            if isinstance(context.error, Exception):
                lines.append(f"**Error:** {type(context.error).__name__}: {context.error}")
            else:
                lines.append(f"**Error:** {context.error}")

        # Check for AI-enhanced content
        if context.extra and "ai_analysis" in context.extra:
            ai_data = context.extra["ai_analysis"]
            lines.append("")
            lines.append("**AI Analysis:**")
            if ai_data.get("analysis"):
                lines.append(ai_data["analysis"])

            if ai_data.get("suggestions"):
                lines.append("")
                lines.append("**Suggested Actions:**")
                lines.append(ai_data["suggestions"])
        else:
            # Standard action required message
            lines.extend(
                [
                    "",
                    "**Action Required:**",
                    "Please investigate and fix the integration manually.",
                ]
            )

        lines.extend(
            [
                "",
                "HA Boss will retry automatically when conditions allow.",
            ]
        )

        message = "\n".join(lines)
        return title, message


class HealingSuccessTemplate(NotificationTemplate):
    """Template for healing success notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render healing success notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Healing Successful"

        lines = [
            f"**Entity:** `{context.entity_id}`",
            f"**Integration:** {context.integration_name or context.integration_id or 'Unknown'}",
            "",
            "Successfully healed the integration.",
        ]

        if context.attempts:
            lines.append(f"Attempts: {context.attempts}")

        message = "\n".join(lines)
        return title, message


class RecoveryTemplate(NotificationTemplate):
    """Template for entity recovery notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render recovery notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Entity Recovered"

        lines = [
            f"**Entity:** `{context.entity_id}`",
            f"**Previous Issue:** {context.issue_type or 'Unknown'}",
            "",
            "The entity has recovered and is now reporting normally.",
            "",
            "No further action needed.",
        ]

        message = "\n".join(lines)
        return title, message


class CircuitBreakerTemplate(NotificationTemplate):
    """Template for circuit breaker notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render circuit breaker notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Circuit Breaker Opened"

        lines = [
            f"**Integration:** {context.integration_name or context.integration_id or 'Unknown'}",
            f"**Consecutive Failures:** {context.failure_count or 0}",
        ]

        if context.reset_time:
            reset_in = CircuitBreakerTemplate.format_time_until(context.reset_time)
            lines.append(f"**Reset In:** {reset_in}")
            reset_at = context.reset_time.strftime("%H:%M:%S")
        else:
            reset_at = "unknown"

        lines.extend(
            [
                "",
                "Auto-healing has been temporarily disabled for this integration",
                "due to repeated failures.",
            ]
        )

        # Check for AI-enhanced content
        if context.extra and "ai_analysis" in context.extra:
            ai_data = context.extra["ai_analysis"]
            lines.append("")
            lines.append("**AI Analysis:**")
            if ai_data.get("analysis"):
                lines.append(ai_data["analysis"])

            if ai_data.get("suggestions"):
                lines.append("")
                lines.append("**Suggested Actions:**")
                lines.append(ai_data["suggestions"])
        else:
            # Standard action required message
            lines.extend(
                [
                    "",
                    "**Action Required:**",
                    "1. Check Home Assistant logs for error details",
                    "2. Fix the integration configuration",
                    "3. Manually reload the integration",
                ]
            )

        lines.extend(
            [
                "",
                f"Automatic healing will resume at {reset_at}.",
            ]
        )

        message = "\n".join(lines)
        return title, message


class ConnectionErrorTemplate(NotificationTemplate):
    """Template for connection error notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render connection error notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Connection Error"

        lines = [
            "**Issue:** Cannot connect to Home Assistant",
        ]

        if context.error:
            lines.append(f"**Error:** {context.error}")

        lines.extend(
            [
                "",
                "**Possible Causes:**",
                "- Home Assistant is offline or restarting",
                "- Network connectivity issues",
                "- Invalid access token",
                "",
                "HA Boss will continue attempting to reconnect.",
            ]
        )

        message = "\n".join(lines)
        return title, message


class WeeklySummaryTemplate(NotificationTemplate):
    """Template for weekly summary notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render weekly summary notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Weekly Summary"

        stats = context.stats or {}

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

        message = "\n".join(lines)
        return title, message


class AnomalyDetectedTemplate(NotificationTemplate):
    """Template for anomaly detection notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render anomaly detection notification.

        Args:
            context: Notification context with anomaly details in extra

        Returns:
            Tuple of (title, message)
        """
        title = "HA Boss: Anomaly Detected"

        # Get anomaly data from extra
        anomaly_data = context.extra or {}

        lines = [
            f"**Type:** {anomaly_data.get('anomaly_type', 'Unknown')}",
            f"**Integration:** {context.integration_name or anomaly_data.get('integration_domain', 'Unknown')}",
            f"**Severity:** {anomaly_data.get('severity_label', 'Unknown')}",
        ]

        # Add description
        if anomaly_data.get("description"):
            lines.extend(["", anomaly_data["description"]])

        # Add AI explanation if available
        if anomaly_data.get("ai_explanation"):
            lines.extend(
                [
                    "",
                    "**AI Analysis:**",
                    anomaly_data["ai_explanation"],
                ]
            )

        # Add additional details
        details = anomaly_data.get("details", {})
        if details:
            lines.append("")
            lines.append("**Details:**")
            if "failure_count" in details:
                lines.append(f"- Recent failures: {details['failure_count']}")
            if "rate_increase" in details:
                lines.append(f"- Rate increase: {details['rate_increase']:.1f}x")
            if "correlation" in details:
                lines.append(f"- Correlation: {details['correlation']:.0%}")
            if "concentration" in details:
                lines.append(f"- Time concentration: {details['concentration']:.0%}")

        lines.extend(
            [
                "",
                "Please investigate the integration for potential issues.",
            ]
        )

        message = "\n".join(lines)
        return title, message


class TemplateRegistry:
    """Registry for mapping notification types to templates."""

    _templates: dict[NotificationType, type[NotificationTemplate]] = {
        NotificationType.HEALING_FAILURE: HealingFailureTemplate,
        NotificationType.HEALING_SUCCESS: HealingSuccessTemplate,
        NotificationType.RECOVERY: RecoveryTemplate,
        NotificationType.CIRCUIT_BREAKER: CircuitBreakerTemplate,
        NotificationType.CONNECTION_ERROR: ConnectionErrorTemplate,
        NotificationType.WEEKLY_SUMMARY: WeeklySummaryTemplate,
        NotificationType.ANOMALY_DETECTED: AnomalyDetectedTemplate,
    }

    @classmethod
    def render(cls, context: NotificationContext) -> tuple[str, str]:
        """Render notification using appropriate template.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)

        Raises:
            ValueError: If notification type has no registered template
        """
        template_class = cls._templates.get(context.notification_type)
        if not template_class:
            raise ValueError(f"No template registered for {context.notification_type}")

        return template_class.render(context)
