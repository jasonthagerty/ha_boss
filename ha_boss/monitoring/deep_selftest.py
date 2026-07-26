"""Deep end-to-end self-test of HA Boss against the live Home Assistant instance.

The heartbeat proves HA Boss is alive; this proves it is *working*. Each check
targets a failure mode that has actually occurred (or is one config rewrite away
from occurring) while the heartbeat stayed green:

- WebSocket connected and REST reachable
- Discovery integrity: every source (automations/scenes/scripts) that found
  objects must also have extracted entity references — a source with objects
  but zero junction rows means extraction is silently broken and the monitored
  set is quietly missing coverage
- Monitored set is non-empty
- Notification pipeline is sound (delegates to the existing self-check)

The verdict is written to an ``input_text`` helper in HA so HA-side automations
can alert on a failed or stale result, and the test can be requested on demand
by turning on an ``input_boolean`` helper. It also runs automatically when the
reported HA version changes — i.e. right after a Home Assistant update — which
is when compatibility breakage would appear.

Like the heartbeat, writing the two helpers is a deliberate, narrow exception
to HA Boss's read-only principle.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from ha_boss.core.config import Config
from ha_boss.core.database import (
    AutomationEntity,
    Database,
    DiscoveryRefresh,
    RuntimeConfig,
    SceneEntity,
    ScriptEntity,
)
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.monitoring.self_check import run_self_check
from ha_boss.monitoring.websocket_client import WebSocketClient
from ha_boss.notifications.manager import NotificationChannel, NotificationManager
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)

# Stable context name → deterministic notification id (haboss_self_check_selftest),
# distinct from the pipeline self-check's "config" context.
_SELFTEST_CONTEXT_NAME = "selftest"

_LAST_HA_VERSION_KEY = "last_seen_ha_version"


class DeepSelfTest:
    """Runs the deep self-test and reports the verdict to Home Assistant."""

    def __init__(
        self,
        config: Config,
        ha_client: HomeAssistantClient,
        database: Database,
        notification_manager: NotificationManager,
        websocket_client: WebSocketClient | None,
        instance_id: str,
    ) -> None:
        """Initialize the deep self-test.

        Args:
            config: HA Boss configuration
            ha_client: Home Assistant REST client
            database: HA Boss database
            notification_manager: Manager used for verdict notifications
            websocket_client: The instance's WebSocket client (None in tests)
            instance_id: Home Assistant instance identifier
        """
        self.config = config
        self.ha_client = ha_client
        self.database = database
        self.notification_manager = notification_manager
        self.websocket_client = websocket_client
        self.instance_id = instance_id
        self._running = False

    async def run(self, trigger: str) -> list[str]:
        """Run all checks, write the verdict helper, and notify on failure.

        Args:
            trigger: What initiated the run — "startup", "version_change",
                or "switch" (on-demand request helper)

        Returns:
            List of human-readable problem descriptions (empty = PASS).
        """
        if self._running:
            logger.info(f"[{self.instance_id}] Deep self-test already running; skipping")
            return []
        self._running = True
        try:
            return await self._run(trigger)
        finally:
            self._running = False

    async def _run(self, trigger: str) -> list[str]:
        logger.info(f"[{self.instance_id}] Deep self-test starting (trigger={trigger})")
        problems: list[str] = []
        ha_version: str | None = None

        # REST reachability (also yields the authoritative current HA version)
        try:
            ha_config = await self.ha_client.get_config()
            ha_version = ha_config.get("version")
        except Exception as e:
            problems.append(f"REST API unreachable: {e}")

        # WebSocket connectivity
        if self.websocket_client is not None and not self.websocket_client.is_connected():
            problems.append("WebSocket is not connected")

        # Discovery integrity + monitored set
        problems.extend(await self._check_discovery_integrity())

        # Notification pipeline (raises/dismisses its own stable-id notification)
        try:
            problems.extend(
                await run_self_check(
                    self.config, self.ha_client, self.notification_manager, self.instance_id
                )
            )
        except Exception as e:
            problems.append(f"Notification pipeline self-check crashed: {e}")

        await self._write_verdict(problems, ha_version)
        if trigger == "switch":
            await self._reset_request_helper()
        await self._notify(problems, ha_version, trigger)

        if problems:
            for problem in problems:
                logger.warning(f"[{self.instance_id}] Deep self-test: {problem}")
        else:
            logger.info(f"[{self.instance_id}] ✓ Deep self-test passed (trigger={trigger})")
        return problems

    async def _check_discovery_integrity(self) -> list[str]:
        """Compare the last refresh's per-source object counts to junction rows."""
        problems: list[str] = []
        async with self.database.async_session() as session:
            refresh = (
                await session.execute(
                    select(DiscoveryRefresh)
                    .where(DiscoveryRefresh.success.is_(True))
                    .order_by(DiscoveryRefresh.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if refresh is None:
                return ["Discovery has never completed a successful refresh"]

            sources = (
                ("automations", refresh.automations_found, AutomationEntity),
                ("scenes", refresh.scenes_found, SceneEntity),
                ("scripts", refresh.scripts_found, ScriptEntity),
            )
            total_refs = 0
            for name, found, model in sources:
                rows = (await session.execute(select(func.count()).select_from(model))).scalar_one()
                total_refs += rows
                if found > 0 and rows == 0:
                    problems.append(
                        f"Discovery found {found} {name} but extracted 0 entity references "
                        f"— {name} extraction is broken and their entities are unmonitored"
                    )

            if total_refs == 0:
                problems.append("Monitored set is empty — discovery extracted nothing")

        return problems

    async def _write_verdict(self, problems: list[str], ha_version: str | None) -> None:
        """Write a short verdict to the result input_text helper."""
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
        version = ha_version or "unknown"
        if problems:
            value = f"FAIL({len(problems)}) ha={version} {stamp}"
        else:
            value = f"PASS ha={version} {stamp}"
        try:
            await self.ha_client.call_service(
                "input_text",
                "set_value",
                {"entity_id": self.config.self_test.result_entity_id, "value": value},
            )
        except Exception as e:
            logger.warning(
                f"[{self.instance_id}] Could not write self-test verdict to "
                f"{self.config.self_test.result_entity_id}: {e}"
            )

    async def _reset_request_helper(self) -> None:
        """Turn the on-demand request input_boolean back off."""
        try:
            await self.ha_client.call_service(
                "input_boolean",
                "turn_off",
                {"entity_id": self.config.self_test.request_entity_id},
            )
        except Exception as e:
            logger.warning(
                f"[{self.instance_id}] Could not reset "
                f"{self.config.self_test.request_entity_id}: {e}"
            )

    async def _notify(self, problems: list[str], ha_version: str | None, trigger: str) -> None:
        """Raise a WARNING on failure; INFO on a version-change pass; dismiss when clean."""
        context = NotificationContext(
            notification_type=NotificationType.SELF_CHECK,
            severity=NotificationSeverity.WARNING if problems else NotificationSeverity.INFO,
            integration_name=_SELFTEST_CONTEXT_NAME,
            extra={
                "problems": problems
                or [f"Deep self-test passed against Home Assistant {ha_version or 'unknown'}"],
                "trigger": trigger,
            },
        )
        try:
            if problems:
                # All channels: unlike the pipeline self-check, the deep test's
                # failures (discovery, connectivity) don't implicate mobile push.
                await self.notification_manager.notify(context)
            elif trigger == "version_change":
                await self.notification_manager.notify(
                    context,
                    channels=[NotificationChannel.CLI, NotificationChannel.HOME_ASSISTANT],
                )
            else:
                await self.notification_manager.dismiss(
                    self.notification_manager.notification_id_for(context)
                )
        except Exception as e:
            logger.error(f"[{self.instance_id}] Self-test notification failed: {e}", exc_info=True)

    async def check_version_change(self, ha_version: str | None) -> bool:
        """Persist the observed HA version; run the self-test when it changed.

        Called from two independent paths: the WebSocket ``on_connected`` hook
        (fires on the initial connect and every reconnect — an HA update always
        causes a reconnect) and the REST version poll. The poll is what makes
        this reliable: when the WebSocket is the thing that broke, the connect
        hook never fires and the update would otherwise go unverified.

        Args:
            ha_version: Version reported by the auth handshake (None = unknown)

        Returns:
            True when a version change was detected and the self-test ran.
        """
        if not ha_version:
            return False

        async with self.database.async_session() as session:
            row = (
                await session.execute(
                    select(RuntimeConfig).where(RuntimeConfig.key == _LAST_HA_VERSION_KEY)
                )
            ).scalar_one_or_none()
            previous = json.loads(row.value) if row else None

            if row is None:
                session.add(
                    RuntimeConfig(
                        key=_LAST_HA_VERSION_KEY,
                        value=json.dumps(ha_version),
                        value_type="string",
                    )
                )
            elif previous != ha_version:
                row.value = json.dumps(ha_version)
            await session.commit()

        if previous is not None and previous != ha_version:
            logger.info(
                f"[{self.instance_id}] Home Assistant version changed "
                f"{previous} → {ha_version}; running deep self-test"
            )
            await self.run(trigger="version_change")
            return True
        return False
