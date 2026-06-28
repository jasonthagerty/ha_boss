"""Tests for notification templates."""

from datetime import UTC, datetime, timedelta

import pytest

from ha_boss.notifications.templates import (
    ActionVerificationFailedTemplate,
    ConnectionErrorTemplate,
    IssueDetectedTemplate,
    NotificationContext,
    NotificationSeverity,
    NotificationTemplate,
    NotificationType,
    OutOfScopeAuditTemplate,
    TemplateRegistry,
)


class TestNotificationTemplate:
    """Tests for NotificationTemplate base class."""

    def test_format_time_ago_just_now(self) -> None:
        """Test time ago formatting for recent times."""
        now = datetime.now(UTC)
        result = NotificationTemplate.format_time_ago(now)
        assert result == "just now"

    def test_format_time_ago_minutes(self) -> None:
        """Test time ago formatting for minutes."""
        dt = datetime.now(UTC) - timedelta(minutes=5)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "5 minutes ago"

    def test_format_time_ago_one_minute(self) -> None:
        """Test time ago formatting for one minute."""
        dt = datetime.now(UTC) - timedelta(minutes=1)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "1 minute ago"

    def test_format_time_ago_hours(self) -> None:
        """Test time ago formatting for hours."""
        dt = datetime.now(UTC) - timedelta(hours=3)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "3 hours ago"

    def test_format_time_ago_one_hour(self) -> None:
        """Test time ago formatting for one hour."""
        dt = datetime.now(UTC) - timedelta(hours=1)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "1 hour ago"

    def test_format_time_ago_days(self) -> None:
        """Test time ago formatting for days."""
        dt = datetime.now(UTC) - timedelta(days=2)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "2 days ago"

    def test_format_time_ago_one_day(self) -> None:
        """Test time ago formatting for one day."""
        dt = datetime.now(UTC) - timedelta(days=1)
        result = NotificationTemplate.format_time_ago(dt)
        assert result == "1 day ago"

    def test_format_time_ago_naive_datetime(self) -> None:
        """Test time ago formatting with naive datetime."""
        dt = datetime.now() - timedelta(minutes=5)
        result = NotificationTemplate.format_time_ago(dt)
        # Should handle naive datetime and return a reasonable time ago string
        assert result in [
            "just now",
            "5 minutes ago",
            "4 minutes ago",
            "6 minutes ago",
            "6 hours ago",
        ]

    def test_format_time_until_less_than_minute(self) -> None:
        """Test time until formatting for very soon."""
        dt = datetime.now(UTC) + timedelta(seconds=30)
        result = NotificationTemplate.format_time_until(dt)
        assert result == "less than a minute"

    def test_format_time_until_minutes(self) -> None:
        """Test time until formatting for minutes."""
        dt = datetime.now(UTC) + timedelta(minutes=10)
        result = NotificationTemplate.format_time_until(dt)
        # Allow for small timing differences due to test execution
        assert result in ["9 minutes", "10 minutes"]

    def test_format_time_until_hours(self) -> None:
        """Test time until formatting for hours."""
        dt = datetime.now(UTC) + timedelta(hours=2)
        result = NotificationTemplate.format_time_until(dt)
        # Allow for small timing differences due to test execution
        assert result in ["1 hour", "2 hours"]

    def test_format_time_until_days(self) -> None:
        """Test time until formatting for days."""
        dt = datetime.now(UTC) + timedelta(days=3)
        result = NotificationTemplate.format_time_until(dt)
        # Allow for small timing differences due to test execution
        assert result in ["2 days", "3 days"]

    def test_render_not_implemented(self) -> None:
        """Test that base class render raises NotImplementedError."""
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
        )
        with pytest.raises(NotImplementedError):
            NotificationTemplate.render(context)


class TestIssueDetectedTemplate:
    """Tests for IssueDetectedTemplate."""

    def test_render_basic(self) -> None:
        """Test rendering an issue-detected notification."""
        context = NotificationContext(
            notification_type=NotificationType.ISSUE_DETECTED,
            severity=NotificationSeverity.WARNING,
            entity_id="binary_sensor.back_patio_motion",
            issue_type="unavailable",
            detected_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        title, message = IssueDetectedTemplate.render(context)

        # Friendly derived name + state in the title
        assert "Back Patio Motion" in title
        assert "unavailable" in title
        assert "binary_sensor.back_patio_motion" in message
        assert "5 minutes ago" in message
        assert "acknowledge" in message.lower()

    def test_render_minimal(self) -> None:
        """Test rendering without optional detected_at."""
        context = NotificationContext(
            notification_type=NotificationType.ISSUE_DETECTED,
            severity=NotificationSeverity.WARNING,
            entity_id="sensor.test",
        )

        title, message = IssueDetectedTemplate.render(context)

        assert "sensor.test" in message
        # issue_type defaults to unavailable
        assert "unavailable" in title.lower()


class TestConnectionErrorTemplate:
    """Tests for ConnectionErrorTemplate."""

    def test_render_basic(self) -> None:
        """Test connection error rendering."""
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
            error="Connection refused",
        )

        title, message = ConnectionErrorTemplate.render(context)

        assert title == "HA Boss: Connection Error"
        assert "Connection refused" in message
        assert "Home Assistant" in message
        assert "reconnect" in message.lower()

    def test_render_without_error(self) -> None:
        """Test connection error without error message."""
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
        )

        title, message = ConnectionErrorTemplate.render(context)

        assert title == "HA Boss: Connection Error"
        assert "reconnect" in message.lower()


class TestOutOfScopeAuditTemplate:
    """Tests for OutOfScopeAuditTemplate."""

    def test_render_basic(self) -> None:
        """Test basic out-of-scope audit rendering with new failures."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={
                "new_failures": [
                    {
                        "entity_id": "sensor.garage_temp",
                        "state": "unavailable",
                        "group": "zigbee2mqtt",
                    },
                    {
                        "entity_id": "light.porch",
                        "state": "unknown",
                        "group": "hue",
                    },
                ],
                "chronic_count": 0,
                "total_out_of_scope": 100,
            },
        )

        title, message = OutOfScopeAuditTemplate.render(context)

        assert "Out-of-Scope Audit" in title
        assert "sensor.garage_temp" in message
        assert "light.porch" in message
        assert "zigbee2mqtt" in message
        assert "hue" in message
        assert "100" in message

    def test_render_with_chronic_count(self) -> None:
        """Test rendering includes chronic suppression line when count > 0."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={
                "new_failures": [
                    {"entity_id": "sensor.x", "state": "unavailable", "group": "sensor"},
                ],
                "chronic_count": 5,
                "total_out_of_scope": 200,
            },
        )

        title, message = OutOfScopeAuditTemplate.render(context)

        assert "5 chronic" in message
        assert "suppressed" in message

    def test_render_no_failures(self) -> None:
        """Test rendering when there are no new or chronic failures."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={
                "new_failures": [],
                "chronic_count": 0,
                "total_out_of_scope": 30,
            },
        )

        title, message = OutOfScopeAuditTemplate.render(context)

        assert "No new unavailable" in message

    def test_render_groups_entities_by_integration(self) -> None:
        """Test that entities are grouped by integration in the rendered output."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={
                "new_failures": [
                    {"entity_id": "light.a", "state": "unavailable", "group": "hue"},
                    {"entity_id": "light.b", "state": "unavailable", "group": "hue"},
                    {"entity_id": "sensor.c", "state": "unavailable", "group": "zwave"},
                ],
                "chronic_count": 0,
                "total_out_of_scope": 10,
            },
        )

        title, message = OutOfScopeAuditTemplate.render(context)

        # Both hue entities should appear under the hue group
        assert "hue" in message
        assert "light.a" in message
        assert "light.b" in message
        assert "zwave" in message
        assert "sensor.c" in message

    def test_render_empty_stats(self) -> None:
        """Test rendering with minimal/empty stats dict."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={},
        )

        title, message = OutOfScopeAuditTemplate.render(context)

        assert "Out-of-Scope Audit" in title
        # Should not crash; returns a sensible default
        assert message


class TestTemplateRegistry:
    """Tests for TemplateRegistry."""

    def test_render_issue_detected(self) -> None:
        """Test registry renders issue detected correctly."""
        context = NotificationContext(
            notification_type=NotificationType.ISSUE_DETECTED,
            severity=NotificationSeverity.WARNING,
            entity_id="sensor.test",
            issue_type="stale",
        )

        title, message = TemplateRegistry.render(context)

        assert title  # pretty title with friendly name + state
        assert "sensor.test" in message

    def test_render_connection_error(self) -> None:
        """Test registry renders connection error correctly."""
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Connection Error"

    def test_render_out_of_scope_audit(self) -> None:
        """Test registry renders out-of-scope audit correctly."""
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            stats={
                "new_failures": [
                    {"entity_id": "light.garage", "state": "unavailable", "group": "hue"},
                ],
                "chronic_count": 2,
                "total_out_of_scope": 50,
            },
        )

        title, message = TemplateRegistry.render(context)

        assert "Out-of-Scope Audit" in title
        assert "light.garage" in message
        assert "hue" in message
        assert "2 chronic" in message


class TestActionVerificationFailedTemplate:
    """Tests for ActionVerificationFailedTemplate."""

    def _make_context(
        self,
        entity_id: str = "light.bedroom",
        service: str = "light.turn_off",
        expected_state: str = "off",
        actual_state: str = "on",
        delay_seconds: int = 30,
    ) -> NotificationContext:
        return NotificationContext(
            notification_type=NotificationType.ACTION_VERIFICATION_FAILED,
            severity=NotificationSeverity.WARNING,
            entity_id=entity_id,
            extra={
                "service": service,
                "expected_state": expected_state,
                "actual_state": actual_state,
                "delay_seconds": delay_seconds,
            },
        )

    def test_title(self) -> None:
        """Template title carries the friendly name and a 'didn't respond' phrasing."""
        context = self._make_context()
        title, _ = ActionVerificationFailedTemplate.render(context)
        assert "Bedroom" in title
        assert "respond" in title.lower()

    def test_body_contains_entity_id(self) -> None:
        """Rendered body contains the target entity ID."""
        context = self._make_context(entity_id="switch.outlet")
        _, message = ActionVerificationFailedTemplate.render(context)
        assert "switch.outlet" in message

    def test_body_contains_service(self) -> None:
        """Rendered body contains the service that was called."""
        context = self._make_context(service="switch.turn_off")
        _, message = ActionVerificationFailedTemplate.render(context)
        assert "switch.turn_off" in message

    def test_body_contains_expected_and_actual_state(self) -> None:
        """Rendered body contains both expected and actual state."""
        context = self._make_context(expected_state="off", actual_state="on")
        _, message = ActionVerificationFailedTemplate.render(context)
        assert "off" in message
        assert "on" in message

    def test_body_contains_delay_seconds(self) -> None:
        """Rendered body contains the delay in seconds."""
        context = self._make_context(delay_seconds=45)
        _, message = ActionVerificationFailedTemplate.render(context)
        assert "45" in message

    def test_render_with_missing_extra_does_not_crash(self) -> None:
        """Rendering with no extra dict falls back to 'unknown' values gracefully."""
        context = NotificationContext(
            notification_type=NotificationType.ACTION_VERIFICATION_FAILED,
            severity=NotificationSeverity.WARNING,
            entity_id="light.bedroom",
            extra=None,
        )
        title, message = ActionVerificationFailedTemplate.render(context)
        assert "Bedroom" in title
        assert message  # Should not crash

    def test_registered_in_template_registry(self) -> None:
        """ActionVerificationFailedTemplate is registered and renders via TemplateRegistry."""
        context = NotificationContext(
            notification_type=NotificationType.ACTION_VERIFICATION_FAILED,
            severity=NotificationSeverity.WARNING,
            entity_id="light.bedroom",
            extra={
                "service": "light.turn_off",
                "expected_state": "off",
                "actual_state": "on",
                "delay_seconds": 30,
            },
        )
        title, message = TemplateRegistry.render(context)
        assert title  # pretty title
        assert "light.bedroom" in message
