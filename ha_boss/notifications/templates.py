"""Notification message templates for various alert types."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class NotificationType(StrEnum):
    """Types of notifications that can be sent."""

    CONNECTION_ERROR = "connection_error"
    ISSUE_DETECTED = "issue_detected"
    OUT_OF_SCOPE_AUDIT = "out_of_scope_audit"
    ACTION_VERIFICATION_FAILED = "action_verification_failed"


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
    friendly_name: str | None = None
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


_SEVERITY_EMOJI: dict[NotificationSeverity, str] = {
    NotificationSeverity.INFO: "ℹ️",
    NotificationSeverity.WARNING: "⚠️",
    NotificationSeverity.ERROR: "🛑",
    NotificationSeverity.CRITICAL: "🚨",
}

# Human-readable phrasing for the common issue types.
_ISSUE_PHRASING: dict[str, str] = {
    "unavailable": "is unavailable",
    "unknown": "is in an unknown state",
    "stale": "stopped updating",
}


def display_name(context: NotificationContext) -> str:
    """Return a human-friendly name for the entity in a notification.

    Prefers the entity's ``friendly_name``; otherwise derives a readable name
    from the entity_id (e.g. ``sensor.back_patio_motion`` -> "Back Patio Motion").
    """
    if context.friendly_name:
        return context.friendly_name
    if context.entity_id:
        object_id = context.entity_id.split(".", 1)[-1]
        return object_id.replace("_", " ").title()
    return "Entity"


def severity_emoji(severity: NotificationSeverity) -> str:
    """Return the emoji for a severity level."""
    return _SEVERITY_EMOJI.get(severity, "")


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


class IssueDetectedTemplate(NotificationTemplate):
    """Template for issue-detected notifications (monitor-and-notify mode)."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render issue-detected notification.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        name = display_name(context)
        issue = context.issue_type or "unavailable"
        phrasing = _ISSUE_PHRASING.get(issue, f"has an issue ({issue})")
        title = f"{severity_emoji(context.severity)} {name} {phrasing}".strip()

        lines = [f"**{name}** (`{context.entity_id}`)"]

        if context.detected_at:
            time_ago = IssueDetectedTemplate.format_time_ago(context.detected_at)
            lines.append(f"Status: **{issue}** since {time_ago}.")
        else:
            lines.append(f"Status: **{issue}**.")

        lines.extend(
            [
                "",
                "Long-press this notification to acknowledge it.",
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


class OutOfScopeAuditTemplate(NotificationTemplate):
    """Template for out-of-scope entity audit digest notifications."""

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render out-of-scope audit digest notification.

        Expects the following keys in ``context.stats``:

        - ``new_failures`` (list[dict]): Each dict has ``entity_id``, ``state``,
          ``group`` (integration/domain), and ``first_unavailable_at`` (ISO string).
        - ``chronic_count`` (int): Number of entities suppressed as chronic.
        - ``total_out_of_scope`` (int): Total out-of-scope entity count.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        title = "🗂️ HA Boss: Out-of-Scope Audit"
        stats = context.stats or {}

        new_failures: list[dict[str, Any]] = stats.get("new_failures", [])
        chronic_count: int = stats.get("chronic_count", 0)
        total_out_of_scope: int = stats.get("total_out_of_scope", 0)

        lines: list[str] = [
            f"**Out-of-Scope Entity Audit** ({total_out_of_scope} total unmonitored)",
            "",
        ]

        if new_failures:
            # Group failures by integration/domain
            groups: dict[str, list[dict[str, Any]]] = {}
            for failure in new_failures:
                group = failure.get("group", "unknown")
                groups.setdefault(group, []).append(failure)

            lines.append("**New Unavailable Entities:**")
            for group_name, entities in sorted(groups.items()):
                lines.append(f"  **{group_name}** ({len(entities)}):")
                for entity in entities:
                    state = entity.get("state", "unavailable")
                    entity_id = entity.get("entity_id", "unknown")
                    lines.append(f"    - `{entity_id}` ({state})")
            lines.append("")

        if chronic_count > 0:
            lines.append(
                f"*{chronic_count} chronically-unavailable "
                f"{'entity' if chronic_count == 1 else 'entities'} suppressed "
                f"(already reported, still unavailable).*"
            )
            lines.append("")

        if not new_failures and chronic_count == 0:
            lines.append("No new unavailable entities detected.")
            lines.append("")

        lines.append("HA Boss monitors only entities referenced by automations/scenes/scripts.")
        lines.append("These entities are outside that monitored set.")

        message = "\n".join(lines)
        return title, message


class ActionVerificationFailedTemplate(NotificationTemplate):
    """Template for action-verification-failed notifications.

    Fired when a state-changing service call did not produce the expected entity
    state within the configured delay window.
    """

    @staticmethod
    def render(context: NotificationContext) -> tuple[str, str]:
        """Render action-verification-failed notification.

        Expects the following keys in ``context.extra``:

        - ``service`` (str): Full service name that was called, e.g. ``"light.turn_off"``.
        - ``expected_state`` (str): The state the entity was expected to reach.
        - ``actual_state`` (str): The state the entity actually has.
        - ``delay_seconds`` (int): How many seconds elapsed before the check ran.

        ``context.entity_id`` must be the target entity ID.

        Args:
            context: Notification context

        Returns:
            Tuple of (title, message)
        """
        name = display_name(context)
        extra = context.extra or {}
        service = extra.get("service", "unknown service")
        expected_state = extra.get("expected_state", "unknown")
        actual_state = extra.get("actual_state", "unknown")
        delay_seconds = extra.get("delay_seconds", 0)

        title = f"{severity_emoji(context.severity)} {name} didn't respond".strip()

        lines = [
            f"**{name}** (`{context.entity_id}`)",
            f"`{service}` expected **{expected_state}** but it's still **{actual_state}** "
            f"after {delay_seconds}s.",
            "",
            "Long-press this notification to acknowledge it.",
        ]

        message = "\n".join(lines)
        return title, message


class TemplateRegistry:
    """Registry for mapping notification types to templates."""

    _templates: dict[NotificationType, type[NotificationTemplate]] = {
        NotificationType.CONNECTION_ERROR: ConnectionErrorTemplate,
        NotificationType.ISSUE_DETECTED: IssueDetectedTemplate,
        NotificationType.OUT_OF_SCOPE_AUDIT: OutOfScopeAuditTemplate,
        NotificationType.ACTION_VERIFICATION_FAILED: ActionVerificationFailedTemplate,
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
