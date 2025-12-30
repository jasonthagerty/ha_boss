"""Database models and management for HA Boss."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ha_boss.core.exceptions import DatabaseError

# Current database schema version
CURRENT_DB_VERSION = 3


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class DatabaseVersion(Base):
    """Track database schema version for migrations."""

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<DatabaseVersion(v{self.version}, {self.applied_at})>"


class Entity(Base):
    """Entity registry and monitoring status."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    friendly_name: Mapped[str | None] = mapped_column(String(255))
    device_id: Mapped[str | None] = mapped_column(String(255), index=True)
    integration_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_state: Mapped[str | None] = mapped_column(String(255))
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_entities_instance_entity", "instance_id", "entity_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Entity({self.instance_id}:{self.entity_id}, state={self.last_state})>"


class HealthEvent(Base):
    """Health events for monitored entities."""

    __tablename__ = "health_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # unavailable, stale, recovered
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def __repr__(self) -> str:
        return f"<HealthEvent({self.instance_id}:{self.entity_id}, {self.event_type}, {self.timestamp})>"


class HealingAction(Base):
    """Healing attempts and their outcomes."""

    __tablename__ = "healing_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    integration_id: Mapped[str | None] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # reload_integration, etc.
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        return f"<HealingAction({self.instance_id}:{self.entity_id}, {self.action}, {status})>"


class Integration(Base):
    """Integration registry for discovered integrations."""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entry_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50))
    entity_ids: Mapped[str | None] = mapped_column(Text)  # JSON string of entity IDs
    is_discovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_successful_reload: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    circuit_breaker_open_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_integrations_instance_entry", "instance_id", "entry_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Integration({self.instance_id}:{self.domain}, {self.title})>"


class StateHistory(Base):
    """Historical state changes for pattern analysis."""

    __tablename__ = "state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    old_state: Mapped[str | None] = mapped_column(String(255))
    new_state: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # time_of_day, day_of_week, etc.

    def __repr__(self) -> str:
        return f"<StateHistory({self.instance_id}:{self.entity_id}, {self.old_state}→{self.new_state})>"


# Phase 2: Pattern Collection Models


class IntegrationReliability(Base):
    """Track individual integration reliability events for pattern analysis."""

    __tablename__ = "integration_reliability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    integration_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    integration_domain: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # heal_success, heal_failure, unavailable
    entity_id: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<IntegrationReliability({self.instance_id}:{self.integration_domain}, {self.event_type}, {self.timestamp})>"


class IntegrationMetrics(Base):
    """Aggregated integration reliability metrics for faster queries."""

    __tablename__ = "integration_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    integration_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    integration_domain: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heal_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heal_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unavailable_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rate: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        return f"<IntegrationMetrics({self.instance_id}:{self.integration_domain}, {self.period_start}, rate={self.success_rate})>"


class PatternInsight(Base):
    """Store pre-calculated pattern insights for analysis."""

    __tablename__ = "pattern_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insight_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # top_failures, time_of_day, correlation
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, weekly, monthly
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<PatternInsight({self.insight_type}, {self.period}, {self.period_start})>"


# Auto-Discovery Models (Schema v2)


class Automation(Base):
    """Automation registry from Home Assistant."""

    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    friendly_name: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # on/off
    mode: Mapped[str | None] = mapped_column(String(50))  # single/restart/queued/parallel

    # Raw configuration for reference
    trigger_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    condition_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    action_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Discovery metadata
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_automations_instance_entity", "instance_id", "entity_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Automation({self.instance_id}:{self.entity_id}, state={self.state})>"


class Scene(Base):
    """Scene registry from Home Assistant."""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    friendly_name: Mapped[str | None] = mapped_column(String(255))
    entities_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (Index("ix_scenes_instance_entity", "instance_id", "entity_id", unique=True),)

    def __repr__(self) -> str:
        return f"<Scene({self.instance_id}:{self.entity_id})>"


class Script(Base):
    """Script registry from Home Assistant."""

    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    friendly_name: Mapped[str | None] = mapped_column(String(255))
    sequence_config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    mode: Mapped[str | None] = mapped_column(String(50))

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    is_monitored: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (Index("ix_scripts_instance_entity", "instance_id", "entity_id", unique=True),)

    def __repr__(self) -> str:
        return f"<Script({self.instance_id}:{self.entity_id})>"


class AutomationEntity(Base):
    """Junction table: automation → entities with relationship type."""

    __tablename__ = "automation_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Relationship context: trigger/condition/action
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index(
            "ix_automation_entities_automation",
            "instance_id",
            "automation_id",
            "relationship_type",
        ),
        Index("ix_automation_entities_entity", "instance_id", "entity_id", "relationship_type"),
        Index(
            "ix_automation_entities_unique",
            "instance_id",
            "automation_id",
            "entity_id",
            "relationship_type",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<AutomationEntity({self.instance_id}:{self.automation_id} → {self.entity_id}, {self.relationship_type})>"


class SceneEntity(Base):
    """Junction table: scene → entities."""

    __tablename__ = "scene_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_state: Mapped[str | None] = mapped_column(String(255))
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_scene_entities_scene", "instance_id", "scene_id"),
        Index("ix_scene_entities_entity", "instance_id", "entity_id"),
        Index("ix_scene_entities_unique", "instance_id", "scene_id", "entity_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<SceneEntity({self.instance_id}:{self.scene_id} → {self.entity_id})>"


class ScriptEntity(Base):
    """Junction table: script → entities."""

    __tablename__ = "script_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    script_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sequence_step: Mapped[int | None] = mapped_column(Integer)
    action_type: Mapped[str | None] = mapped_column(String(100))
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_script_entities_script", "instance_id", "script_id"),
        Index("ix_script_entities_entity", "instance_id", "entity_id"),
        Index("ix_script_entities_unique", "instance_id", "script_id", "entity_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ScriptEntity({self.instance_id}:{self.script_id} → {self.entity_id})>"


class DiscoveryRefresh(Base):
    """Track discovery refresh operations for audit and debugging."""

    __tablename__ = "discovery_refreshes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="default"
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # startup/manual/periodic/event
    trigger_source: Mapped[str | None] = mapped_column(String(100))

    automations_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scenes_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scripts_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entities_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    duration_seconds: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        return f"<DiscoveryRefresh({self.trigger_type}, {status}, {self.timestamp})>"


class Database:
    """Database manager for HA Boss."""

    def __init__(self, db_path: Path | str, echo: bool = False) -> None:
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file
            echo: Enable SQL query logging
        """
        self.db_path = Path(db_path)
        self.echo = echo

        # Create async engine
        db_url = f"sqlite+aiosqlite:///{self.db_path}"
        self.engine = create_async_engine(db_url, echo=echo)

        # Create session factory
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Initialize database (create tables if they don't exist)."""
        try:
            # Create parent directory if it doesn't exist
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create all tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Set initial version if this is a new database
            await self._ensure_version()
        except Exception as e:
            raise DatabaseError(f"Failed to initialize database: {e}") from e

    async def _ensure_version(self) -> None:
        """Ensure database version is set (initialize if new database)."""
        async with self.async_session() as session:
            # Check if version table has any records
            result = await session.execute(select(DatabaseVersion))
            version_record = result.scalars().first()

            if version_record is None:
                # New database - set current version
                new_version = DatabaseVersion(
                    version=CURRENT_DB_VERSION,
                    description=f"Initial schema v{CURRENT_DB_VERSION}",
                )
                session.add(new_version)
                await session.commit()

    async def get_version(self) -> int | None:
        """Get current database schema version.

        Returns:
            Current version number or None if not initialized
        """
        try:
            async with self.async_session() as session:
                result = await session.execute(
                    select(DatabaseVersion).order_by(DatabaseVersion.version.desc())
                )
                version_record = result.scalars().first()
                return version_record.version if version_record else None
        except Exception:
            # Table doesn't exist yet
            return None

    async def validate_version(self) -> tuple[bool, str]:
        """Validate database schema version.

        Returns:
            Tuple of (is_valid, message)
        """
        current_version = await self.get_version()

        if current_version is None:
            return False, "Database not initialized"

        if current_version < CURRENT_DB_VERSION:
            return (
                False,
                f"Database outdated (v{current_version}, need v{CURRENT_DB_VERSION}). Run migrations.",
            )

        if current_version > CURRENT_DB_VERSION:
            return (
                False,
                f"Database too new (v{current_version}, app supports v{CURRENT_DB_VERSION}). Update HA Boss.",
            )

        return True, f"Database version v{current_version} is current"

    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()

    async def __aenter__(self) -> "Database":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object
    ) -> None:
        """Exit async context manager."""
        await self.close()

    async def cleanup_old_records(self, retention_days: int) -> dict[str, int]:
        """Clean up old records based on retention policy.

        Args:
            retention_days: Keep records newer than this many days

        Returns:
            Dictionary with counts of deleted records per table
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)
        deleted_counts = {}

        async with self.async_session() as session:
            # Clean up old health events
            result = await session.execute(
                select(HealthEvent).where(HealthEvent.timestamp < cutoff_date)
            )
            old_events = result.scalars().all()
            for event in old_events:
                await session.delete(event)
            deleted_counts["health_events"] = len(old_events)

            # Clean up old healing actions
            result = await session.execute(
                select(HealingAction).where(HealingAction.timestamp < cutoff_date)
            )
            old_actions = result.scalars().all()
            for action in old_actions:
                await session.delete(action)
            deleted_counts["healing_actions"] = len(old_actions)

            # Clean up old state history
            result = await session.execute(
                select(StateHistory).where(StateHistory.timestamp < cutoff_date)
            )
            old_history = result.scalars().all()
            for history in old_history:
                await session.delete(history)
            deleted_counts["state_history"] = len(old_history)

            await session.commit()

        return deleted_counts


async def init_database(db_path: Path | str, echo: bool = False) -> Database:
    """Initialize database and create tables.

    Args:
        db_path: Path to SQLite database file
        echo: Enable SQL query logging

    Returns:
        Initialized database manager
    """
    db = Database(db_path, echo=echo)
    await db.init_db()
    return db
