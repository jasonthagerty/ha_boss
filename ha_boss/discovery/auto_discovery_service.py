"""Multi-instance auto-discovery service with HA Boss Bridge support."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp
from sqlalchemy import delete, select, union_all

from ha_boss.core.config import Config, HomeAssistantInstance
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
from ha_boss.discovery.bridge_client import BridgeClient
from ha_boss.discovery.entity_discovery import EntityExtractor

logger = logging.getLogger(__name__)


class AutoDiscoveryService:
    """Orchestrate multi-instance entity discovery with HA Boss Bridge support.

    This service manages discovery across multiple Home Assistant instances,
    attempting to use HA Boss Bridge for full configuration access and falling
    back gracefully to standard /api/states when bridge is unavailable.
    """

    def __init__(
        self,
        config: Config,
        database: Database,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize auto-discovery service.

        Args:
            config: HA Boss configuration
            database: Database manager
            session: Shared aiohttp session
        """
        self.config = config
        self.database = database
        self.session = session

        # Bridge clients per instance (lazy initialization)
        self._bridge_clients: dict[str, BridgeClient] = {}

        # HA clients per instance (lazy initialization)
        self._ha_clients: dict[str, HomeAssistantClient] = {}

    def _get_bridge_client(self, instance: HomeAssistantInstance) -> BridgeClient:
        """Get or create bridge client for instance.

        Args:
            instance: HA instance configuration

        Returns:
            Bridge client for this instance
        """
        if instance.instance_id not in self._bridge_clients:
            self._bridge_clients[instance.instance_id] = BridgeClient(instance, self.session)
        return self._bridge_clients[instance.instance_id]

    def _get_ha_client(self, instance: HomeAssistantInstance) -> HomeAssistantClient:
        """Get or create HA client for instance.

        Args:
            instance: HA instance configuration

        Returns:
            HA client for this instance
        """
        if instance.instance_id not in self._ha_clients:
            # Create client with instance URL and token
            self._ha_clients[instance.instance_id] = HomeAssistantClient(
                base_url=instance.url,
                token=instance.token,
                session=self.session,
            )
        return self._ha_clients[instance.instance_id]

    async def discover_all_instances(
        self, trigger_type: str = "manual", trigger_source: str | None = None
    ) -> dict[str, dict[str, int]]:
        """Discover entities across all configured instances.

        Args:
            trigger_type: Type of trigger (startup/manual/periodic)
            trigger_source: Source of trigger (optional)

        Returns:
            Dictionary mapping instance_id to discovery statistics
        """
        logger.info(
            "Starting multi-instance discovery for %d instances",
            len(self.config.home_assistant.instances),
        )

        results = {}

        # Discover each instance in parallel
        tasks = [
            self.discover_instance(instance, trigger_type, trigger_source)
            for instance in self.config.home_assistant.instances
        ]

        instance_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        for instance, result in zip(
            self.config.home_assistant.instances, instance_results, strict=True
        ):
            if isinstance(result, Exception):
                logger.error(
                    "Discovery failed for instance %s: %s",
                    instance.instance_id,
                    result,
                    exc_info=result,
                )
                results[instance.instance_id] = {
                    "error": str(result),
                    "automations_found": 0,
                    "scenes_found": 0,
                    "scripts_found": 0,
                    "entities_discovered": 0,
                }
            else:
                results[instance.instance_id] = result

        logger.info("Multi-instance discovery completed for %d instances", len(results))
        return results

    async def discover_instance(
        self,
        instance: HomeAssistantInstance,
        trigger_type: str = "manual",
        trigger_source: str | None = None,
    ) -> dict[str, int]:
        """Discover entities for a single instance.

        Args:
            instance: HA instance to discover
            trigger_type: Type of trigger
            trigger_source: Source of trigger

        Returns:
            Discovery statistics
        """
        logger.info("Starting discovery for instance %s", instance.instance_id)

        stats = {
            "automations_found": 0,
            "scenes_found": 0,
            "scripts_found": 0,
            "entities_discovered": 0,
            "used_bridge": False,
        }

        start_time = datetime.now(UTC)

        try:
            # Try bridge first if enabled
            bridge_client = self._get_bridge_client(instance)

            if instance.bridge_enabled and await bridge_client.is_available():
                logger.info("Using HA Boss Bridge for instance %s", instance.instance_id)
                stats["used_bridge"] = True

                # Fetch via bridge
                if self.config.monitoring.auto_discovery.enabled:
                    stats["automations_found"] = await self._discover_automations_via_bridge(
                        instance, bridge_client
                    )

                    if self.config.monitoring.auto_discovery.include_scenes:
                        stats["scenes_found"] = await self._discover_scenes_via_bridge(
                            instance, bridge_client
                        )

                    if self.config.monitoring.auto_discovery.include_scripts:
                        stats["scripts_found"] = await self._discover_scripts_via_bridge(
                            instance, bridge_client
                        )
            else:
                logger.info(
                    "Bridge not available for instance %s, using fallback mode",
                    instance.instance_id,
                )
                stats["used_bridge"] = False

                # Fallback to standard /api/states
                ha_client = self._get_ha_client(instance)

                if self.config.monitoring.auto_discovery.enabled:
                    stats["automations_found"] = await self._discover_automations_via_states(
                        instance, ha_client
                    )

                    if self.config.monitoring.auto_discovery.include_scenes:
                        stats["scenes_found"] = await self._discover_scenes_via_states(
                            instance, ha_client
                        )

                    if self.config.monitoring.auto_discovery.include_scripts:
                        stats["scripts_found"] = await self._discover_scripts_via_states(
                            instance, ha_client
                        )

            # TODO: Count unique entities discovered (need to query junction tables)
            stats["entities_discovered"] = await self._count_discovered_entities(instance)

            # Record successful discovery
            duration = (datetime.now(UTC) - start_time).total_seconds()
            await self._record_refresh(
                instance_id=instance.instance_id,
                trigger_type=trigger_type,
                trigger_source=trigger_source,
                stats=stats,
                duration=duration,
                success=True,
            )

            logger.info(
                "Discovery completed for instance %s: %d automations, %d scenes, %d scripts "
                "(bridge=%s, %.2fs)",
                instance.instance_id,
                stats["automations_found"],
                stats["scenes_found"],
                stats["scripts_found"],
                stats["used_bridge"],
                duration,
            )

            return stats

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            logger.error(
                "Discovery failed for instance %s: %s",
                instance.instance_id,
                e,
                exc_info=True,
            )

            # Record failed discovery
            await self._record_refresh(
                instance_id=instance.instance_id,
                trigger_type=trigger_type,
                trigger_source=trigger_source,
                stats=stats,
                duration=duration,
                success=False,
                error=str(e),
            )

            raise

    async def _discover_automations_via_bridge(
        self, instance: HomeAssistantInstance, bridge_client: BridgeClient
    ) -> int:
        """Discover automations using bridge with full configs.

        Args:
            instance: HA instance
            bridge_client: Bridge client

        Returns:
            Number of automations discovered
        """
        automations = await bridge_client.get_automations()
        logger.debug(
            "Fetched %d automations from bridge for %s", len(automations), instance.instance_id
        )

        # Clear existing automation relationships for this instance
        async with self.database.async_session() as session:
            await session.execute(
                delete(AutomationEntity).where(AutomationEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        # Process each automation
        for automation in automations:
            await self._process_automation_from_bridge(instance, automation)

        return len(automations)

    async def _process_automation_from_bridge(
        self, instance: HomeAssistantInstance, automation_data: dict[str, Any]
    ) -> None:
        """Process automation from bridge response.

        Args:
            instance: HA instance
            automation_data: Automation data from bridge
        """
        entity_id = automation_data.get("entity_id", "")
        if not entity_id:
            return

        # Extract entity references from full config
        entity_refs = EntityExtractor.extract_from_automation(automation_data)

        async with self.database.async_session() as session:
            # Upsert automation record
            automation = Automation(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=automation_data.get("friendly_name"),
                state=automation_data.get("state", "off"),
                mode=automation_data.get("mode"),
                trigger_config=automation_data.get("trigger"),
                condition_config=automation_data.get("condition"),
                action_config=automation_data.get("action"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(automation)

            # Insert automation-entity relationships
            for relationship_type, entities in entity_refs.items():
                for entity_ref_id, context in entities:
                    relationship = AutomationEntity(
                        instance_id=instance.instance_id,
                        automation_id=entity_id,
                        entity_id=entity_ref_id,
                        relationship_type=relationship_type,
                        context=context,
                        discovered_at=datetime.now(UTC),
                    )
                    await session.merge(relationship)

            await session.commit()

    async def _discover_automations_via_states(
        self, instance: HomeAssistantInstance, ha_client: HomeAssistantClient
    ) -> int:
        """Discover automations using fallback /api/states (limited data).

        Args:
            instance: HA instance
            ha_client: HA client

        Returns:
            Number of automations discovered
        """
        states = await ha_client.get_states()
        automations = [s for s in states if s.get("entity_id", "").startswith("automation.")]

        # Filter disabled if configured
        if self.config.monitoring.auto_discovery.skip_disabled_automations:
            automations = [a for a in automations if a.get("state") == "on"]

        logger.debug(
            "Fetched %d automations from /api/states for %s (limited data)",
            len(automations),
            instance.instance_id,
        )

        # Clear existing
        async with self.database.async_session() as session:
            await session.execute(
                delete(AutomationEntity).where(AutomationEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        # Process each
        for auto_state in automations:
            await self._process_automation_from_states(instance, auto_state)

        return len(automations)

    async def _process_automation_from_states(
        self, instance: HomeAssistantInstance, auto_state: dict[str, Any]
    ) -> None:
        """Process automation from /api/states (limited data).

        Args:
            instance: HA instance
            auto_state: Automation state from /api/states
        """
        entity_id = auto_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = auto_state.get("attributes", {})

        # Extract what we can from attributes (usually limited)
        entity_refs = EntityExtractor.extract_from_automation(attrs)

        async with self.database.async_session() as session:
            automation = Automation(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                state=auto_state.get("state", "off"),
                mode=attrs.get("mode"),
                trigger_config=attrs.get("trigger"),  # Usually None from /api/states
                condition_config=attrs.get("condition"),
                action_config=attrs.get("action"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(automation)

            # Insert relationships (if any were extractable)
            for relationship_type, entities in entity_refs.items():
                for entity_ref_id, context in entities:
                    relationship = AutomationEntity(
                        instance_id=instance.instance_id,
                        automation_id=entity_id,
                        entity_id=entity_ref_id,
                        relationship_type=relationship_type,
                        context=context,
                        discovered_at=datetime.now(UTC),
                    )
                    await session.merge(relationship)

            await session.commit()

    async def _discover_scenes_via_bridge(
        self, instance: HomeAssistantInstance, bridge_client: BridgeClient
    ) -> int:
        """Discover scenes using bridge."""
        scenes = await bridge_client.get_scenes()

        async with self.database.async_session() as session:
            await session.execute(
                delete(SceneEntity).where(SceneEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        for scene_data in scenes:
            await self._process_scene_from_bridge(instance, scene_data)

        return len(scenes)

    async def _process_scene_from_bridge(
        self, instance: HomeAssistantInstance, scene_data: dict[str, Any]
    ) -> None:
        """Process scene from bridge response."""
        entity_id = scene_data.get("entity_id", "")
        if not entity_id:
            return

        entity_refs = EntityExtractor.extract_from_scene(scene_data)

        async with self.database.async_session() as session:
            scene = Scene(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=scene_data.get("friendly_name"),
                entities_config=scene_data.get("entities"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(scene)

            for entity_ref_id, context in entity_refs:
                relationship = SceneEntity(
                    instance_id=instance.instance_id,
                    scene_id=entity_id,
                    entity_id=entity_ref_id,
                    target_state=context.get("config", {}).get("state"),
                    attributes=context.get("config", {}).get("attributes"),
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _discover_scenes_via_states(
        self, instance: HomeAssistantInstance, ha_client: HomeAssistantClient
    ) -> int:
        """Discover scenes using /api/states fallback."""
        states = await ha_client.get_states()
        scenes = [s for s in states if s.get("entity_id", "").startswith("scene.")]

        async with self.database.async_session() as session:
            await session.execute(
                delete(SceneEntity).where(SceneEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        for scene_state in scenes:
            await self._process_scene_from_states(instance, scene_state)

        return len(scenes)

    async def _process_scene_from_states(
        self, instance: HomeAssistantInstance, scene_state: dict[str, Any]
    ) -> None:
        """Process scene from /api/states."""
        entity_id = scene_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = scene_state.get("attributes", {})
        entity_refs = EntityExtractor.extract_from_scene(attrs)

        async with self.database.async_session() as session:
            scene = Scene(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                entities_config=attrs.get("entities"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(scene)

            for entity_ref_id, context in entity_refs:
                relationship = SceneEntity(
                    instance_id=instance.instance_id,
                    scene_id=entity_id,
                    entity_id=entity_ref_id,
                    target_state=context.get("config", {}).get("state"),
                    attributes=context.get("config", {}).get("attributes"),
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _discover_scripts_via_bridge(
        self, instance: HomeAssistantInstance, bridge_client: BridgeClient
    ) -> int:
        """Discover scripts using bridge."""
        scripts = await bridge_client.get_scripts()

        async with self.database.async_session() as session:
            await session.execute(
                delete(ScriptEntity).where(ScriptEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        for script_data in scripts:
            await self._process_script_from_bridge(instance, script_data)

        return len(scripts)

    async def _process_script_from_bridge(
        self, instance: HomeAssistantInstance, script_data: dict[str, Any]
    ) -> None:
        """Process script from bridge response."""
        entity_id = script_data.get("entity_id", "")
        if not entity_id:
            return

        entity_refs = EntityExtractor.extract_from_script(script_data)

        async with self.database.async_session() as session:
            script = Script(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=script_data.get("friendly_name"),
                sequence_config=script_data.get("sequence"),
                mode=script_data.get("mode"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(script)

            for entity_ref_id, context in entity_refs:
                relationship = ScriptEntity(
                    instance_id=instance.instance_id,
                    script_id=entity_id,
                    entity_id=entity_ref_id,
                    sequence_step=context.get("step"),
                    action_type=context.get("action_type"),
                    context=context,
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _discover_scripts_via_states(
        self, instance: HomeAssistantInstance, ha_client: HomeAssistantClient
    ) -> int:
        """Discover scripts using /api/states fallback."""
        states = await ha_client.get_states()
        scripts = [s for s in states if s.get("entity_id", "").startswith("script.")]

        async with self.database.async_session() as session:
            await session.execute(
                delete(ScriptEntity).where(ScriptEntity.instance_id == instance.instance_id)
            )
            await session.commit()

        for script_state in scripts:
            await self._process_script_from_states(instance, script_state)

        return len(scripts)

    async def _process_script_from_states(
        self, instance: HomeAssistantInstance, script_state: dict[str, Any]
    ) -> None:
        """Process script from /api/states."""
        entity_id = script_state.get("entity_id", "")
        if not entity_id:
            return

        attrs = script_state.get("attributes", {})
        entity_refs = EntityExtractor.extract_from_script(attrs)

        async with self.database.async_session() as session:
            script = Script(
                instance_id=instance.instance_id,
                entity_id=entity_id,
                friendly_name=attrs.get("friendly_name"),
                sequence_config=attrs.get("sequence"),
                mode=attrs.get("mode"),
                discovered_at=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )

            await session.merge(script)

            for entity_ref_id, context in entity_refs:
                relationship = ScriptEntity(
                    instance_id=instance.instance_id,
                    script_id=entity_id,
                    entity_id=entity_ref_id,
                    sequence_step=context.get("step"),
                    action_type=context.get("action_type"),
                    context=context,
                    discovered_at=datetime.now(UTC),
                )
                await session.merge(relationship)

            await session.commit()

    async def _count_discovered_entities(self, instance: HomeAssistantInstance) -> int:
        """Count unique entities discovered for an instance.

        Args:
            instance: HA instance

        Returns:
            Count of unique entity IDs
        """
        async with self.database.async_session() as session:
            # Union of entity_ids from all junction tables for this instance
            auto_entities = select(AutomationEntity.entity_id.distinct()).where(
                AutomationEntity.instance_id == instance.instance_id
            )
            scene_entities = select(SceneEntity.entity_id.distinct()).where(
                SceneEntity.instance_id == instance.instance_id
            )
            script_entities = select(ScriptEntity.entity_id.distinct()).where(
                ScriptEntity.instance_id == instance.instance_id
            )

            combined = union_all(auto_entities, scene_entities, script_entities).subquery()
            result = await session.execute(select(combined.c.entity_id.distinct()))
            unique_entities = result.scalars().all()

            return len(unique_entities)

    async def _record_refresh(
        self,
        instance_id: str,
        trigger_type: str,
        trigger_source: str | None,
        stats: dict[str, int],
        duration: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record discovery refresh in database.

        Args:
            instance_id: Instance identifier
            trigger_type: Type of trigger
            trigger_source: Source of trigger
            stats: Discovery statistics
            duration: Duration in seconds
            success: Whether refresh succeeded
            error: Error message if failed
        """
        async with self.database.async_session() as session:
            refresh = DiscoveryRefresh(
                instance_id=instance_id,
                trigger_type=trigger_type,
                trigger_source=trigger_source,
                automations_found=stats.get("automations_found", 0),
                scenes_found=stats.get("scenes_found", 0),
                scripts_found=stats.get("scripts_found", 0),
                entities_discovered=stats.get("entities_discovered", 0),
                duration_seconds=duration,
                timestamp=datetime.now(UTC),
                success=success,
                error_message=error,
            )
            session.add(refresh)
            await session.commit()
