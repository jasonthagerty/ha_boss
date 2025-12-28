"""Entity discovery service for automations, scenes, and scripts."""

import asyncio
import fnmatch
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from ha_boss.core.config import Config
from ha_boss.core.database import (
    Automation,
    AutomationEntity,
    Database,
    DiscoveryRefresh,
    Scene,
    SceneEntity,
    Script,
    ScriptEntity,
)
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


class EntityExtractor:
    """Extract entity references from Home Assistant automation/scene/script configurations.

    This class provides pure functions for extracting entity_id references from
    automation triggers/conditions/actions, scene entity lists, and script sequences.
    """

    @staticmethod
    def extract_from_automation(
        attrs: dict[str, Any],
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """Extract entity references from automation configuration.

        Args:
            attrs: Automation attributes from Home Assistant state

        Returns:
            Dictionary mapping relationship types to (entity_id, context) tuples:
            {
                "trigger": [(entity_id, context), ...],
                "condition": [(entity_id, context), ...],
                "action": [(entity_id, context), ...]
            }
        """
        result: dict[str, list[tuple[str, dict[str, Any]]]] = {
            "trigger": [],
            "condition": [],
            "action": [],
        }

        # Extract from triggers
        triggers = attrs.get("trigger", [])
        if isinstance(triggers, dict):
            triggers = [triggers]
        elif not isinstance(triggers, list):
            triggers = []

        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            entity_ids = EntityExtractor._extract_entity_ids_recursive(trigger)
            platform = trigger.get("platform", "unknown")
            for entity_id in entity_ids:
                context = {"platform": platform, "config": trigger}
                result["trigger"].append((entity_id, context))

        # Extract from conditions
        conditions = attrs.get("condition", [])
        if isinstance(conditions, dict):
            conditions = [conditions]
        elif not isinstance(conditions, list):
            conditions = []

        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            entity_ids = EntityExtractor._extract_entity_ids_recursive(condition)
            condition_type = condition.get("condition", "unknown")
            for entity_id in entity_ids:
                context = {"condition_type": condition_type, "config": condition}
                result["condition"].append((entity_id, context))

        # Extract from actions
        actions = attrs.get("action", [])
        if isinstance(actions, dict):
            actions = [actions]
        elif not isinstance(actions, list):
            actions = []

        for idx, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            entity_ids = EntityExtractor._extract_entity_ids_recursive(action)
            service = action.get("service", "unknown")
            for entity_id in entity_ids:
                context = {"service": service, "step": idx, "config": action}
                result["action"].append((entity_id, context))

        return result

    @staticmethod
    def extract_from_scene(attrs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Extract entity references from scene configuration.

        Args:
            attrs: Scene attributes from Home Assistant state

        Returns:
            List of (entity_id, context) tuples
        """
        result: list[tuple[str, dict[str, Any]]] = []

        # Scenes have entity_id list in attributes
        # Also check entities_config for nested configuration
        entity_ids_attr = attrs.get("entity_id", [])
        if isinstance(entity_ids_attr, str):
            entity_ids_attr = [entity_ids_attr]

        for entity_id in entity_ids_attr:
            if isinstance(entity_id, str) and entity_id:
                result.append((entity_id, {"source": "entity_id_list"}))

        # Also extract from entities configuration if present
        entities_config = attrs.get("entities", {})
        if isinstance(entities_config, dict):
            for entity_id, entity_config in entities_config.items():
                if isinstance(entity_id, str) and entity_id:
                    context = {"source": "entities_config", "config": entity_config}
                    result.append((entity_id, context))

        return result

    @staticmethod
    def extract_from_script(attrs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Extract entity references from script configuration.

        Args:
            attrs: Script attributes from Home Assistant state

        Returns:
            List of (entity_id, context) tuples
        """
        result: list[tuple[str, dict[str, Any]]] = []

        # Extract from sequence
        sequence = attrs.get("sequence", [])
        if isinstance(sequence, dict):
            sequence = [sequence]
        elif not isinstance(sequence, list):
            sequence = []

        for idx, step in enumerate(sequence):
            if not isinstance(step, dict):
                continue
            entity_ids = EntityExtractor._extract_entity_ids_recursive(step)
            service = step.get("service", step.get("action", "unknown"))
            for entity_id in entity_ids:
                context = {
                    "sequence_step": idx,
                    "service": service,
                    "config": step,
                }
                result.append((entity_id, context))

        return result

    @staticmethod
    def _extract_entity_ids_recursive(item: Any) -> set[str]:
        """Recursively extract entity_id values from nested dict/list structures.

        This handles all the various places entity_id can appear:
        - Direct "entity_id" field (string or list)
        - Nested "target.entity_id"
        - Nested "data.entity_id"
        - Other nested structures

        Args:
            item: Configuration item to search (dict, list, or primitive)

        Returns:
            Set of entity_id strings found
        """
        entity_ids: set[str] = set()

        if isinstance(item, dict):
            for key, value in item.items():
                if key == "entity_id":
                    # Direct entity_id field
                    if isinstance(value, str) and value:
                        entity_ids.add(value)
                    elif isinstance(value, list):
                        for entity_id in value:
                            if isinstance(entity_id, str) and entity_id:
                                entity_ids.add(entity_id)
                else:
                    # Recurse into nested structures
                    entity_ids.update(EntityExtractor._extract_entity_ids_recursive(value))

        elif isinstance(item, list):
            # Recurse into list items
            for sub_item in item:
                entity_ids.update(EntityExtractor._extract_entity_ids_recursive(sub_item))

        # Filter out invalid entity IDs (must contain a domain separator)
        return {eid for eid in entity_ids if "." in eid}


class EntityDiscoveryService:
    """Service for discovering and tracking entities from automations, scenes, and scripts.

    This service scans Home Assistant automations, scenes, and scripts to automatically
    build a monitored entity set. It extracts entity references, stores relationships
    in the database, and merges with config.yaml patterns.
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        database: Database,
        config: Config,
    ) -> None:
        """Initialize entity discovery service.

        Args:
            ha_client: Home Assistant API client
            database: Database manager
            config: HA Boss configuration
        """
        self.ha_client = ha_client
        self.database = database
        self.config = config

        # In-memory state
        self._monitored_set: set[str] = set()
        self._auto_discovered_entities: set[str] = set()
        self._refresh_lock = asyncio.Lock()
        self._periodic_task: asyncio.Task[None] | None = None

    async def discover_and_refresh(
        self, trigger_type: str, trigger_source: str | None = None
    ) -> dict[str, int]:
        """Perform full discovery cycle with database persistence.

        Args:
            trigger_type: Type of trigger (startup/manual/periodic/event)
            trigger_source: Source of trigger (optional details)

        Returns:
            Statistics dictionary with counts
        """
        async with self._refresh_lock:
            logger.info(f"Starting discovery refresh (trigger={trigger_type})")
            start_time = time.time()
            stats = {
                "automations_found": 0,
                "scenes_found": 0,
                "scripts_found": 0,
                "entities_discovered": 0,
            }

            try:
                # Fetch and process automations, scenes, scripts
                if self.config.monitoring.auto_discovery.enabled:
                    stats["automations_found"] = await self._fetch_and_process_automations()

                    if self.config.monitoring.auto_discovery.include_scenes:
                        stats["scenes_found"] = await self._fetch_and_process_scenes()

                    if self.config.monitoring.auto_discovery.include_scripts:
                        stats["scripts_found"] = await self._fetch_and_process_scripts()

                # Build monitored entity set
                await self._build_monitored_set()
                stats["entities_discovered"] = len(self._auto_discovered_entities)

                # Record successful refresh
                duration = time.time() - start_time
                await self._record_refresh(
                    trigger_type=trigger_type,
                    trigger_source=trigger_source,
                    stats=stats,
                    duration=duration,
                    success=True,
                )

                logger.info(
                    f"Discovery refresh completed: {stats['automations_found']} automations, "
                    f"{stats['scenes_found']} scenes, {stats['scripts_found']} scripts, "
                    f"{stats['entities_discovered']} entities discovered ({duration:.2f}s)"
                )

                return stats

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Discovery refresh failed: {e}", exc_info=True)

                # Record failed refresh
                await self._record_refresh(
                    trigger_type=trigger_type,
                    trigger_source=trigger_source,
                    stats=stats,
                    duration=duration,
                    success=False,
                    error=str(e),
                )

                raise

    async def _fetch_and_process_automations(self) -> int:
        """Fetch automations from HA and store in database.

        Returns:
            Number of automations processed
        """
        logger.debug("Fetching automations from Home Assistant")
        states = await self.ha_client.get_states()
        automations = [s for s in states if s.get("entity_id", "").startswith("automation.")]

        # Filter disabled automations if configured
        if self.config.monitoring.auto_discovery.skip_disabled_automations:
            automations = [a for a in automations if a.get("state") == "on"]

        logger.debug(f"Processing {len(automations)} automations")

        # Clear existing automation relationships
        async with self.database.async_session() as session:
            await session.execute(delete(AutomationEntity))
            await session.commit()

        # Process each automation
        for auto_state in automations:
            await self._process_automation(auto_state)

        return len(automations)

    async def _process_automation(self, auto_state: dict[str, Any]) -> None:
        """Process a single automation and store in database.

        Args:
            auto_state: Automation state from Home Assistant
        """
        entity_id = auto_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = auto_state.get("attributes", {})
        state = auto_state.get("state", "off")

        # Extract entity references
        entity_refs = EntityExtractor.extract_from_automation(attrs)

        async with self.database.async_session() as session:
            # Upsert automation record
            automation = Automation(
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                state=state,
                mode=attrs.get("mode"),
                trigger_config=attrs.get("trigger"),
                condition_config=attrs.get("condition"),
                action_config=attrs.get("action"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            # Merge to handle existing records
            await session.merge(automation)

            # Insert automation-entity relationships
            for relationship_type, entities in entity_refs.items():
                for entity_ref_id, context in entities:
                    relationship = AutomationEntity(
                        automation_id=entity_id,
                        entity_id=entity_ref_id,
                        relationship_type=relationship_type,
                        context=context,
                        discovered_at=datetime.now(UTC),
                    )
                    await session.merge(relationship)

            await session.commit()

    async def _fetch_and_process_scenes(self) -> int:
        """Fetch scenes from HA and store in database.

        Returns:
            Number of scenes processed
        """
        logger.debug("Fetching scenes from Home Assistant")
        states = await self.ha_client.get_states()
        scenes = [s for s in states if s.get("entity_id", "").startswith("scene.")]

        logger.debug(f"Processing {len(scenes)} scenes")

        # Clear existing scene relationships
        async with self.database.async_session() as session:
            await session.execute(delete(SceneEntity))
            await session.commit()

        # Process each scene
        for scene_state in scenes:
            await self._process_scene(scene_state)

        return len(scenes)

    async def _process_scene(self, scene_state: dict[str, Any]) -> None:
        """Process a single scene and store in database.

        Args:
            scene_state: Scene state from Home Assistant
        """
        entity_id = scene_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = scene_state.get("attributes", {})

        # Extract entity references
        entity_refs = EntityExtractor.extract_from_scene(attrs)

        async with self.database.async_session() as session:
            # Upsert scene record
            scene = Scene(
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                entities_config=attrs.get("entities"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(scene)

            # Insert scene-entity relationships
            for entity_ref_id, context in entity_refs:
                relationship = SceneEntity(
                    scene_id=entity_id,
                    entity_id=entity_ref_id,
                    target_state=context.get("config", {}).get("state"),
                    attributes=context.get("config", {}).get("attributes"),
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _fetch_and_process_scripts(self) -> int:
        """Fetch scripts from HA and store in database.

        Returns:
            Number of scripts processed
        """
        logger.debug("Fetching scripts from Home Assistant")
        states = await self.ha_client.get_states()
        scripts = [s for s in states if s.get("entity_id", "").startswith("script.")]

        logger.debug(f"Processing {len(scripts)} scripts")

        # Clear existing script relationships
        async with self.database.async_session() as session:
            await session.execute(delete(ScriptEntity))
            await session.commit()

        # Process each script
        for script_state in scripts:
            await self._process_script(script_state)

        return len(scripts)

    async def _process_script(self, script_state: dict[str, Any]) -> None:
        """Process a single script and store in database.

        Args:
            script_state: Script state from Home Assistant
        """
        entity_id = script_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = script_state.get("attributes", {})

        # Extract entity references
        entity_refs = EntityExtractor.extract_from_script(attrs)

        async with self.database.async_session() as session:
            # Upsert script record
            script = Script(
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                mode=attrs.get("mode"),
                sequence_config=attrs.get("sequence"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(script)

            # Insert script-entity relationships
            for entity_ref_id, context in entity_refs:
                relationship = ScriptEntity(
                    script_id=entity_id,
                    entity_id=entity_ref_id,
                    sequence_step=context.get("sequence_step"),
                    action_type=context.get("service"),
                    context=context,
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _build_monitored_set(self) -> None:
        """Build final monitored entity set from auto-discovered + config patterns.

        Formula: (auto_discovered ∪ config.include) - config.exclude
        """
        # Get all auto-discovered entities from database
        auto_discovered: set[str] = set()

        async with self.database.async_session() as session:
            # Get entities from automation relationships
            result = await session.execute(select(AutomationEntity.entity_id).distinct())
            auto_discovered.update(entity_id for (entity_id,) in result.all())

            # Get entities from scene relationships
            result = await session.execute(select(SceneEntity.entity_id).distinct())
            auto_discovered.update(entity_id for (entity_id,) in result.all())

            # Get entities from script relationships
            result = await session.execute(select(ScriptEntity.entity_id).distinct())
            auto_discovered.update(entity_id for (entity_id,) in result.all())

        self._auto_discovered_entities = auto_discovered

        # Apply config.include patterns (ADD to auto-discovered)
        # For include patterns, we need to get all entities from HA and match patterns
        # For MVP, we'll just use auto-discovered + manual patterns from include
        monitored = auto_discovered.copy()

        # Note: config.include patterns would need entity list from StateTracker
        # For now, we just use auto-discovered entities
        # In StateTracker integration, it will handle include patterns

        # Apply config.exclude patterns (REMOVE)
        excluded: set[str] = set()
        for pattern in self.config.monitoring.exclude:
            excluded.update(
                entity_id for entity_id in monitored if fnmatch.fnmatch(entity_id, pattern)
            )

        monitored -= excluded

        self._monitored_set = monitored
        logger.debug(
            f"Built monitored set: {len(auto_discovered)} auto-discovered, "
            f"{len(excluded)} excluded, {len(monitored)} final"
        )

    async def _record_refresh(
        self,
        trigger_type: str,
        trigger_source: str | None,
        stats: dict[str, int],
        duration: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record discovery refresh in database.

        Args:
            trigger_type: Type of trigger
            trigger_source: Source of trigger
            stats: Discovery statistics
            duration: Duration in seconds
            success: Whether refresh succeeded
            error: Error message if failed
        """
        async with self.database.async_session() as session:
            refresh = DiscoveryRefresh(
                trigger_type=trigger_type,
                trigger_source=trigger_source,
                automations_found=stats["automations_found"],
                scenes_found=stats["scenes_found"],
                scripts_found=stats["scripts_found"],
                entities_discovered=stats["entities_discovered"],
                duration_seconds=duration,
                timestamp=datetime.now(UTC),
                success=success,
                error_message=error,
            )
            session.add(refresh)
            await session.commit()

    def is_entity_monitored(self, entity_id: str) -> bool:
        """Check if entity is in the monitored set.

        Args:
            entity_id: Entity to check

        Returns:
            True if entity should be monitored
        """
        # If auto-discovery is disabled, return True (defer to StateTracker filtering)
        if not self.config.monitoring.auto_discovery.enabled:
            return True

        return entity_id in self._monitored_set

    def get_monitored_entities(self) -> set[str]:
        """Get current monitored entity set.

        Returns:
            Set of entity IDs to monitor
        """
        return self._monitored_set.copy()

    async def start_periodic_refresh(self, interval_seconds: int) -> None:
        """Start periodic discovery refresh background task.

        Args:
            interval_seconds: Refresh interval (0 = disabled)
        """
        if interval_seconds <= 0:
            logger.info("Periodic discovery refresh disabled (interval=0)")
            return

        if self._periodic_task and not self._periodic_task.done():
            logger.warning("Periodic refresh already running")
            return

        logger.info(f"Starting periodic discovery refresh (interval={interval_seconds}s)")

        async def refresh_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await self.discover_and_refresh(
                        trigger_type="periodic", trigger_source="background_task"
                    )
                except asyncio.CancelledError:
                    logger.info("Periodic refresh task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Periodic refresh failed: {e}", exc_info=True)
                    # Continue running despite errors

        self._periodic_task = asyncio.create_task(refresh_loop())

    async def stop_periodic_refresh(self) -> None:
        """Stop periodic discovery refresh background task."""
        if self._periodic_task and not self._periodic_task.done():
            logger.info("Stopping periodic discovery refresh")
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass
            self._periodic_task = None

    async def get_automations_for_entity(self, entity_id: str) -> list[dict[str, Any]]:
        """Get all automations that use a specific entity.

        Args:
            entity_id: Entity to search for

        Returns:
            List of automation details with relationship info
        """
        results: list[dict[str, Any]] = []

        async with self.database.async_session() as session:
            # Query automation-entity relationships
            query = (
                select(Automation, AutomationEntity)
                .join(AutomationEntity, Automation.entity_id == AutomationEntity.automation_id)
                .where(AutomationEntity.entity_id == entity_id)
            )

            result = await session.execute(query)
            for automation, relationship in result.all():
                results.append(
                    {
                        "automation_id": automation.entity_id,
                        "friendly_name": automation.friendly_name,
                        "state": automation.state,
                        "relationship_type": relationship.relationship_type,
                        "context": relationship.context,
                    }
                )

        return results
