"""Configuration management for HA Boss MCP Server."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    """MCP server transport and connection settings."""

    transport: Literal["stdio", "http", "sse"] = Field(
        default="stdio", description="MCP transport mode"
    )
    host: str = Field(default="0.0.0.0", description="HTTP/SSE server host")
    port: int = Field(default=8001, ge=1, le=65535, description="HTTP/SSE server port")

    model_config = SettingsConfigDict(env_prefix="MCP_")


class HABossSettings(BaseSettings):
    """HA Boss API connection settings."""

    api_url: str = Field(
        default="http://haboss:8000", description="HA Boss API base URL"
    )
    api_key: str | None = Field(
        default=None, description="API key for HA Boss authentication"
    )
    database_path: str = Field(
        default="/app/data/ha_boss.db", description="Path to HA Boss SQLite database"
    )

    model_config = SettingsConfigDict(env_prefix="HABOSS_")


class AuthSettings(BaseSettings):
    """Authentication settings for MCP server."""

    enabled: bool = Field(default=False, description="Enable OAuth authentication")
    provider: Literal["google", "github", "azure", "auth0"] = Field(
        default="google", description="OAuth provider"
    )
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    base_url: str | None = Field(default=None, description="OAuth callback base URL")

    model_config = SettingsConfigDict(env_prefix="MCP_AUTH_")


class ToolsSettings(BaseSettings):
    """Tool enablement settings."""

    enabled: list[str] = Field(
        default=["monitoring", "healing", "patterns", "service"],
        description="Enabled tool categories",
    )

    model_config = SettingsConfigDict(env_prefix="MCP_TOOLS_")


class MCPConfig(BaseSettings):
    """Complete MCP server configuration."""

    mcp: MCPSettings = Field(default_factory=MCPSettings)
    haboss: HABossSettings = Field(default_factory=HABossSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_config(config_path: str | Path | None = None) -> MCPConfig:
    """Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to mcp_config.yaml file. If None, searches in:
            - /app/config/mcp_config.yaml (Docker)
            - ./config/mcp_config.yaml (local)
            - ./mcp_config.yaml (fallback)

    Returns:
        MCPConfig: Loaded configuration with environment variable overrides

    Note:
        Environment variables take precedence over YAML configuration.
        Use prefixes: MCP_, HABOSS_, MCP_AUTH_, MCP_TOOLS_
    """
    # Determine config file path
    if config_path is None:
        # Search in common locations
        search_paths = [
            Path("/app/config/mcp_config.yaml"),  # Docker
            Path("config/mcp_config.yaml"),  # Local
            Path("mcp_config.yaml"),  # Fallback
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break
    else:
        config_path = Path(config_path)

    # Start with defaults
    config_data = {}

    # Load from YAML if file exists
    if config_path and Path(config_path).exists():
        with open(config_path, "r") as f:
            yaml_data = yaml.safe_load(f) or {}
            config_data = yaml_data

    # Create config with YAML data + environment overrides
    # Environment variables automatically override via Pydantic settings
    if config_data:
        # Manually create nested settings from YAML
        mcp_config = MCPConfig(
            mcp=MCPSettings(**config_data.get("mcp", {})),
            haboss=HABossSettings(**config_data.get("haboss", {})),
            auth=AuthSettings(**config_data.get("auth", {})),
            tools=ToolsSettings(**config_data.get("tools", {})),
        )
    else:
        # Use defaults + environment variables
        mcp_config = MCPConfig()

    return mcp_config


def validate_config(config: MCPConfig) -> None:
    """Validate configuration and raise errors for invalid settings.

    Args:
        config: Configuration to validate

    Raises:
        ValueError: If configuration is invalid
    """
    # Check if database path is accessible (if not default)
    if config.haboss.database_path != "/app/data/ha_boss.db":
        db_path = Path(config.haboss.database_path)
        if not db_path.parent.exists():
            raise ValueError(
                f"Database directory does not exist: {db_path.parent}"
            )

    # Validate OAuth settings if enabled
    if config.auth.enabled:
        if not config.auth.client_id or not config.auth.client_secret:
            raise ValueError(
                "OAuth is enabled but client_id or client_secret is missing"
            )
        if not config.auth.base_url:
            raise ValueError("OAuth is enabled but base_url is missing")

    # Validate tool categories
    valid_categories = {"monitoring", "healing", "patterns", "service"}
    invalid = set(config.tools.enabled) - valid_categories
    if invalid:
        raise ValueError(f"Invalid tool categories: {invalid}")
