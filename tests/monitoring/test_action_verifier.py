"""Tests for ActionVerifier — action (service-call) verification."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import (
    ActionVerificationConfig,
    Config,
    HomeAssistantConfig,
    MonitoringConfig,
    NotificationsConfig,
)
from ha_boss.monitoring.action_verifier import (
    ActionVerifier,
    _expected_state_for_homeassistant,
    _resolve_expected_state,
)
from ha_boss.notifications.templates import NotificationSeverity, NotificationType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    enabled: bool = True,
    delay_seconds: int = 0,  # zero-delay so tests don't actually wait
) -> Config:
    """Build a minimal Config with the given action_verification settings."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        monitoring=MonitoringConfig(
            action_verification=ActionVerificationConfig(
                enabled=enabled,
                delay_seconds=delay_seconds if delay_seconds > 0 else 1,
            ),
        ),
        notifications=NotificationsConfig(on_healing_failure=False),
        mode="production",
    )


def _make_verifier(
    *,
    ha_client: AsyncMock | None = None,
    notification_manager: AsyncMock | None = None,
    delay_seconds: int = 0,
) -> ActionVerifier:
    """Create an ActionVerifier with mocked dependencies."""
    cfg = _make_config(delay_seconds=max(delay_seconds, 1))
    # Patch delay_seconds to 0 so tests complete instantly
    cfg.monitoring.action_verification.delay_seconds = delay_seconds  # type: ignore[assignment]

    ha_client = ha_client or AsyncMock()
    notification_manager = notification_manager or AsyncMock()
    return ActionVerifier(
        ha_client=ha_client,
        notification_manager=notification_manager,
        config=cfg,
        instance_id="default",
    )


def _state_response(state: str) -> dict[str, Any]:
    """Build a minimal HA state dict."""
    return {"entity_id": "light.bedroom", "state": state, "attributes": {}}


# ---------------------------------------------------------------------------
# Tests: verb map / expected-state resolution
# ---------------------------------------------------------------------------


class TestVerbMap:
    """Unit tests for the domain/service → expected-state mapping."""

    @pytest.mark.parametrize(
        "domain,service,entity_id,expected",
        [
            # Simple toggle domains — turn_off
            ("light", "turn_off", "light.bedroom", "off"),
            ("switch", "turn_off", "switch.fan", "off"),
            ("fan", "turn_off", "fan.ceiling", "off"),
            ("input_boolean", "turn_off", "input_boolean.flag", "off"),
            ("humidifier", "turn_off", "humidifier.h", "off"),
            ("siren", "turn_off", "siren.alarm", "off"),
            # Simple toggle domains — turn_on
            ("light", "turn_on", "light.bedroom", "on"),
            ("switch", "turn_on", "switch.fan", "on"),
            # cover
            ("cover", "close_cover", "cover.garage", "closed"),
            ("cover", "open_cover", "cover.garage", "open"),
            # lock
            ("lock", "lock", "lock.front_door", "locked"),
            ("lock", "unlock", "lock.front_door", "unlocked"),
            # media_player — only turn_off is in scope
            ("media_player", "turn_off", "media_player.tv", "off"),
        ],
    )
    def test_expected_state_mapped(
        self, domain: str, service: str, entity_id: str, expected: str
    ) -> None:
        """Known (domain, service) pairs resolve to the correct expected state."""
        result = _resolve_expected_state(domain, service, entity_id)
        assert result == expected

    @pytest.mark.parametrize(
        "domain,service,entity_id",
        [
            # toggle is ambiguous
            ("light", "toggle", "light.bedroom"),
            # media_player turn_on is ambiguous
            ("media_player", "turn_on", "media_player.tv"),
            # unknown domain/service
            ("climate", "set_temperature", "climate.living_room"),
            ("unknown_domain", "unknown_service", "sensor.foo"),
        ],
    )
    def test_unmapped_returns_none(self, domain: str, service: str, entity_id: str) -> None:
        """Unmapped or ambiguous (domain, service) pairs return None (skip)."""
        result = _resolve_expected_state(domain, service, entity_id)
        assert result is None

    # homeassistant domain — per-target-entity resolution
    @pytest.mark.parametrize(
        "service,entity_id,expected",
        [
            ("turn_off", "light.bedroom", "off"),
            ("turn_on", "light.bedroom", "on"),
            ("turn_off", "switch.main", "off"),
            ("turn_on", "switch.main", "on"),
            # cover: on/off → open/closed
            ("turn_on", "cover.garage", "open"),
            ("turn_off", "cover.garage", "closed"),
            # media_player: only turn_off in scope
            ("turn_off", "media_player.tv", "off"),
        ],
    )
    def test_homeassistant_domain_resolved_per_entity(
        self, service: str, entity_id: str, expected: str
    ) -> None:
        """homeassistant.turn_on/off resolves expected state from entity domain."""
        result = _resolve_expected_state("homeassistant", service, entity_id)
        assert result == expected

    @pytest.mark.parametrize(
        "service,entity_id",
        [
            # lock has no on/off concept
            ("turn_on", "lock.front_door"),
            ("turn_off", "lock.front_door"),
            # media_player turn_on is ambiguous even under homeassistant domain
            ("turn_on", "media_player.tv"),
            # toggle is not on/off
            ("toggle", "light.bedroom"),
        ],
    )
    def test_homeassistant_domain_ambiguous_returns_none(
        self, service: str, entity_id: str
    ) -> None:
        """homeassistant domain with ambiguous combos returns None."""
        result = _resolve_expected_state("homeassistant", service, entity_id)
        assert result is None


class TestExpectedStateForHomeassistant:
    """Unit tests for the homeassistant-specific helper."""

    def test_cover_turn_on(self) -> None:
        assert _expected_state_for_homeassistant("turn_on", "cover") == "open"

    def test_cover_turn_off(self) -> None:
        assert _expected_state_for_homeassistant("turn_off", "cover") == "closed"

    def test_lock_returns_none(self) -> None:
        assert _expected_state_for_homeassistant("turn_on", "lock") is None
        assert _expected_state_for_homeassistant("turn_off", "lock") is None

    def test_non_turn_service_returns_none(self) -> None:
        assert _expected_state_for_homeassistant("toggle", "light") is None


# ---------------------------------------------------------------------------
# Tests: target extraction from service_data
# ---------------------------------------------------------------------------


class TestTargetExtraction:
    """Tests for entity_id resolution from service_data."""

    @pytest.mark.asyncio
    async def test_entity_id_string_schedules_check(self) -> None:
        """A string entity_id schedules one verification task."""
        verifier = _make_verifier(delay_seconds=0)
        verifier._schedule_check = MagicMock()  # type: ignore[method-assign]

        await verifier.handle_service_call(
            {
                "domain": "light",
                "service": "turn_off",
                "service_data": {"entity_id": "light.bedroom"},
            }
        )

        verifier._schedule_check.assert_called_once_with(
            "light.bedroom", "off", "light", "turn_off"
        )

    @pytest.mark.asyncio
    async def test_entity_id_list_schedules_one_check_per_entity(self) -> None:
        """A list of entity_ids schedules a check for each."""
        verifier = _make_verifier(delay_seconds=0)
        verifier._schedule_check = MagicMock()  # type: ignore[method-assign]

        await verifier.handle_service_call(
            {
                "domain": "switch",
                "service": "turn_off",
                "service_data": {"entity_id": ["switch.a", "switch.b"]},
            }
        )

        assert verifier._schedule_check.call_count == 2
        called_entity_ids = {c.args[0] for c in verifier._schedule_check.call_args_list}
        assert called_entity_ids == {"switch.a", "switch.b"}

    @pytest.mark.asyncio
    async def test_missing_entity_id_skips(self) -> None:
        """No entity_id in service_data → no task scheduled (device_id/area_id scope)."""
        verifier = _make_verifier(delay_seconds=0)
        verifier._schedule_check = MagicMock()  # type: ignore[method-assign]

        await verifier.handle_service_call(
            {
                "domain": "light",
                "service": "turn_off",
                "service_data": {"area_id": "living_room"},
            }
        )

        verifier._schedule_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmapped_service_does_not_schedule(self) -> None:
        """Calls to unmapped services (e.g. toggle) are silently skipped."""
        verifier = _make_verifier(delay_seconds=0)
        verifier._schedule_check = MagicMock()  # type: ignore[method-assign]

        await verifier.handle_service_call(
            {
                "domain": "light",
                "service": "toggle",
                "service_data": {"entity_id": "light.bedroom"},
            }
        )

        verifier._schedule_check.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: verification logic
# ---------------------------------------------------------------------------


class TestVerification:
    """Tests for the core _verify coroutine behaviour."""

    @pytest.mark.asyncio
    async def test_state_reached_no_notification(self) -> None:
        """When the entity reaches the expected state, no notification is sent."""
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": "off", "attributes": {}})
        notification_manager = AsyncMock()

        verifier = _make_verifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            delay_seconds=0,
        )

        await verifier._verify("light.bedroom", "off", "light", "turn_off")

        notification_manager.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_not_reached_sends_warning(self) -> None:
        """When the entity did NOT reach expected state, notify() is called with WARNING."""
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": "on", "attributes": {}})
        notification_manager = AsyncMock()

        verifier = _make_verifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            delay_seconds=0,
        )

        await verifier._verify("light.bedroom", "off", "light", "turn_off")

        notification_manager.notify.assert_called_once()
        context = notification_manager.notify.call_args[0][0]
        assert context.notification_type == NotificationType.ACTION_VERIFICATION_FAILED
        assert context.severity == NotificationSeverity.WARNING
        assert context.entity_id == "light.bedroom"
        assert context.extra["expected_state"] == "off"
        assert context.extra["actual_state"] == "on"
        assert context.extra["service"] == "light.turn_off"

    @pytest.mark.asyncio
    async def test_notification_includes_delay_seconds(self) -> None:
        """The notification extra dict carries the configured delay_seconds."""
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": "on"})
        notification_manager = AsyncMock()

        cfg = _make_config(delay_seconds=1)
        cfg.monitoring.action_verification.delay_seconds = 42  # type: ignore[assignment]
        verifier = ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )
        # Override sleep so test doesn't wait 42 seconds
        with patch("asyncio.sleep", new=AsyncMock()):
            await verifier._verify("switch.outlet", "off", "switch", "turn_off")

        context = notification_manager.notify.call_args[0][0]
        assert context.extra["delay_seconds"] == 42

    @pytest.mark.asyncio
    async def test_get_state_failure_does_not_notify(self) -> None:
        """If fetching the entity state fails, no spurious notification is sent."""
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(side_effect=Exception("connection error"))
        notification_manager = AsyncMock()

        verifier = _make_verifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            delay_seconds=0,
        )

        await verifier._verify("light.bedroom", "off", "light", "turn_off")

        notification_manager.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_called_without_explicit_channels(self) -> None:
        """notify() is called with no explicit channels so severity routing applies.

        This ensures WARNING severity causes routing to CLI + HA + MOBILE.
        """
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": "on"})
        notification_manager = AsyncMock()

        verifier = _make_verifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            delay_seconds=0,
        )

        await verifier._verify("light.bedroom", "off", "light", "turn_off")

        # Confirm notify was called with only the context (no channels kwarg)
        call_args = notification_manager.notify.call_args
        # channels should be absent or None so severity routing applies
        if len(call_args.args) > 1:
            assert call_args.args[1] is None
        else:
            assert call_args.kwargs.get("channels") is None


class TestUnavailableOkOnTurnOff:
    """Tests for treating 'unavailable' as a successful turn_off for unavailable_ok entities."""

    def _verifier_with_unavailable_ok(
        self,
        patterns: list[str],
        actual_state: str,
        notification_manager: AsyncMock,
    ) -> ActionVerifier:
        """Build a verifier whose target returns ``actual_state`` and has the given patterns."""
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": actual_state, "attributes": {}})
        cfg = _make_config(delay_seconds=1)
        cfg.monitoring.action_verification.delay_seconds = 0  # type: ignore[assignment]
        cfg.monitoring.unavailable_ok = patterns
        return ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )

    @pytest.mark.asyncio
    async def test_unavailable_after_turn_off_is_success(self) -> None:
        """A TV that goes 'unavailable' after turn_off is treated as success (no warning)."""
        notification_manager = AsyncMock()
        verifier = self._verifier_with_unavailable_ok(
            ["media_player.lg_webos_tv_oled65c8pua"], "unavailable", notification_manager
        )

        await verifier._verify(
            "media_player.lg_webos_tv_oled65c8pua", "off", "media_player", "turn_off"
        )

        notification_manager.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_unavailable_not_in_list_still_warns(self) -> None:
        """An entity NOT in unavailable_ok still warns when it lands on 'unavailable'."""
        notification_manager = AsyncMock()
        verifier = self._verifier_with_unavailable_ok(
            ["media_player.lg_webos_tv_oled65c8pua"], "unavailable", notification_manager
        )

        await verifier._verify("light.back_patio", "off", "light", "turn_off")

        notification_manager.notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_unavailable_after_turn_on_still_warns(self) -> None:
        """unavailable_ok only excuses turn_off; a turn_on landing on 'unavailable' still warns."""
        notification_manager = AsyncMock()
        verifier = self._verifier_with_unavailable_ok(
            ["switch.flaky"], "unavailable", notification_manager
        )

        await verifier._verify("switch.flaky", "on", "switch", "turn_on")

        notification_manager.notify.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: supersede semantics
# ---------------------------------------------------------------------------


class TestSupersede:
    """Tests for the 'latest command wins' cancellation semantics."""

    @pytest.mark.asyncio
    async def test_second_command_cancels_first_pending_check(self) -> None:
        """A second command for the same entity cancels the first pending check."""
        ha_client = AsyncMock()
        # First check: state "on" (mismatched)
        # Second check: state "off" (matched — no notify)
        ha_client.get_state = AsyncMock(return_value={"state": "off"})
        notification_manager = AsyncMock()

        # Use a non-zero delay so the first task doesn't complete before we supersede it
        cfg = _make_config(delay_seconds=1)
        cfg.monitoring.action_verification.delay_seconds = 60  # type: ignore[assignment]
        verifier = ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )

        # Schedule first check (long delay → will be cancelled)
        verifier._schedule_check("light.bedroom", "off", "light", "turn_off")
        first_task = verifier._pending.get("light.bedroom")
        assert first_task is not None
        assert not first_task.done()

        # Immediately schedule second check for the same entity
        verifier._schedule_check("light.bedroom", "on", "light", "turn_on")
        second_task = verifier._pending.get("light.bedroom")

        # Yield to the event loop so asyncio processes the cancellation
        await asyncio.sleep(0)

        # First task should have been cancelled (done() covers cancelling + cancelled)
        assert first_task.cancelled() or first_task.done()
        assert second_task is not None
        assert second_task is not first_task

        # Let the second task complete
        second_task.cancel()
        await asyncio.gather(second_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_third_command_keeps_only_latest_tracked(self) -> None:
        """Three rapid commands on one entity leave exactly the latest task tracked.

        Regression: a superseded task's finally-cleanup must not evict the newer
        task's _pending entry (which would leave it untracked and risk a duplicate
        notification on the next supersede / shutdown).
        """
        ha_client = AsyncMock()
        ha_client.get_state = AsyncMock(return_value={"state": "off"})
        notification_manager = AsyncMock()

        cfg = _make_config(delay_seconds=1)
        cfg.monitoring.action_verification.delay_seconds = 60  # type: ignore[assignment]
        verifier = ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )

        verifier._schedule_check("light.bedroom", "off", "light", "turn_off")
        t1 = verifier._pending.get("light.bedroom")
        verifier._schedule_check("light.bedroom", "on", "light", "turn_on")
        t2 = verifier._pending.get("light.bedroom")
        verifier._schedule_check("light.bedroom", "off", "light", "turn_off")
        t3 = verifier._pending.get("light.bedroom")

        # Let cancellations of t1 and t2 process
        for _ in range(3):
            await asyncio.sleep(0)

        assert t1 is not t2 and t2 is not t3
        assert t1 is not None and (t1.cancelled() or t1.done())
        assert t2 is not None and (t2.cancelled() or t2.done())
        # Latest task must still be tracked (not evicted by a superseded finally)
        assert verifier._pending.get("light.bedroom") is t3
        assert t3 is not None and not t3.done()

        await verifier.shutdown()
        assert verifier._pending == {}

    @pytest.mark.asyncio
    async def test_supersede_second_command_is_verified(self) -> None:
        """After superseding, only the second command's verification runs."""
        ha_client = AsyncMock()
        # Return expected state "on" — second command says turn_on → no notify
        ha_client.get_state = AsyncMock(return_value={"state": "on"})
        notification_manager = AsyncMock()

        cfg = _make_config(delay_seconds=1)
        # Use near-zero delay for speed, but positive (model rule: gt=0 but we patch)
        cfg.monitoring.action_verification.delay_seconds = 0  # type: ignore[assignment]
        verifier = ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )

        # First command: turn_off (expect "off")
        verifier._schedule_check("light.bedroom", "off", "light", "turn_off")
        # Supersede immediately: turn_on (expect "on")
        verifier._schedule_check("light.bedroom", "on", "light", "turn_on")

        # Allow the second task to run to completion
        await asyncio.sleep(0.05)

        # Entity is "on" which matches the second command → no notification
        notification_manager.notify.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Tests for the shutdown() method."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_pending_tasks(self) -> None:
        """shutdown() cancels all pending verification tasks."""
        ha_client = AsyncMock()
        notification_manager = AsyncMock()

        cfg = _make_config(delay_seconds=1)
        cfg.monitoring.action_verification.delay_seconds = 60  # type: ignore[assignment]
        verifier = ActionVerifier(
            ha_client=ha_client,
            notification_manager=notification_manager,
            config=cfg,
            instance_id="default",
        )

        verifier._schedule_check("light.bedroom", "off", "light", "turn_off")
        verifier._schedule_check("switch.outlet", "off", "switch", "turn_off")

        assert len(verifier._pending) == 2

        await verifier.shutdown()

        assert len(verifier._pending) == 0

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        """Calling shutdown() twice does not raise."""
        verifier = _make_verifier(delay_seconds=0)
        await verifier.shutdown()
        await verifier.shutdown()  # Should not raise


# ---------------------------------------------------------------------------
# Tests: config defaults
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests for ActionVerificationConfig defaults and MonitoringConfig integration."""

    def test_action_verification_config_defaults(self) -> None:
        """ActionVerificationConfig defaults: disabled, 30-second delay."""
        cfg = ActionVerificationConfig()
        assert cfg.enabled is False
        assert cfg.delay_seconds == 30

    def test_monitoring_config_has_action_verification_field(self) -> None:
        """MonitoringConfig exposes action_verification as a nested config."""
        mc = MonitoringConfig()
        assert isinstance(mc.action_verification, ActionVerificationConfig)
        assert mc.action_verification.enabled is False

    def test_delay_seconds_must_be_positive(self) -> None:
        """delay_seconds must be > 0."""
        import pytest as _pytest
        from pydantic import ValidationError

        with _pytest.raises(ValidationError):
            ActionVerificationConfig(delay_seconds=0)
