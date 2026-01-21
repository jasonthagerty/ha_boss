"""Database migration: v4 → v5 - Add runtime configuration tables.

This migration adds tables to store runtime configuration overrides
and Home Assistant instance configurations with encrypted tokens.

Changes:
- Add runtime_config table for dashboard-editable settings
- Add stored_instances table for HA instance management
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Note: This function is registered via the migration registry in __init__.py
async def migrate_v4_to_v5(session: AsyncSession) -> None:
    """Migrate database from v4 to v5.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v4 to v5")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Create runtime_config table
        await connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS runtime_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key VARCHAR(255) NOT NULL UNIQUE,
                value TEXT NOT NULL,
                value_type VARCHAR(50) NOT NULL,
                updated_at DATETIME NOT NULL,
                updated_by VARCHAR(50) NOT NULL DEFAULT 'dashboard'
            )
        """)
        )
        logger.info("Created runtime_config table")

        # Create index for runtime_config
        await connection.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_runtime_config_key
            ON runtime_config(key)
        """)
        )
        logger.info("Created index for runtime_config")

        # Create stored_instances table
        await connection.execute(
            text("""
            CREATE TABLE IF NOT EXISTS stored_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL UNIQUE,
                url VARCHAR(1024) NOT NULL,
                encrypted_token TEXT NOT NULL,
                bridge_enabled BOOLEAN NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                source VARCHAR(50) NOT NULL DEFAULT 'dashboard',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        )
        logger.info("Created stored_instances table")

        # Create index for stored_instances
        await connection.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_stored_instances_instance_id
            ON stored_instances(instance_id)
        """)
        )
        logger.info("Created index for stored_instances")

        # Update schema version
        # Note: Use literal 5 here, not CURRENT_DB_VERSION which may be higher
        from sqlalchemy import select

        from ha_boss.core.database import DatabaseVersion

        target_version = 5
        result = await session.execute(
            select(DatabaseVersion).where(DatabaseVersion.version == target_version)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=target_version,
                applied_at=datetime.now(UTC),
                description="Add runtime configuration tables",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v4 → v5 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v4 → v5 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def downgrade_v5_to_v4(session: AsyncSession) -> None:
    """Downgrade database from v5 to v4.

    Args:
        session: Database session

    Raises:
        RuntimeError: If downgrade fails
    """
    logger.info("Starting downgrade from v5 to v4")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Drop stored_instances table
        await connection.execute(text("DROP TABLE IF EXISTS stored_instances"))
        logger.info("Dropped stored_instances table")

        # Drop runtime_config table
        await connection.execute(text("DROP TABLE IF EXISTS runtime_config"))
        logger.info("Dropped runtime_config table")

        # Update schema version to v4
        await connection.execute(text("DELETE FROM schema_version WHERE version = 5"))
        await session.commit()

        logger.info("Downgrade v5 → v4 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Downgrade v5 → v4 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Downgrade failed: {e}") from e
