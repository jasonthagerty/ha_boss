"""Pattern collection service for tracking integration reliability."""

import logging
from datetime import UTC, datetime
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.database import Database, IntegrationReliability

logger = logging.getLogger(__name__)


class PatternCollector:
    """Collects and stores integration reliability patterns.

    Records healing attempts, failures, and entity unavailable events
    for pattern analysis. All errors are caught and logged to prevent
    service disruption.
    """

    def __init__(
        self,
        config: Config,
        database: Database,
    ) -> None:
        """Initialize pattern collector.

        Args:
            config: HA Boss configuration
            database: Database manager
        """
        self.config = config
        self.database = database
        self._event_count = 0  # For testing/monitoring

    async def record_healing_attempt(
        self,
        integration_id: str,
        integration_domain: str,
        entity_id: str | None,
        success: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a healing attempt (success or failure).

        Args:
            integration_id: Integration config entry ID
            integration_domain: Integration domain (e.g., 'hue', 'zwave')
            entity_id: Entity that triggered healing (optional)
            success: Whether healing succeeded
            details: Additional context (optional)
        """
        # Check if pattern collection is enabled
        if not self.config.intelligence.pattern_collection_enabled:
            return

        event_type = "heal_success" if success else "heal_failure"

        try:
            await self._record_event(
                integration_id=integration_id,
                integration_domain=integration_domain,
                entity_id=entity_id,
                event_type=event_type,
                details=details,
            )
            logger.debug(
                f"Recorded {event_type} for {integration_domain} "
                f"(integration_id={integration_id})"
            )
        except Exception as e:
            # Graceful degradation: log but don't crash
            logger.error(f"Failed to record healing attempt: {e}", exc_info=True)

    async def record_entity_unavailable(
        self,
        integration_id: str | None,
        integration_domain: str | None,
        entity_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an entity becoming unavailable.

        Args:
            integration_id: Integration config entry ID (if known)
            integration_domain: Integration domain (if known)
            entity_id: Entity that became unavailable
            details: Additional context (optional)
        """
        # Check if pattern collection is enabled
        if not self.config.intelligence.pattern_collection_enabled:
            return

        # If integration info is missing, use entity domain as fallback
        if not integration_id or not integration_domain:
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            integration_id = integration_id or f"domain_{domain}"
            integration_domain = integration_domain or domain

        try:
            await self._record_event(
                integration_id=integration_id,
                integration_domain=integration_domain,
                entity_id=entity_id,
                event_type="unavailable",
                details=details,
            )
            logger.debug(
                f"Recorded unavailable event for {entity_id} " f"(domain={integration_domain})"
            )
        except Exception as e:
            # Graceful degradation: log but don't crash
            logger.error(f"Failed to record entity unavailable: {e}", exc_info=True)

    async def _record_event(
        self,
        integration_id: str,
        integration_domain: str,
        entity_id: str | None,
        event_type: str,
        details: dict[str, Any] | None,
    ) -> None:
        """Internal method to record an event in the database.

        Args:
            integration_id: Integration config entry ID
            integration_domain: Integration domain
            entity_id: Entity ID (optional)
            event_type: Type of event (heal_success, heal_failure, unavailable)
            details: Additional context (optional)
        """
        timestamp = datetime.now(UTC)

        async with self.database.async_session() as session:
            event = IntegrationReliability(
                integration_id=integration_id,
                integration_domain=integration_domain,
                timestamp=timestamp,
                event_type=event_type,
                entity_id=entity_id,
                details=details,
            )
            session.add(event)
            await session.commit()

        self._event_count += 1

    def get_event_count(self) -> int:
        """Get total number of events recorded.

        Returns:
            Total event count (for testing/monitoring)
        """
        return self._event_count
