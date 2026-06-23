"""Out-of-scope entity audit for HA Boss.

Periodically scans all Home Assistant entities that are NOT in the monitored
set (i.e. not referenced by any automation/scene/script) and delivers an INFO
digest of newly-unavailable ones via persistent notification.

Chronic failures (unavailable for longer than ``chronic_threshold_seconds``)
are counted but not listed per-entity to avoid digest noise.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ha_boss.core.config import Config
from ha_boss.core.database import Database, OutOfScopeAuditStatus
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.discovery.entity_discovery import EntityDiscoveryService
from ha_boss.healing.integration_manager import IntegrationDiscovery
from ha_boss.notifications.manager import NotificationChannel, NotificationManager
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)

# Stable notification_id used so each new digest replaces the previous one.
_AUDIT_NOTIFICATION_ID_SUFFIX = "out_of_scope_audit"


class OutOfScopeAuditor:
    """Audits out-of-scope entities for unavailability and sends a digest.

    An entity is *out-of-scope* when it is present in the full HA state list
    but absent from the monitored set returned by
    ``entity_discovery.get_monitored_entities()``.

    A digest is sent only when there are net-new bad entities since the last
    run. Entities that have been bad longer than ``chronic_threshold_seconds``
    are counted but suppressed (not listed individually).
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        entity_discovery: EntityDiscoveryService | None,
        integration_discovery: IntegrationDiscovery | None,
        database: Database,
        notification_manager: NotificationManager,
        config: Config,
        instance_id: str,
    ) -> None:
        """Initialise the auditor.

        Args:
            ha_client: Home Assistant REST/WebSocket client.
            entity_discovery: Discovery service that tracks the monitored set.
                If None, the monitored set is assumed to be empty and all
                entities are treated as out-of-scope.
            integration_discovery: Optional discovery service for entity →
                integration/domain mapping used for grouping the digest.
            database: Database manager for baseline persistence.
            notification_manager: Notification manager for sending the digest.
            config: HA Boss configuration.
            instance_id: Unique identifier for the Home Assistant instance.
        """
        self.ha_client = ha_client
        self.entity_discovery = entity_discovery
        self.integration_discovery = integration_discovery
        self.database = database
        self.notification_manager = notification_manager
        self.config = config
        self.instance_id = instance_id

        self._audit_cfg = config.monitoring.out_of_scope_audit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_audit(self) -> dict[str, Any]:
        """Run one full out-of-scope audit cycle.

        Steps:
        1. Fetch all entity states from HA.
        2. Compute out-of-scope = all - monitored.
        3. Classify as bad (unavailable/unknown, optionally stale).
        4. Load current baseline from DB.
        5. Determine net-new bad entities (not in baseline).
        6. Classify existing baseline entries as chronic vs recent.
        7. Upsert bad entities into baseline; delete recovered ones.
        8. Send digest if there are net-new failures.

        Returns:
            Summary stats dict with keys:
            - ``total_out_of_scope``: int
            - ``bad_count``: int
            - ``new_count``: int
            - ``chronic_count``: int
            - ``recovered_count``: int
            - ``notified``: bool
        """
        logger.info(f"[{self.instance_id}] Starting out-of-scope entity audit")
        now = datetime.now(UTC)

        # 1. Fetch all states
        all_states: list[dict[str, Any]] = await self.ha_client.get_states()
        all_entity_ids: set[str] = {s["entity_id"] for s in all_states if "entity_id" in s}

        # 2. Compute out-of-scope set
        monitored: set[str] = (
            self.entity_discovery.get_monitored_entities()
            if self.entity_discovery is not None
            else set()
        )
        out_of_scope_ids: set[str] = all_entity_ids - monitored

        # Build quick lookup: entity_id → state string
        state_map: dict[str, str] = {
            s["entity_id"]: s.get("state", "") for s in all_states if "entity_id" in s
        }
        # Build last_updated lookup for stale detection
        last_updated_map: dict[str, str] = {
            s["entity_id"]: s.get("last_updated", "") for s in all_states if "entity_id" in s
        }

        # 3. Classify bad out-of-scope entities
        bad_entity_ids: set[str] = set()
        for eid in out_of_scope_ids:
            state = state_map.get(eid, "")
            if state in ("unavailable", "unknown"):
                bad_entity_ids.add(eid)
            elif self._audit_cfg.include_stale:
                (
                    bad_entity_ids.add(eid)
                    if self._is_stale(last_updated_map.get(eid, ""), now)
                    else None
                )

        # 4. Load current baseline from DB
        async with self.database.async_session() as session:
            result = await session.execute(
                select(OutOfScopeAuditStatus).where(
                    OutOfScopeAuditStatus.instance_id == self.instance_id
                )
            )
            baseline_rows: list[OutOfScopeAuditStatus] = list(result.scalars().all())

        baseline: dict[str, OutOfScopeAuditStatus] = {r.entity_id: r for r in baseline_rows}

        # 5. Net-new = bad now but NOT in baseline
        new_bad: set[str] = bad_entity_ids - set(baseline.keys())

        # 6. Classify existing bad entities as chronic vs recent
        chronic_threshold = timedelta(seconds=self._audit_cfg.chronic_threshold_seconds)
        chronic_bad: set[str] = set()
        for eid, row in baseline.items():
            if eid in bad_entity_ids:
                age = (
                    now - row.first_unavailable_at.replace(tzinfo=UTC)
                    if row.first_unavailable_at.tzinfo is None
                    else now - row.first_unavailable_at
                )
                if age > chronic_threshold:
                    chronic_bad.add(eid)

        # Recovered = was in baseline, now NOT bad
        recovered: set[str] = set(baseline.keys()) - bad_entity_ids

        # 7. Update baseline
        await self._update_baseline(bad_entity_ids, recovered, state_map, now)

        # 8. Build and send digest if there are net-new failures
        new_failures: list[dict[str, Any]] = []
        for eid in sorted(new_bad):
            group = self._get_group(eid)
            new_failures.append(
                {
                    "entity_id": eid,
                    "state": state_map.get(eid, "unavailable"),
                    "group": group,
                    "first_unavailable_at": now.isoformat(),
                }
            )

        notified = False
        if new_failures:
            await self._send_digest(new_failures, len(chronic_bad), len(out_of_scope_ids))
            notified = True

        stats: dict[str, Any] = {
            "total_out_of_scope": len(out_of_scope_ids),
            "bad_count": len(bad_entity_ids),
            "new_count": len(new_bad),
            "chronic_count": len(chronic_bad),
            "recovered_count": len(recovered),
            "notified": notified,
        }

        logger.info(
            f"[{self.instance_id}] Out-of-scope audit complete: "
            f"{len(out_of_scope_ids)} out-of-scope, "
            f"{len(bad_entity_ids)} bad, {len(new_bad)} new, "
            f"{len(chronic_bad)} chronic, {len(recovered)} recovered"
        )
        return stats

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_stale(self, last_updated_iso: str, now: datetime) -> bool:
        """Return True if the entity has not been updated within the stale threshold.

        Args:
            last_updated_iso: ISO-8601 string from HA state's ``last_updated`` field.
            now: Current UTC time.

        Returns:
            True if the entity is stale.
        """
        if not last_updated_iso:
            return False
        try:
            last_updated = datetime.fromisoformat(last_updated_iso.replace("Z", "+00:00"))
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=UTC)
            threshold = timedelta(seconds=self.config.monitoring.stale_threshold_seconds)
            return (now - last_updated) > threshold
        except (ValueError, TypeError):
            return False

    def _get_group(self, entity_id: str) -> str:
        """Return an integration name or entity domain for grouping.

        Tries the integration-discovery mapping first; falls back to the
        entity's domain (the part before the first ``'.'``).

        Args:
            entity_id: Entity ID to look up.

        Returns:
            Group label string (integration domain or entity domain).
        """
        if self._audit_cfg.group_by_integration and self.integration_discovery is not None:
            entry_id = self.integration_discovery.get_integration_for_entity(entity_id)
            if entry_id:
                domain = self.integration_discovery.get_domain(entry_id)
                if domain:
                    return domain

        # Fallback: entity domain (e.g. "light" from "light.office_lamp")
        return entity_id.split(".")[0] if "." in entity_id else "unknown"

    async def _update_baseline(
        self,
        bad_entity_ids: set[str],
        recovered: set[str],
        state_map: dict[str, str],
        now: datetime,
    ) -> None:
        """Upsert bad entities into baseline and delete recovered ones.

        Args:
            bad_entity_ids: Currently-bad entity IDs.
            recovered: Entity IDs that have recovered since last run.
            state_map: Current state strings keyed by entity_id.
            now: Current UTC time for timestamps.
        """
        async with self.database.async_session() as session:
            # Delete recovered entities
            if recovered:
                await session.execute(
                    delete(OutOfScopeAuditStatus).where(
                        OutOfScopeAuditStatus.instance_id == self.instance_id,
                        OutOfScopeAuditStatus.entity_id.in_(recovered),
                    )
                )

            # Upsert bad entities (insert new, update last_seen_at + last_state on conflict)
            for eid in bad_entity_ids:
                state = state_map.get(eid, "unavailable")
                stmt = (
                    sqlite_insert(OutOfScopeAuditStatus)
                    .values(
                        instance_id=self.instance_id,
                        entity_id=eid,
                        first_unavailable_at=now,
                        last_state=state,
                        last_seen_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["instance_id", "entity_id"],
                        set_={
                            "last_state": state,
                            "last_seen_at": now,
                            "updated_at": now,
                        },
                    )
                )
                await session.execute(stmt)

            await session.commit()

    async def _send_digest(
        self,
        new_failures: list[dict[str, Any]],
        chronic_count: int,
        total_out_of_scope: int,
    ) -> None:
        """Send the audit digest via the notification manager.

        Uses a stable notification_id so each digest replaces the previous one
        in the HA persistent-notification panel.

        Args:
            new_failures: List of newly-bad entity dicts.
            chronic_count: Number of chronically-bad entities (suppressed).
            total_out_of_scope: Total count of out-of-scope entities.
        """
        context = NotificationContext(
            notification_type=NotificationType.OUT_OF_SCOPE_AUDIT,
            severity=NotificationSeverity.INFO,
            # Use integration_name to encode the stable notification suffix so
            # _generate_notification_id produces a constant ID for this instance.
            integration_name=_AUDIT_NOTIFICATION_ID_SUFFIX,
            stats={
                "new_failures": new_failures,
                "chronic_count": chronic_count,
                "total_out_of_scope": total_out_of_scope,
            },
        )

        # First dismiss the previous digest so the new one replaces it cleanly.
        prev_notification_id = (
            f"haboss_{NotificationType.OUT_OF_SCOPE_AUDIT.value}"
            f"_{_AUDIT_NOTIFICATION_ID_SUFFIX.replace(' ', '_').lower()}"
        )
        try:
            await self.notification_manager.dismiss(prev_notification_id)
        except Exception as exc:
            logger.debug(f"[{self.instance_id}] Could not dismiss previous audit digest: {exc}")

        await self.notification_manager.notify(
            context,
            channels=[NotificationChannel.CLI, NotificationChannel.HOME_ASSISTANT],
        )
        logger.info(
            f"[{self.instance_id}] Sent out-of-scope audit digest "
            f"({len(new_failures)} new failures, {chronic_count} chronic)"
        )
