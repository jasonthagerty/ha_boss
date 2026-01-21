"""Database migration: v2 → v3 - Add instance_id support for multi-instance architecture.

This migration adds instance_id to all tables and updates primary keys to support
multiple Home Assistant instances being monitored by a single HA Boss instance.

Changes:
- Add instance_id column to all tables (default="default")
- Change primary keys from entity_id to integer ID
- Add composite unique indexes (instance_id, entity_id)
- Preserve all existing data with instance_id="default"
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from ha_boss.core.database import DatabaseVersion

logger = logging.getLogger(__name__)


# Note: This function is registered via the migration registry in __init__.py
async def migrate_v2_to_v3(session: AsyncSession) -> None:
    """Migrate database from v2 to v3.

    Args:
        session: Database session

    Raises:
        RuntimeError: If migration fails
    """
    logger.info("Starting migration from v2 to v3")

    try:
        # Get SQLAlchemy connection for raw SQL
        connection = await session.connection()

        # SQLite doesn't support ALTER TABLE ADD COLUMN with constraints,
        # so we need to use the recreate table pattern

        # Tables to migrate with their new structure
        tables_to_migrate = [
            # Core monitoring tables
            "entities",
            "health_events",
            "healing_actions",
            "integrations",
            "state_history",
            # Pattern collection tables
            "integration_reliability",
            "integration_metrics",
            # Discovery tables
            "automations",
            "scenes",
            "scripts",
            "automation_entities",
            "scene_entities",
            "script_entities",
            "discovery_refreshes",
        ]

        for table_name in tables_to_migrate:
            await _migrate_table(connection, table_name)

        # Update schema version
        # Note: Use literal 3 here, not CURRENT_DB_VERSION which may be higher
        from sqlalchemy import select

        target_version = 3
        result = await session.execute(
            select(DatabaseVersion).where(DatabaseVersion.version == target_version)
        )
        existing_version = result.scalar_one_or_none()

        if existing_version is None:
            new_version = DatabaseVersion(
                version=target_version,
                applied_at=datetime.now(UTC),
                description="Add instance_id for multi-instance support",
            )
            session.add(new_version)
            await session.commit()

        logger.info("Migration v2 → v3 completed successfully")

    except Exception as e:
        await session.rollback()
        logger.error("Migration v2 → v3 failed: %s", e, exc_info=True)
        raise RuntimeError(f"Migration failed: {e}") from e


async def _migrate_table(connection, table_name: str) -> None:
    """Migrate a single table to add instance_id.

    Uses SQLite's table recreation pattern since ALTER TABLE is limited.

    Args:
        connection: Database connection
        table_name: Name of table to migrate
    """
    logger.debug("Migrating table: %s", table_name)

    # Check if table exists
    inspector = inspect(connection)
    if table_name not in await connection.run_sync(lambda sync_conn: inspector.get_table_names()):
        logger.warning("Table %s does not exist, skipping migration", table_name)
        return

    # Get table-specific migration strategy
    if table_name == "entities":
        await _migrate_entities_table(connection)
    elif table_name == "health_events":
        await _migrate_health_events_table(connection)
    elif table_name == "healing_actions":
        await _migrate_healing_actions_table(connection)
    elif table_name == "integrations":
        await _migrate_integrations_table(connection)
    elif table_name == "state_history":
        await _migrate_state_history_table(connection)
    elif table_name == "integration_reliability":
        await _migrate_integration_reliability_table(connection)
    elif table_name == "integration_metrics":
        await _migrate_integration_metrics_table(connection)
    elif table_name == "automations":
        await _migrate_automations_table(connection)
    elif table_name == "scenes":
        await _migrate_scenes_table(connection)
    elif table_name == "scripts":
        await _migrate_scripts_table(connection)
    elif table_name == "automation_entities":
        await _migrate_automation_entities_table(connection)
    elif table_name == "scene_entities":
        await _migrate_scene_entities_table(connection)
    elif table_name == "script_entities":
        await _migrate_script_entities_table(connection)
    elif table_name == "discovery_refreshes":
        await _migrate_discovery_refreshes_table(connection)


async def _migrate_entities_table(connection) -> None:
    """Migrate entities table: entity_id (PK) → id (PK) + instance_id + entity_id."""
    await connection.execute(text("""
        CREATE TABLE entities_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            domain VARCHAR(50) NOT NULL,
            friendly_name VARCHAR(255),
            device_id VARCHAR(255),
            integration_id VARCHAR(255),
            last_seen DATETIME NOT NULL,
            last_state VARCHAR(255),
            is_monitored BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """))

    # Copy data
    await connection.execute(text("""
        INSERT INTO entities_new (instance_id, entity_id, domain, friendly_name, device_id,
                                  integration_id, last_seen, last_state, is_monitored,
                                  created_at, updated_at)
        SELECT 'default', entity_id, domain, friendly_name, device_id, integration_id,
               last_seen, last_state, is_monitored, created_at, updated_at
        FROM entities
        """))

    # Create indexes
    await connection.execute(
        text("CREATE INDEX ix_entities_instance_id ON entities_new (instance_id)")
    )
    await connection.execute(text("CREATE INDEX ix_entities_entity_id ON entities_new (entity_id)"))
    await connection.execute(text("CREATE INDEX ix_entities_domain ON entities_new (domain)"))
    await connection.execute(text("CREATE INDEX ix_entities_device_id ON entities_new (device_id)"))
    await connection.execute(
        text("CREATE INDEX ix_entities_integration_id ON entities_new (integration_id)")
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_entities_instance_entity ON entities_new (instance_id, entity_id)"
        )
    )

    # Swap tables
    await connection.execute(text("DROP TABLE entities"))
    await connection.execute(text("ALTER TABLE entities_new RENAME TO entities"))


async def _migrate_health_events_table(connection) -> None:
    """Migrate health_events table."""
    await connection.execute(text("""
        CREATE TABLE health_events_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            timestamp DATETIME NOT NULL,
            details JSON
        )
        """))

    await connection.execute(text("""
        INSERT INTO health_events_new (instance_id, entity_id, event_type, timestamp, details)
        SELECT 'default', entity_id, event_type, timestamp, details
        FROM health_events
        """))

    await connection.execute(
        text("CREATE INDEX ix_health_events_instance_id ON health_events_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_health_events_entity_id ON health_events_new (entity_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_health_events_event_type ON health_events_new (event_type)")
    )
    await connection.execute(
        text("CREATE INDEX ix_health_events_timestamp ON health_events_new (timestamp)")
    )

    await connection.execute(text("DROP TABLE health_events"))
    await connection.execute(text("ALTER TABLE health_events_new RENAME TO health_events"))


async def _migrate_healing_actions_table(connection) -> None:
    """Migrate healing_actions table."""
    await connection.execute(text("""
        CREATE TABLE healing_actions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            integration_id VARCHAR(255),
            action VARCHAR(100) NOT NULL,
            attempt_number INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            success BOOLEAN NOT NULL,
            error TEXT,
            duration_seconds FLOAT
        )
        """))

    await connection.execute(text("""
        INSERT INTO healing_actions_new (instance_id, entity_id, integration_id, action,
                                         attempt_number, timestamp, success, error, duration_seconds)
        SELECT 'default', entity_id, integration_id, action, attempt_number, timestamp,
               success, error, duration_seconds
        FROM healing_actions
        """))

    await connection.execute(
        text("CREATE INDEX ix_healing_actions_instance_id ON healing_actions_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_healing_actions_entity_id ON healing_actions_new (entity_id)")
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_healing_actions_integration_id ON healing_actions_new (integration_id)"
        )
    )
    await connection.execute(
        text("CREATE INDEX ix_healing_actions_timestamp ON healing_actions_new (timestamp)")
    )

    await connection.execute(text("DROP TABLE healing_actions"))
    await connection.execute(text("ALTER TABLE healing_actions_new RENAME TO healing_actions"))


async def _migrate_integrations_table(connection) -> None:
    """Migrate integrations table: entry_id (PK) → id (PK) + instance_id + entry_id."""
    await connection.execute(text("""
        CREATE TABLE integrations_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entry_id VARCHAR(255) NOT NULL,
            domain VARCHAR(100) NOT NULL,
            title VARCHAR(255) NOT NULL,
            source VARCHAR(50),
            entity_ids TEXT,
            is_discovered BOOLEAN NOT NULL DEFAULT 0,
            disabled BOOLEAN NOT NULL DEFAULT 0,
            last_successful_reload DATETIME,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            circuit_breaker_open_until DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO integrations_new (instance_id, entry_id, domain, title, source, entity_ids,
                                      is_discovered, disabled, last_successful_reload,
                                      consecutive_failures, circuit_breaker_open_until,
                                      created_at, updated_at)
        SELECT 'default', entry_id, domain, title, source, entity_ids, is_discovered, disabled,
               last_successful_reload, consecutive_failures, circuit_breaker_open_until,
               created_at, updated_at
        FROM integrations
        """))

    await connection.execute(
        text("CREATE INDEX ix_integrations_instance_id ON integrations_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_integrations_entry_id ON integrations_new (entry_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_integrations_domain ON integrations_new (domain)")
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_integrations_instance_entry ON integrations_new (instance_id, entry_id)"
        )
    )

    await connection.execute(text("DROP TABLE integrations"))
    await connection.execute(text("ALTER TABLE integrations_new RENAME TO integrations"))


async def _migrate_state_history_table(connection) -> None:
    """Migrate state_history table."""
    await connection.execute(text("""
        CREATE TABLE state_history_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            old_state VARCHAR(255),
            new_state VARCHAR(255) NOT NULL,
            timestamp DATETIME NOT NULL,
            context JSON
        )
        """))

    await connection.execute(text("""
        INSERT INTO state_history_new (instance_id, entity_id, old_state, new_state, timestamp, context)
        SELECT 'default', entity_id, old_state, new_state, timestamp, context
        FROM state_history
        """))

    await connection.execute(
        text("CREATE INDEX ix_state_history_instance_id ON state_history_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_state_history_entity_id ON state_history_new (entity_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_state_history_timestamp ON state_history_new (timestamp)")
    )

    await connection.execute(text("DROP TABLE state_history"))
    await connection.execute(text("ALTER TABLE state_history_new RENAME TO state_history"))


async def _migrate_integration_reliability_table(connection) -> None:
    """Migrate integration_reliability table."""
    await connection.execute(text("""
        CREATE TABLE integration_reliability_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            integration_id VARCHAR(255) NOT NULL,
            integration_domain VARCHAR(100) NOT NULL,
            timestamp DATETIME NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(255),
            details JSON,
            created_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO integration_reliability_new (instance_id, integration_id, integration_domain,
                                                 timestamp, event_type, entity_id, details, created_at)
        SELECT 'default', integration_id, integration_domain, timestamp, event_type,
               entity_id, details, created_at
        FROM integration_reliability
        """))

    await connection.execute(
        text(
            "CREATE INDEX ix_integration_reliability_instance_id ON integration_reliability_new (instance_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_reliability_integration_id ON integration_reliability_new (integration_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_reliability_integration_domain ON integration_reliability_new (integration_domain)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_reliability_timestamp ON integration_reliability_new (timestamp)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_reliability_event_type ON integration_reliability_new (event_type)"
        )
    )

    await connection.execute(text("DROP TABLE integration_reliability"))
    await connection.execute(
        text("ALTER TABLE integration_reliability_new RENAME TO integration_reliability")
    )


async def _migrate_integration_metrics_table(connection) -> None:
    """Migrate integration_metrics table."""
    await connection.execute(text("""
        CREATE TABLE integration_metrics_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            integration_id VARCHAR(255) NOT NULL,
            integration_domain VARCHAR(100) NOT NULL,
            period_start DATETIME NOT NULL,
            period_end DATETIME NOT NULL,
            total_events INTEGER NOT NULL DEFAULT 0,
            heal_successes INTEGER NOT NULL DEFAULT 0,
            heal_failures INTEGER NOT NULL DEFAULT 0,
            unavailable_events INTEGER NOT NULL DEFAULT 0,
            success_rate FLOAT
        )
        """))

    await connection.execute(text("""
        INSERT INTO integration_metrics_new (instance_id, integration_id, integration_domain,
                                             period_start, period_end, total_events, heal_successes,
                                             heal_failures, unavailable_events, success_rate)
        SELECT 'default', integration_id, integration_domain, period_start, period_end,
               total_events, heal_successes, heal_failures, unavailable_events, success_rate
        FROM integration_metrics
        """))

    await connection.execute(
        text(
            "CREATE INDEX ix_integration_metrics_instance_id ON integration_metrics_new (instance_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_metrics_integration_id ON integration_metrics_new (integration_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_metrics_integration_domain ON integration_metrics_new (integration_domain)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_integration_metrics_period_start ON integration_metrics_new (period_start)"
        )
    )

    await connection.execute(text("DROP TABLE integration_metrics"))
    await connection.execute(
        text("ALTER TABLE integration_metrics_new RENAME TO integration_metrics")
    )


async def _migrate_automations_table(connection) -> None:
    """Migrate automations table: entity_id (PK) → id (PK) + instance_id + entity_id."""
    await connection.execute(text("""
        CREATE TABLE automations_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            friendly_name VARCHAR(255),
            state VARCHAR(50) NOT NULL,
            mode VARCHAR(50),
            trigger_config JSON,
            condition_config JSON,
            action_config JSON,
            discovered_at DATETIME NOT NULL,
            last_seen DATETIME NOT NULL,
            is_monitored BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO automations_new (instance_id, entity_id, friendly_name, state, mode,
                                     trigger_config, condition_config, action_config,
                                     discovered_at, last_seen, is_monitored, created_at, updated_at)
        SELECT 'default', entity_id, friendly_name, state, mode, trigger_config, condition_config,
               action_config, discovered_at, last_seen, is_monitored, created_at, updated_at
        FROM automations
        """))

    await connection.execute(
        text("CREATE INDEX ix_automations_instance_id ON automations_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_automations_entity_id ON automations_new (entity_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_automations_last_seen ON automations_new (last_seen)")
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_automations_instance_entity ON automations_new (instance_id, entity_id)"
        )
    )

    await connection.execute(text("DROP TABLE automations"))
    await connection.execute(text("ALTER TABLE automations_new RENAME TO automations"))


async def _migrate_scenes_table(connection) -> None:
    """Migrate scenes table."""
    await connection.execute(text("""
        CREATE TABLE scenes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            friendly_name VARCHAR(255),
            entities_config JSON,
            discovered_at DATETIME NOT NULL,
            last_seen DATETIME NOT NULL,
            is_monitored BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO scenes_new (instance_id, entity_id, friendly_name, entities_config,
                                discovered_at, last_seen, is_monitored, created_at, updated_at)
        SELECT 'default', entity_id, friendly_name, entities_config, discovered_at, last_seen,
               is_monitored, created_at, updated_at
        FROM scenes
        """))

    await connection.execute(text("CREATE INDEX ix_scenes_instance_id ON scenes_new (instance_id)"))
    await connection.execute(text("CREATE INDEX ix_scenes_entity_id ON scenes_new (entity_id)"))
    await connection.execute(text("CREATE INDEX ix_scenes_last_seen ON scenes_new (last_seen)"))
    await connection.execute(
        text("CREATE UNIQUE INDEX ix_scenes_instance_entity ON scenes_new (instance_id, entity_id)")
    )

    await connection.execute(text("DROP TABLE scenes"))
    await connection.execute(text("ALTER TABLE scenes_new RENAME TO scenes"))


async def _migrate_scripts_table(connection) -> None:
    """Migrate scripts table."""
    await connection.execute(text("""
        CREATE TABLE scripts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            entity_id VARCHAR(255) NOT NULL,
            friendly_name VARCHAR(255),
            sequence_config JSON,
            mode VARCHAR(50),
            discovered_at DATETIME NOT NULL,
            last_seen DATETIME NOT NULL,
            is_monitored BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO scripts_new (instance_id, entity_id, friendly_name, sequence_config, mode,
                                 discovered_at, last_seen, is_monitored, created_at, updated_at)
        SELECT 'default', entity_id, friendly_name, sequence_config, mode, discovered_at,
               last_seen, is_monitored, created_at, updated_at
        FROM scripts
        """))

    await connection.execute(
        text("CREATE INDEX ix_scripts_instance_id ON scripts_new (instance_id)")
    )
    await connection.execute(text("CREATE INDEX ix_scripts_entity_id ON scripts_new (entity_id)"))
    await connection.execute(text("CREATE INDEX ix_scripts_last_seen ON scripts_new (last_seen)"))
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_scripts_instance_entity ON scripts_new (instance_id, entity_id)"
        )
    )

    await connection.execute(text("DROP TABLE scripts"))
    await connection.execute(text("ALTER TABLE scripts_new RENAME TO scripts"))


async def _migrate_automation_entities_table(connection) -> None:
    """Migrate automation_entities table."""
    await connection.execute(text("""
        CREATE TABLE automation_entities_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            automation_id VARCHAR(255) NOT NULL,
            entity_id VARCHAR(255) NOT NULL,
            relationship_type VARCHAR(50) NOT NULL,
            context JSON,
            discovered_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO automation_entities_new (instance_id, automation_id, entity_id,
                                             relationship_type, context, discovered_at)
        SELECT 'default', automation_id, entity_id, relationship_type, context, discovered_at
        FROM automation_entities
        """))

    await connection.execute(
        text(
            "CREATE INDEX ix_automation_entities_instance_id ON automation_entities_new (instance_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_automation_entities_automation_id ON automation_entities_new (automation_id)"
        )
    )
    await connection.execute(
        text("CREATE INDEX ix_automation_entities_entity_id ON automation_entities_new (entity_id)")
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_automation_entities_relationship_type ON automation_entities_new (relationship_type)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_automation_entities_automation ON automation_entities_new (instance_id, automation_id, relationship_type)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_automation_entities_entity ON automation_entities_new (instance_id, entity_id, relationship_type)"
        )
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_automation_entities_unique ON automation_entities_new (instance_id, automation_id, entity_id, relationship_type)"
        )
    )

    await connection.execute(text("DROP TABLE automation_entities"))
    await connection.execute(
        text("ALTER TABLE automation_entities_new RENAME TO automation_entities")
    )


async def _migrate_scene_entities_table(connection) -> None:
    """Migrate scene_entities table."""
    await connection.execute(text("""
        CREATE TABLE scene_entities_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            scene_id VARCHAR(255) NOT NULL,
            entity_id VARCHAR(255) NOT NULL,
            target_state VARCHAR(255),
            attributes JSON,
            discovered_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO scene_entities_new (instance_id, scene_id, entity_id, target_state,
                                        attributes, discovered_at)
        SELECT 'default', scene_id, entity_id, target_state, attributes, discovered_at
        FROM scene_entities
        """))

    await connection.execute(
        text("CREATE INDEX ix_scene_entities_instance_id ON scene_entities_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_scene_entities_scene_id ON scene_entities_new (scene_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_scene_entities_entity_id ON scene_entities_new (entity_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_scene_entities_scene ON scene_entities_new (instance_id, scene_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_scene_entities_entity ON scene_entities_new (instance_id, entity_id)")
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_scene_entities_unique ON scene_entities_new (instance_id, scene_id, entity_id)"
        )
    )

    await connection.execute(text("DROP TABLE scene_entities"))
    await connection.execute(text("ALTER TABLE scene_entities_new RENAME TO scene_entities"))


async def _migrate_script_entities_table(connection) -> None:
    """Migrate script_entities table."""
    await connection.execute(text("""
        CREATE TABLE script_entities_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            script_id VARCHAR(255) NOT NULL,
            entity_id VARCHAR(255) NOT NULL,
            sequence_step INTEGER,
            action_type VARCHAR(100),
            context JSON,
            discovered_at DATETIME NOT NULL
        )
        """))

    await connection.execute(text("""
        INSERT INTO script_entities_new (instance_id, script_id, entity_id, sequence_step,
                                         action_type, context, discovered_at)
        SELECT 'default', script_id, entity_id, sequence_step, action_type, context, discovered_at
        FROM script_entities
        """))

    await connection.execute(
        text("CREATE INDEX ix_script_entities_instance_id ON script_entities_new (instance_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_script_entities_script_id ON script_entities_new (script_id)")
    )
    await connection.execute(
        text("CREATE INDEX ix_script_entities_entity_id ON script_entities_new (entity_id)")
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_script_entities_script ON script_entities_new (instance_id, script_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_script_entities_entity ON script_entities_new (instance_id, entity_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE UNIQUE INDEX ix_script_entities_unique ON script_entities_new (instance_id, script_id, entity_id)"
        )
    )

    await connection.execute(text("DROP TABLE script_entities"))
    await connection.execute(text("ALTER TABLE script_entities_new RENAME TO script_entities"))


async def _migrate_discovery_refreshes_table(connection) -> None:
    """Migrate discovery_refreshes table."""
    await connection.execute(text("""
        CREATE TABLE discovery_refreshes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id VARCHAR(255) NOT NULL DEFAULT 'default',
            trigger_type VARCHAR(50) NOT NULL,
            trigger_source VARCHAR(100),
            automations_found INTEGER NOT NULL DEFAULT 0,
            scenes_found INTEGER NOT NULL DEFAULT 0,
            scripts_found INTEGER NOT NULL DEFAULT 0,
            entities_discovered INTEGER NOT NULL DEFAULT 0,
            duration_seconds FLOAT,
            timestamp DATETIME NOT NULL,
            success BOOLEAN NOT NULL,
            error_message TEXT
        )
        """))

    await connection.execute(text("""
        INSERT INTO discovery_refreshes_new (instance_id, trigger_type, trigger_source,
                                             automations_found, scenes_found, scripts_found,
                                             entities_discovered, duration_seconds, timestamp,
                                             success, error_message)
        SELECT 'default', trigger_type, trigger_source, automations_found, scenes_found,
               scripts_found, entities_discovered, duration_seconds, timestamp, success, error_message
        FROM discovery_refreshes
        """))

    await connection.execute(
        text(
            "CREATE INDEX ix_discovery_refreshes_instance_id ON discovery_refreshes_new (instance_id)"
        )
    )
    await connection.execute(
        text(
            "CREATE INDEX ix_discovery_refreshes_trigger_type ON discovery_refreshes_new (trigger_type)"
        )
    )
    await connection.execute(
        text("CREATE INDEX ix_discovery_refreshes_timestamp ON discovery_refreshes_new (timestamp)")
    )

    await connection.execute(text("DROP TABLE discovery_refreshes"))
    await connection.execute(
        text("ALTER TABLE discovery_refreshes_new RENAME TO discovery_refreshes")
    )
