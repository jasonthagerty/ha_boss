"""Database migration: v3 → v4 - Add automation execution tracking tables.

This migration adds tables to track automation executions and service calls
for usage-based optimization recommendations.

Changes:
- Add automation_executions table
- Add automation_service_calls table
- Add composite indexes for query performance
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ha_boss.core.database import CURRENT_DB_VERSION, DatabaseVersion

logger = logging.getLogger(__name__)


async def migrate_v3_to_v4(session: AsyncSession) -> None:
    """Migrate database from v3 to v4.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v3 to v4")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Create automation_executions table
        await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS automation_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id VARCHAR(255) NOT NULL,
                    automation_id VARCHAR(255) NOT NULL,
                    executed_at DATETIME NOT NULL,
                    trigger_type VARCHAR(100),
                    duration_ms INTEGER,
                    success BOOLEAN NOT NULL DEFAULT 1,
                    error_message TEXT
                )
                """))
        logger.info("Created automation_executions table")

        # Create indexes for automation_executions
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_automation_executions_instance_id
                ON automation_executions(instance_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_automation_executions_automation_id
                ON automation_executions(automation_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_automation_executions_instance_automation
                ON automation_executions(instance_id, automation_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_automation_executions_executed_at
                ON automation_executions(executed_at)
                """))
        logger.info("Created indexes for automation_executions")

        # Create automation_service_calls table
        await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS automation_service_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id VARCHAR(255) NOT NULL,
                    automation_id VARCHAR(255) NOT NULL,
                    service_name VARCHAR(255) NOT NULL,
                    entity_id VARCHAR(255),
                    called_at DATETIME NOT NULL,
                    response_time_ms INTEGER,
                    success BOOLEAN NOT NULL DEFAULT 1
                )
                """))
        logger.info("Created automation_service_calls table")

        # Create indexes for automation_service_calls
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_automation_service_calls_instance_id
                ON automation_service_calls(instance_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_automation_service_calls_automation_id
                ON automation_service_calls(automation_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_automation_service_calls_instance_automation
                ON automation_service_calls(instance_id, automation_id)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_automation_service_calls_called_at
                ON automation_service_calls(called_at)
                """))
        await connection.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_automation_service_calls_service_name
                ON automation_service_calls(service_name)
                """))
        logger.info("Created indexes for automation_service_calls")

        # Update schema version (check if version 4 already exists to support idempotency)
        from sqlalchemy import select

        result = await session.execute(
            select(DatabaseVersion).where(DatabaseVersion.version == CURRENT_DB_VERSION)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=CURRENT_DB_VERSION,
                applied_at=datetime.now(UTC),
                description="Add automation execution tracking tables",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v3 → v4 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v3 → v4 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def downgrade_v4_to_v3(session: AsyncSession) -> None:
    """Downgrade database from v4 to v3.

    Args:
        session: Database session

    Raises:
        RuntimeError: If downgrade fails
    """
    logger.info("Starting downgrade from v4 to v3")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Drop automation_service_calls table
        await connection.execute(text("DROP TABLE IF EXISTS automation_service_calls"))
        logger.info("Dropped automation_service_calls table")

        # Drop automation_executions table
        await connection.execute(text("DROP TABLE IF EXISTS automation_executions"))
        logger.info("Dropped automation_executions table")

        # Update schema version to v3
        await connection.execute(text("DELETE FROM schema_version WHERE version = 4"))
        await session.commit()

        logger.info("Downgrade v4 → v3 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Downgrade v4 → v3 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Downgrade failed: {e}") from e
