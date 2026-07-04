"""Tests for the notification-pipeline self-check."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.core.config import Config
from ha_boss.monitoring.self_check import run_self_check
from ha_boss.notifications.manager import NotificationChannel


def _config(**overrides):
    """Build a Config with a valid instance and the given section overrides."""
    data = {"home_assistant": {"url": "http://test:8123", "token": "tok"}}
    data.update(overrides)
    return Config(**data)


def _ha_client(services=None, state_exists=True):
    """Mock HA client with a /api/services registry and get_state behavior."""
    client = AsyncMock()
    client.get_services.return_value = [
        {"domain": "notify", "services": {name: {} for name in (services or [])}},
        {"domain": "light", "services": {"turn_on": {}, "turn_off": {}}},
    ]
    if state_exists:
        client.get_state.return_value = {"entity_id": "input_datetime.ha_boss_heartbeat"}
    else:
        client.get_state.side_effect = Exception("404: entity not found")
    return client


def _notification_manager():
    manager = MagicMock()
    manager.notify = AsyncMock()
    manager.dismiss = AsyncMock()
    manager.notification_id_for.return_value = "haboss_self_check_config"
    return manager


@pytest.mark.asyncio
async def test_all_good_no_problems_and_dismisses_prior_warning():
    """A healthy pipeline reports no problems and clears any earlier warning."""
    config = _config(
        notifications={"mobile_push_services": ["notify.mobile_app_phone"]},
    )
    client = _ha_client(services=["mobile_app_phone"])
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert problems == []
    manager.notify.assert_not_awaited()
    manager.dismiss.assert_awaited_once_with("haboss_self_check_config")


@pytest.mark.asyncio
async def test_mobile_disabled_while_alerting_enabled_is_flagged():
    """Empty mobile_push_services with on_issue_detected on -> warning notification."""
    config = _config(notifications={"mobile_push_services": [], "on_issue_detected": True})
    client = _ha_client()
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert len(problems) == 1
    assert "Mobile push is disabled" in problems[0]
    manager.notify.assert_awaited_once()
    _, kwargs = manager.notify.await_args
    # Mobile may be exactly what's broken: warn via HA + CLI only.
    assert kwargs["channels"] == [
        NotificationChannel.CLI,
        NotificationChannel.HOME_ASSISTANT,
    ]
    manager.dismiss.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_service_missing_from_registry_is_flagged():
    """A push service absent from HA's registry (renamed phone) is reported."""
    config = _config(
        notifications={"mobile_push_services": ["notify.mobile_app_ghost"]},
    )
    client = _ha_client(services=["mobile_app_phone"])
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert len(problems) == 1
    assert "notify.mobile_app_ghost" in problems[0]
    manager.notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_registry_fetch_failure_is_flagged_not_raised():
    """If /api/services can't be fetched, that itself is a reported problem."""
    config = _config(
        notifications={"mobile_push_services": ["notify.mobile_app_phone"]},
    )
    client = _ha_client()
    client.get_services.side_effect = Exception("boom")
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert len(problems) == 1
    assert "service registry" in problems[0]


@pytest.mark.asyncio
async def test_heartbeat_target_missing_is_flagged():
    """Heartbeat enabled but helper missing in HA -> reported."""
    config = _config(
        notifications={"mobile_push_services": ["notify.mobile_app_phone"]},
        heartbeat={"enabled": True},
    )
    client = _ha_client(services=["mobile_app_phone"], state_exists=False)
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert len(problems) == 1
    assert "input_datetime.ha_boss_heartbeat" in problems[0]


@pytest.mark.asyncio
async def test_heartbeat_target_present_passes():
    """Heartbeat enabled and helper exists -> clean run."""
    config = _config(
        notifications={"mobile_push_services": ["notify.mobile_app_phone"]},
        heartbeat={"enabled": True},
    )
    client = _ha_client(services=["mobile_app_phone"], state_exists=True)
    manager = _notification_manager()

    problems = await run_self_check(config, client, manager, "default")

    assert problems == []
    client.get_state.assert_awaited_once_with("input_datetime.ha_boss_heartbeat")
