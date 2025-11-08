"""Configuration management with Pydantic."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ha_boss.core.exceptions import ConfigurationError


class HomeAssistantConfig(BaseSettings):
    """Home Assistant connection configuration."""

    url: str = Field(..., description="Home Assistant instance URL")
    token: str = Field(..., description="Long-lived access token")

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
            raise ValueError("HA_TOKEN environment variable is not set")
        return v


class MonitoringConfig(BaseSettings):
    """Entity monitoring configuration."""

    include: list[str] = Field(
        default_factory=list,
        description="Entity patterns to monitor (empty = all)",
    )
    exclude: list[str] = Field(
        default_factory=lambda: [
            "sensor.time*",
            "sensor.date*",
            "sensor.uptime*",
            "sun.sun",
        ],
        description="Entity patterns to exclude",
    )
    grace_period_seconds: int = Field(
        default=300,
        description="Grace period before entity considered unavailable",
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


class Config(BaseSettings):
    """Main HA Boss configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    home_assistant: HomeAssistantConfig
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    healing: HealingConfig = Field(default_factory=HealingConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    rest: RESTConfig = Field(default_factory=RESTConfig)

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
