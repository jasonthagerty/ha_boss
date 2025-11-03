"""Database models and management for HA Boss."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ha_boss.core.exceptions import DatabaseError


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class Entity(Base):
    """Entity registry and monitoring status."""

    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(255), primary_key=True)
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

    def __repr__(self) -> str:
        return f"<Entity({self.entity_id}, state={self.last_state})>"


class HealthEvent(Base):
    """Health events for monitored entities."""

    __tablename__ = "health_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # unavailable, stale, recovered
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def __repr__(self) -> str:
        return f"<HealthEvent({self.entity_id}, {self.event_type}, {self.timestamp})>"


class HealingAction(Base):
    """Healing attempts and their outcomes."""

    __tablename__ = "healing_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
        return f"<HealingAction({self.entity_id}, {self.action}, {status})>"


class Integration(Base):
    """Integration registry for discovered integrations."""

    __tablename__ = "integrations"

    entry_id: Mapped[str] = mapped_column(String(255), primary_key=True)
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

    def __repr__(self) -> str:
        return f"<Integration({self.domain}, {self.title})>"


class StateHistory(Base):
    """Historical state changes for pattern analysis."""

    __tablename__ = "state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    old_state: Mapped[str | None] = mapped_column(String(255))
    new_state: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # time_of_day, day_of_week, etc.

    def __repr__(self) -> str:
        return f"<StateHistory({self.entity_id}, {self.old_state}→{self.new_state})>"


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
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as e:
            raise DatabaseError(f"Failed to initialize database: {e}") from e

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
