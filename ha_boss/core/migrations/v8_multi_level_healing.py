"""Database migration: v7 → v8 - Add multi-level healing support.

This migration adds tables and columns to support intelligent multi-level healing
that targets failures at the appropriate level: entity → device → integration.

Changes:
- Add healing_strategies table for available healing actions at each level
- Add device_healing_actions table for device-level healing attempts
- Add entity_healing_actions table for entity-level healing attempts
- Add healing_cascade_executions table for full healing cascade tracking
- Add automation_health_status table for consecutive success/failure tracking
- Add columns to automation_outcome_patterns for healing strategy results
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v7_to_v8(session: AsyncSession) -> None:
    """Migrate database from v7 to v8.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v7 to v8")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Create healing_strategies table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS healing_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level VARCHAR(50) NOT NULL,
                strategy_type VARCHAR(100) NOT NULL,
                parameters JSON,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL
            )
        """))
        logger.info("Created healing_strategies table")

        # Create device_healing_actions table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS device_healing_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                device_id VARCHAR(255) NOT NULL,
                action_type VARCHAR(100) NOT NULL,
                triggered_by VARCHAR(100),
                automation_id VARCHAR(255),
                execution_id INTEGER,
                success BOOLEAN,
                error_message TEXT,
                duration_seconds REAL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (execution_id) REFERENCES automation_executions(id)
            )
        """))
        logger.info("Created device_healing_actions table")

        # Create indexes for device_healing_actions
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_device_healing_actions_instance_id
            ON device_healing_actions(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_device_healing_actions_device_id
            ON device_healing_actions(device_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_device_healing_actions_created_at
            ON device_healing_actions(created_at)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_device_healing_actions_instance_device
            ON device_healing_actions(instance_id, device_id)
        """))
        logger.info("Created indexes for device_healing_actions")

        # Create entity_healing_actions table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS entity_healing_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                entity_id VARCHAR(255) NOT NULL,
                action_type VARCHAR(100) NOT NULL,
                service_domain VARCHAR(100),
                service_name VARCHAR(100),
                service_data JSON,
                triggered_by VARCHAR(100),
                automation_id VARCHAR(255),
                execution_id INTEGER,
                success BOOLEAN,
                error_message TEXT,
                duration_seconds REAL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (execution_id) REFERENCES automation_executions(id)
            )
        """))
        logger.info("Created entity_healing_actions table")

        # Create indexes for entity_healing_actions
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_entity_healing_actions_instance_id
            ON entity_healing_actions(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_entity_healing_actions_entity_id
            ON entity_healing_actions(entity_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_entity_healing_actions_created_at
            ON entity_healing_actions(created_at)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_entity_healing_actions_instance_entity
            ON entity_healing_actions(instance_id, entity_id)
        """))
        logger.info("Created indexes for entity_healing_actions")

        # Create healing_cascade_executions table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS healing_cascade_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                automation_id VARCHAR(255) NOT NULL,
                execution_id INTEGER,
                trigger_type VARCHAR(100) NOT NULL,
                failed_entities JSON,
                entity_level_attempted BOOLEAN DEFAULT 0,
                entity_level_success BOOLEAN,
                device_level_attempted BOOLEAN DEFAULT 0,
                device_level_success BOOLEAN,
                integration_level_attempted BOOLEAN DEFAULT 0,
                integration_level_success BOOLEAN,
                routing_strategy VARCHAR(50) NOT NULL,
                matched_pattern_id INTEGER,
                final_success BOOLEAN,
                total_duration_seconds REAL,
                created_at DATETIME NOT NULL,
                completed_at DATETIME,
                FOREIGN KEY (execution_id) REFERENCES automation_executions(id),
                FOREIGN KEY (matched_pattern_id) REFERENCES automation_outcome_patterns(id)
            )
        """))
        logger.info("Created healing_cascade_executions table")

        # Create indexes for healing_cascade_executions
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_cascade_executions_instance_id
            ON healing_cascade_executions(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_cascade_executions_automation_id
            ON healing_cascade_executions(automation_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_healing_cascade_executions_created_at
            ON healing_cascade_executions(created_at)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_healing_cascade_executions_instance_automation
            ON healing_cascade_executions(instance_id, automation_id)
        """))
        logger.info("Created indexes for healing_cascade_executions")

        # Create automation_health_status table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS automation_health_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                automation_id VARCHAR(255) NOT NULL,
                consecutive_successes INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                is_validated_healthy BOOLEAN NOT NULL DEFAULT 0,
                last_validation_at DATETIME,
                total_executions INTEGER NOT NULL DEFAULT 0,
                total_successes INTEGER NOT NULL DEFAULT 0,
                total_failures INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL,
                UNIQUE(instance_id, automation_id)
            )
        """))
        logger.info("Created automation_health_status table")

        # Create indexes for automation_health_status
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_health_status_instance_id
            ON automation_health_status(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_health_status_automation_id
            ON automation_health_status(automation_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_automation_health_status_instance_automation
            ON automation_health_status(instance_id, automation_id)
        """))
        logger.info("Created indexes for automation_health_status")

        # Add columns to automation_outcome_patterns (check if they don't exist first)
        # SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN
        # so we need to check manually
        result = await connection.execute(text("PRAGMA table_info(automation_outcome_patterns)"))
        existing_columns = {row[1] for row in result.fetchall()}

        if "successful_healing_level" not in existing_columns:
            await connection.execute(text("""
                ALTER TABLE automation_outcome_patterns
                ADD COLUMN successful_healing_level VARCHAR(50)
            """))
            logger.info("Added successful_healing_level column to automation_outcome_patterns")
        else:
            logger.info("Column successful_healing_level already exists, skipping")

        if "successful_healing_strategy" not in existing_columns:
            await connection.execute(text("""
                ALTER TABLE automation_outcome_patterns
                ADD COLUMN successful_healing_strategy VARCHAR(255)
            """))
            logger.info("Added successful_healing_strategy column to automation_outcome_patterns")
        else:
            logger.info("Column successful_healing_strategy already exists, skipping")

        if "healing_success_count" not in existing_columns:
            await connection.execute(text("""
                ALTER TABLE automation_outcome_patterns
                ADD COLUMN healing_success_count INTEGER DEFAULT 0
            """))
            logger.info("Added healing_success_count column to automation_outcome_patterns")
        else:
            logger.info("Column healing_success_count already exists, skipping")

        # Update schema version
        from sqlalchemy import select

        from ha_boss.core.database import DatabaseVersion

        target_version = 8
        result = await session.execute(  # type: ignore[assignment]
            select(DatabaseVersion).where(DatabaseVersion.version == target_version)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=target_version,
                applied_at=datetime.now(UTC),
                description="Add multi-level healing support",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v7 → v8 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v7 → v8 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def downgrade_v8_to_v7(session: AsyncSession) -> None:
    """Downgrade database from v8 to v7.

    Args:
        session: Database session

    Raises:
        RuntimeError: If downgrade fails
    """
    logger.info("Starting downgrade from v8 to v7")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Drop new tables in reverse order of creation
        await connection.execute(text("DROP TABLE IF EXISTS automation_health_status"))
        await connection.execute(text("DROP TABLE IF EXISTS healing_cascade_executions"))
        await connection.execute(text("DROP TABLE IF EXISTS entity_healing_actions"))
        await connection.execute(text("DROP TABLE IF EXISTS device_healing_actions"))
        await connection.execute(text("DROP TABLE IF EXISTS healing_strategies"))
        logger.info("Dropped multi-level healing tables")

        # Remove added columns from automation_outcome_patterns
        # SQLite doesn't support DROP COLUMN, so we need to recreate the table
        # First, create a backup with the new columns still present
        await connection.execute(text("""
            ALTER TABLE automation_outcome_patterns
            RENAME TO automation_outcome_patterns_old
        """))

        # Recreate the table without the new columns
        await connection.execute(text("""
            CREATE TABLE automation_outcome_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                automation_id VARCHAR(255) NOT NULL,
                entity_id VARCHAR(255) NOT NULL,
                observed_state VARCHAR(255) NOT NULL,
                observed_attributes JSON,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                first_observed DATETIME NOT NULL,
                last_observed DATETIME NOT NULL
            )
        """))

        # Copy data back
        await connection.execute(text("""
            INSERT INTO automation_outcome_patterns
            (id, instance_id, automation_id, entity_id, observed_state,
             observed_attributes, occurrence_count, first_observed, last_observed)
            SELECT id, instance_id, automation_id, entity_id, observed_state,
                   observed_attributes, occurrence_count, first_observed, last_observed
            FROM automation_outcome_patterns_old
        """))

        # Recreate indexes
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_patterns_instance_id
            ON automation_outcome_patterns(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_patterns_automation_id
            ON automation_outcome_patterns(automation_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_patterns_entity_id
            ON automation_outcome_patterns(entity_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_patterns_last_observed
            ON automation_outcome_patterns(last_observed)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_automation_outcome_patterns_automation
            ON automation_outcome_patterns(instance_id, automation_id)
        """))
        await connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_outcome_patterns_unique
            ON automation_outcome_patterns(instance_id, automation_id, entity_id)
        """))

        # Drop the old table
        await connection.execute(text("DROP TABLE IF EXISTS automation_outcome_patterns_old"))
        logger.info("Removed columns from automation_outcome_patterns")

        # Update schema version
        await connection.execute(text("DELETE FROM schema_version WHERE version = 8"))
        await session.commit()

        logger.info("Downgrade v8 → v7 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Downgrade v8 → v7 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Downgrade failed: {e}") from e
