"""Configuration management with Pydantic."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ha_boss.core.exceptions import ConfigurationError


class HomeAssistantInstance(BaseModel):
    """Configuration for a single Home Assistant instance."""

    instance_id: str = Field(..., description="Unique identifier for this HA instance")
    url: str = Field(..., description="Home Assistant instance URL")
    token: str = Field(..., description="Long-lived access token")
    bridge_enabled: bool = Field(
        default=True, description="Attempt to use HA Boss Bridge if available"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL doesn't end with trailing slash."""
        return v.rstrip("/")

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Ensure token is not empty."""
        if not v or v.startswith("${"):
            raise ValueError("Token is not set or is a placeholder")
        return v

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, v: str) -> str:
        """Ensure instance_id is valid."""
        if not v or not v.strip():
            raise ValueError("instance_id cannot be empty")
        # Convert to safe identifier (no spaces, special chars)
        return v.strip().replace(" ", "_").lower()


class HomeAssistantConfig(BaseSettings):
    """Home Assistant connection configuration (supports single and multi-instance)."""

    # Legacy single-instance fields (deprecated but supported for backward compatibility)
    url: str | None = Field(None, description="[DEPRECATED] Use instances instead")
    token: str | None = Field(None, description="[DEPRECATED] Use instances instead")

    # New multi-instance field
    instances: list[HomeAssistantInstance] = Field(
        default_factory=list, description="List of Home Assistant instances to monitor"
    )

    @model_validator(mode="after")
    def validate_instances(self) -> "HomeAssistantConfig":
        """Convert legacy single-instance config to multi-instance format.

        Note: Empty instances list is allowed - instances can be configured via
        the dashboard and stored in the database. The service will load them
        at startup.
        """

        # Helper to check if a value is a valid (not placeholder) string
        def is_valid_value(v: str | None) -> bool:
            if not v:
                return False
            # Reject environment variable placeholders that weren't substituted
            if v.startswith("${") and v.endswith("}"):
                return False
            return True

        # If legacy fields are set (and not placeholders) and instances is empty,
        # convert to instances format
        if is_valid_value(self.url) and is_valid_value(self.token) and not self.instances:
            self.instances = [
                HomeAssistantInstance(
                    instance_id="default",
                    url=self.url,  # type: ignore[arg-type]
                    token=self.token,  # type: ignore[arg-type]
                    bridge_enabled=True,
                )
            ]
            # Clear legacy fields after conversion
            self.url = None
            self.token = None
        else:
            # Clear placeholder values from legacy fields
            if not is_valid_value(self.url):
                self.url = None
            if not is_valid_value(self.token):
                self.token = None

        # Note: Empty instances list is now allowed - instances can be loaded
        # from the database (dashboard-configured instances)

        # Validate unique instance IDs (if any instances are configured)
        if self.instances:
            instance_ids = [inst.instance_id for inst in self.instances]
            if len(instance_ids) != len(set(instance_ids)):
                raise ValueError(
                    "Duplicate instance_id values found. Each instance must have a unique ID."
                )

        return self

    def get_instance(self, instance_id: str) -> HomeAssistantInstance | None:
        """Get instance configuration by ID.

        Args:
            instance_id: Instance identifier

        Returns:
            Instance configuration or None if not found
        """
        for instance in self.instances:
            if instance.instance_id == instance_id:
                return instance
        return None

    def get_default_instance(self) -> HomeAssistantInstance:
        """Get the default/first instance.

        Returns:
            First instance configuration

        Raises:
            ValueError: If no instances configured
        """
        if not self.instances:
            raise ValueError("No instances configured")
        return self.instances[0]


class AutoDiscoveryConfig(BaseSettings):
    """Auto-discovery configuration for finding entities in automations/scenes/scripts."""

    enabled: bool = Field(
        default=True,
        description="Enable auto-discovery of entities from automations/scenes/scripts",
    )
    skip_disabled_automations: bool = Field(
        default=True,
        description="Skip disabled automations during discovery",
    )
    include_scenes: bool = Field(
        default=True,
        description="Include entities from scenes",
    )
    include_scripts: bool = Field(
        default=True,
        description="Include entities from scripts",
    )
    refresh_interval_seconds: int = Field(
        default=3600,
        description="Periodic discovery refresh interval (0 = disabled)",
        ge=0,
    )
    refresh_on_automation_reload: bool = Field(
        default=True,
        description="Trigger discovery refresh when automations reload",
    )
    refresh_on_scene_reload: bool = Field(
        default=True,
        description="Trigger discovery refresh when scenes reload",
    )
    refresh_on_script_reload: bool = Field(
        default=True,
        description="Trigger discovery refresh when scripts reload",
    )


class EntityOverride(BaseModel):
    """Per-entity configuration override."""

    grace_period_seconds: int | None = Field(
        None,
        description="Override grace period for this specific entity",
        ge=0,
    )


class MonitoringConfig(BaseSettings):
    """Entity monitoring configuration."""

    include: list[str] = Field(
        default_factory=list,
        description="Entity patterns to ADD to auto-discovered entities",
    )
    exclude: list[str] = Field(
        default_factory=lambda: [
            "sensor.time*",
            "sensor.date*",
            "sensor.uptime*",
            "sun.sun",
        ],
        description="Entity patterns to exclude from monitoring",
    )
    grace_period_seconds: int = Field(
        default=300,
        description="Default grace period before entity considered unavailable",
        ge=0,
    )
    stale_threshold_seconds: int = Field(
        default=3600,
        description="Threshold for stale entities (no updates)",
        ge=0,
    )
    snapshot_interval_seconds: int = Field(
        default=300,
        description="REST API snapshot interval for validation",
        ge=60,
    )
    health_check_interval_seconds: int = Field(
        default=60,
        description="Periodic health check interval",
        ge=10,
    )

    # Auto-discovery configuration
    auto_discovery: AutoDiscoveryConfig = Field(
        default_factory=AutoDiscoveryConfig,
        description="Auto-discovery configuration",
    )

    # Per-entity overrides
    entity_overrides: dict[str, EntityOverride] = Field(
        default_factory=dict,
        description="Per-entity configuration overrides",
    )

    def get_entity_grace_period(self, entity_id: str) -> int:
        """Get grace period for entity, checking overrides first.

        Args:
            entity_id: Entity to get grace period for

        Returns:
            Grace period in seconds (override or default)
        """
        override = self.entity_overrides.get(entity_id)
        if override and override.grace_period_seconds is not None:
            return override.grace_period_seconds
        return self.grace_period_seconds


class HealingConfig(BaseSettings):
    """Auto-healing configuration."""

    enabled: bool = Field(default=True, description="Enable auto-healing")
    max_attempts: int = Field(
        default=3,
        description="Max healing attempts per integration",
        ge=1,
        le=10,
    )
    cooldown_seconds: int = Field(
        default=300,
        description="Cooldown between attempts",
        ge=0,
    )
    circuit_breaker_threshold: int = Field(
        default=10,
        description="Stop trying after N total failures",
        ge=1,
    )
    circuit_breaker_reset_seconds: int = Field(
        default=3600,
        description="Reset circuit breaker after this time",
        ge=0,
    )

    # Entity-level healing configuration
    entity_healing_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for entity-level healing",
    )
    entity_healing_base_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Base delay in seconds for exponential backoff",
    )

    # Device-level healing configuration
    device_healing_reboot_timeout: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Timeout in seconds for device reboot operations",
    )


class NotificationsConfig(BaseSettings):
    """Notification configuration."""

    on_healing_failure: bool = Field(
        default=True,
        description="Notify when healing fails",
    )
    weekly_summary: bool = Field(
        default=True,
        description="Send weekly summary reports",
    )
    ha_service: str = Field(
        default="persistent_notification.create",
        description="Home Assistant notification service",
    )
    ai_enhanced: bool = Field(
        default=True,
        description="Enable AI-enhanced notifications with LLM analysis",
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log level",
    )
    format: Literal["json", "text"] = Field(
        default="text",
        description="Log format",
    )
    file: Path = Field(
        default=Path("/data/ha_boss.log"),
        description="Log file path",
    )
    max_size_mb: int = Field(
        default=10,
        description="Max log file size in MB",
        ge=1,
    )
    backup_count: int = Field(
        default=5,
        description="Number of backup log files to keep",
        ge=0,
    )


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    path: Path = Field(
        default=Path("/data/ha_boss.db"),
        description="SQLite database path",
    )
    echo: bool = Field(
        default=False,
        description="Enable SQL query logging",
    )
    retention_days: int = Field(
        default=30,
        description="History retention in days",
        ge=1,
    )


class WebSocketConfig(BaseSettings):
    """WebSocket client configuration."""

    reconnect_delay_seconds: int = Field(
        default=5,
        description="Reconnect delay",
        ge=1,
    )
    heartbeat_interval_seconds: int = Field(
        default=30,
        description="Heartbeat interval",
        ge=10,
    )
    timeout_seconds: int = Field(
        default=10,
        description="Connection timeout",
        ge=5,
    )


class RESTConfig(BaseSettings):
    """REST API client configuration."""

    timeout_seconds: int = Field(
        default=10,
        description="Request timeout",
        ge=1,
    )
    retry_attempts: int = Field(
        default=3,
        description="Retry attempts for failed requests",
        ge=0,
    )
    retry_base_delay_seconds: float = Field(
        default=1.0,
        description="Base delay for exponential backoff",
        ge=0.1,
    )


class IntelligenceConfig(BaseSettings):
    """Intelligence layer configuration."""

    pattern_collection_enabled: bool = Field(
        default=True,
        description="Enable pattern collection for reliability analysis",
    )

    # Anomaly detection configuration
    anomaly_detection_enabled: bool = Field(
        default=True,
        description="Enable automatic anomaly detection",
    )
    anomaly_sensitivity_threshold: float = Field(
        default=2.0,
        description="Standard deviations for anomaly detection (higher = less sensitive)",
        ge=1.0,
        le=5.0,
    )
    anomaly_scan_hours: int = Field(
        default=24,
        description="Hours of data to scan for anomalies",
        ge=1,
        le=168,
    )

    # AI/LLM configuration (Phase 3)
    ollama_enabled: bool = Field(
        default=True,
        description="Enable Ollama for AI features",
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API URL",
    )
    ollama_model: str = Field(
        default="llama3.1:8b",
        description="Ollama model to use",
    )
    ollama_timeout_seconds: float = Field(
        default=30.0,
        description="Ollama request timeout",
        ge=1.0,
    )

    claude_enabled: bool = Field(
        default=False,
        description="Enable Claude API for complex tasks",
    )
    claude_api_key: str | None = Field(
        default=None,
        description="Claude API key (optional)",
    )
    claude_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Claude model to use",
    )


class OutcomeValidationConfig(BaseSettings):
    """Outcome validation configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable automatic outcome validation for automations",
    )
    validation_delay_seconds: float = Field(
        default=5.0,
        description="Delay before validating outcomes (allows states to settle)",
        ge=0.1,
        le=60.0,
    )
    analyze_failures: bool = Field(
        default=True,
        description="Enable AI analysis of reported automation failures",
    )
    consecutive_success_threshold: int = Field(
        default=3,
        ge=1,
        le=100,
        description="Number of consecutive successes required for validation gating",
    )


class APIConfig(BaseModel):
    """REST API configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable REST API server",
    )
    host: str = Field(
        default="0.0.0.0",
        description="API server host",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="API server port",
    )
    cors_enabled: bool = Field(
        default=True,
        description="Enable CORS middleware",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins (* for all)",
    )
    auth_enabled: bool = Field(
        default=False,
        description="Enable API key authentication",
    )
    api_keys: list[str] = Field(
        default_factory=list,
        description="Valid API keys for authentication",
    )
    require_https: bool = Field(
        default=False,
        description="Require HTTPS for API requests",
    )


class Config(BaseSettings):
    """Main HA Boss configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown environment variables
    )

    home_assistant: HomeAssistantConfig
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    healing: HealingConfig = Field(default_factory=HealingConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    rest: RESTConfig = Field(default_factory=RESTConfig)
    intelligence: IntelligenceConfig = Field(default_factory=IntelligenceConfig)
    outcome_validation: OutcomeValidationConfig = Field(default_factory=OutcomeValidationConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    mode: Literal["production", "dry_run", "testing"] = Field(
        default="production",
        description="Operational mode",
    )

    @property
    def is_dry_run(self) -> bool:
        """Check if running in dry-run mode."""
        return self.mode == "dry_run"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.mode == "production"


def load_config(config_path: Path | str | None = None) -> Config:
    """Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to config.yaml file. If None, uses default locations:
                    - ./config.yaml
                    - ./config/config.yaml
                    - /config/config.yaml

    Returns:
        Loaded and validated configuration

    Raises:
        ConfigurationError: If configuration is invalid or cannot be loaded
    """
    # Find config file
    if config_path is None:
        search_paths = [
            Path("config.yaml"),
            Path("config/config.yaml"),
            Path("/config/config.yaml"),
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break

    if config_path is None:
        raise ConfigurationError(
            "No configuration file found. Create config.yaml or set CONFIG_PATH"
        )

    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    # Load YAML
    try:
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {e}") from e
    except Exception as e:
        raise ConfigurationError(f"Failed to read {config_path}: {e}") from e

    if not isinstance(yaml_data, dict):
        raise ConfigurationError(f"Config file must contain a YAML object: {config_path}")

    # Substitute environment variables in YAML
    yaml_data = _substitute_env_vars(yaml_data)

    # Create config from YAML data
    try:
        config = Config(**yaml_data)
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration: {e}") from e

    return config


def _substitute_env_vars(data: Any) -> Any:
    """Recursively substitute ${ENV_VAR} placeholders with environment variables.

    Args:
        data: Configuration data (dict, list, str, or primitive)

    Returns:
        Data with environment variables substituted
    """
    if isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Check if it's an environment variable reference
        if data.startswith("${") and data.endswith("}"):
            env_var = data[2:-1]
            value = os.getenv(env_var)
            if value is None:
                # Keep the placeholder if env var not set
                # Validation will catch required missing values
                return data
            return value
        return data
    else:
        return data
