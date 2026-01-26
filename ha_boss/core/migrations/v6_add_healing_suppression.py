"""Database migration: v5 → v6 - Add healing suppression support.

This migration adds a column to the entities table to allow suppressing
auto-healing for specific entities while keeping them monitored.

Changes:
- Add healing_suppressed column to entities table
- Create index for faster lookup of suppressed entities per instance
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v5_to_v6(session: AsyncSession) -> None:
    """Migrate database from v5 to v6.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v5 to v6")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Add healing_suppressed column to entities table
        # SQLite doesn't support IF NOT EXISTS for columns, so we check first
        result = await connection.execute(text("PRAGMA table_info(entities)"))
        columns = [row[1] for row in result.fetchall()]

        if "healing_suppressed" not in columns:
            await connection.execute(text("""
                ALTER TABLE entities ADD COLUMN healing_suppressed BOOLEAN NOT NULL DEFAULT 0
            """))
            logger.info("Added healing_suppressed column to entities table")
        else:
            logger.info("healing_suppressed column already exists")

        # Create index for faster lookup of suppressed entities per instance
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_entities_healing_suppressed
            ON entities(instance_id, healing_suppressed)
        """))
        logger.info("Created index for healing_suppressed")

        # Update schema version
        from sqlalchemy import select

        from ha_boss.core.database import DatabaseVersion

        target_version = 6
        result = await session.execute(
            select(DatabaseVersion).where(DatabaseVersion.version == target_version)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=target_version,
                applied_at=datetime.now(UTC),
                description="Add healing suppression support",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v5 → v6 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v5 → v6 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def downgrade_v6_to_v5(session: AsyncSession) -> None:
    """Downgrade database from v6 to v5.

    Args:
        session: Database session

    Raises:
        RuntimeError: If downgrade fails
    """
    logger.info("Starting downgrade from v6 to v5")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # SQLite doesn't support DROP COLUMN directly in older versions
        # We need to recreate the table without the column
        # For simplicity, we just drop the index and leave the column
        # (it won't affect functionality)
        await connection.execute(text("DROP INDEX IF EXISTS ix_entities_healing_suppressed"))
        logger.info("Dropped healing_suppressed index")

        # Update schema version to v5
        await connection.execute(text("DELETE FROM schema_version WHERE version = 6"))
        await session.commit()

        logger.info("Downgrade v6 → v5 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Downgrade v6 → v5 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Downgrade failed: {e}") from e
