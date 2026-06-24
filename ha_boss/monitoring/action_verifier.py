"""Action verification for HA Boss.

Observes ``call_service`` WebSocket events and verifies that the target entity
reaches the expected state within a configurable delay.  If the state was NOT
reached a WARNING notification is sent so the user can investigate.

Only a conservative set of (domain, service) → expected-state mappings are
checked; unmapped or ambiguous calls (e.g. ``toggle``) are silently skipped.

Supersede semantics: if a second command for the *same* entity arrives before
its pending check fires, the old check task is cancelled and replaced by the
new one (latest command wins).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.notifications.manager import NotificationManager
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verb → expected-state mapping
# ---------------------------------------------------------------------------

# Domains for which turn_on → "on" and turn_off → "off" are unambiguous.
_SIMPLE_TOGGLE_DOMAINS: frozenset[str] = frozenset(
    {
        "light",
        "switch",
        "fan",
        "input_boolean",
        "humidifier",
        "siren",
    }
)

# (domain, service) → expected state.  Built at module level for fast lookup.
_VERB_MAP: dict[tuple[str, str], str] = {}

for _domain in _SIMPLE_TOGGLE_DOMAINS:
    _VERB_MAP[(_domain, "turn_on")] = "on"
    _VERB_MAP[(_domain, "turn_off")] = "off"

# media_player: turn_off is deterministic; turn_on is ambiguous (skip).
_VERB_MAP[("media_player", "turn_off")] = "off"

# cover
_VERB_MAP[("cover", "open_cover")] = "open"
_VERB_MAP[("cover", "close_cover")] = "closed"

# lock
_VERB_MAP[("lock", "lock")] = "locked"
_VERB_MAP[("lock", "unlock")] = "unlocked"


def _expected_state_for_homeassistant(
    service: str,
    entity_domain: str,
) -> str | None:
    """Resolve expected state for ``homeassistant.turn_on`` / ``turn_off`` calls.

    The ``homeassistant`` domain routes the call to whatever domain the target
    entity belongs to.  We apply the same conservative mapping used by the
    specific-domain entries.

    Args:
        service: Service name (``"turn_on"`` or ``"turn_off"``).
        entity_domain: Domain of the target entity (e.g. ``"light"``).

    Returns:
        Expected state string, or ``None`` if the combination is ambiguous /
        not in scope (e.g. ``lock`` has no on/off concept).
    """
    if service not in ("turn_on", "turn_off"):
        return None

    # cover: on/off map to open/closed
    if entity_domain == "cover":
        return "open" if service == "turn_on" else "closed"

    # lock: on/off are not meaningful — skip
    if entity_domain == "lock":
        return None

    # Simple toggle domains
    if entity_domain in _SIMPLE_TOGGLE_DOMAINS:
        return "on" if service == "turn_on" else "off"

    # media_player: only turn_off is deterministic
    if entity_domain == "media_player" and service == "turn_off":
        return "off"

    return None


def _resolve_expected_state(
    domain: str,
    service: str,
    entity_id: str,
) -> str | None:
    """Return the expected entity state for a given (domain, service, entity_id) triple.

    Args:
        domain: HA service domain (e.g. ``"light"``, ``"homeassistant"``).
        service: Service name (e.g. ``"turn_off"``).
        entity_id: Target entity ID (used only for ``homeassistant`` domain lookup).

    Returns:
        Expected state string, or ``None`` if the call is out-of-scope / ambiguous.
    """
    if domain == "homeassistant":
        entity_domain = entity_id.split(".")[0] if "." in entity_id else ""
        return _expected_state_for_homeassistant(service, entity_domain)

    return _VERB_MAP.get((domain, service))


# ---------------------------------------------------------------------------
# ActionVerifier
# ---------------------------------------------------------------------------


class ActionVerifier:
    """Verifies that state-changing service calls produce the expected entity state.

    Constructor Args:
        ha_client: Home Assistant REST client used to fetch live entity state.
        notification_manager: Manager for sending WARNING notifications.
        config: HA Boss configuration (reads ``monitoring.action_verification``).
        instance_id: Unique identifier for the Home Assistant instance.
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        notification_manager: NotificationManager,
        config: Config,
        instance_id: str,
    ) -> None:
        """Initialise the verifier.

        Args:
            ha_client: Home Assistant REST/WebSocket client.
            notification_manager: Notification manager for sending failure alerts.
            config: HA Boss configuration.
            instance_id: Unique identifier for the Home Assistant instance.
        """
        self.ha_client = ha_client
        self.notification_manager = notification_manager
        self.config = config
        self.instance_id = instance_id

        self._av_cfg = config.monitoring.action_verification

        # Pending verification tasks keyed by entity_id.
        # When a new command arrives for the same entity the previous task is cancelled.
        self._pending: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_service_call(self, data: dict[str, Any]) -> None:
        """Process a ``call_service`` event and schedule a verification check if applicable.

        Args:
            data: The ``call_service`` event data dict with keys
                ``domain``, ``service``, ``service_data``.
        """
        domain: str = data.get("domain", "")
        service: str = data.get("service", "")
        service_data: dict[str, Any] = data.get("service_data", {}) or {}

        # Extract target entity IDs (may be str, list[str], or absent)
        raw_entity_id = service_data.get("entity_id")
        if raw_entity_id is None:
            # device_id / area_id only — out of v1 scope
            logger.debug(
                f"[{self.instance_id}] action_verifier: no entity_id in service_data for "
                f"{domain}.{service}, skipping"
            )
            return

        entity_ids: list[str] = (
            [raw_entity_id] if isinstance(raw_entity_id, str) else list(raw_entity_id)
        )

        for entity_id in entity_ids:
            expected = _resolve_expected_state(domain, service, entity_id)
            if expected is None:
                logger.debug(
                    f"[{self.instance_id}] action_verifier: no expected state for "
                    f"{domain}.{service} on {entity_id}, skipping"
                )
                continue

            self._schedule_check(entity_id, expected, domain, service)

    async def shutdown(self) -> None:
        """Cancel all pending verification tasks (call during service shutdown)."""
        for _entity_id, task in list(self._pending.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._pending.clear()
        logger.debug(f"[{self.instance_id}] action_verifier: all pending checks cancelled")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _schedule_check(
        self,
        entity_id: str,
        expected: str,
        domain: str,
        service: str,
    ) -> None:
        """Schedule (or replace) a deferred verification check for ``entity_id``.

        Supersede: if there is already a pending check for this entity, cancel it
        first so only the *latest* command is verified (latest wins).

        Args:
            entity_id: Target entity to verify.
            expected: Expected state string.
            domain: Service domain.
            service: Service name.
        """
        existing = self._pending.get(entity_id)
        if existing and not existing.done():
            logger.debug(
                f"[{self.instance_id}] action_verifier: superseding pending check for {entity_id}"
            )
            existing.cancel()

        task = asyncio.create_task(
            self._verify(entity_id, expected, domain, service),
            name=f"action_verify_{self.instance_id}_{entity_id}",
        )
        self._pending[entity_id] = task

        logger.debug(
            f"[{self.instance_id}] action_verifier: scheduled check for {entity_id} "
            f"(expected={expected!r}) in {self._av_cfg.delay_seconds}s"
        )

    async def _verify(
        self,
        entity_id: str,
        expected: str,
        domain: str,
        service: str,
    ) -> None:
        """Sleep, then fetch the entity state and notify on mismatch.

        Args:
            entity_id: Entity to check.
            expected: State the entity should be in.
            domain: Domain of the originating service call (for the notification body).
            service: Service name of the originating service call.
        """
        try:
            await asyncio.sleep(self._av_cfg.delay_seconds)

            # Fetch fresh state directly from HA REST (bypass local cache)
            try:
                state_data = await self.ha_client.get_state(entity_id)
                actual = state_data.get("state", "unknown")
            except Exception as exc:
                logger.warning(
                    f"[{self.instance_id}] action_verifier: failed to fetch state for "
                    f"{entity_id}: {exc}"
                )
                return

            if actual == expected:
                logger.debug(
                    f"[{self.instance_id}] action_verifier: {entity_id} reached expected "
                    f"state {expected!r} — OK"
                )
                return

            # Some entities (e.g. a TV/media player) report 'unavailable' as their
            # normal powered-off state, so a successful turn_off lands on
            # 'unavailable' rather than 'off'. Treat that as success.
            if (
                actual == "unavailable"
                and expected == "off"
                and self.config.monitoring.is_unavailable_expected(entity_id)
            ):
                logger.debug(
                    f"[{self.instance_id}] action_verifier: {entity_id} is 'unavailable' after "
                    f"turn_off — accepted as expected powered-off state (unavailable_ok)"
                )
                return

            # State mismatch — send WARNING notification
            logger.warning(
                f"[{self.instance_id}] action_verifier: {entity_id} did NOT reach expected "
                f"state {expected!r} (actual={actual!r}) after {self._av_cfg.delay_seconds}s"
            )

            context = NotificationContext(
                notification_type=NotificationType.ACTION_VERIFICATION_FAILED,
                severity=NotificationSeverity.WARNING,
                entity_id=entity_id,
                extra={
                    "service": f"{domain}.{service}",
                    "expected_state": expected,
                    "actual_state": actual,
                    "delay_seconds": self._av_cfg.delay_seconds,
                },
            )

            await self.notification_manager.notify(context)

        except asyncio.CancelledError:
            logger.debug(
                f"[{self.instance_id}] action_verifier: check for {entity_id} was superseded"
            )
            raise
        finally:
            # Only clear our own slot. A superseding command may have already
            # replaced us in _pending with a newer task — don't evict that one
            # (doing so would leave it untracked: not cancellable on the next
            # supersede or on shutdown, risking a duplicate notification).
            if self._pending.get(entity_id) is asyncio.current_task():
                self._pending.pop(entity_id, None)
