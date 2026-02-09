"""Pydantic models for YAML-based healing plan definitions.

These models validate healing plan configurations loaded from YAML files
or submitted via the API. Plans define match criteria and ordered healing
steps that integrate with the cascade orchestrator.
"""

from pydantic import BaseModel, Field, field_validator


class TimeWindow(BaseModel):
    """Time window restriction for plan matching."""

    start_hour: int = Field(default=0, ge=0, le=23)
    end_hour: int = Field(default=24, ge=0, le=24)


class MatchCriteria(BaseModel):
    """Criteria for matching a healing plan to a failure.

    Uses fnmatch glob patterns for entity matching, consistent with
    the existing monitoring include/exclude patterns.
    """

    entity_patterns: list[str] = Field(
        default_factory=list,
        description="fnmatch glob patterns for entity IDs (e.g., 'light.zigbee_*')",
    )
    integration_domains: list[str] = Field(
        default_factory=list,
        description="Integration domains to match (e.g., 'zha', 'zigbee2mqtt')",
    )
    failure_types: list[str] = Field(
        default_factory=list,
        description="Failure types to match (e.g., 'unavailable', 'unknown')",
    )
    device_manufacturers: list[str] = Field(
        default_factory=list,
        description="Optional device manufacturer filter",
    )
    time_window: TimeWindow | None = Field(
        default=None,
        description="Optional time-of-day restriction",
    )

    @field_validator("entity_patterns", "integration_domains", "failure_types")
    @classmethod
    def at_least_one_criterion(cls, v: list[str], info: object) -> list[str]:
        """Individual fields can be empty; overall match is checked at plan level."""
        return v

    def has_any_criteria(self) -> bool:
        """Check if at least one matching criterion is defined."""
        return bool(
            self.entity_patterns
            or self.integration_domains
            or self.failure_types
            or self.device_manufacturers
        )


class HealingStep(BaseModel):
    """A single healing step within a plan."""

    name: str = Field(..., description="Step identifier")
    level: str = Field(
        ...,
        description="Healing level: 'entity', 'device', or 'integration'",
    )
    action: str = Field(
        ...,
        description="Healing action (e.g., 'retry_service_call', 'reconnect', 'reload_integration')",
    )
    params: dict[str, object] = Field(
        default_factory=dict,
        description="Action-specific parameters",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=600.0,
        description="Timeout for this step",
    )

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate healing level is one of the known levels."""
        valid_levels = {"entity", "device", "integration"}
        if v not in valid_levels:
            raise ValueError(f"Invalid level '{v}', must be one of: {valid_levels}")
        return v


class OnFailureConfig(BaseModel):
    """Configuration for what happens when all plan steps fail."""

    escalate: bool = Field(default=True, description="Escalate to notifications")
    cooldown_seconds: int = Field(
        default=600,
        ge=0,
        description="Cooldown before this plan can be tried again",
    )


class HealingPlanDefinition(BaseModel):
    """Complete healing plan definition matching the YAML schema.

    This is the top-level model that validates a complete healing plan,
    whether loaded from a YAML file or submitted via the API.
    """

    name: str = Field(..., description="Unique plan identifier")
    version: int = Field(default=1, ge=1, description="Plan version")
    description: str = Field(default="", description="Human-readable description")
    enabled: bool = Field(default=True, description="Whether the plan is active")
    priority: int = Field(
        default=0,
        ge=0,
        description="Higher priority plans are evaluated first",
    )

    match: MatchCriteria = Field(
        ...,
        description="Criteria for matching failures to this plan",
    )
    steps: list[HealingStep] = Field(
        ...,
        min_length=1,
        description="Ordered list of healing steps to execute",
    )
    on_failure: OnFailureConfig = Field(
        default_factory=OnFailureConfig,
        description="What to do when all steps fail",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for filtering and categorization",
    )

    @field_validator("match")
    @classmethod
    def validate_match_has_criteria(cls, v: MatchCriteria) -> MatchCriteria:
        """Ensure at least one matching criterion is defined."""
        if not v.has_any_criteria():
            raise ValueError(
                "Match criteria must have at least one of: "
                "entity_patterns, integration_domains, failure_types, device_manufacturers"
            )
        return v
