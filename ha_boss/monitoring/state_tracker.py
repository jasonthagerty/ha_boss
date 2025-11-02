"""Entity state tracking with in-memory cache."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from sqlalchemy import select

from ha_boss.core.database import Database, Entity, StateHistory
from ha_boss.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class EntityState:
    """Represents a single entity's current state."""

    def __init__(
        self,
        entity_id: str,
        state: str,
        last_updated: datetime,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Initialize entity state.

        Args:
            entity_id: Entity identifier (e.g., "sensor.temperature")
            state: Current state value
            last_updated: When state was last updated
            attributes: Optional state attributes
        """
        self.entity_id = entity_id
        self.state = state
        self.last_updated = last_updated
        self.attributes = attributes or {}

    def __repr__(self) -> str:
        return f"<EntityState({self.entity_id}, state={self.state}, updated={self.last_updated})>"


class StateTracker:
    """In-memory cache of entity states with database persistence.

    Maintains a real-time cache of entity states received via WebSocket,
    persists state changes to database, and provides fast lookups for
    health monitoring.
    """

    def __init__(
        self,
        database: Database,
        on_state_updated: (
            Callable[[EntityState, EntityState | None], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        """Initialize state tracker.

        Args:
            database: Database manager for persistence
            on_state_updated: Optional callback for state changes (new_state, old_state)
        """
        self.database = database
        self.on_state_updated = on_state_updated

        # In-memory cache: entity_id -> EntityState
        self._cache: dict[str, EntityState] = {}

        # Lock for concurrent access
        self._lock = asyncio.Lock()

    async def initialize(self, initial_states: list[dict[str, Any]]) -> None:
        """Initialize cache with initial state snapshot from REST API.

        Args:
            initial_states: List of state dicts from Home Assistant
        """
        async with self._lock:
            for state_data in initial_states:
                entity_id = state_data.get("entity_id")
                if not entity_id:
                    continue

                state = state_data.get("state")
                last_updated_str = state_data.get("last_updated")
                attributes = state_data.get("attributes", {})

                # Parse timestamp
                try:
                    last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    last_updated = datetime.utcnow()

                entity_state = EntityState(
                    entity_id=entity_id,
                    state=state,
                    last_updated=last_updated,
                    attributes=attributes,
                )

                self._cache[entity_id] = entity_state

                # Persist to database
                await self._persist_entity(entity_state)

            logger.info(f"Initialized state tracker with {len(self._cache)} entities")

    async def update_state(self, state_data: dict[str, Any]) -> None:
        """Update entity state from WebSocket state_changed event.

        Args:
            state_data: State change event data from WebSocket
        """
        entity_id = state_data.get("entity_id")
        if not entity_id:
            logger.warning("Received state_changed event without entity_id")
            return

        new_state_data = state_data.get("new_state")
        if not new_state_data:
            # Entity was removed
            await self._remove_entity(entity_id)
            return

        # Extract state information
        new_state = new_state_data.get("state")
        last_updated_str = new_state_data.get("last_updated")
        attributes = new_state_data.get("attributes", {})

        # Parse timestamp
        try:
            last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            last_updated = datetime.utcnow()

        # Create new state object
        new_entity_state = EntityState(
            entity_id=entity_id,
            state=new_state,
            last_updated=last_updated,
            attributes=attributes,
        )

        # Update cache
        async with self._lock:
            old_state = self._cache.get(entity_id)
            self._cache[entity_id] = new_entity_state

            # Persist to database
            await self._persist_entity(new_entity_state)

            # Record state history if state actually changed
            if old_state and old_state.state != new_state:
                await self._record_state_history(
                    entity_id=entity_id,
                    old_state=old_state.state,
                    new_state=new_state,
                    timestamp=last_updated,
                )

        # Call callback if registered
        if self.on_state_updated:
            try:
                await self.on_state_updated(new_entity_state, old_state)
            except Exception as e:
                logger.error(f"Error in state_updated callback: {e}", exc_info=True)

    async def get_state(self, entity_id: str) -> EntityState | None:
        """Get current state for an entity.

        Args:
            entity_id: Entity identifier

        Returns:
            Entity state or None if not found
        """
        async with self._lock:
            return self._cache.get(entity_id)

    async def get_all_states(self) -> dict[str, EntityState]:
        """Get all cached entity states.

        Returns:
            Dictionary of entity_id -> EntityState
        """
        async with self._lock:
            return dict(self._cache)

    async def get_entities_by_domain(self, domain: str) -> list[EntityState]:
        """Get all entities for a specific domain.

        Args:
            domain: Entity domain (e.g., "sensor", "binary_sensor")

        Returns:
            List of entity states for the domain
        """
        async with self._lock:
            return [
                state
                for entity_id, state in self._cache.items()
                if entity_id.startswith(f"{domain}.")
            ]

    async def is_entity_monitored(self, entity_id: str) -> bool:
        """Check if an entity exists and is being monitored.

        Args:
            entity_id: Entity identifier

        Returns:
            True if entity is in cache (being monitored)
        """
        async with self._lock:
            return entity_id in self._cache

    async def _persist_entity(self, entity_state: EntityState) -> None:
        """Persist entity state to database.

        Args:
            entity_state: Entity state to persist
        """
        try:
            async with self.database.async_session() as session:
                # Check if entity exists
                result = await session.execute(
                    select(Entity).where(Entity.entity_id == entity_state.entity_id)
                )
                entity = result.scalar_one_or_none()

                if entity:
                    # Update existing entity
                    entity.last_seen = entity_state.last_updated
                    entity.last_state = entity_state.state
                    entity.updated_at = datetime.utcnow()
                else:
                    # Create new entity
                    # Extract domain from entity_id (e.g., "sensor" from "sensor.temperature")
                    domain = entity_state.entity_id.split(".")[0]
                    friendly_name = entity_state.attributes.get("friendly_name")

                    entity = Entity(
                        entity_id=entity_state.entity_id,
                        domain=domain,
                        friendly_name=friendly_name,
                        last_seen=entity_state.last_updated,
                        last_state=entity_state.state,
                        is_monitored=True,
                    )
                    session.add(entity)

                await session.commit()

        except Exception as e:
            logger.error(f"Failed to persist entity {entity_state.entity_id}: {e}", exc_info=True)
            raise DatabaseError(f"Failed to persist entity: {e}") from e

    async def _record_state_history(
        self, entity_id: str, old_state: str, new_state: str, timestamp: datetime
    ) -> None:
        """Record state change in history table.

        Args:
            entity_id: Entity identifier
            old_state: Previous state value
            new_state: New state value
            timestamp: When change occurred
        """
        try:
            async with self.database.async_session() as session:
                history = StateHistory(
                    entity_id=entity_id,
                    old_state=old_state,
                    new_state=new_state,
                    timestamp=timestamp,
                )
                session.add(history)
                await session.commit()

        except Exception as e:
            logger.error(f"Failed to record state history for {entity_id}: {e}", exc_info=True)
            # Don't raise - history is non-critical

    async def _remove_entity(self, entity_id: str) -> None:
        """Remove entity from cache when it's deleted from HA.

        Args:
            entity_id: Entity identifier
        """
        async with self._lock:
            if entity_id in self._cache:
                del self._cache[entity_id]
                logger.info(f"Entity {entity_id} removed from cache")


async def create_state_tracker(
    database: Database,
    initial_states: list[dict[str, Any]],
    on_state_updated: (
        Callable[[EntityState, EntityState | None], Coroutine[Any, Any, None]] | None
    ) = None,
) -> StateTracker:
    """Create and initialize a state tracker.

    Args:
        database: Database manager
        initial_states: Initial state snapshot from Home Assistant
        on_state_updated: Optional callback for state changes

    Returns:
        Initialized state tracker
    """
    tracker = StateTracker(database, on_state_updated=on_state_updated)
    await tracker.initialize(initial_states)
    return tracker
