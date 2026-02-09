"""Pydantic models for API requests and responses."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class InstanceInfo(BaseModel):
    """Home Assistant instance information."""

    instance_id: str = Field(..., description="Instance identifier")
    url: str = Field(..., description="Home Assistant URL")
    websocket_connected: bool = Field(..., description="Is WebSocket connected")
    state: str = Field(..., description="Instance connection state")


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
    """Health check endpoint response.

    DEPRECATED: Use EnhancedHealthCheckResponse for comprehensive health checks.
    This model is kept for backward compatibility reference only.
    """

    status: str = Field(..., description="Health status (healthy/degraded/unhealthy)")
    service_running: bool = Field(..., description="Is service running")
    ha_connected: bool = Field(..., description="Is Home Assistant connected")
    websocket_connected: bool = Field(..., description="Is WebSocket connected")
    database_accessible: bool = Field(..., description="Is database accessible")
    timestamp: datetime = Field(..., description="Health check timestamp")


class ComponentHealth(BaseModel):
    """Individual component health status."""

    status: Literal["healthy", "degraded", "unhealthy", "unknown"] = Field(
        ..., description="Component health status"
    )
    message: str | None = Field(None, description="Status message or explanation")
    last_update: datetime | None = Field(None, description="Last successful update timestamp")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional component-specific details"
    )


class PerformanceMetrics(BaseModel):
    """Service performance metrics."""

    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    memory_usage_mb: float | None = Field(None, description="Memory usage in megabytes")
    rest_api_latency_ms: float | None = Field(
        None, description="Last REST API request latency in milliseconds"
    )
    websocket_latency_ms: float | None = Field(
        None, description="Last WebSocket ping latency in milliseconds"
    )
    db_query_latency_ms: float | None = Field(
        None, description="Last database query latency in milliseconds"
    )


class EnhancedHealthCheckResponse(BaseModel):
    """Comprehensive health check response with tier-based component status.

    This response provides detailed health information across 5 tiers:
    - Tier 1 (critical): Service cannot run without these components
    - Tier 2 (essential): Core functionality components
    - Tier 3 (operational): Health monitoring components
    - Tier 4 (healing): Auto-healing capability components
    - Tier 5 (intelligence): Optional AI features (graceful degradation)

    HTTP Status Codes:
    - 200 OK: Status is "healthy" or "degraded" (service still functional)
    - 503 Service Unavailable: Status is "unhealthy" (critical failure)
    """

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ..., description="Overall health status determined by tier priority"
    )
    timestamp: datetime = Field(..., description="Health check timestamp")
    version: str = Field(default="2.0.0", description="Health check schema version")

    # Component status by tier
    critical: dict[str, ComponentHealth] = Field(
        ..., description="Tier 1: Critical components (service cannot run without these)"
    )
    essential: dict[str, ComponentHealth] = Field(
        ..., description="Tier 2: Essential components (core functionality)"
    )
    operational: dict[str, ComponentHealth] = Field(
        ..., description="Tier 3: Operational components (health monitoring)"
    )
    healing: dict[str, ComponentHealth] = Field(
        ..., description="Tier 4: Healing components (auto-healing capability)"
    )
    intelligence: dict[str, ComponentHealth] = Field(
        ..., description="Tier 5: Intelligence components (optional AI features)"
    )

    # Performance metrics
    performance: PerformanceMetrics = Field(..., description="Service performance metrics")

    # Summary counts
    summary: dict[str, int] = Field(
        ...,
        description='Component count summary by status (e.g., {"healthy": 18, "degraded": 2})',
    )


class EntityStateResponse(BaseModel):
    """Entity state information."""

    entity_id: str = Field(..., description="Entity ID")
    state: str = Field(..., description="Current state")
    attributes: dict[str, Any] = Field(default_factory=dict, description="State attributes")
    last_changed: datetime | None = Field(None, description="Last state change time")
    last_updated: datetime | None = Field(None, description="Last update time")
    monitored: bool = Field(..., description="Is entity being monitored")
    instance_id: str | None = Field(None, description="Instance ID (present in aggregate mode)")


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
    instance_id: str | None = Field(None, description="Instance ID (present in aggregate mode)")


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


class HealingActionResponse(BaseModel):
    """Healing action result."""

    entity_id: str = Field(..., description="Entity ID")
    integration: str | None = Field(None, description="Integration name")
    action_type: str = Field(..., description="Healing action type")
    success: bool = Field(..., description="Was healing successful")
    timestamp: datetime = Field(..., description="Action timestamp")
    message: str = Field(..., description="Result message")
    instance_id: str | None = Field(None, description="Instance ID (present in aggregate mode)")
    trigger_reason: str | None = Field(
        None, description="Why healing was triggered (unavailable, stale, unknown, manual_heal)"
    )
    error_message: str | None = Field(None, description="Error message if healing failed")
    attempt_number: int | None = Field(None, description="Attempt number for this entity")


class HealingHistoryResponse(BaseModel):
    """Healing action history."""

    actions: list[HealingActionResponse] = Field(..., description="Healing actions")
    total_count: int = Field(..., description="Total actions in history")
    success_count: int = Field(..., description="Successful actions")
    failure_count: int = Field(..., description="Failed actions")


class SuppressedEntityResponse(BaseModel):
    """Response for a suppressed entity."""

    entity_id: str = Field(..., description="Entity ID")
    instance_id: str = Field(..., description="Instance ID")
    friendly_name: str | None = Field(None, description="Entity friendly name")
    integration: str | None = Field(None, description="Integration name")
    suppressed_since: datetime | None = Field(None, description="When entity was last updated")


class SuppressedEntitiesResponse(BaseModel):
    """Response for list of suppressed entities."""

    entities: list[SuppressedEntityResponse] = Field(
        default_factory=list, description="List of suppressed entities"
    )
    total_count: int = Field(..., description="Total count of suppressed entities")


class SuppressionActionResponse(BaseModel):
    """Response for suppression action (suppress/unsuppress)."""

    entity_id: str = Field(..., description="Entity ID")
    suppressed: bool = Field(..., description="Whether healing is now suppressed")
    message: str = Field(..., description="Result message")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Error details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Error timestamp")


# ==================== Discovery API Models ====================


class DiscoveryRefreshRequest(BaseModel):
    """Request to trigger manual discovery refresh."""

    trigger_source: str = Field(default="user_action", description="Source of trigger")


class DiscoveryRefreshResponse(BaseModel):
    """Discovery refresh result."""

    success: bool = Field(..., description="Was refresh successful")
    automations_found: int = Field(..., description="Number of automations discovered")
    scenes_found: int = Field(..., description="Number of scenes discovered")
    scripts_found: int = Field(..., description="Number of scripts discovered")
    entities_discovered: int = Field(..., description="Number of entities discovered")
    duration_seconds: float = Field(..., description="Refresh duration in seconds")
    timestamp: datetime = Field(..., description="Refresh timestamp")


class DiscoveryStatsResponse(BaseModel):
    """Discovery statistics."""

    auto_discovery_enabled: bool = Field(..., description="Is auto-discovery enabled")
    total_automations: int = Field(..., description="Total automations discovered")
    enabled_automations: int = Field(..., description="Enabled automations")
    total_scenes: int = Field(..., description="Total scenes discovered")
    total_scripts: int = Field(..., description="Total scripts discovered")
    total_entities: int = Field(..., description="Total entities discovered")
    monitored_entities: int = Field(..., description="Number of monitored entities")
    last_refresh: datetime | None = Field(None, description="Last refresh timestamp")
    next_refresh: datetime | None = Field(None, description="Next scheduled refresh")
    refresh_interval_seconds: int = Field(..., description="Configured refresh interval")


class AutomationSummary(BaseModel):
    """Automation summary (list view)."""

    entity_id: str = Field(..., description="Automation entity ID")
    friendly_name: str | None = Field(None, description="Automation friendly name")
    state: str = Field(..., description="Automation state (on/off)")
    entity_count: int = Field(..., description="Number of entities used")
    discovered_at: datetime = Field(..., description="Discovery timestamp")
    instance_id: str | None = Field(None, description="Instance ID (present in aggregate mode)")


class AutomationDetailResponse(BaseModel):
    """Detailed automation information."""

    entity_id: str = Field(..., description="Automation entity ID")
    friendly_name: str | None = Field(None, description="Automation friendly name")
    state: str = Field(..., description="Automation state (on/off)")
    mode: str | None = Field(None, description="Automation mode")
    discovered_at: datetime = Field(..., description="Discovery timestamp")
    last_seen: datetime = Field(..., description="Last seen timestamp")
    entities: dict[str, list[str]] = Field(
        ..., description="Entities grouped by relationship type (trigger/condition/action)"
    )
    entity_count: int = Field(..., description="Total number of entities")


class EntityAutomationUsage(BaseModel):
    """Entity usage in automation/scene/script."""

    id: str = Field(..., description="Automation/scene/script entity ID")
    friendly_name: str | None = Field(None, description="Friendly name")
    type: Literal["automation", "scene", "script"] = Field(..., description="Usage type")
    relationship_type: str | None = Field(
        None, description="Relationship type (trigger/condition/action for automations)"
    )


class EntityAutomationsResponse(BaseModel):
    """Entity usage in automations/scenes/scripts."""

    entity_id: str = Field(..., description="Entity ID")
    automations: list[EntityAutomationUsage] = Field(
        default_factory=list, description="Automations using this entity"
    )
    scenes: list[EntityAutomationUsage] = Field(
        default_factory=list, description="Scenes using this entity"
    )
    scripts: list[EntityAutomationUsage] = Field(
        default_factory=list, description="Scripts using this entity"
    )
    total_usage: int = Field(..., description="Total number of usages")


# ==================== Configuration API Models ====================


class ConfigSettingMetadata(BaseModel):
    """Metadata for a configuration setting."""

    key: str = Field(..., description="Setting key (e.g., 'monitoring.grace_period_seconds')")
    label: str = Field(..., description="Human-readable label")
    description: str = Field(..., description="Description of the setting")
    value_type: str = Field(..., description="Value type: string, int, float, bool, list, dict")
    editable: bool = Field(default=True, description="Whether setting can be edited from dashboard")
    requires_restart: bool = Field(
        default=False, description="Whether changes require service restart"
    )
    section: str = Field(default="general", description="Configuration section")
    min_value: float | int | None = Field(None, description="Minimum value for numeric settings")
    max_value: float | int | None = Field(None, description="Maximum value for numeric settings")
    options: list[str] | None = Field(None, description="Allowed values for enum-like settings")


class ConfigValueResponse(BaseModel):
    """Configuration value with source information."""

    key: str = Field(..., description="Setting key")
    value: Any = Field(..., description="Current value")
    source: str = Field(..., description="Source of value: default, yaml, database, or environment")
    editable: bool = Field(default=True, description="Whether setting can be edited")
    requires_restart: bool = Field(
        default=False, description="Whether changes require service restart"
    )


class ConfigResponse(BaseModel):
    """Full configuration response."""

    settings: dict[str, ConfigValueResponse] = Field(
        ..., description="All configuration settings with values and sources"
    )
    restart_required: bool = Field(
        default=False, description="Whether pending changes require restart"
    )


class ConfigUpdateRequest(BaseModel):
    """Request to update configuration settings."""

    settings: dict[str, Any] = Field(..., description="Settings to update (key -> value)")


class ConfigUpdateResponse(BaseModel):
    """Response from configuration update."""

    updated: list[str] = Field(..., description="List of successfully updated settings")
    errors: list[str] = Field(default_factory=list, description="List of validation errors")
    restart_required: bool = Field(
        default=False, description="Whether changes require service restart"
    )


class ConfigValidationResponse(BaseModel):
    """Response from configuration validation."""

    valid: bool = Field(..., description="Whether all settings are valid")
    errors: list[str] = Field(default_factory=list, description="List of validation errors")


class ConfigSchemaResponse(BaseModel):
    """Configuration schema for UI generation."""

    settings: dict[str, ConfigSettingMetadata] = Field(
        ..., description="All editable settings with metadata"
    )
    sections: list[str] = Field(..., description="Available configuration sections")


class ConfigInstanceInfo(BaseModel):
    """Home Assistant instance configuration (safe for API - token masked)."""

    instance_id: str = Field(..., description="Instance identifier")
    url: str = Field(..., description="Home Assistant URL")
    masked_token: str = Field(..., description="Masked token (e.g., 'eyJ...xxxx')")
    bridge_enabled: bool = Field(..., description="Whether bridge is enabled")
    is_active: bool = Field(..., description="Whether instance is active")
    source: str = Field(..., description="Configuration source: dashboard, yaml, import")
    created_at: datetime | None = Field(None, description="When instance was created")
    updated_at: datetime | None = Field(None, description="When instance was last updated")


class ConfigInstanceCreateRequest(BaseModel):
    """Request to create a new HA instance."""

    instance_id: str = Field(..., description="Unique instance identifier")
    url: str = Field(..., description="Home Assistant URL")
    token: str = Field(..., description="Long-lived access token")
    bridge_enabled: bool = Field(default=True, description="Enable bridge if available")


class ConfigInstanceUpdateRequest(BaseModel):
    """Request to update an HA instance."""

    url: str | None = Field(None, description="New URL (optional)")
    token: str | None = Field(None, description="New token (optional)")
    bridge_enabled: bool | None = Field(None, description="New bridge setting (optional)")
    is_active: bool | None = Field(None, description="New active status (optional)")


class ConfigInstanceTestRequest(BaseModel):
    """Request to test HA instance connection."""

    url: str = Field(..., description="Home Assistant URL to test")
    token: str = Field(..., description="Access token to test")


class ConfigInstanceTestResponse(BaseModel):
    """Response from HA instance connection test."""

    success: bool = Field(..., description="Whether connection was successful")
    message: str = Field(..., description="Result message")
    version: str | None = Field(None, description="Home Assistant version if connected")
    location_name: str | None = Field(None, description="HA location name if connected")


# Automation Desired States Models


class InferenceMethod(StrEnum):
    """Methods for inferring automation desired states."""

    AI_ANALYSIS = "ai_analysis"
    USER_ANNOTATED = "user_annotated"
    LEARNED = "learned"


class DesiredStateResponse(BaseModel):
    """Desired state for an automation target entity."""

    entity_id: str = Field(..., description="Target entity ID")
    desired_state: str = Field(..., description="Expected state (e.g., 'on', 'off')")
    desired_attributes: dict[str, Any] | None = Field(
        None, description="Expected attributes (e.g., brightness, temperature)"
    )
    confidence: float = Field(..., description="Confidence score (0.0-1.0)")
    inference_method: InferenceMethod = Field(
        ..., description="How this was inferred (ai_analysis, user_annotated, learned)"
    )
    created_at: datetime = Field(..., description="When this was created")
    updated_at: datetime = Field(..., description="When this was last updated")


class DesiredStateCreateRequest(BaseModel):
    """Request to create/update a desired state."""

    entity_id: str = Field(..., description="Target entity ID")
    desired_state: str = Field(..., description="Expected state")
    desired_attributes: dict[str, Any] | None = Field(
        None, description="Expected attributes (optional)"
    )


class DesiredStateUpdateRequest(BaseModel):
    """Request to update an existing desired state."""

    desired_state: str | None = Field(None, description="New desired state (optional)")
    desired_attributes: dict[str, Any] | None = Field(
        None, description="New desired attributes (optional)"
    )
    confidence: float | None = Field(
        None, description="New confidence score (optional)", ge=0.0, le=1.0
    )


class InferredStateResponse(BaseModel):
    """AI-inferred desired state (not yet saved)."""

    entity_id: str = Field(..., description="Target entity ID")
    desired_state: str = Field(..., description="Inferred state")
    desired_attributes: dict[str, Any] | None = Field(None, description="Inferred attributes")
    confidence: float = Field(..., description="AI confidence score (0.0-1.0)")


# Failure Reporting Models


class FailureReportRequest(BaseModel):
    """Request to report an automation failure."""

    execution_id: int | None = Field(None, description="Specific execution ID (optional)")
    failed_entities: list[str] | None = Field(
        None,
        min_length=1,
        max_length=50,
        description="List of entities that failed (1-50 entities, optional)",
    )
    user_description: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="User's description of what went wrong (1-1000 characters, optional)",
    )


class EntityFailureDetail(BaseModel):
    """Details about a failed entity state."""

    entity_id: str = Field(..., description="Entity that failed")
    desired_state: str | None = Field(None, description="Expected state")
    actual_state: str | None = Field(None, description="Actual state at validation time")
    root_cause: str | None = Field(None, description="Suspected root cause")


class AIFailureAnalysis(BaseModel):
    """AI-generated analysis of automation failure."""

    root_cause: str = Field(..., description="AI-identified root cause of failure")
    suggested_healing: list[str] = Field(..., description="List of suggested healing actions")
    healing_level: Literal["entity", "device", "integration"] = Field(
        ..., description="Level at which healing should be applied"
    )


class FailureReportResponse(BaseModel):
    """Response from failure report with validation and AI analysis."""

    execution_id: int = Field(..., description="Execution ID that was validated")
    automation_id: str = Field(..., description="Automation ID")
    overall_success: bool = Field(..., description="Whether validation passed")
    failed_entities: list[EntityFailureDetail] = Field(
        ..., description="Details of failed entities"
    )
    ai_analysis: AIFailureAnalysis | None = Field(
        None, description="AI-generated analysis (if enabled)"
    )
    user_description: str | None = Field(None, description="User's reported description")


# ==================== Healing API Models ====================


class EntityActionResponse(BaseModel):
    """Entity-level healing action details."""

    id: int = Field(..., description="Entity healing action ID")
    entity_id: str = Field(..., description="Entity ID")
    action_type: str = Field(
        ..., description="Healing action type (retry_service_call, alternative_params)"
    )
    service_domain: str | None = Field(None, description="Service domain")
    service_name: str | None = Field(None, description="Service name")
    success: bool | None = Field(None, description="Whether action succeeded")
    error_message: str | None = Field(None, description="Error message if failed")
    duration_seconds: float | None = Field(None, description="Action duration in seconds")


class DeviceActionResponse(BaseModel):
    """Device-level healing action details."""

    id: int = Field(..., description="Device healing action ID")
    device_id: str = Field(..., description="Device ID")
    action_type: str = Field(..., description="Healing action type (reconnect, reboot, rediscover)")
    success: bool | None = Field(None, description="Whether action succeeded")
    error_message: str | None = Field(None, description="Error message if failed")
    duration_seconds: float | None = Field(None, description="Action duration in seconds")


class HealingCascadeResponse(BaseModel):
    """Detailed healing cascade execution information."""

    id: int = Field(..., description="Healing cascade execution ID")
    instance_id: str = Field(..., description="Home Assistant instance ID")
    automation_id: str = Field(..., description="Automation ID that triggered healing")
    execution_id: int | None = Field(
        None, description="Automation execution ID that triggered healing"
    )
    trigger_type: str = Field(
        ..., description="What triggered the cascade (trigger_failure, outcome_failure)"
    )
    routing_strategy: str = Field(
        ..., description="Routing strategy used (intelligent, sequential)"
    )

    # Level attempt/success flags
    entity_level_attempted: bool = Field(
        ..., description="Whether entity-level healing was attempted"
    )
    entity_level_success: bool | None = Field(None, description="Entity level healing success")
    device_level_attempted: bool = Field(
        ..., description="Whether device-level healing was attempted"
    )
    device_level_success: bool | None = Field(None, description="Device level healing success")
    integration_level_attempted: bool = Field(
        ..., description="Whether integration-level healing was attempted"
    )
    integration_level_success: bool | None = Field(
        None, description="Integration level healing success"
    )

    # Results
    final_success: bool | None = Field(
        None,
        description="Overall cascade success (true if final outcome achieved, false if all levels failed)",
    )
    total_duration_seconds: float | None = Field(None, description="Total cascade execution time")

    # Timestamps
    created_at: datetime = Field(..., description="When cascade was initiated")
    completed_at: datetime | None = Field(None, description="When cascade completed")

    # Child actions
    entity_actions: list[EntityActionResponse] = Field(
        default_factory=list, description="Entity-level healing actions performed"
    )
    device_actions: list[DeviceActionResponse] = Field(
        default_factory=list, description="Device-level healing actions performed"
    )


class HealingStatisticsByLevel(BaseModel):
    """Healing statistics for a specific level (entity/device/integration)."""

    level: Literal["entity", "device", "integration"] = Field(..., description="Healing level")
    total_attempts: int = Field(..., description="Total attempts at this level")
    successful_attempts: int = Field(..., description="Successful attempts")
    failed_attempts: int = Field(..., description="Failed attempts")
    success_rate: float = Field(..., description="Success rate as percentage (0-100)", ge=0, le=100)
    average_duration_seconds: float | None = Field(
        None, description="Average healing duration at this level in seconds"
    )


class HealingStatisticsResponse(BaseModel):
    """Overall healing statistics aggregated by level."""

    instance_id: str = Field(..., description="Home Assistant instance ID")
    time_range: dict[str, datetime] = Field(
        ..., description="Time range as dict with 'start_date' and 'end_date'"
    )
    statistics_by_level: list[HealingStatisticsByLevel] = Field(
        ..., description="Statistics broken down by healing level"
    )
    total_cascades: int = Field(..., description="Total healing cascades in time range")
    successful_cascades: int = Field(
        ..., description="Successful healing cascades (final_success=true)"
    )


class AutomationHealthResponse(BaseModel):
    """Health and validation status for an automation."""

    instance_id: str = Field(..., description="Home Assistant instance ID")
    automation_id: str = Field(..., description="Automation ID")

    # Consecutive tracking
    consecutive_successes: int = Field(..., description="Current consecutive successful executions")
    consecutive_failures: int = Field(..., description="Current consecutive failed executions")

    # Validation status
    is_validated_healthy: bool = Field(
        ..., description="Whether automation has met consecutive success threshold"
    )

    # Statistics
    total_executions: int = Field(..., description="Total execution attempts")
    total_successes: int = Field(..., description="Successful executions")
    total_failures: int = Field(..., description="Failed executions")

    # Reliability score
    reliability_score: float = Field(
        ..., description="Success rate as percentage (0-100)", ge=0, le=100
    )

    # Recent activity
    last_execution_at: datetime | None = Field(None, description="Last execution time")
    last_success_at: datetime | None = Field(None, description="Last successful execution")
    last_failure_at: datetime | None = Field(None, description="Last failed execution")


# --- Healing Plan API Models ---


class HealingPlanStepResponse(BaseModel):
    """A single step in a healing plan."""

    name: str = Field(..., description="Step name")
    level: str = Field(..., description="Healing level (entity, device, integration)")
    action: str = Field(..., description="Healing action")
    params: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    timeout_seconds: float = Field(..., description="Step timeout")


class HealingPlanMatchCriteria(BaseModel):
    """Match criteria for a healing plan."""

    entity_patterns: list[str] = Field(default_factory=list, description="Entity ID glob patterns")
    integration_domains: list[str] = Field(default_factory=list, description="Integration domains")
    failure_types: list[str] = Field(default_factory=list, description="Failure types to match")


class HealingPlanResponse(BaseModel):
    """Healing plan details."""

    name: str = Field(..., description="Plan name")
    description: str = Field("", description="Plan description")
    version: int = Field(1, description="Plan version")
    enabled: bool = Field(True, description="Whether plan is enabled")
    priority: int = Field(0, description="Plan priority (higher = evaluated first)")
    source: str = Field("user", description="Plan source (builtin or user)")
    match_criteria: HealingPlanMatchCriteria = Field(..., description="Match criteria")
    steps: list[HealingPlanStepResponse] = Field(..., description="Healing steps")
    tags: list[str] = Field(default_factory=list, description="Plan tags")


class HealingPlanListResponse(BaseModel):
    """List of healing plans."""

    plans: list[HealingPlanResponse] = Field(..., description="List of plans")
    total: int = Field(..., description="Total number of plans")


class HealingPlanExecutionResponse(BaseModel):
    """Healing plan execution record."""

    id: int = Field(..., description="Execution ID")
    plan_name: str = Field(..., description="Plan name")
    success: bool = Field(..., description="Whether execution succeeded")
    steps_attempted: int = Field(0, description="Steps attempted")
    steps_succeeded: int = Field(0, description="Steps that succeeded")
    total_duration_seconds: float = Field(0.0, description="Total duration")
    created_at: datetime = Field(..., description="Execution timestamp")
    error_message: str | None = Field(None, description="Error message if failed")


class HealingPlanValidationResponse(BaseModel):
    """Result of YAML plan validation."""

    valid: bool = Field(..., description="Whether the plan YAML is valid")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    plan: HealingPlanResponse | None = Field(None, description="Parsed plan if valid")


class HealingPlanMatchTestRequest(BaseModel):
    """Request to test which plan matches a failure scenario."""

    entity_ids: list[str] = Field(..., description="Entity IDs to test")
    failure_type: str = Field("unavailable", description="Failure type")
    instance_id: str = Field("default", description="Instance ID")


class HealingPlanMatchTestResponse(BaseModel):
    """Result of plan match testing."""

    matched: bool = Field(..., description="Whether any plan matched")
    plan_name: str | None = Field(None, description="Matched plan name")
    plan_priority: int | None = Field(None, description="Matched plan priority")
