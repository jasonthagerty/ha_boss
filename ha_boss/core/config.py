"""Configuration management with Pydantic."""

import fnmatch
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


class OutOfScopeAuditConfig(BaseSettings):
    """Configuration for the out-of-scope entity audit."""

    enabled: bool = Field(
        default=False,
        description="Enable periodic audit of out-of-scope entities",
    )
    interval_seconds: int = Field(
        default=86400,
        description="Audit interval in seconds (default: 1 day)",
        ge=0,
    )
    chronic_threshold_seconds: int = Field(
        default=259200,
        description="Seconds before an entity is considered chronically unavailable (default: 3 days)",
        ge=0,
    )
    include_stale: bool = Field(
        default=False,
        description="Include stale entities (no update within stale_threshold_seconds) in audit",
    )
    group_by_integration: bool = Field(
        default=True,
        description="Group digest by integration (domain fallback if mapping unavailable)",
    )


class CloudHandlingConfig(BaseSettings):
    """Handling for internet-dependent (cloud) integrations.

    Cloud integrations (HA manifest ``iot_class`` of ``cloud_polling`` /
    ``cloud_push``) flap ``unavailable`` based on external availability that HA
    Boss cannot heal, so alerting on them — especially via mobile push — is
    noisy. When enabled, entities belonging to a cloud integration get a longer
    grace period and (optionally) no mobile push; they still alert via HA/CLI.
    """

    enabled: bool = Field(
        default=True,
        description="Enable gentler handling of cloud (internet-dependent) integrations",
    )
    iot_classes: list[str] = Field(
        default_factory=lambda: ["cloud_polling", "cloud_push"],
        description="HA manifest iot_class values treated as 'cloud' / internet-dependent",
    )
    suppress_mobile_push: bool = Field(
        default=True,
        description="Do not send mobile push for cloud-entity issues (HA/CLI only)",
    )
    grace_period_seconds: int | None = Field(
        default=900,
        description=(
            "Grace period for cloud entities before reporting (None = use the default "
            "monitoring grace_period_seconds)"
        ),
        ge=0,
    )


class ActionVerificationConfig(BaseSettings):
    """Configuration for action (service-call) verification.

    When enabled, HA Boss observes state-changing service calls and checks that
    the target entity reaches the expected state within ``delay_seconds``.  If
    the entity did NOT reach the expected state a WARNING notification is sent.
    """

    enabled: bool = Field(
        default=False,
        description="Enable action verification (check that service calls take effect)",
    )
    delay_seconds: int = Field(
        default=30,
        description="Seconds to wait before checking whether the action took effect",
        gt=0,
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
    unavailable_ok: list[str] = Field(
        default_factory=list,
        description=(
            "Entity patterns for which the 'unavailable' state is expected/normal "
            "(e.g. a TV or media player that reports unavailable when powered off). "
            "Matching entities are not flagged as unavailable/stale by the health "
            "monitor, and a turn_off that leaves them unavailable is treated as "
            "success by the action verifier."
        ),
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

    # Out-of-scope entity audit configuration
    out_of_scope_audit: OutOfScopeAuditConfig = Field(
        default_factory=OutOfScopeAuditConfig,
        description="Periodic audit of entities not in the monitored set",
    )

    # Action verification configuration
    action_verification: ActionVerificationConfig = Field(
        default_factory=ActionVerificationConfig,
        description="Verify that service calls produce the expected entity state",
    )

    # Cloud (internet-dependent) integration handling
    cloud_handling: CloudHandlingConfig = Field(
        default_factory=CloudHandlingConfig,
        description="Gentler handling of cloud/internet-dependent integrations",
    )

    # Per-entity overrides
    entity_overrides: dict[str, EntityOverride] = Field(
        default_factory=dict,
        description="Per-entity configuration overrides",
    )

    def get_entity_grace_period(self, entity_id: str, is_cloud: bool = False) -> int:
        """Get grace period for entity, checking overrides first.

        Precedence: explicit per-entity override > cloud grace (when ``is_cloud``
        and cloud handling enabled with a configured cloud grace) > default.

        Args:
            entity_id: Entity to get grace period for
            is_cloud: Whether the entity belongs to a cloud integration

        Returns:
            Grace period in seconds
        """
        override = self.entity_overrides.get(entity_id)
        if override and override.grace_period_seconds is not None:
            return override.grace_period_seconds
        if (
            is_cloud
            and self.cloud_handling.enabled
            and self.cloud_handling.grace_period_seconds is not None
        ):
            return self.cloud_handling.grace_period_seconds
        return self.grace_period_seconds

    def is_unavailable_expected(self, entity_id: str) -> bool:
        """Check if 'unavailable' is an expected/normal state for an entity.

        Used to suppress false-positive alerts for devices that report
        ``unavailable`` when they are simply powered off (e.g. TVs).

        Args:
            entity_id: Entity to check against the ``unavailable_ok`` patterns.

        Returns:
            True if the entity matches any ``unavailable_ok`` pattern.
        """
        return any(fnmatch.fnmatch(entity_id, pattern) for pattern in self.unavailable_ok)


class NotificationsConfig(BaseSettings):
    """Notification configuration."""

    on_issue_detected: bool = Field(
        default=True,
        description="Notify when a monitored entity goes unavailable, unknown, or stale",
    )
    mobile_push_services: list[str] = Field(
        default_factory=list,
        description=(
            "notify services (e.g. 'notify.mobile_app_your_phone') to also send mobile "
            "push alerts to; empty = mobile push disabled. May be supplied via a "
            "${ENV_VAR} placeholder so the value can live in .env"
        ),
    )
    ha_service: str = Field(
        default="persistent_notification.create",
        description="Home Assistant notification service",
    )

    @field_validator("mobile_push_services", mode="after")
    @classmethod
    def _drop_unset_push_services(cls, services: list[str]) -> list[str]:
        """Drop empty and unsubstituted ``${ENV_VAR}`` placeholder entries.

        Lets the config template carry ``${HABOSS_MOBILE_PUSH_SERVICE}``; when the
        env var is unset (placeholder left intact) or empty, the entry is removed,
        leaving mobile push disabled instead of calling a bogus ``notify.`` service.
        """
        return [s for s in services if s and not (s.startswith("${") and s.endswith("}"))]


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
    max_reconnect_delay_seconds: int = Field(
        default=300,
        description="Maximum delay between reconnect attempts (exponential backoff cap)",
        ge=5,
    )
    reconnect_notify_after_seconds: int = Field(
        default=1800,
        description=(
            "Fire the on_connect_lost notification callback after being disconnected "
            "for this many seconds (default: 30 minutes)"
        ),
        ge=60,
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


class HeartbeatConfig(BaseSettings):
    """Dead-man's-switch heartbeat configuration.

    When enabled, HA Boss periodically stamps an ``input_datetime`` helper in
    Home Assistant. A Home Assistant automation alerts when the stamp goes
    stale, so HA itself watches the watchdog — catching a dead container,
    crash loop, or hung process that HA Boss cannot report on its own.
    """

    enabled: bool = Field(
        default=False,
        description="Send a periodic heartbeat timestamp to Home Assistant",
    )
    entity_id: str = Field(
        default="input_datetime.ha_boss_heartbeat",
        description="input_datetime helper to stamp with each heartbeat",
    )
    interval_seconds: int = Field(
        default=300,
        description="Seconds between heartbeats",
        ge=30,
    )


class SelfTestConfig(BaseSettings):
    """Deep self-test configuration.

    The deep self-test validates HA Boss end-to-end against the live instance:
    WebSocket connectivity, REST reachability, discovery integrity (each source
    that found objects must also have extracted entity references), monitored-set
    sanity, and the notification pipeline. It runs at startup, whenever the
    Home Assistant version changes (i.e. after an HA update), and on demand when
    an ``input_boolean`` request helper in HA is turned on. The verdict is
    written to an ``input_text`` helper so HA-side automations can alert on a
    failed or stale result.
    """

    enabled: bool = Field(
        default=False,
        description="Enable the deep self-test (startup, HA version change, on demand)",
    )
    request_entity_id: str = Field(
        default="input_boolean.ha_boss_selftest_request",
        description="input_boolean watched for on-demand self-test requests",
    )
    result_entity_id: str = Field(
        default="input_text.ha_boss_selftest_result",
        description="input_text helper the self-test verdict is written to",
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
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    rest: RESTConfig = Field(default_factory=RESTConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    self_test: SelfTestConfig = Field(default_factory=SelfTestConfig)

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
