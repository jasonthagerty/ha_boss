"""Pydantic models for MCP tool request/response schemas."""

from pydantic import BaseModel, Field


# Entity Models
class EntityState(BaseModel):
    """Entity state information."""

    entity_id: str = Field(description="Entity ID (e.g., 'sensor.temperature')")
    domain: str = Field(description="Entity domain (e.g., 'sensor', 'light')")
    state: str | None = Field(description="Current state value")
    friendly_name: str | None = Field(description="Human-readable name")
    integration_id: str | None = Field(description="Associated integration entry ID")
    last_updated: str = Field(description="Last update timestamp (ISO format)")


class EntityHistoryEntry(BaseModel):
    """Single state change entry."""

    old_state: str | None = Field(description="Previous state value")
    new_state: str = Field(description="New state value")
    timestamp: str = Field(description="Change timestamp (ISO format)")


# Health & Service Models
class ServiceStatus(BaseModel):
    """HA Boss service status."""

    status: str = Field(description="Service status (running, degraded, unhealthy)")
    uptime_seconds: float = Field(description="Service uptime in seconds")
    total_entities: int = Field(description="Total monitored entities")
    total_healing_attempts: int = Field(description="Total healing attempts")
    successful_healings: int = Field(description="Successful healing count")


class ComponentHealth(BaseModel):
    """Individual component health status."""

    component: str = Field(description="Component name")
    status: str = Field(description="Status (healthy, degraded, unhealthy, unknown)")
    message: str | None = Field(description="Status message or error")
    tier: int = Field(description="Component tier (1=critical, 5=intelligence)")


class HealthCheck(BaseModel):
    """Comprehensive health check result."""

    overall_status: str = Field(description="Overall status (healthy, degraded, unhealthy)")
    timestamp: str = Field(description="Check timestamp (ISO format)")
    components: list[ComponentHealth] = Field(description="Component health details")


# Healing Models
class HealingAction(BaseModel):
    """Healing action record."""

    id: int = Field(description="Action ID")
    entity_id: str = Field(description="Healed entity ID")
    integration_id: str | None = Field(description="Target integration")
    action: str = Field(description="Action type (reload_integration, etc.)")
    timestamp: str = Field(description="Action timestamp (ISO format)")
    success: bool = Field(description="Whether action succeeded")
    error: str | None = Field(description="Error message if failed")
    duration_seconds: float | None = Field(description="Action duration")


class HealingStats(BaseModel):
    """Healing statistics summary."""

    total_attempts: int = Field(description="Total healing attempts")
    successful_attempts: int = Field(description="Successful attempts")
    failed_attempts: int = Field(description="Failed attempts")
    success_rate: float = Field(description="Success rate percentage")
    days: int = Field(description="Days of data analyzed")


class HealingResult(BaseModel):
    """Result of a healing trigger."""

    entity_id: str = Field(description="Healed entity ID")
    action: str = Field(description="Action performed")
    success: bool = Field(description="Whether healing succeeded")
    dry_run: bool = Field(description="Whether this was a dry run")
    message: str = Field(description="Result message")
    duration_seconds: float | None = Field(description="Action duration")


# Pattern Analysis Models
class IntegrationReliability(BaseModel):
    """Integration reliability statistics."""

    integration_domain: str = Field(description="Integration domain (e.g., 'hue')")
    total_events: int = Field(description="Total events recorded")
    heal_successes: int = Field(description="Successful healing events")
    heal_failures: int = Field(description="Failed healing events")
    unavailable_events: int = Field(description="Unavailable entity events")
    reliability_score: float = Field(description="Reliability percentage (0-100)")
    days_analyzed: int = Field(description="Days of data analyzed")


class FailureEvent(BaseModel):
    """Failure event record."""

    timestamp: str = Field(description="Event timestamp (ISO format)")
    entity_id: str = Field(description="Affected entity ID")
    integration_domain: str | None = Field(description="Integration domain")
    event_type: str = Field(description="Event type (unavailable, heal_failure, etc.)")
    resolved: bool = Field(description="Whether issue was resolved")
    resolution_time_seconds: float | None = Field(description="Time to resolution")


class Anomaly(BaseModel):
    """Detected anomaly."""

    entity_id: str = Field(description="Entity with anomaly")
    anomaly_type: str = Field(description="Type of anomaly detected")
    severity: str = Field(description="Severity (low, medium, high)")
    timestamp: str = Field(description="Detection timestamp (ISO format)")
    description: str = Field(description="Human-readable description")
    ai_insights: str | None = Field(description="AI-generated insights (if available)")


# Configuration Model
class ConfigSummary(BaseModel):
    """Sanitized configuration summary."""

    monitored_entities_count: int = Field(description="Number of monitored entities")
    auto_healing_enabled: bool = Field(description="Whether auto-healing is enabled")
    healing_max_attempts: int = Field(description="Maximum healing attempts per entity")
    grace_period_seconds: int = Field(description="Grace period before triggering healing")
    api_enabled: bool = Field(description="Whether REST API is enabled")
    llm_enabled: bool = Field(description="Whether LLM features are enabled")
