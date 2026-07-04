"""Self-check of HA Boss's own alerting pipeline.

Every major HA Boss failure to date has been a silent self-misconfiguration
(mobile push emptied by a config rewrite, notify service renamed, heartbeat
target deleted) rather than a missed Home Assistant problem. This module
actively validates the notification pipeline against the live instance at
startup and periodically, and raises a persistent notification when something
is off — so a broken alert path is itself alerted on.
"""

import logging
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.notifications.manager import NotificationChannel, NotificationManager
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
)

logger = logging.getLogger(__name__)

# Stable context name so the self-check notification ID is deterministic
# (haboss_self_check_config): repeat findings dedupe, and a clean run can
# dismiss a previously-raised warning.
_SELF_CHECK_CONTEXT_NAME = "config"


def _notify_service_names(services_payload: list[dict[str, Any]]) -> set[str]:
    """Extract notify service names from a ``/api/services`` response.

    The endpoint returns a list of ``{"domain": ..., "services": {name: ...}}``
    entries; unexpected shapes yield an empty set (treated as unvalidatable).
    """
    names: set[str] = set()
    for entry in services_payload:
        if isinstance(entry, dict) and entry.get("domain") == "notify":
            services = entry.get("services")
            if isinstance(services, dict):
                names.update(services.keys())
    return names


async def run_self_check(
    config: Config,
    ha_client: HomeAssistantClient,
    notification_manager: NotificationManager,
    instance_id: str,
) -> list[str]:
    """Validate the alerting pipeline; notify (HA + CLI) about any problems.

    Checks:
    - Mobile push configured when issue alerts are enabled
    - Every configured mobile push service exists in HA's service registry
    - The heartbeat target helper exists (when heartbeat is enabled)

    A clean run dismisses any previously-raised self-check notification.

    Args:
        config: HA Boss configuration
        ha_client: Home Assistant API client
        notification_manager: Manager used to raise/dismiss the warning
        instance_id: Home Assistant instance identifier (for logging)

    Returns:
        List of human-readable problem descriptions (empty = all good).
    """
    problems: list[str] = []

    notif = config.notifications
    if notif.on_issue_detected and not notif.mobile_push_services:
        problems.append(
            "Mobile push is disabled (mobile_push_services is empty) while "
            "on_issue_detected is enabled — alerts will only appear in the HA UI. "
            "If unintended, set HABOSS_MOBILE_PUSH_SERVICE in .env and restart."
        )

    if notif.mobile_push_services:
        try:
            registry = _notify_service_names(await ha_client.get_services())
        except Exception as e:
            registry = None
            problems.append(
                f"Could not fetch the HA service registry to validate push services: {e}"
            )
        if registry is not None:
            for configured in notif.mobile_push_services:
                service_name = configured.split(".", 1)[-1]
                if service_name not in registry:
                    problems.append(
                        f"Configured mobile push service '{configured}' does not exist on "
                        "this HA instance (companion app renamed or re-registered?) — "
                        "pushes to it are silently lost."
                    )

    if config.heartbeat.enabled:
        try:
            await ha_client.get_state(config.heartbeat.entity_id)
        except Exception:
            problems.append(
                f"Heartbeat target '{config.heartbeat.entity_id}' not found in HA — "
                "the dead-man's-switch automation will treat HA Boss as stale."
            )

    context = NotificationContext(
        notification_type=NotificationType.SELF_CHECK,
        severity=NotificationSeverity.WARNING,
        integration_name=_SELF_CHECK_CONTEXT_NAME,
        extra={"problems": problems},
    )

    if problems:
        for problem in problems:
            logger.warning(f"[{instance_id}] Self-check: {problem}")
        # HA + CLI only: mobile may be exactly what is broken.
        await notification_manager.notify(
            context,
            channels=[NotificationChannel.CLI, NotificationChannel.HOME_ASSISTANT],
        )
    else:
        logger.info(f"[{instance_id}] ✓ Self-check passed: notification pipeline OK")
        await notification_manager.dismiss(notification_manager.notification_id_for(context))

    return problems
