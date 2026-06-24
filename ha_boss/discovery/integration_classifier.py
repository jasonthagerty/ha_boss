"""Classify entities by their integration's IoT class (cloud vs local).

Builds an ``entity_id -> iot_class`` map by combining two WS-only Home Assistant
APIs:

* ``manifest/list``            -> integration ``domain -> iot_class``
* ``config/entity_registry/list`` -> ``entity_id -> platform`` (integration domain)

This lets HA Boss recognise internet-dependent (cloud) integrations — e.g.
PlayStation Network, Plex, Life360 — which flap ``unavailable`` based on
external availability that HA Boss cannot heal, and treat them more gently
(longer grace, no mobile push) instead of paging on every blip.

Degrades safely: if the refresh fails, the classifier simply reports every
entity as non-cloud, so callers fall back to default behaviour.
"""

import logging

from sqlalchemy import update

from ha_boss.core.config import Config
from ha_boss.core.database import Database, Integration
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


class IntegrationClassifier:
    """Maps entities to their integration's IoT class and flags cloud entities."""

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        config: Config,
        database: Database | None = None,
        instance_id: str = "default",
    ) -> None:
        """Initialise the classifier.

        Args:
            ha_client: HA client used for the manifest / entity-registry WS calls.
            config: HA Boss configuration (reads ``monitoring.cloud_handling``).
            database: Optional database; when provided, discovered iot_class values
                are persisted onto the ``integrations`` rows for visibility.
            instance_id: Home Assistant instance identifier.
        """
        self.ha_client = ha_client
        self.config = config
        self.database = database
        self.instance_id = instance_id

        # entity_id -> iot_class (e.g. "cloud_polling"); only populated entries kept
        self._entity_iot_class: dict[str, str] = {}
        # integration domain -> iot_class
        self._domain_iot_class: dict[str, str] = {}

    async def refresh(self) -> int:
        """Rebuild the entity→iot_class map from HA manifests + entity registry.

        Returns:
            Number of entities with a resolved iot_class.

        Raises:
            Exception: Propagates WS/transport errors so the caller can decide
                whether to continue without classification.
        """
        manifests = await self.ha_client.get_integration_manifests()
        domain_iot: dict[str, str] = {}
        for manifest in manifests:
            domain = manifest.get("domain")
            iot_class = manifest.get("iot_class")
            if domain and iot_class:
                domain_iot[domain] = iot_class

        registry = await self.ha_client.get_entity_registry()
        entity_iot: dict[str, str] = {}
        for entry in registry:
            entity_id = entry.get("entity_id")
            platform = entry.get("platform")
            if entity_id and platform:
                iot_class = domain_iot.get(platform)
                if iot_class:
                    entity_iot[entity_id] = iot_class

        self._domain_iot_class = domain_iot
        self._entity_iot_class = entity_iot

        cloud_classes = set(self.config.monitoring.cloud_handling.iot_classes)
        cloud_count = sum(1 for c in entity_iot.values() if c in cloud_classes)
        logger.info(
            f"[{self.instance_id}] Integration classifier: {len(entity_iot)} entities "
            f"classified across {len(domain_iot)} integrations ({cloud_count} cloud)"
        )

        if self.database is not None:
            await self._persist_iot_classes(domain_iot)

        return len(entity_iot)

    def iot_class_for(self, entity_id: str) -> str | None:
        """Return the iot_class for an entity, or None if unknown."""
        return self._entity_iot_class.get(entity_id)

    def is_cloud(self, entity_id: str) -> bool:
        """Whether an entity belongs to a cloud (internet-dependent) integration.

        Returns False when cloud handling is disabled or the entity's iot_class is
        unknown / not in the configured cloud set.
        """
        if not self.config.monitoring.cloud_handling.enabled:
            return False
        iot_class = self._entity_iot_class.get(entity_id)
        return iot_class in set(self.config.monitoring.cloud_handling.iot_classes)

    async def _persist_iot_classes(self, domain_iot: dict[str, str]) -> None:
        """Best-effort: write iot_class onto existing integration rows by domain."""
        if self.database is None:
            return
        try:
            async with self.database.async_session() as session:
                for domain, iot_class in domain_iot.items():
                    await session.execute(
                        update(Integration)
                        .where(
                            Integration.instance_id == self.instance_id,
                            Integration.domain == domain,
                        )
                        .values(iot_class=iot_class)
                    )
                await session.commit()
        except Exception as e:  # pragma: no cover - persistence is non-critical
            logger.debug(f"[{self.instance_id}] Failed to persist iot_class values: {e}")
