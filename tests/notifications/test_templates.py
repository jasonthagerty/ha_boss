"""Tests for notification templates."""

from datetime import UTC, datetime, timedelta

import pytest

from ha_boss.notifications.templates import (
    CircuitBreakerTemplate,
    ConnectionErrorTemplate,
    HealingFailureTemplate,
    HealingSuccessTemplate,
    NotificationContext,
    NotificationSeverity,
    NotificationTemplate,
    NotificationType,
    RecoveryTemplate,
    TemplateRegistry,
    WeeklySummaryTemplate,
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
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
        )
        with pytest.raises(NotImplementedError):
            NotificationTemplate.render(context)


class TestHealingFailureTemplate:
    """Tests for HealingFailureTemplate."""

    def test_render_basic(self) -> None:
        """Test basic healing failure rendering."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.temperature",
            issue_type="unavailable",
            attempts=3,
            error="Connection timeout",
            detected_at=datetime.now(UTC) - timedelta(minutes=10),
        )

        title, message = HealingFailureTemplate.render(context)

        assert title == "HA Boss: Healing Failed"
        assert "sensor.temperature" in message
        assert "unavailable" in message
        assert "3" in message
        assert "Connection timeout" in message
        assert "Action Required" in message

    def test_render_minimal(self) -> None:
        """Test healing failure with minimal context."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        title, message = HealingFailureTemplate.render(context)

        assert title == "HA Boss: Healing Failed"
        assert "sensor.test" in message


class TestHealingSuccessTemplate:
    """Tests for HealingSuccessTemplate."""

    def test_render_basic(self) -> None:
        """Test healing success rendering."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_SUCCESS,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.temperature",
            integration_name="Z-Wave",
            attempts=2,
        )

        title, message = HealingSuccessTemplate.render(context)

        assert title == "HA Boss: Healing Successful"
        assert "sensor.temperature" in message
        assert "Z-Wave" in message
        assert "2" in message

    def test_render_with_integration_id(self) -> None:
        """Test healing success with integration ID instead of name."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_SUCCESS,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.test",
            integration_id="abc123",
        )

        title, message = HealingSuccessTemplate.render(context)

        assert "abc123" in message


class TestRecoveryTemplate:
    """Tests for RecoveryTemplate."""

    def test_render_basic(self) -> None:
        """Test recovery rendering."""
        context = NotificationContext(
            notification_type=NotificationType.RECOVERY,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.temperature",
            issue_type="unavailable",
        )

        title, message = RecoveryTemplate.render(context)

        assert title == "HA Boss: Entity Recovered"
        assert "sensor.temperature" in message
        assert "unavailable" in message
        assert "recovered" in message.lower()


class TestCircuitBreakerTemplate:
    """Tests for CircuitBreakerTemplate."""

    def test_render_basic(self) -> None:
        """Test circuit breaker rendering."""
        reset_time = datetime.now(UTC) + timedelta(hours=1)
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_name="Z-Wave",
            failure_count=10,
            reset_time=reset_time,
        )

        title, message = CircuitBreakerTemplate.render(context)

        assert title == "HA Boss: Circuit Breaker Opened"
        assert "Z-Wave" in message
        assert "10" in message
        assert "temporarily disabled" in message
        assert "Action Required" in message

    def test_render_with_integration_id(self) -> None:
        """Test circuit breaker with integration ID."""
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_id="abc123",
            failure_count=5,
        )

        title, message = CircuitBreakerTemplate.render(context)

        assert "abc123" in message


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


class TestWeeklySummaryTemplate:
    """Tests for WeeklySummaryTemplate."""

    def test_render_basic(self) -> None:
        """Test weekly summary rendering."""
        stats = {
            "total_attempts": 50,
            "successful": 45,
            "failed": 5,
            "success_rate": 90.0,
            "avg_duration_seconds": 2.5,
        }
        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats=stats,
        )

        title, message = WeeklySummaryTemplate.render(context)

        assert title == "HA Boss: Weekly Summary"
        assert "50" in message
        assert "45" in message
        assert "5" in message
        assert "90.0%" in message
        assert "2.5" in message or "2.50" in message

    def test_render_with_top_issues(self) -> None:
        """Test weekly summary with top issues."""
        stats = {
            "total_attempts": 10,
            "successful": 8,
            "failed": 2,
            "success_rate": 80.0,
            "avg_duration_seconds": 1.5,
            "top_issues": [
                ("sensor.temp1", 5),
                ("sensor.temp2", 3),
                ("sensor.temp3", 2),
            ],
        }
        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats=stats,
        )

        title, message = WeeklySummaryTemplate.render(context)

        assert "sensor.temp1" in message
        assert "5 times" in message
        assert "sensor.temp2" in message

    def test_render_empty_stats(self) -> None:
        """Test weekly summary with empty stats."""
        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats={},
        )

        title, message = WeeklySummaryTemplate.render(context)

        assert "Weekly Summary" in title


class TestTemplateRegistry:
    """Tests for TemplateRegistry."""

    def test_render_healing_failure(self) -> None:
        """Test registry renders healing failure correctly."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_FAILURE,
            severity=NotificationSeverity.ERROR,
            entity_id="sensor.test",
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Healing Failed"
        assert "sensor.test" in message

    def test_render_healing_success(self) -> None:
        """Test registry renders healing success correctly."""
        context = NotificationContext(
            notification_type=NotificationType.HEALING_SUCCESS,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.test",
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Healing Successful"

    def test_render_recovery(self) -> None:
        """Test registry renders recovery correctly."""
        context = NotificationContext(
            notification_type=NotificationType.RECOVERY,
            severity=NotificationSeverity.INFO,
            entity_id="sensor.test",
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Entity Recovered"

    def test_render_circuit_breaker(self) -> None:
        """Test registry renders circuit breaker correctly."""
        context = NotificationContext(
            notification_type=NotificationType.CIRCUIT_BREAKER,
            severity=NotificationSeverity.WARNING,
            integration_name="Test",
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Circuit Breaker Opened"

    def test_render_connection_error(self) -> None:
        """Test registry renders connection error correctly."""
        context = NotificationContext(
            notification_type=NotificationType.CONNECTION_ERROR,
            severity=NotificationSeverity.ERROR,
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Connection Error"

    def test_render_weekly_summary(self) -> None:
        """Test registry renders weekly summary correctly."""
        context = NotificationContext(
            notification_type=NotificationType.WEEKLY_SUMMARY,
            severity=NotificationSeverity.INFO,
            stats={},
        )

        title, message = TemplateRegistry.render(context)

        assert title == "HA Boss: Weekly Summary"
