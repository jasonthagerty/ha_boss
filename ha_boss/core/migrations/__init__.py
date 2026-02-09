"""Database migration system for HA Boss.

This module provides a registry-based migration system that automatically
discovers and runs migrations to upgrade the database schema.

Usage:
    Migrations are automatically registered when imported. The migration
    runner will find all migrations needed to get from the current version
    to the target version and run them in order.

Adding a new migration:
    1. Create a new file: v{N}_description.py
    2. Implement async migrate_v{N-1}_to_v{N}(session) function
    3. Register it: MIGRATION_REGISTRY.register(N, migrate_v{N-1}_to_v{N}, "Description")
"""

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """Represents a database migration."""

    target_version: int
    migrate_func: Callable[[AsyncSession], Coroutine[Any, Any, None]]
    description: str


class MigrationRegistry:
    """Registry for database migrations.

    Maintains a collection of migrations that can be queried to find
    the path from any source version to any target version.
    """

    def __init__(self) -> None:
        self._migrations: dict[int, Migration] = {}

    def register(
        self,
        target_version: int,
        migrate_func: Callable[[AsyncSession], Coroutine[Any, Any, None]],
        description: str,
    ) -> None:
        """Register a migration.

        Args:
            target_version: The version this migration upgrades TO
            migrate_func: Async function that performs the migration
            description: Human-readable description of the migration
        """
        if target_version in self._migrations:
            logger.warning(f"Overwriting existing migration for version {target_version}")

        self._migrations[target_version] = Migration(
            target_version=target_version,
            migrate_func=migrate_func,
            description=description,
        )
        logger.debug(f"Registered migration to v{target_version}: {description}")

    def get_migrations_for_upgrade(self, from_version: int, to_version: int) -> list[Migration]:
        """Get all migrations needed to upgrade from one version to another.

        Args:
            from_version: Current database version
            to_version: Target database version

        Returns:
            List of migrations to run, in order
        """
        if from_version >= to_version:
            return []

        # Find all migrations where from_version < target_version <= to_version
        needed_migrations = [
            m for v, m in self._migrations.items() if from_version < v <= to_version
        ]

        # Sort by target version to ensure correct order
        needed_migrations.sort(key=lambda m: m.target_version)

        return needed_migrations

    def get_migration(self, target_version: int) -> Migration | None:
        """Get a specific migration by target version.

        Args:
            target_version: The version to get migration for

        Returns:
            Migration or None if not found
        """
        return self._migrations.get(target_version)

    @property
    def latest_version(self) -> int:
        """Get the latest version available in the registry."""
        if not self._migrations:
            return 0
        return max(self._migrations.keys())

    @property
    def all_versions(self) -> list[int]:
        """Get all registered migration versions in order."""
        return sorted(self._migrations.keys())


# Global migration registry
MIGRATION_REGISTRY = MigrationRegistry()


def register_migration(target_version: int, description: str) -> Callable[
    [Callable[[AsyncSession], Coroutine[Any, Any, None]]],
    Callable[[AsyncSession], Coroutine[Any, Any, None]],
]:
    """Decorator to register a migration function.

    Usage:
        @register_migration(3, "Add instance_id for multi-instance support")
        async def migrate_v2_to_v3(session: AsyncSession) -> None:
            ...

    Args:
        target_version: The version this migration upgrades TO
        description: Human-readable description

    Returns:
        Decorator function
    """

    def decorator(
        func: Callable[[AsyncSession], Coroutine[Any, Any, None]],
    ) -> Callable[[AsyncSession], Coroutine[Any, Any, None]]:
        MIGRATION_REGISTRY.register(target_version, func, description)
        return func

    return decorator


# Import and register all migrations
# This must be at the end of the file after MIGRATION_REGISTRY is defined
def _load_migrations() -> None:
    """Load and register all migration modules."""
    from ha_boss.core.migrations.v3_add_instance_id import migrate_v2_to_v3
    from ha_boss.core.migrations.v4_add_automation_tracking import migrate_v3_to_v4
    from ha_boss.core.migrations.v5_add_runtime_config import migrate_v4_to_v5
    from ha_boss.core.migrations.v6_add_healing_suppression import migrate_v5_to_v6
    from ha_boss.core.migrations.v7_add_outcome_validation import migrate_v6_to_v7
    from ha_boss.core.migrations.v8_multi_level_healing import migrate_v7_to_v8
    from ha_boss.core.migrations.v9_add_healing_plans import migrate_v8_to_v9

    # Register all migrations with the registry
    MIGRATION_REGISTRY.register(
        target_version=3,
        migrate_func=migrate_v2_to_v3,
        description="Add instance_id for multi-instance support",
    )
    MIGRATION_REGISTRY.register(
        target_version=4,
        migrate_func=migrate_v3_to_v4,
        description="Add automation execution tracking tables",
    )
    MIGRATION_REGISTRY.register(
        target_version=5,
        migrate_func=migrate_v4_to_v5,
        description="Add runtime configuration tables",
    )
    MIGRATION_REGISTRY.register(
        target_version=6,
        migrate_func=migrate_v5_to_v6,
        description="Add healing suppression support",
    )
    MIGRATION_REGISTRY.register(
        target_version=7,
        migrate_func=migrate_v6_to_v7,
        description="Add outcome validation support",
    )
    MIGRATION_REGISTRY.register(
        target_version=8,
        migrate_func=migrate_v7_to_v8,
        description="Add multi-level healing support",
    )
    MIGRATION_REGISTRY.register(
        target_version=9,
        migrate_func=migrate_v8_to_v9,
        description="Add healing plan framework",
    )


_load_migrations()
