"""Database migration: v8 → v9 - Add healing plan framework tables.

This migration adds tables to support configurable YAML-based healing plans
that augment the existing cascade orchestrator with user-defined strategies.

Changes:
- Add healing_plans table for plan definitions
- Add healing_plan_executions table for execution tracking
- Add timeout_seconds column to healing_cascade_executions (from Issue #207)
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v8_to_v9(session: AsyncSession) -> None:
    """Migrate database from v8 to v9.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v8 to v9")

    try:
        connection = await session.connection()

        # Create healing_plans table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS healing_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL UNIQUE,
                version INTEGER NOT NULL DEFAULT 1,
                description TEXT,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 0,
                source VARCHAR(50) NOT NULL DEFAULT 'user',
                match_criteria JSON,
                steps JSON,
                on_failure JSON,
                tags JSON,
                total_executions INTEGER NOT NULL DEFAULT 0,
                total_successes INTEGER NOT NULL DEFAULT 0,
                total_failures INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        logger.info("Created healing_plans table")

        # Create index on healing_plans name
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_plans_name
            ON healing_plans(name)
        """))

        # Create healing_plan_executions table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS healing_plan_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                plan_name VARCHAR(255) NOT NULL,
                instance_id VARCHAR(255) NOT NULL,
                automation_id VARCHAR(255),
                cascade_execution_id INTEGER,
                target_entities JSON,
                steps_attempted JSON,
                steps_succeeded INTEGER NOT NULL DEFAULT 0,
                steps_failed INTEGER NOT NULL DEFAULT 0,
                overall_success BOOLEAN,
                total_duration_seconds REAL,
                error_message TEXT,
                created_at DATETIME NOT NULL,
                completed_at DATETIME
            )
        """))
        logger.info("Created healing_plan_executions table")

        # Create indexes for healing_plan_executions
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_plan_executions_plan_id
            ON healing_plan_executions(plan_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_plan_executions_instance_id
            ON healing_plan_executions(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_plan_executions_created_at
            ON healing_plan_executions(created_at)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_healing_plan_executions_plan_instance
            ON healing_plan_executions(plan_id, instance_id)
        """))

        # Add timeout_seconds to healing_cascade_executions (Issue #207)
        # Use try/except for idempotency (column may already exist on new installs)
        try:
            await connection.execute(
                text("ALTER TABLE healing_cascade_executions ADD COLUMN timeout_seconds REAL")
            )
            logger.info("Added timeout_seconds column to healing_cascade_executions")
        except Exception:
            logger.debug("timeout_seconds column already exists, skipping")

        # Update schema version
        await connection.execute(
            text(
                "INSERT INTO schema_version (version, description, applied_at) VALUES (9, 'Add healing plan framework', datetime('now'))"
            )
        )
        logger.info("Updated schema version to 9")

        await session.commit()
        logger.info("Migration v8 → v9 completed successfully")

    except Exception as e:
        logger.error(f"Migration v8 → v9 failed: {e}", exc_info=True)
        raise RuntimeError(f"Migration v8 → v9 failed: {e}") from e
