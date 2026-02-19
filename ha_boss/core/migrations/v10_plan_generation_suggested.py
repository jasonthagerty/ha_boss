"""Database migration: v9 → v10 - Add plan_generation_suggested flag.

This migration adds a boolean column to healing_cascade_executions to track
when no healing plan matched and AI plan generation was suggested.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v9_to_v10(session: AsyncSession) -> None:
    """Migrate database from v9 to v10.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v9 to v10")

    try:
        connection = await session.connection()

        # Add plan_generation_suggested column to healing_cascade_executions
        # Use try/except for idempotency (column may already exist on new installs)
        try:
            await connection.execute(
                text(
                    "ALTER TABLE healing_cascade_executions "
                    "ADD COLUMN plan_generation_suggested BOOLEAN DEFAULT FALSE"
                )
            )
            logger.info("Added plan_generation_suggested column to healing_cascade_executions")
        except Exception:
            logger.debug("plan_generation_suggested column already exists, skipping")

        # Update schema version
        await connection.execute(
            text(
                "INSERT INTO schema_version (version, description, applied_at) "
                "VALUES (10, 'Add plan_generation_suggested flag', datetime('now'))"
            )
        )
        logger.info("Updated schema version to 10")

        await session.commit()
        logger.info("Migration v9 → v10 completed successfully")

    except Exception as e:
        logger.error(f"Migration v9 → v10 failed: {e}", exc_info=True)
        raise RuntimeError(f"Migration v9 → v10 failed: {e}") from e
