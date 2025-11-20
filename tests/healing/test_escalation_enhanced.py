"""Tests for enhanced notification escalation with AI analysis."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import Config, NotificationsConfig
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.intelligence.llm_router import LLMRouter
from ha_boss.monitoring.health_monitor import HealthIssue
from ha_boss.notifications import NotificationContext


@pytest.fixture
def mock_config():
    """Create mock config with AI enhancements enabled."""
    config = MagicMock(spec=Config)
    config.notifications = MagicMock(spec=NotificationsConfig)
    config.notifications.on_healing_failure = True
    config.notifications.weekly_summary = True
    config.notifications.ai_enhanced = True
    config.mode = "production"
    config.is_dry_run = False
    return config


@pytest.fixture
def mock_config_ai_disabled():
    """Create mock config with AI enhancements disabled."""
    config = MagicMock(spec=Config)
    config.notifications = MagicMock(spec=NotificationsConfig)
    config.notifications.on_healing_failure = True
    config.notifications.weekly_summary = True
    config.notifications.ai_enhanced = False
    config.mode = "production"
    config.is_dry_run = False
    return config


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    return MagicMock()


@pytest.fixture
def mock_llm_router():
    """Create mock LLM router."""
    router = MagicMock(spec=LLMRouter)
    router.generate = AsyncMock(
        return_value="ANALYSIS:\nTest analysis\n\nSUGGESTIONS:\n1. Test suggestion"
    )
    return router


@pytest.fixture
def health_issue():
    """Create test health issue."""
    return HealthIssue(
        entity_id="sensor.test_sensor",
        issue_type="unavailable",
        detected_at=datetime.now(UTC),
        details={},
    )


@pytest.mark.asyncio
async def test_escalator_with_ai_enabled(mock_config, mock_ha_client, mock_llm_router):
    """Test that escalator creates enhanced generator when AI enabled."""
    escalator = NotificationEscalator(mock_config, mock_ha_client, mock_llm_router)

    assert escalator.enhanced_generator is not None


@pytest.mark.asyncio
async def test_escalator_without_llm_router(mock_config, mock_ha_client):
    """Test that escalator works without LLM router."""
    escalator = NotificationEscalator(mock_config, mock_ha_client, None)

    assert escalator.enhanced_generator is None


@pytest.mark.asyncio
async def test_escalator_ai_disabled_in_config(
    mock_config_ai_disabled, mock_ha_client, mock_llm_router
):
    """Test that escalator doesn't create generator when AI disabled in config."""
    escalator = NotificationEscalator(mock_config_ai_disabled, mock_ha_client, mock_llm_router)

    assert escalator.enhanced_generator is None


@pytest.mark.asyncio
async def test_notify_healing_failure_with_ai_analysis(
    mock_config, mock_ha_client, mock_llm_router, health_issue
):
    """Test that healing failure notification includes AI analysis."""
    escalator = NotificationEscalator(mock_config, mock_ha_client, mock_llm_router)

    # Mock notification manager
    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        await escalator.notify_healing_failure(
            health_issue=health_issue,
            error=Exception("Test error"),
            attempts=3,
            healing_stats={"success_rate": 50.0, "total_attempts": 10},
            integration_info={"domain": "test", "title": "Test Integration"},
        )

        # Verify notification was sent
        mock_nm.notify.assert_called_once()

        # Check that context includes AI analysis
        context = mock_nm.notify.call_args[0][0]
        assert isinstance(context, NotificationContext)
        assert context.extra is not None
        assert "ai_analysis" in context.extra


@pytest.mark.asyncio
async def test_notify_healing_failure_without_ai(
    mock_config_ai_disabled, mock_ha_client, health_issue
):
    """Test that healing failure works without AI enhancement."""
    escalator = NotificationEscalator(mock_config_ai_disabled, mock_ha_client, None)

    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        await escalator.notify_healing_failure(
            health_issue=health_issue,
            error=Exception("Test error"),
            attempts=3,
        )

        # Verify notification was sent
        mock_nm.notify.assert_called_once()

        # Check that context doesn't have AI analysis
        context = mock_nm.notify.call_args[0][0]
        assert context.extra is None


@pytest.mark.asyncio
async def test_notify_healing_failure_ai_generation_fails(
    mock_config, mock_ha_client, mock_llm_router, health_issue
):
    """Test graceful fallback when AI generation fails."""
    # Make LLM return None (failure)
    mock_llm_router.generate.return_value = None

    escalator = NotificationEscalator(mock_config, mock_ha_client, mock_llm_router)

    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        await escalator.notify_healing_failure(
            health_issue=health_issue,
            error=Exception("Test error"),
            attempts=3,
        )

        # Notification should still be sent
        mock_nm.notify.assert_called_once()

        # Context should not have AI analysis (generation failed)
        context = mock_nm.notify.call_args[0][0]
        assert context.extra is None


@pytest.mark.asyncio
async def test_notify_circuit_breaker_with_ai_analysis(
    mock_config, mock_ha_client, mock_llm_router
):
    """Test that circuit breaker notification includes AI analysis."""
    escalator = NotificationEscalator(mock_config, mock_ha_client, mock_llm_router)

    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        reset_time = datetime.now(UTC) + timedelta(hours=1)

        await escalator.notify_circuit_breaker_open(
            integration_name="Test Integration",
            failure_count=10,
            reset_time=reset_time,
            healing_stats={"success_rate": 20.0, "total_attempts": 50},
        )

        # Verify notification was sent
        mock_nm.notify.assert_called_once()

        # Check that context includes AI analysis
        context = mock_nm.notify.call_args[0][0]
        assert context.extra is not None
        assert "ai_analysis" in context.extra


@pytest.mark.asyncio
async def test_notify_circuit_breaker_without_ai(mock_config_ai_disabled, mock_ha_client):
    """Test circuit breaker notification without AI enhancement."""
    escalator = NotificationEscalator(mock_config_ai_disabled, mock_ha_client, None)

    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        reset_time = datetime.now(UTC) + timedelta(hours=1)

        await escalator.notify_circuit_breaker_open(
            integration_name="Test Integration",
            failure_count=10,
            reset_time=reset_time,
        )

        # Notification should still be sent
        mock_nm.notify.assert_called_once()

        # Context should not have AI analysis
        context = mock_nm.notify.call_args[0][0]
        assert context.extra is None


@pytest.mark.asyncio
async def test_notify_healing_failure_disabled(
    mock_config, mock_ha_client, mock_llm_router, health_issue
):
    """Test that notifications respect disabled setting."""
    mock_config.notifications.on_healing_failure = False

    escalator = NotificationEscalator(mock_config, mock_ha_client, mock_llm_router)

    with patch.object(escalator, "notification_manager") as mock_nm:
        mock_nm.notify = AsyncMock()

        await escalator.notify_healing_failure(
            health_issue=health_issue,
            error=Exception("Test error"),
            attempts=3,
        )

        # Notification should NOT be sent
        mock_nm.notify.assert_not_called()

        # LLM should NOT be called
        mock_llm_router.generate.assert_not_called()
