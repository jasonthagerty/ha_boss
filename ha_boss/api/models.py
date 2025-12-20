"""Pydantic models for API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ServiceStatusResponse(BaseModel):
    """Service status information."""

    state: str = Field(..., description="Current service state")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    start_time: datetime | None = Field(None, description="Service start time")
    health_checks_performed: int = Field(..., description="Total health checks performed")
    healings_attempted: int = Field(..., description="Total healing attempts")
    healings_succeeded: int = Field(..., description="Successful healings")
    healings_failed: int = Field(..., description="Failed healings")
    monitored_entities: int = Field(..., description="Number of monitored entities")


class HealthCheckResponse(BaseModel):
    """Health check endpoint response."""

    status: str = Field(..., description="Health status (healthy/degraded/unhealthy)")
    service_running: bool = Field(..., description="Is service running")
    ha_connected: bool = Field(..., description="Is Home Assistant connected")
    websocket_connected: bool = Field(..., description="Is WebSocket connected")
    database_accessible: bool = Field(..., description="Is database accessible")
    timestamp: datetime = Field(..., description="Health check timestamp")


class EntityStateResponse(BaseModel):
    """Entity state information."""

    entity_id: str = Field(..., description="Entity ID")
    state: str = Field(..., description="Current state")
    attributes: dict[str, Any] = Field(default_factory=dict, description="State attributes")
    last_changed: datetime | None = Field(None, description="Last state change time")
    last_updated: datetime | None = Field(None, description="Last update time")
    monitored: bool = Field(..., description="Is entity being monitored")


class EntityHistoryResponse(BaseModel):
    """Entity state history."""

    entity_id: str = Field(..., description="Entity ID")
    history: list[dict[str, Any]] = Field(..., description="State history entries")
    count: int = Field(..., description="Number of history entries")


class IntegrationReliabilityResponse(BaseModel):
    """Integration reliability statistics."""

    integration: str = Field(..., description="Integration name")
    total_entities: int = Field(..., description="Total entities in integration")
    unavailable_count: int = Field(..., description="Currently unavailable entities")
    failure_count: int = Field(..., description="Total failure events")
    success_count: int = Field(..., description="Total success events")
    reliability_percent: float = Field(..., description="Reliability percentage")
    last_failure: datetime | None = Field(None, description="Last failure timestamp")


class FailureEventResponse(BaseModel):
    """Failure event information."""

    id: int = Field(..., description="Event ID")
    entity_id: str = Field(..., description="Entity ID")
    integration: str | None = Field(None, description="Integration name")
    state: str = Field(..., description="Entity state")
    timestamp: datetime = Field(..., description="Event timestamp")
    resolved: bool = Field(..., description="Is failure resolved")
    resolution_time: datetime | None = Field(None, description="Resolution timestamp")


class WeeklySummaryResponse(BaseModel):
    """Weekly summary statistics."""

    start_date: datetime = Field(..., description="Summary start date")
    end_date: datetime = Field(..., description="Summary end date")
    total_health_checks: int = Field(..., description="Health checks performed")
    total_failures: int = Field(..., description="Total failures detected")
    total_healings: int = Field(..., description="Healing attempts")
    success_rate: float = Field(..., description="Healing success rate")
    top_failing_integrations: list[str] = Field(..., description="Most problematic integrations")
    ai_insights: str | None = Field(None, description="AI-generated insights")


class AutomationAnalysisRequest(BaseModel):
    """Request to analyze an automation."""

    automation_id: str = Field(..., description="Automation ID to analyze")


class AutomationAnalysisResponse(BaseModel):
    """Automation analysis result."""

    automation_id: str = Field(..., description="Automation ID")
    alias: str = Field(..., description="Automation alias")
    analysis: str = Field(..., description="AI-generated analysis")
    suggestions: list[str] = Field(default_factory=list, description="Optimization suggestions")
    complexity_score: int | None = Field(None, description="Complexity score (1-10)")


class AutomationGenerateRequest(BaseModel):
    """Request to generate an automation."""

    description: str = Field(..., description="Natural language description")
    mode: str = Field("single", description="Automation mode")


class AutomationGenerateResponse(BaseModel):
    """Generated automation result."""

    automation_id: str = Field(..., description="Generated automation ID")
    alias: str = Field(..., description="Automation alias")
    description: str = Field(..., description="Automation description")
    yaml_content: str = Field(..., description="Generated YAML")
    validation_errors: list[str] | None = Field(None, description="Validation errors if any")
    is_valid: bool = Field(..., description="Is automation valid")


class AutomationCreateRequest(BaseModel):
    """Request to create an automation in Home Assistant."""

    automation_yaml: str = Field(..., description="Automation YAML to create")


class AutomationCreateResponse(BaseModel):
    """Automation creation result."""

    success: bool = Field(..., description="Was creation successful")
    automation_id: str | None = Field(None, description="Created automation ID")
    message: str = Field(..., description="Result message")


class HealingActionResponse(BaseModel):
    """Healing action result."""

    entity_id: str = Field(..., description="Entity ID")
    integration: str | None = Field(None, description="Integration name")
    action_type: str = Field(..., description="Healing action type")
    success: bool = Field(..., description="Was healing successful")
    timestamp: datetime = Field(..., description="Action timestamp")
    message: str = Field(..., description="Result message")


class HealingHistoryResponse(BaseModel):
    """Healing action history."""

    actions: list[HealingActionResponse] = Field(..., description="Healing actions")
    total_count: int = Field(..., description="Total actions in history")
    success_count: int = Field(..., description="Successful actions")
    failure_count: int = Field(..., description="Failed actions")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Error details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Error timestamp")
