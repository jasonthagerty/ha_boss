"""Integration discovery and management for Home Assistant auto-healing.

This module provides functionality to discover and map Home Assistant entities
to their parent integrations, enabling targeted integration reloads.
"""

import json
import logging
from pathlib import Path
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.database import Database, Integration
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


class IntegrationDiscovery:
    """Discovers and maps Home Assistant entities to their parent integrations.

    Provides multiple discovery methods with fallback:
    1. Storage file parsing (most reliable if accessible)
    2. API-based entity→device→integration mapping
    3. User-provided manual mappings

    Maintains an in-memory cache for fast lookups and persists to database.
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        database: Database,
        config: Config,
    ) -> None:
        """Initialize integration discovery.

        Args:
            ha_client: Home Assistant API client
            database: Database instance for persistence
            config: Configuration instance
        """
        self.ha_client = ha_client
        self.database = database
        self.config = config

        # In-memory cache: entity_id -> integration_entry_id
        self._entity_to_integration: dict[str, str] = {}

        # In-memory cache: integration_entry_id -> integration details
        self._integrations: dict[str, dict[str, Any]] = {}

    async def discover_all(self, storage_path: Path | None = None) -> dict[str, str]:
        """Discover all entity→integration mappings.

        Attempts multiple discovery methods in priority order:
        1. Storage file parsing (if path provided)
        2. API-based discovery
        3. Load from database cache

        Args:
            storage_path: Optional path to HA storage directory

        Returns:
            Dictionary mapping entity_id to integration_entry_id

        Raises:
            Exception: If all discovery methods fail
        """
        logger.info("Starting integration discovery")

        # Try storage file parsing first (most reliable)
        if storage_path:
            try:
                await self._discover_from_storage(storage_path)
                logger.info(
                    f"Discovered {len(self._entity_to_integration)} " f"entities from storage files"
                )
            except Exception as e:
                logger.warning(f"Storage file discovery failed: {e}")

        # Try API-based discovery
        if not self._entity_to_integration:
            try:
                await self._discover_from_api()
                logger.info(f"Discovered {len(self._entity_to_integration)} " f"entities from API")
            except Exception as e:
                logger.warning(f"API-based discovery failed: {e}")

        # Load from database cache as fallback
        if not self._entity_to_integration:
            try:
                await self._load_from_database()
                logger.info(
                    f"Loaded {len(self._entity_to_integration)} " f"entities from database cache"
                )
            except Exception as e:
                logger.warning(f"Database cache load failed: {e}")

        # Persist discoveries to database
        if self._entity_to_integration:
            await self._save_to_database()

        if not self._entity_to_integration:
            logger.error("All discovery methods failed")
            raise Exception("Failed to discover any integrations")

        return self._entity_to_integration

    async def _discover_from_storage(self, storage_path: Path) -> None:
        """Discover integrations by parsing HA storage files.

        Args:
            storage_path: Path to HA .storage directory

        Raises:
            FileNotFoundError: If storage files not found
            json.JSONDecodeError: If files cannot be parsed
        """
        config_entries_file = storage_path / "core.config_entries"

        if not config_entries_file.exists():
            raise FileNotFoundError(f"Config entries file not found: {config_entries_file}")

        with open(config_entries_file) as f:
            data = json.load(f)

        entries = data.get("data", {}).get("entries", [])

        # Build integration details cache
        for entry in entries:
            entry_id = entry.get("entry_id")
            domain = entry.get("domain")
            title = entry.get("title")

            if entry_id and domain:
                self._integrations[entry_id] = {
                    "entry_id": entry_id,
                    "domain": domain,
                    "title": title or domain,
                    "source": "storage_file",
                }

        # Get entity registry to map entities to config entries
        entity_registry_file = storage_path / "core.entity_registry"

        if entity_registry_file.exists():
            with open(entity_registry_file) as f:
                entity_data = json.load(f)

            entities = entity_data.get("data", {}).get("entities", [])

            for entity in entities:
                entity_id = entity.get("entity_id")
                config_entry_id = entity.get("config_entry_id")

                if entity_id and config_entry_id:
                    self._entity_to_integration[entity_id] = config_entry_id

        logger.debug(
            f"Parsed {len(self._integrations)} integrations and "
            f"{len(self._entity_to_integration)} entities from storage"
        )

    async def _discover_from_api(self) -> None:
        """Discover integrations using Home Assistant API.

        Uses the device registry and entity registry APIs to map
        entities to their parent integrations via devices.

        Note: This method may not work for all entity types (some entities
        don't have device associations).
        """
        # Get all entities
        states = await self.ha_client.get_states()

        # Try to get config from API (may contain integration info)
        try:
            config = await self.ha_client.get_config()
            logger.debug(f"Retrieved HA config: version {config.get('version')}")
        except Exception as e:
            logger.warning(f"Could not retrieve HA config: {e}")

        # For now, we'll implement a basic mapping based on entity domains
        # This is a fallback when storage files aren't accessible
        # A more sophisticated implementation would query additional APIs

        for state in states:
            entity_id = state.get("entity_id", "")
            if not entity_id:
                continue

            # Extract domain from entity_id (e.g., "sensor" from "sensor.temperature")
            domain = entity_id.split(".")[0] if "." in entity_id else None

            if domain:
                # Use domain as a pseudo-entry-id for entities without
                # explicit integration mapping
                # This allows basic healing by domain even without full discovery
                entry_id = f"domain_{domain}"

                self._entity_to_integration[entity_id] = entry_id

                # Track domain-based pseudo-integration
                if entry_id not in self._integrations:
                    self._integrations[entry_id] = {
                        "entry_id": entry_id,
                        "domain": domain,
                        "title": domain.title(),
                        "source": "api_domain",
                    }

        logger.debug(
            f"Mapped {len(self._entity_to_integration)} entities " f"from API (domain-based)"
        )

    async def _load_from_database(self) -> None:
        """Load cached integration mappings from database."""
        async with self.database.async_session() as session:
            from sqlalchemy import select

            result = await session.execute(select(Integration))
            integrations = result.scalars().all()

            for integration in integrations:
                self._integrations[integration.entry_id] = {
                    "entry_id": integration.entry_id,
                    "domain": integration.domain,
                    "title": integration.title,
                    "source": "database_cache",
                }

                # Restore entity mappings if available
                if integration.entity_ids:
                    entity_ids = json.loads(integration.entity_ids)
                    for entity_id in entity_ids:
                        self._entity_to_integration[entity_id] = integration.entry_id

    async def _save_to_database(self) -> None:
        """Persist discovered integrations to database."""
        async with self.database.async_session() as session:
            from sqlalchemy import select

            # Group entities by integration
            integration_entities: dict[str, list[str]] = {}
            for entity_id, entry_id in self._entity_to_integration.items():
                integration_entities.setdefault(entry_id, []).append(entity_id)

            # Save or update each integration
            for entry_id, details in self._integrations.items():
                result = await session.execute(
                    select(Integration).where(Integration.entry_id == entry_id)
                )
                existing = result.scalar_one_or_none()

                entity_ids_json = json.dumps(integration_entities.get(entry_id, []))

                if existing:
                    # Update existing
                    existing.domain = details["domain"]
                    existing.title = details["title"]
                    existing.entity_ids = entity_ids_json
                    existing.is_discovered = True
                else:
                    # Create new
                    integration = Integration(
                        entry_id=entry_id,
                        domain=details["domain"],
                        title=details["title"],
                        entity_ids=entity_ids_json,
                        is_discovered=True,
                    )
                    session.add(integration)

            await session.commit()

        logger.info(f"Saved {len(self._integrations)} integrations to database")

    def get_integration_for_entity(self, entity_id: str) -> str | None:
        """Get integration entry ID for a given entity.

        Args:
            entity_id: Entity ID to look up

        Returns:
            Integration entry ID, or None if not found
        """
        return self._entity_to_integration.get(entity_id)

    def get_integration_details(self, entry_id: str) -> dict[str, Any] | None:
        """Get integration details for a given entry ID.

        Args:
            entry_id: Integration entry ID

        Returns:
            Dictionary with integration details, or None if not found
        """
        return self._integrations.get(entry_id)

    def get_all_integrations(self) -> dict[str, dict[str, Any]]:
        """Get all discovered integrations.

        Returns:
            Dictionary mapping entry_id to integration details
        """
        return self._integrations.copy()

    def get_entity_count(self) -> int:
        """Get total number of mapped entities.

        Returns:
            Count of entities with integration mappings
        """
        return len(self._entity_to_integration)

    async def add_manual_mapping(
        self, entity_id: str, entry_id: str, domain: str, title: str | None = None
    ) -> None:
        """Manually add an entity→integration mapping.

        Useful for entities that couldn't be discovered automatically.

        Args:
            entity_id: Entity ID to map
            entry_id: Integration entry ID
            domain: Integration domain
            title: Optional human-readable title
        """
        self._entity_to_integration[entity_id] = entry_id

        if entry_id not in self._integrations:
            self._integrations[entry_id] = {
                "entry_id": entry_id,
                "domain": domain,
                "title": title or domain,
                "source": "manual",
            }

        # Persist to database
        await self._save_to_database()

        logger.info(f"Added manual mapping: {entity_id} -> {entry_id}")
