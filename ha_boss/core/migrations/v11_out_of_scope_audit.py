"""Database migration: v10 → v11 - Add out-of-scope audit status table.

This migration creates the ``out_of_scope_audit_status`` table used by the
out-of-scope entity audit feature to track which entities are currently in a
bad state so only net-new failures are reported each run.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v10_to_v11(session: AsyncSession) -> None:
    """Migrate database from v10 to v11.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v10 to v11")

    try:
        connection = await session.connection()

        # Create the out_of_scope_audit_status table
        # Use try/except for idempotency (table may already exist on new installs)
        try:
            await connection.execute(text("""
                    CREATE TABLE out_of_scope_audit_status (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        instance_id VARCHAR(255) NOT NULL,
                        entity_id VARCHAR(255) NOT NULL,
                        first_unavailable_at DATETIME NOT NULL,
                        last_state VARCHAR(255),
                        last_seen_at DATETIME NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT (datetime('now')),
                        updated_at DATETIME NOT NULL DEFAULT (datetime('now')),
                        UNIQUE (instance_id, entity_id)
                    )
                    """))
            logger.info("Created out_of_scope_audit_status table")
        except Exception:
            logger.debug("out_of_scope_audit_status table already exists, skipping")

        # Add indexes for common query patterns
        try:
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_oos_audit_instance_id "
                    "ON out_of_scope_audit_status (instance_id)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_oos_audit_instance_entity "
                    "ON out_of_scope_audit_status (instance_id, entity_id)"
                )
            )
            logger.info("Created indexes for out_of_scope_audit_status")
        except Exception:
            logger.debug("Indexes for out_of_scope_audit_status already exist, skipping")

        # Update schema version
        await connection.execute(
            text(
                "INSERT INTO schema_version (version, description, applied_at) "
                "VALUES (11, 'Add out-of-scope audit status table', datetime('now'))"
            )
        )
        logger.info("Updated schema version to 11")

        await session.commit()
        logger.info("Migration v10 → v11 completed successfully")

    except Exception as e:
        logger.error(f"Migration v10 → v11 failed: {e}", exc_info=True)
        raise RuntimeError(f"Migration v10 → v11 failed: {e}") from e
