"""Configuration service for managing runtime settings.

Implements the HA add-on precedence model:
    ENV VARIABLES    (highest - immutable from dashboard)
          ↓
    DASHBOARD CONFIG (stored in SQLite runtime_config table)
          ↓
    YAML FILE        (config.yaml - base configuration)
          ↓
    CODE DEFAULTS    (lowest - Pydantic defaults)
"""

import json
import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ha_boss.core.database import Database, RuntimeConfig, StoredInstance
from ha_boss.core.encryption import EncryptionError, decrypt_token, encrypt_token, mask_token
from ha_boss.core.exceptions import ConfigServiceError

logger = logging.getLogger(__name__)


class ConfigSource(StrEnum):
    """Source of a configuration value."""

    DEFAULT = "default"
    YAML = "yaml"
    DATABASE = "database"
    ENVIRONMENT = "environment"


class SettingMetadata(BaseModel):
    """Metadata for a configuration setting."""

    key: str
    label: str
    description: str
    value_type: str  # string, int, float, bool, list, dict
    editable: bool = True
    requires_restart: bool = False
    section: str = "general"
    min_value: float | int | None = None
    max_value: float | int | None = None
    options: list[str] | None = None  # For enum-like settings


class ConfigValue(BaseModel):
    """A configuration value with its source and metadata."""

    key: str
    value: Any
    source: ConfigSource
    editable: bool = True
    requires_restart: bool = False


class InstanceInfo(BaseModel):
    """Home Assistant instance information (safe for API response)."""

    instance_id: str
    url: str
    masked_token: str
    bridge_enabled: bool
    is_active: bool
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


# Settings that can be edited from the dashboard
EDITABLE_SETTINGS: dict[str, SettingMetadata] = {
    # Monitoring settings
    "monitoring.grace_period_seconds": SettingMetadata(
        key="monitoring.grace_period_seconds",
        label="Grace Period",
        description="Default grace period before entity is considered unavailable (seconds)",
        value_type="int",
        section="monitoring",
        min_value=0,
        max_value=3600,
    ),
    "monitoring.stale_threshold_seconds": SettingMetadata(
        key="monitoring.stale_threshold_seconds",
        label="Stale Threshold",
        description="Threshold for considering entities stale (seconds)",
        value_type="int",
        section="monitoring",
        min_value=0,
        max_value=86400,
    ),
    "monitoring.include": SettingMetadata(
        key="monitoring.include",
        label="Include Patterns",
        description="Entity patterns to add to auto-discovered entities (one per line)",
        value_type="list",
        section="monitoring",
    ),
    "monitoring.exclude": SettingMetadata(
        key="monitoring.exclude",
        label="Exclude Patterns",
        description="Entity patterns to exclude from monitoring (one per line)",
        value_type="list",
        section="monitoring",
    ),
    "monitoring.auto_discovery.enabled": SettingMetadata(
        key="monitoring.auto_discovery.enabled",
        label="Auto-Discovery",
        description="Enable auto-discovery of entities from automations/scenes/scripts",
        value_type="bool",
        section="monitoring",
    ),
    "monitoring.auto_discovery.skip_disabled_automations": SettingMetadata(
        key="monitoring.auto_discovery.skip_disabled_automations",
        label="Skip Disabled Automations",
        description="Skip disabled automations during discovery",
        value_type="bool",
        section="monitoring",
    ),
    "monitoring.auto_discovery.include_scenes": SettingMetadata(
        key="monitoring.auto_discovery.include_scenes",
        label="Include Scenes",
        description="Include entities from scenes in discovery",
        value_type="bool",
        section="monitoring",
    ),
    "monitoring.auto_discovery.include_scripts": SettingMetadata(
        key="monitoring.auto_discovery.include_scripts",
        label="Include Scripts",
        description="Include entities from scripts in discovery",
        value_type="bool",
        section="monitoring",
    ),
    # Healing settings
    "healing.enabled": SettingMetadata(
        key="healing.enabled",
        label="Auto-Healing Enabled",
        description="Enable automatic healing of failed integrations",
        value_type="bool",
        section="healing",
    ),
    "healing.max_attempts": SettingMetadata(
        key="healing.max_attempts",
        label="Max Attempts",
        description="Maximum healing attempts per integration",
        value_type="int",
        section="healing",
        min_value=1,
        max_value=10,
    ),
    "healing.cooldown_seconds": SettingMetadata(
        key="healing.cooldown_seconds",
        label="Cooldown",
        description="Cooldown between healing attempts (seconds)",
        value_type="int",
        section="healing",
        min_value=0,
        max_value=3600,
    ),
    "healing.circuit_breaker_threshold": SettingMetadata(
        key="healing.circuit_breaker_threshold",
        label="Circuit Breaker Threshold",
        description="Stop trying after this many total failures",
        value_type="int",
        section="healing",
        min_value=1,
        max_value=100,
    ),
    "healing.circuit_breaker_reset_seconds": SettingMetadata(
        key="healing.circuit_breaker_reset_seconds",
        label="Circuit Breaker Reset",
        description="Reset circuit breaker after this time (seconds)",
        value_type="int",
        section="healing",
        min_value=0,
        max_value=86400,
    ),
    # Notification settings
    "notifications.on_healing_failure": SettingMetadata(
        key="notifications.on_healing_failure",
        label="Notify on Failure",
        description="Send notification when healing fails",
        value_type="bool",
        section="notifications",
    ),
    "notifications.weekly_summary": SettingMetadata(
        key="notifications.weekly_summary",
        label="Weekly Summary",
        description="Send weekly summary reports",
        value_type="bool",
        section="notifications",
    ),
    "notifications.ai_enhanced": SettingMetadata(
        key="notifications.ai_enhanced",
        label="AI Enhanced",
        description="Enable AI-enhanced notifications with LLM analysis",
        value_type="bool",
        section="notifications",
    ),
    # Intelligence settings
    "intelligence.pattern_collection_enabled": SettingMetadata(
        key="intelligence.pattern_collection_enabled",
        label="Pattern Collection",
        description="Enable pattern collection for reliability analysis",
        value_type="bool",
        section="intelligence",
    ),
    "intelligence.anomaly_detection_enabled": SettingMetadata(
        key="intelligence.anomaly_detection_enabled",
        label="Anomaly Detection",
        description="Enable automatic anomaly detection",
        value_type="bool",
        section="intelligence",
    ),
    "intelligence.anomaly_sensitivity_threshold": SettingMetadata(
        key="intelligence.anomaly_sensitivity_threshold",
        label="Anomaly Sensitivity",
        description="Standard deviations for anomaly detection (higher = less sensitive)",
        value_type="float",
        section="intelligence",
        min_value=1.0,
        max_value=5.0,
    ),
    "intelligence.ollama_enabled": SettingMetadata(
        key="intelligence.ollama_enabled",
        label="Ollama Enabled",
        description="Enable Ollama for AI features",
        value_type="bool",
        section="intelligence",
    ),
    "intelligence.claude_enabled": SettingMetadata(
        key="intelligence.claude_enabled",
        label="Claude Enabled",
        description="Enable Claude API for complex tasks",
        value_type="bool",
        section="intelligence",
    ),
    # Logging settings
    "logging.level": SettingMetadata(
        key="logging.level",
        label="Log Level",
        description="Logging verbosity level",
        value_type="string",
        section="logging",
        options=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    # Database settings
    "database.retention_days": SettingMetadata(
        key="database.retention_days",
        label="Retention Days",
        description="Keep history for this many days",
        value_type="int",
        section="database",
        min_value=1,
        max_value=365,
    ),
}

# Settings that require service restart (not hot-reloadable)
RESTART_REQUIRED_SETTINGS: set[str] = set()
# Note: None of the editable settings currently require restart
# HA instance changes are handled separately

# Environment variable mappings (these override all other sources)
ENV_OVERRIDES: dict[str, str] = {
    "HA_BOSS_MONITORING_GRACE_PERIOD": "monitoring.grace_period_seconds",
    "HA_BOSS_MONITORING_STALE_THRESHOLD": "monitoring.stale_threshold_seconds",
    "HA_BOSS_HEALING_ENABLED": "healing.enabled",
    "HA_BOSS_HEALING_MAX_ATTEMPTS": "healing.max_attempts",
    "HA_BOSS_LOG_LEVEL": "logging.level",
    "HA_BOSS_DB_RETENTION_DAYS": "database.retention_days",
}


class ConfigService:
    """Service for managing runtime configuration.

    Handles configuration from multiple sources with proper precedence:
    ENV > database > yaml > defaults
    """

    def __init__(self, database: Database, yaml_config: dict[str, Any] | None = None) -> None:
        """Initialize configuration service.

        Args:
            database: Database instance for runtime config storage
            yaml_config: Parsed YAML configuration (optional)
        """
        self.database = database
        self.yaml_config = yaml_config or {}
        self._cache: dict[str, ConfigValue] = {}
        self._cache_time: datetime | None = None

    async def get_all_config(self, include_readonly: bool = False) -> dict[str, ConfigValue]:
        """Get all configuration values with sources.

        Args:
            include_readonly: Include read-only settings (secrets masked)

        Returns:
            Dictionary of setting key -> ConfigValue
        """
        result: dict[str, ConfigValue] = {}

        # Get editable settings
        for key, metadata in EDITABLE_SETTINGS.items():
            value = await self.get_setting(key)
            source = await self._get_source(key)
            result[key] = ConfigValue(
                key=key,
                value=value,
                source=source,
                editable=metadata.editable and source != ConfigSource.ENVIRONMENT,
                requires_restart=metadata.key in RESTART_REQUIRED_SETTINGS,
            )

        return result

    async def get_setting(self, key: str) -> Any:
        """Get a configuration setting value.

        Follows precedence: ENV > database > yaml > default

        Args:
            key: Setting key (e.g., "monitoring.grace_period_seconds")

        Returns:
            Setting value
        """
        # Check environment override first
        for env_var, setting_key in ENV_OVERRIDES.items():
            if setting_key == key and env_var in os.environ:
                return self._convert_value(os.environ[env_var], key)

        # Check database
        db_value = await self._get_from_database(key)
        if db_value is not None:
            return db_value

        # Check YAML config
        yaml_value = self._get_from_yaml(key)
        if yaml_value is not None:
            return yaml_value

        # Return default
        return self._get_default(key)

    async def set_setting(self, key: str, value: Any, updated_by: str = "dashboard") -> ConfigValue:
        """Set a configuration setting value.

        Args:
            key: Setting key
            value: New value
            updated_by: Who made the change (for audit)

        Returns:
            Updated ConfigValue

        Raises:
            ConfigServiceError: If setting is not editable or invalid
        """
        # Validate key is editable
        if key not in EDITABLE_SETTINGS:
            raise ConfigServiceError(f"Setting '{key}' is not editable")

        metadata = EDITABLE_SETTINGS[key]

        # Check if environment override exists
        for env_var, setting_key in ENV_OVERRIDES.items():
            if setting_key == key and env_var in os.environ:
                raise ConfigServiceError(
                    f"Setting '{key}' is overridden by environment variable {env_var}"
                )

        # Validate value
        validated_value = self._validate_value(key, value, metadata)

        # Store in database
        async with self.database.async_session() as session:
            await self._set_in_database(
                session, key, validated_value, metadata.value_type, updated_by
            )
            await session.commit()

        # Clear cache
        self._cache.pop(key, None)

        logger.info(f"Setting '{key}' updated to '{validated_value}' by {updated_by}")

        return ConfigValue(
            key=key,
            value=validated_value,
            source=ConfigSource.DATABASE,
            editable=True,
            requires_restart=key in RESTART_REQUIRED_SETTINGS,
        )

    async def delete_setting(self, key: str) -> bool:
        """Delete a setting from database (reverts to yaml/default).

        Args:
            key: Setting key

        Returns:
            True if setting was deleted, False if not found
        """
        async with self.database.async_session() as session:
            result = await session.execute(delete(RuntimeConfig).where(RuntimeConfig.key == key))
            await session.commit()
            # CursorResult has rowcount but mypy doesn't see it
            deleted: bool = bool(result.rowcount and result.rowcount > 0)  # type: ignore[attr-defined]

        if deleted:
            self._cache.pop(key, None)
            logger.info(f"Setting '{key}' deleted from database")

        return deleted

    async def get_schema(self) -> dict[str, SettingMetadata]:
        """Get configuration schema for UI generation.

        Returns:
            Dictionary of setting key -> SettingMetadata
        """
        return EDITABLE_SETTINGS.copy()

    async def validate_config(self, updates: dict[str, Any]) -> list[str]:
        """Validate configuration updates without applying.

        Args:
            updates: Dictionary of setting key -> new value

        Returns:
            List of validation errors (empty if valid)
        """
        errors: list[str] = []

        for key, value in updates.items():
            if key not in EDITABLE_SETTINGS:
                errors.append(f"Unknown setting: {key}")
                continue

            metadata = EDITABLE_SETTINGS[key]

            try:
                self._validate_value(key, value, metadata)
            except ConfigServiceError as e:
                errors.append(str(e))

        return errors

    async def get_hot_reload_changes(
        self, updates: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Separate updates into hot-reloadable and restart-required.

        Args:
            updates: Dictionary of setting key -> new value

        Returns:
            Tuple of (hot_reloadable, restart_required_keys)
        """
        hot_reloadable = {}
        restart_required = []

        for key, value in updates.items():
            if key in RESTART_REQUIRED_SETTINGS:
                restart_required.append(key)
            else:
                hot_reloadable[key] = value

        return hot_reloadable, restart_required

    # Instance Management

    async def get_instances(self) -> list[InstanceInfo]:
        """Get all configured HA instances (tokens masked).

        Returns:
            List of instance information
        """
        instances: list[InstanceInfo] = []

        async with self.database.async_session() as session:
            result = await session.execute(
                select(StoredInstance).order_by(StoredInstance.created_at)
            )
            for row in result.scalars():
                instances.append(
                    InstanceInfo(
                        instance_id=row.instance_id,
                        url=row.url,
                        masked_token=mask_token(self._safe_decrypt(row.encrypted_token)),
                        bridge_enabled=row.bridge_enabled,
                        is_active=row.is_active,
                        source=row.source,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                )

        return instances

    async def add_instance(
        self,
        instance_id: str,
        url: str,
        token: str,
        bridge_enabled: bool = True,
        source: str = "dashboard",
    ) -> InstanceInfo:
        """Add a new HA instance.

        Args:
            instance_id: Unique identifier for the instance
            url: Home Assistant URL
            token: Long-lived access token
            bridge_enabled: Enable bridge if available
            source: Source of the configuration

        Returns:
            Created instance info

        Raises:
            ConfigServiceError: If instance_id already exists
        """
        # Validate inputs
        if not instance_id or not instance_id.strip():
            raise ConfigServiceError("instance_id cannot be empty")
        if not url or not url.strip():
            raise ConfigServiceError("url cannot be empty")
        if not token or not token.strip():
            raise ConfigServiceError("token cannot be empty")

        # Normalize instance_id
        instance_id = instance_id.strip().replace(" ", "_").lower()
        url = url.rstrip("/")

        # Encrypt token
        try:
            encrypted_token = encrypt_token(token)
        except EncryptionError as e:
            raise ConfigServiceError(f"Failed to encrypt token: {e}") from e

        async with self.database.async_session() as session:
            # Check for existing
            result = await session.execute(
                select(StoredInstance).where(StoredInstance.instance_id == instance_id)
            )
            if result.scalar_one_or_none():
                raise ConfigServiceError(f"Instance '{instance_id}' already exists")

            # Create new instance
            now = datetime.now(UTC)
            new_instance = StoredInstance(
                instance_id=instance_id,
                url=url,
                encrypted_token=encrypted_token,
                bridge_enabled=bridge_enabled,
                is_active=True,
                source=source,
                created_at=now,
                updated_at=now,
            )
            session.add(new_instance)
            await session.commit()

            logger.info(f"Added new HA instance: {instance_id}")

            return InstanceInfo(
                instance_id=instance_id,
                url=url,
                masked_token=mask_token(token),
                bridge_enabled=bridge_enabled,
                is_active=True,
                source=source,
                created_at=now,
                updated_at=now,
            )

    async def update_instance(
        self,
        instance_id: str,
        url: str | None = None,
        token: str | None = None,
        bridge_enabled: bool | None = None,
        is_active: bool | None = None,
    ) -> InstanceInfo:
        """Update an existing HA instance.

        Args:
            instance_id: Instance to update
            url: New URL (optional)
            token: New token (optional)
            bridge_enabled: New bridge setting (optional)
            is_active: New active status (optional)

        Returns:
            Updated instance info

        Raises:
            ConfigServiceError: If instance not found
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(StoredInstance).where(StoredInstance.instance_id == instance_id)
            )
            instance = result.scalar_one_or_none()

            if not instance:
                raise ConfigServiceError(f"Instance '{instance_id}' not found")

            if url is not None:
                instance.url = url.rstrip("/")
            if token is not None:
                try:
                    instance.encrypted_token = encrypt_token(token)
                except EncryptionError as e:
                    raise ConfigServiceError(f"Failed to encrypt token: {e}") from e
            if bridge_enabled is not None:
                instance.bridge_enabled = bridge_enabled
            if is_active is not None:
                instance.is_active = is_active

            instance.updated_at = datetime.now(UTC)
            await session.commit()

            # Get current token for masking
            current_token = self._safe_decrypt(instance.encrypted_token)

            logger.info(f"Updated HA instance: {instance_id}")

            return InstanceInfo(
                instance_id=instance.instance_id,
                url=instance.url,
                masked_token=mask_token(current_token),
                bridge_enabled=instance.bridge_enabled,
                is_active=instance.is_active,
                source=instance.source,
                created_at=instance.created_at,
                updated_at=instance.updated_at,
            )

    async def delete_instance(self, instance_id: str) -> bool:
        """Delete an HA instance.

        Args:
            instance_id: Instance to delete

        Returns:
            True if deleted, False if not found
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                delete(StoredInstance).where(StoredInstance.instance_id == instance_id)
            )
            await session.commit()
            # CursorResult has rowcount but mypy doesn't see it
            deleted: bool = bool(result.rowcount and result.rowcount > 0)  # type: ignore[attr-defined]

        if deleted:
            logger.info(f"Deleted HA instance: {instance_id}")

        return deleted

    async def get_instance_token(self, instance_id: str) -> str | None:
        """Get decrypted token for an instance (internal use only).

        Args:
            instance_id: Instance ID

        Returns:
            Decrypted token or None if not found
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(StoredInstance).where(StoredInstance.instance_id == instance_id)
            )
            instance = result.scalar_one_or_none()

            if not instance:
                return None

            return self._safe_decrypt(instance.encrypted_token)

    async def get_active_instances_for_startup(
        self,
    ) -> list[tuple[str, str, str, bool]]:
        """Get active instances with decrypted tokens for service startup.

        Returns:
            List of (instance_id, url, token, bridge_enabled) tuples
            for all active instances stored in the database.
        """
        instances: list[tuple[str, str, str, bool]] = []

        async with self.database.async_session() as session:
            result = await session.execute(
                select(StoredInstance)
                .where(StoredInstance.is_active == True)  # noqa: E712
                .order_by(StoredInstance.created_at)
            )
            for row in result.scalars():
                token = self._safe_decrypt(row.encrypted_token)
                if token and token != "[decryption failed]":
                    instances.append((row.instance_id, row.url, token, row.bridge_enabled))
                else:
                    logger.warning(
                        f"Skipping instance '{row.instance_id}': failed to decrypt token"
                    )

        return instances

    # Private Methods

    async def _get_source(self, key: str) -> ConfigSource:
        """Determine the source of a setting value."""
        # Check environment override
        for env_var, setting_key in ENV_OVERRIDES.items():
            if setting_key == key and env_var in os.environ:
                return ConfigSource.ENVIRONMENT

        # Check database
        async with self.database.async_session() as session:
            result = await session.execute(select(RuntimeConfig).where(RuntimeConfig.key == key))
            if result.scalar_one_or_none():
                return ConfigSource.DATABASE

        # Check YAML
        if self._get_from_yaml(key) is not None:
            return ConfigSource.YAML

        return ConfigSource.DEFAULT

    async def _get_from_database(self, key: str) -> Any | None:
        """Get setting value from database."""
        async with self.database.async_session() as session:
            result = await session.execute(select(RuntimeConfig).where(RuntimeConfig.key == key))
            config = result.scalar_one_or_none()

            if config:
                return json.loads(config.value)

        return None

    async def _set_in_database(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        value_type: str,
        updated_by: str,
    ) -> None:
        """Set setting value in database."""
        json_value = json.dumps(value)

        # Check if exists
        result = await session.execute(select(RuntimeConfig).where(RuntimeConfig.key == key))
        existing = result.scalar_one_or_none()

        if existing:
            existing.value = json_value
            existing.value_type = value_type
            existing.updated_at = datetime.now(UTC)
            existing.updated_by = updated_by
        else:
            new_config = RuntimeConfig(
                key=key,
                value=json_value,
                value_type=value_type,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            )
            session.add(new_config)

    def _get_from_yaml(self, key: str) -> Any | None:
        """Get setting value from YAML config."""
        parts = key.split(".")
        current = self.yaml_config

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _get_default(self, key: str) -> Any:
        """Get default value for a setting from Pydantic models."""
        # Import here to avoid circular imports
        from ha_boss.core.config import (
            DatabaseConfig,
            HealingConfig,
            IntelligenceConfig,
            LoggingConfig,
            MonitoringConfig,
            NotificationsConfig,
        )

        parts = key.split(".")
        section = parts[0]
        field_path = parts[1:]

        # Map sections to config classes
        section_classes = {
            "monitoring": MonitoringConfig,
            "healing": HealingConfig,
            "notifications": NotificationsConfig,
            "intelligence": IntelligenceConfig,
            "logging": LoggingConfig,
            "database": DatabaseConfig,
        }

        if section not in section_classes:
            return None

        # Create default instance
        config_class = section_classes[section]
        try:
            default_config = config_class()
        except Exception:
            return None

        # Navigate to field
        current = default_config
        for part in field_path:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return None

        return current

    def _convert_value(self, value: str, key: str) -> Any:
        """Convert string value to appropriate type based on setting metadata."""
        if key not in EDITABLE_SETTINGS:
            return value

        metadata = EDITABLE_SETTINGS[key]
        value_type = metadata.value_type

        if value_type == "bool":
            return value.lower() in ("true", "1", "yes", "on")
        elif value_type == "int":
            return int(value)
        elif value_type == "float":
            return float(value)
        elif value_type == "list":
            return [v.strip() for v in value.split(",") if v.strip()]

        return value

    def _validate_value(self, key: str, value: Any, metadata: SettingMetadata) -> Any:
        """Validate and convert a value for a setting.

        Args:
            key: Setting key
            value: Value to validate
            metadata: Setting metadata

        Returns:
            Validated/converted value

        Raises:
            ConfigServiceError: If validation fails
        """
        value_type = metadata.value_type

        # Type conversion and validation
        try:
            if value_type == "bool":
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
                return bool(value)

            elif value_type == "int":
                int_val = int(value)
                if metadata.min_value is not None and int_val < metadata.min_value:
                    raise ConfigServiceError(
                        f"{key}: value {int_val} is below minimum {metadata.min_value}"
                    )
                if metadata.max_value is not None and int_val > metadata.max_value:
                    raise ConfigServiceError(
                        f"{key}: value {int_val} is above maximum {metadata.max_value}"
                    )
                return int_val

            elif value_type == "float":
                float_val = float(value)
                if metadata.min_value is not None and float_val < metadata.min_value:
                    raise ConfigServiceError(
                        f"{key}: value {float_val} is below minimum {metadata.min_value}"
                    )
                if metadata.max_value is not None and float_val > metadata.max_value:
                    raise ConfigServiceError(
                        f"{key}: value {float_val} is above maximum {metadata.max_value}"
                    )
                return float_val

            elif value_type == "string":
                str_val = str(value)
                if metadata.options and str_val not in metadata.options:
                    raise ConfigServiceError(
                        f"{key}: value '{str_val}' not in allowed options: {metadata.options}"
                    )
                return str_val

            elif value_type == "list":
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    # Support newline or comma separated
                    if "\n" in value:
                        return [v.strip() for v in value.split("\n") if v.strip()]
                    return [v.strip() for v in value.split(",") if v.strip()]
                raise ConfigServiceError(f"{key}: expected list, got {type(value).__name__}")

            elif value_type == "dict":
                if isinstance(value, dict):
                    return value
                raise ConfigServiceError(f"{key}: expected dict, got {type(value).__name__}")

            else:
                return value

        except ConfigServiceError:
            raise
        except Exception as e:
            raise ConfigServiceError(f"{key}: invalid value - {e}") from e

    def _safe_decrypt(self, encrypted: str) -> str:
        """Safely decrypt a token, returning placeholder on error."""
        try:
            return decrypt_token(encrypted)
        except EncryptionError:
            return "[decryption failed]"
