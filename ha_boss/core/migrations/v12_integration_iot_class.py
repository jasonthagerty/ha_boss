"""Database migration: v11 → v12 - Add iot_class to integrations.

Adds the ``iot_class`` column to the ``integrations`` table so HA Boss can
record each integration's Home Assistant manifest IoT class (e.g.
``cloud_polling``, ``cloud_push``, ``local_push``) and treat internet-dependent
(cloud) integrations more gently when they flap unavailable.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v11_to_v12(session: AsyncSession) -> None:
    """Migrate database from v11 to v12.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v11 to v12")

    try:
        connection = await session.connection()

        # Add iot_class column. SQLite has no "ADD COLUMN IF NOT EXISTS", so guard
        # against re-runs (column may already exist on new installs / partial runs).
        try:
            await connection.execute(
                text("ALTER TABLE integrations ADD COLUMN iot_class VARCHAR(50)")
            )
            logger.info("Added iot_class column to integrations")
        except Exception:
            logger.debug("integrations.iot_class already exists, skipping")

        # Update schema version
        await connection.execute(
            text(
                "INSERT INTO schema_version (version, description, applied_at) "
                "VALUES (12, 'Add iot_class to integrations', datetime('now'))"
            )
        )
        logger.info("Updated schema version to 12")

        await session.commit()
        logger.info("Successfully migrated from v11 to v12")

    except Exception as e:
        await session.rollback()
        logger.error(f"Migration from v11 to v12 failed: {e}")
        raise RuntimeError(f"Migration v11 to v12 failed: {e}") from e
