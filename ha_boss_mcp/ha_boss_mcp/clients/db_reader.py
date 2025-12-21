"""Read-only SQLite database client for HA Boss data."""

import aiosqlite
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class DBReaderError(Exception):
    """Base exception for database reader errors."""

    pass


class DBReader:
    """Async read-only client for HA Boss SQLite database.

    Provides direct database access for performance-optimized queries.
    All operations are read-only to maintain data integrity.

    Attributes:
        db_path: Path to SQLite database file
        max_retries: Maximum connection retry attempts
        retry_delay: Delay between retries in seconds
    """

    def __init__(
        self,
        db_path: str | Path,
        max_retries: int = 30,
        retry_delay: float = 2.0,
    ) -> None:
        """Initialize database reader.

        Args:
            db_path: Path to HA Boss SQLite database
            max_retries: Max retries to wait for DB (default: 30 = 60s)
            retry_delay: Seconds between retries (default: 2.0)
        """
        self.db_path = Path(db_path)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._db_ready = False

    async def wait_for_database(self) -> None:
        """Wait for database to be created by main HA Boss service.

        Retries for max_retries attempts with retry_delay between attempts.

        Raises:
            DBReaderError: If database not available after all retries
        """
        for attempt in range(self.max_retries):
            if self.db_path.exists():
                # Verify it's a valid SQLite database
                try:
                    async with aiosqlite.connect(self.db_path) as db:
                        # Check if schema_version table exists
                        async with db.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                        ) as cursor:
                            result = await cursor.fetchone()
                            if result:
                                self._db_ready = True
                                return
                except Exception:
                    pass  # Not ready yet

            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay)

        raise DBReaderError(
            f"Database not available at {self.db_path} after {self.max_retries * self.retry_delay}s. "
            "Ensure HA Boss main service is running and has initialized the database."
        )

    async def ensure_ready(self) -> None:
        """Ensure database is ready (wait if not)."""
        if not self._db_ready:
            await self.wait_for_database()

    async def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Get entity by ID.

        Args:
            entity_id: Entity ID (e.g., "sensor.temperature")

        Returns:
            Entity data dict or None if not found
        """
        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT entity_id, domain, friendly_name, device_id,
                       integration_id, last_seen, last_state, is_monitored
                FROM entities
                WHERE entity_id = ?
                """,
                (entity_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def list_entities(
        self, limit: int = 100, offset: int = 0, monitored_only: bool = True
    ) -> list[dict[str, Any]]:
        """List entities with pagination.

        Args:
            limit: Maximum entities to return
            offset: Pagination offset
            monitored_only: Only return monitored entities

        Returns:
            List of entity dicts
        """
        await self.ensure_ready()
        where_clause = "WHERE is_monitored = 1" if monitored_only else ""

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = f"""
                SELECT entity_id, domain, friendly_name, device_id,
                       integration_id, last_seen, last_state, is_monitored
                FROM entities
                {where_clause}
                ORDER BY entity_id
                LIMIT ? OFFSET ?
            """
            async with db.execute(query, (limit, offset)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_entity_history(
        self, entity_id: str, hours: int = 24, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Get state change history for an entity.

        Args:
            entity_id: Entity ID
            hours: Hours of history to retrieve
            limit: Maximum history entries

        Returns:
            List of state changes with timestamps
        """
        since = datetime.utcnow() - timedelta(hours=hours)

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT old_state, new_state, timestamp, context
                FROM state_history
                WHERE entity_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (entity_id, since.isoformat(), limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_health_events(
        self, entity_id: str | None = None, days: int = 7, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Get health events.

        Args:
            entity_id: Optional entity ID filter
            days: Days of events to retrieve
            limit: Maximum events

        Returns:
            List of health events
        """
        since = datetime.utcnow() - timedelta(days=days)

        where_clause = "WHERE timestamp >= ?"
        params: tuple[Any, ...] = (since.isoformat(),)

        if entity_id:
            where_clause += " AND entity_id = ?"
            params = (since.isoformat(), entity_id)

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = f"""
                SELECT id, entity_id, event_type, timestamp, details
                FROM health_events
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            async with db.execute(query, params + (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_healing_actions(
        self, entity_id: str | None = None, days: int = 7, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get healing actions.

        Args:
            entity_id: Optional entity ID filter
            days: Days of actions to retrieve
            limit: Maximum actions

        Returns:
            List of healing actions
        """
        since = datetime.utcnow() - timedelta(days=days)

        where_clause = "WHERE timestamp >= ?"
        params: tuple[Any, ...] = (since.isoformat(),)

        if entity_id:
            where_clause += " AND entity_id = ?"
            params = (since.isoformat(), entity_id)

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = f"""
                SELECT id, entity_id, integration_id, action, attempt_number,
                       timestamp, success, error, duration_seconds
                FROM healing_actions
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            async with db.execute(query, params + (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_healing_stats(self, days: int = 7) -> dict[str, Any]:
        """Get healing statistics.

        Args:
            days: Days of data to analyze

        Returns:
            Dict with success/failure counts and rates
        """
        since = datetime.utcnow() - timedelta(days=days)

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            # Get total count and success count
            async with db.execute(
                """
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_attempts
                FROM healing_actions
                WHERE timestamp >= ?
                """,
                (since.isoformat(),),
            ) as cursor:
                row = await cursor.fetchone()
                total = row[0] if row else 0
                successful = row[1] if row else 0

                success_rate = (successful / total * 100) if total > 0 else 0.0

                return {
                    "total_attempts": total,
                    "successful_attempts": successful,
                    "failed_attempts": total - successful,
                    "success_rate": round(success_rate, 2),
                    "days": days,
                }

    async def get_integration(self, entry_id: str) -> dict[str, Any] | None:
        """Get integration by entry ID.

        Args:
            entry_id: Integration entry ID

        Returns:
            Integration data dict or None if not found
        """
        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT entry_id, domain, title, source, entity_ids,
                       is_discovered, disabled, last_successful_reload,
                       consecutive_failures, circuit_breaker_open_until
                FROM integrations
                WHERE entry_id = ?
                """,
                (entry_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def list_integrations(
        self, domain: str | None = None, disabled_only: bool = False
    ) -> list[dict[str, Any]]:
        """List integrations.

        Args:
            domain: Optional domain filter (e.g., "hue")
            disabled_only: Only return disabled integrations

        Returns:
            List of integration dicts
        """
        where_clauses = []
        params: list[Any] = []

        if domain:
            where_clauses.append("domain = ?")
            params.append(domain)

        if disabled_only:
            where_clauses.append("disabled = 1")

        where_clause = " AND ".join(where_clauses) if where_clauses else ""
        if where_clause:
            where_clause = f"WHERE {where_clause}"

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = f"""
                SELECT entry_id, domain, title, source, entity_ids,
                       is_discovered, disabled, last_successful_reload,
                       consecutive_failures, circuit_breaker_open_until
                FROM integrations
                {where_clause}
                ORDER BY domain, title
            """
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_reliability_events(
        self, integration_domain: str | None = None, days: int = 7, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Get integration reliability events.

        Args:
            integration_domain: Optional integration domain filter
            days: Days of events to retrieve
            limit: Maximum events

        Returns:
            List of reliability events
        """
        since = datetime.utcnow() - timedelta(days=days)

        where_clause = "WHERE timestamp >= ?"
        params: tuple[Any, ...] = (since.isoformat(),)

        if integration_domain:
            where_clause += " AND integration_domain = ?"
            params = (since.isoformat(), integration_domain)

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = f"""
                SELECT id, integration_id, integration_domain, timestamp,
                       event_type, entity_id
                FROM integration_reliability
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            async with db.execute(query, params + (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def count_entities(self, monitored_only: bool = True) -> int:
        """Count total entities.

        Args:
            monitored_only: Only count monitored entities

        Returns:
            Total entity count
        """
        where_clause = "WHERE is_monitored = 1" if monitored_only else ""

        await self.ensure_ready()
        async with aiosqlite.connect(self.db_path) as db:
            query = f"SELECT COUNT(*) FROM entities {where_clause}"
            async with db.execute(query) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
