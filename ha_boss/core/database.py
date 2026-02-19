"""Database models and management for HA Boss."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ha_boss.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# Current database schema version
CURRENT_DB_VERSION = 9


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
    healing_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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


class AutomationExecution(Base):
    """Track automation executions for pattern analysis.

    Records each time an automation runs, including success/failure,
    trigger type, and execution duration. Used by AutomationAnalyzer
    to provide usage-based optimization recommendations.
    """

    __tablename__ = "automation_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "idx_automation_executions_instance_automation",
            "instance_id",
            "automation_id",
        ),
        Index("idx_automation_executions_executed_at", "executed_at"),
    )

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        return f"<AutomationExecution({self.instance_id}:{self.automation_id}, {status}, {self.executed_at})>"


class AutomationServiceCall(Base):
    """Track service calls made by automations.

    Records each service call triggered by an automation, including
    response times and success status. Used to identify slow or
    unreliable service calls in optimization analysis.
    """

    __tablename__ = "automation_service_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(255))
    called_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index(
            "idx_automation_service_calls_instance_automation",
            "instance_id",
            "automation_id",
        ),
        Index("idx_automation_service_calls_called_at", "called_at"),
        Index("idx_automation_service_calls_service_name", "service_name"),
    )

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        return f"<AutomationServiceCall({self.instance_id}:{self.automation_id} -> {self.service_name}, {status})>"


# Outcome Validation Models (Schema v7)


class AutomationDesiredState(Base):
    """Track desired outcomes for automations (inferred or user-annotated).

    Stores what state an automation is trying to achieve for each target
    entity. Used to validate whether automation executions succeed in
    reaching their intended goals.
    """

    __tablename__ = "automation_desired_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    desired_state: Mapped[str] = mapped_column(String(255), nullable=False)
    desired_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inference_method: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # ai_analysis, user_annotated, learned
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
        Index(
            "idx_automation_desired_states_automation",
            "instance_id",
            "automation_id",
        ),
        Index(
            "idx_automation_desired_states_unique",
            "instance_id",
            "automation_id",
            "entity_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<AutomationDesiredState({self.instance_id}:{self.automation_id} -> {self.entity_id} = {self.desired_state}, confidence={self.confidence})>"


class AutomationOutcomeValidation(Base):
    """Track outcome validation results for automation executions.

    Records whether each automation execution achieved its desired outcomes
    by comparing expected states to actual states after execution.
    """

    __tablename__ = "automation_outcome_validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    execution_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )  # FK to AutomationExecution
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    desired_state: Mapped[str] = mapped_column(String(255), nullable=False)
    desired_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actual_state: Mapped[str | None] = mapped_column(String(255))
    actual_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    achieved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_to_achievement_ms: Mapped[int | None] = mapped_column(Integer)
    user_description: Mapped[str | None] = mapped_column(Text)  # User-reported failure description
    validation_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "idx_automation_outcome_validations_execution",
            "instance_id",
            "execution_id",
        ),
        Index(
            "idx_automation_outcome_validations_achieved",
            "instance_id",
            "achieved",
        ),
    )

    def __repr__(self) -> str:
        status = "achieved" if self.achieved else "failed"
        return f"<AutomationOutcomeValidation(execution_id={self.execution_id}, {self.entity_id}, {status})>"


class AutomationOutcomePattern(Base):
    """Learn patterns from successful automation executions.

    Tracks what states automations actually achieve when they run successfully,
    used to refine desired state inferences and increase confidence over time.
    """

    __tablename__ = "automation_outcome_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    observed_state: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_observed: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    last_observed: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    # Multi-level healing tracking (v8)
    successful_healing_level: Mapped[str | None] = mapped_column(String(50))
    successful_healing_strategy: Mapped[str | None] = mapped_column(String(255))
    healing_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index(
            "idx_automation_outcome_patterns_automation",
            "instance_id",
            "automation_id",
        ),
        Index(
            "idx_automation_outcome_patterns_unique",
            "instance_id",
            "automation_id",
            "entity_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<AutomationOutcomePattern({self.instance_id}:{self.automation_id} -> {self.entity_id} = {self.observed_state}, count={self.occurrence_count})>"


# Multi-Level Healing Models (Schema v8)


class HealingStrategy(Base):
    """Available healing actions at each level.

    Defines the strategies available for healing failures at different levels:
    entity (retry, alternative parameters), device (reconnect, reboot, rediscover),
    and integration (reload, restart).
    """

    __tablename__ = "healing_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # entity, device, integration
    strategy_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # retry_service_call, device_reconnect, reload_integration, etc.
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # Strategy-specific parameters
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<HealingStrategy({self.level}::{self.strategy_type}, enabled={self.enabled})>"


class DeviceHealingAction(Base):
    """Track device-level healing attempts.

    Records when healing actions are performed at the device level (reconnect,
    reboot, rediscover) and their outcomes.
    """

    __tablename__ = "device_healing_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # References stored_instances
    device_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # reconnect, reboot, rediscover
    triggered_by: Mapped[str | None] = mapped_column(
        String(100)
    )  # automation_failure, manual, pattern
    automation_id: Mapped[str | None] = mapped_column(String(255))
    execution_id: Mapped[int | None] = mapped_column(Integer)  # FK to AutomationExecution
    success: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_device_healing_actions_instance_device", "instance_id", "device_id"),
    )

    def __repr__(self) -> str:
        status = "success" if self.success else "failed" if self.success is False else "pending"
        return f"<DeviceHealingAction({self.instance_id}:{self.device_id}, {self.action_type}, {status})>"


class EntityHealingAction(Base):
    """Track entity-level healing attempts.

    Records when healing actions are performed at the entity level (retry service
    call with same or alternative parameters) and their outcomes.
    """

    __tablename__ = "entity_healing_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # References stored_instances
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # retry_service_call, alternative_params
    service_domain: Mapped[str | None] = mapped_column(String(100))
    service_name: Mapped[str | None] = mapped_column(String(100))
    service_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # Service call parameters
    triggered_by: Mapped[str | None] = mapped_column(
        String(100)
    )  # automation_failure, manual, pattern
    automation_id: Mapped[str | None] = mapped_column(String(255))
    execution_id: Mapped[int | None] = mapped_column(Integer)  # FK to AutomationExecution
    success: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_entity_healing_actions_instance_entity", "instance_id", "entity_id"),
    )

    def __repr__(self) -> str:
        status = "success" if self.success else "failed" if self.success is False else "pending"
        return f"<EntityHealingAction({self.instance_id}:{self.entity_id}, {self.action_type}, {status})>"


class HealingCascadeExecution(Base):
    """Track full healing cascade attempts.

    Records the progression of healing attempts through multiple levels (entity,
    device, integration) and whether each level's healing was successful. Tracks
    which routing strategy was used (intelligent vs sequential) and final outcome.
    """

    __tablename__ = "healing_cascade_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # References stored_instances
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    execution_id: Mapped[int | None] = mapped_column(Integer)  # FK to AutomationExecution
    trigger_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # trigger_failure, outcome_failure
    failed_entities: Mapped[list[str] | None] = mapped_column(JSON)  # List of entities that failed

    # Cascade progression
    entity_level_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entity_level_success: Mapped[bool | None] = mapped_column(Boolean)
    device_level_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    device_level_success: Mapped[bool | None] = mapped_column(Boolean)
    integration_level_attempted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    integration_level_success: Mapped[bool | None] = mapped_column(Boolean)

    # Routing
    routing_strategy: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # intelligent, sequential
    matched_pattern_id: Mapped[int | None] = mapped_column(
        Integer
    )  # FK to AutomationOutcomePattern

    # Results
    final_success: Mapped[bool | None] = mapped_column(Boolean)
    total_duration_seconds: Mapped[float | None] = mapped_column(Float)
    timeout_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # AI plan generation
    plan_generation_suggested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_healing_cascade_executions_instance_automation", "instance_id", "automation_id"),
    )

    def __repr__(self) -> str:
        status = (
            "success"
            if self.final_success
            else "failed" if self.final_success is False else "in_progress"
        )
        return f"<HealingCascadeExecution({self.instance_id}:{self.automation_id}, {self.routing_strategy}, {status})>"


class AutomationHealthStatus(Base):
    """Track consecutive success/failure counts for validation gating.

    Maintains per-automation counters for consecutive successes and failures,
    used to determine when an automation is "validated healthy" (meets consecutive
    success threshold) for reliability scoring.
    """

    __tablename__ = "automation_health_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # References stored_instances
    automation_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Consecutive tracking
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Validation gating
    is_validated_healthy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_validation_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Statistics
    total_executions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_automation_health_status_instance_automation",
            "instance_id",
            "automation_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<AutomationHealthStatus({self.instance_id}:{self.automation_id}, successes={self.consecutive_successes}, failures={self.consecutive_failures})>"


# Healing Plan Models (Schema v9)


class HealingPlan(Base):
    """Stored healing plan definitions.

    Plans define match criteria and ordered healing steps that can be
    loaded from YAML files or managed via the API. Plans are evaluated
    before the existing cascade routing to provide configurable healing
    strategies.
    """

    __tablename__ = "healing_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="user")  # builtin, user

    # Match criteria (stored as JSON)
    match_criteria: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Healing steps (stored as JSON list)
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)

    # On-failure config (stored as JSON)
    on_failure: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Tags for filtering
    tags: Mapped[list[str] | None] = mapped_column(JSON)

    # Execution stats (updated by plan executor)
    total_executions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"<HealingPlan({self.name}, priority={self.priority}, {status})>"


class HealingPlanExecution(Base):
    """Track individual healing plan executions.

    Records which plan was used, which entities were targeted, which steps
    were attempted, and the overall outcome.
    """

    __tablename__ = "healing_plan_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    automation_id: Mapped[str | None] = mapped_column(String(255))
    cascade_execution_id: Mapped[int | None] = mapped_column(
        Integer
    )  # FK to HealingCascadeExecution

    # Entities targeted
    target_entities: Mapped[list[str] | None] = mapped_column(JSON)

    # Step execution details (JSON list of step results)
    steps_attempted: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    steps_succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steps_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Results
    overall_success: Mapped[bool | None] = mapped_column(Boolean)
    total_duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (Index("idx_healing_plan_executions_plan_instance", "plan_id", "instance_id"),)

    def __repr__(self) -> str:
        status = (
            "success"
            if self.overall_success
            else "failed" if self.overall_success is False else "in_progress"
        )
        return f"<HealingPlanExecution(plan={self.plan_name}, {status})>"


# Configuration Management Models (Schema v5)


class RuntimeConfig(Base):
    """Store runtime configuration overrides from dashboard.

    Stores configuration values that override YAML defaults but are
    overridden by environment variables. Values are JSON-serialized.
    """

    __tablename__ = "runtime_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized
    value_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # string, int, float, bool, list, dict
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(50), nullable=False, default="dashboard")

    def __repr__(self) -> str:
        return f"<RuntimeConfig({self.key}={self.value[:50]}...)>"


class StoredInstance(Base):
    """Store Home Assistant instance configurations.

    Stores HA instance configurations with encrypted tokens.
    These supplement or replace YAML-configured instances.
    """

    __tablename__ = "stored_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet encrypted
    bridge_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="dashboard"
    )  # dashboard, yaml, import
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
        status = "active" if self.is_active else "inactive"
        return f"<StoredInstance({self.instance_id}, {self.url}, {status})>"


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

            # Run any pending migrations for existing databases
            await self._run_migrations()
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

    async def _run_migrations(self) -> None:
        """Run pending database migrations.

        Uses the migration registry to find and run all migrations needed
        to upgrade from the current version to CURRENT_DB_VERSION.
        Creates a backup before any migrations are run.

        Raises:
            DatabaseError: If migration fails
        """
        from ha_boss.core.migrations import MIGRATION_REGISTRY

        current_version = await self.get_version()

        if current_version is None:
            # Database not initialized yet, nothing to migrate
            return

        if current_version >= CURRENT_DB_VERSION:
            # Already at current version
            return

        # Get all migrations needed
        migrations = MIGRATION_REGISTRY.get_migrations_for_upgrade(
            current_version, CURRENT_DB_VERSION
        )

        if not migrations:
            logger.warning(
                f"No migrations found for v{current_version} → v{CURRENT_DB_VERSION}. "
                "This may indicate missing migration files."
            )
            return

        logger.info(
            f"Running {len(migrations)} migration(s) from v{current_version} to v{CURRENT_DB_VERSION}"
        )
        for m in migrations:
            logger.info(f"  - v{m.target_version}: {m.description}")

        # Create backup before any migrations
        backup_path = await self._backup_database(current_version)
        logger.info(f"Created database backup at: {backup_path}")

        try:
            # Run migrations sequentially
            for migration in migrations:
                prev_version = migration.target_version - 1
                logger.info(
                    f"Running migration: v{prev_version} → v{migration.target_version} "
                    f"({migration.description})"
                )

                async with self.async_session() as session:
                    await migration.migrate_func(session)

                logger.info(f"Migration to v{migration.target_version} completed successfully")

            # Verify final version
            final_version = await self.get_version()
            if final_version != CURRENT_DB_VERSION:
                raise DatabaseError(
                    f"Migration completed but version mismatch: "
                    f"expected v{CURRENT_DB_VERSION}, got v{final_version}"
                )

            logger.info(f"All migrations completed. Database now at v{CURRENT_DB_VERSION}")

        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            logger.error(f"Database backup available at: {backup_path}")
            raise DatabaseError(f"Failed to run migrations: {e}") from e

    async def _backup_database(self, version: int) -> Path:
        """Create a backup of the database before migration.

        Args:
            version: Current database version (used in backup filename)

        Returns:
            Path to the backup file

        Raises:
            DatabaseError: If backup fails
        """
        import shutil

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{self.db_path.stem}_v{version}_backup_{timestamp}{self.db_path.suffix}"
        backup_path = self.db_path.parent / backup_name

        try:
            # Close connections before backup to ensure data is flushed
            await self.engine.dispose()

            # Copy the database file
            shutil.copy2(self.db_path, backup_path)

            # Recreate the engine after backup
            self.engine = create_async_engine(
                f"sqlite+aiosqlite:///{self.db_path}",
                echo=False,
            )
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            logger.info(f"Database backup created: {backup_path}")
            return backup_path

        except Exception as e:
            raise DatabaseError(f"Failed to create database backup: {e}") from e

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
