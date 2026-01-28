"""Database migration: v6 → v7 - Add outcome validation support.

This migration adds tables to support tracking desired automation outcomes,
validating execution results, and learning patterns from successful runs.

Changes:
- Add automation_desired_states table for tracking expected outcomes
- Add automation_outcome_validations table for execution validation results
- Add automation_outcome_patterns table for learning from successful executions
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def migrate_v6_to_v7(session: AsyncSession) -> None:
    """Migrate database from v6 to v7.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v6 to v7")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Create automation_desired_states table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS automation_desired_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                automation_id VARCHAR(255) NOT NULL,
                entity_id VARCHAR(255) NOT NULL,
                desired_state VARCHAR(255) NOT NULL,
                desired_attributes JSON,
                confidence FLOAT NOT NULL DEFAULT 0.0,
                inference_method VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        logger.info("Created automation_desired_states table")

        # Create indexes for automation_desired_states
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_desired_states_instance_id
            ON automation_desired_states(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_desired_states_automation_id
            ON automation_desired_states(automation_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_desired_states_entity_id
            ON automation_desired_states(entity_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_desired_states_inference_method
            ON automation_desired_states(inference_method)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_automation_desired_states_automation
            ON automation_desired_states(instance_id, automation_id)
        """))
        await connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_desired_states_unique
            ON automation_desired_states(instance_id, automation_id, entity_id)
        """))
        logger.info("Created indexes for automation_desired_states")

        # Create automation_outcome_validations table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS automation_outcome_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id VARCHAR(255) NOT NULL,
                execution_id INTEGER NOT NULL,
                entity_id VARCHAR(255) NOT NULL,
                desired_state VARCHAR(255) NOT NULL,
                desired_attributes JSON,
                actual_state VARCHAR(255),
                actual_attributes JSON,
                achieved BOOLEAN NOT NULL,
                time_to_achievement_ms INTEGER,
                user_description TEXT,
                validation_timestamp DATETIME NOT NULL
            )
        """))
        logger.info("Created automation_outcome_validations table")

        # Create indexes for automation_outcome_validations
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_validations_instance_id
            ON automation_outcome_validations(instance_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_validations_execution_id
            ON automation_outcome_validations(execution_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_validations_entity_id
            ON automation_outcome_validations(entity_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_automation_outcome_validations_validation_timestamp
            ON automation_outcome_validations(validation_timestamp)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_automation_outcome_validations_execution
            ON automation_outcome_validations(instance_id, execution_id)
        """))
        await connection.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_automation_outcome_validations_achieved
            ON automation_outcome_validations(instance_id, achieved)
        """))
        logger.info("Created indexes for automation_outcome_validations")

        # Create automation_outcome_patterns table
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS automation_outcome_patterns (
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
        logger.info("Created automation_outcome_patterns table")

        # Create indexes for automation_outcome_patterns
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
        logger.info("Created indexes for automation_outcome_patterns")

        # Update schema version
        from sqlalchemy import select

        from ha_boss.core.database import DatabaseVersion

        target_version = 7
        result = await session.execute(
            select(DatabaseVersion).where(DatabaseVersion.version == target_version)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=target_version,
                applied_at=datetime.now(UTC),
                description="Add outcome validation support",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v6 → v7 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v6 → v7 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def downgrade_v7_to_v6(session: AsyncSession) -> None:
    """Downgrade database from v7 to v6.

    Args:
        session: Database session

    Raises:
        RuntimeError: If downgrade fails
    """
    logger.info("Starting downgrade from v7 to v6")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # Drop tables
        await connection.execute(text("DROP TABLE IF EXISTS automation_outcome_patterns"))
        await connection.execute(text("DROP TABLE IF EXISTS automation_outcome_validations"))
        await connection.execute(text("DROP TABLE IF EXISTS automation_desired_states"))
        logger.info("Dropped outcome validation tables")

        # Update schema version to v6
        await connection.execute(text("DELETE FROM schema_version WHERE version = 7"))
        await session.commit()

        logger.info("Downgrade v7 → v6 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Downgrade v7 → v6 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Downgrade failed: {e}") from e
