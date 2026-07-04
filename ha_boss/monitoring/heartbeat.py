"""Dead-man's-switch heartbeat.

Periodically stamps an ``input_datetime`` helper in Home Assistant so an
HA-side automation can alert when HA Boss stops beating (dead container,
crash loop, hung process). This inverts the watching: Home Assistant itself
watches the watchdog, covering failures HA Boss cannot report on its own.
"""

import logging
import time

from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


async def send_heartbeat(ha_client: HomeAssistantClient, entity_id: str) -> None:
    """Stamp the heartbeat helper with the current time.

    Uses the ``timestamp`` form of ``input_datetime.set_datetime`` (epoch
    seconds) so the value is timezone-safe regardless of container/HA locale.

    Args:
        ha_client: Home Assistant API client
        entity_id: The input_datetime helper to stamp

    Raises:
        HomeAssistantAPIError: If the service call fails (e.g. helper missing)
    """
    await ha_client.call_service(
        "input_datetime",
        "set_datetime",
        {"entity_id": entity_id, "timestamp": int(time.time())},
    )
