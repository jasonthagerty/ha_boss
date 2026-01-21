"""Configuration management API endpoints."""

import logging
from typing import Any

import aiohttp
from fastapi import APIRouter, HTTPException

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    ConfigInstanceCreateRequest,
    ConfigInstanceInfo,
    ConfigInstanceTestRequest,
    ConfigInstanceTestResponse,
    ConfigInstanceUpdateRequest,
    ConfigResponse,
    ConfigSchemaResponse,
    ConfigSettingMetadata,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    ConfigValidationResponse,
    ConfigValueResponse,
)
from ha_boss.core.config_service import ConfigService
from ha_boss.core.exceptions import ConfigServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_config_service() -> ConfigService:
    """Get or create the config service instance.

    Returns:
        ConfigService instance

    Raises:
        HTTPException: If service is not initialized
    """
    service = get_service()
    if not hasattr(service, "_config_service") or service._config_service is None:  # type: ignore[attr-defined]
        if service.database is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        # Initialize config service with database
        service._config_service = ConfigService(  # type: ignore[attr-defined]
            database=service.database,
            yaml_config=_config_to_dict(service.config),
        )
    return service._config_service  # type: ignore[attr-defined, return-value, no-any-return]


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Convert Pydantic config to dictionary for yaml_config parameter.

    Args:
        config: Pydantic config object

    Returns:
        Dictionary representation
    """
    if hasattr(config, "model_dump"):
        result: dict[str, Any] = config.model_dump()
        return result
    elif hasattr(config, "dict"):
        result = config.dict()
        return result
    return {}


# ==================== Configuration Settings ====================


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Get all configuration settings with sources.

    Returns current configuration values along with their sources
    (default, yaml, database, or environment). Settings overridden
    by environment variables are marked as non-editable.

    Returns:
        Configuration settings with values and source information
    """
    try:
        config_service = _get_config_service()
        all_config = await config_service.get_all_config()

        settings = {}
        for key, config_value in all_config.items():
            settings[key] = ConfigValueResponse(
                key=config_value.key,
                value=config_value.value,
                source=config_value.source.value,
                editable=config_value.editable,
                requires_restart=config_value.requires_restart,
            )

        return ConfigResponse(settings=settings, restart_required=False)

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.put("/config", response_model=ConfigUpdateResponse)
async def update_config(request: ConfigUpdateRequest) -> ConfigUpdateResponse:
    """Update configuration settings.

    Updates one or more configuration settings. Settings overridden
    by environment variables cannot be changed.

    Args:
        request: Settings to update

    Returns:
        Update result with list of updated settings and any errors
    """
    try:
        config_service = _get_config_service()

        # Validate all settings first
        errors = await config_service.validate_config(request.settings)
        if errors:
            return ConfigUpdateResponse(updated=[], errors=errors, restart_required=False)

        # Apply updates
        updated = []
        update_errors = []
        restart_required = False

        for key, value in request.settings.items():
            try:
                result = await config_service.set_setting(key, value, updated_by="api")
                updated.append(key)
                if result.requires_restart:
                    restart_required = True
            except ConfigServiceError as e:
                update_errors.append(str(e))

        return ConfigUpdateResponse(
            updated=updated,
            errors=update_errors,
            restart_required=restart_required,
        )

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.get("/config/schema", response_model=ConfigSchemaResponse)
async def get_config_schema() -> ConfigSchemaResponse:
    """Get configuration schema for UI generation.

    Returns metadata for all editable settings including
    labels, descriptions, value types, and validation constraints.

    Returns:
        Configuration schema with setting metadata
    """
    try:
        config_service = _get_config_service()
        schema = await config_service.get_schema()

        settings = {}
        sections = set()

        for key, metadata in schema.items():
            settings[key] = ConfigSettingMetadata(
                key=metadata.key,
                label=metadata.label,
                description=metadata.description,
                value_type=metadata.value_type,
                editable=metadata.editable,
                requires_restart=metadata.requires_restart,
                section=metadata.section,
                min_value=metadata.min_value,
                max_value=metadata.max_value,
                options=metadata.options,
            )
            sections.add(metadata.section)

        return ConfigSchemaResponse(
            settings=settings,
            sections=sorted(sections),
        )

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.post("/config/validate", response_model=ConfigValidationResponse)
async def validate_config(request: ConfigUpdateRequest) -> ConfigValidationResponse:
    """Validate configuration settings without applying.

    Validates settings and returns any errors without
    actually saving the changes.

    Args:
        request: Settings to validate

    Returns:
        Validation result with any errors
    """
    try:
        config_service = _get_config_service()
        errors = await config_service.validate_config(request.settings)

        return ConfigValidationResponse(
            valid=len(errors) == 0,
            errors=errors,
        )

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.post("/config/reload")
async def reload_config() -> dict[str, str]:
    """Apply hot-reloadable configuration changes.

    Signals components to reload their configuration.
    Only hot-reloadable settings are affected; changes to
    restart-required settings need a service restart.

    Returns:
        Status message
    """
    try:
        # Ensure service is running
        get_service()

        # For now, just log that a reload was requested
        # Full hot-reload implementation requires coordination with service components
        logger.info("Configuration reload requested via API")

        # TODO: Implement actual hot-reload coordination
        # This would involve:
        # 1. Loading updated config from database
        # 2. Calling reload methods on relevant components
        # 3. Broadcasting config change via WebSocket

        return {"status": "reload_requested", "message": "Configuration reload initiated"}

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


# ==================== Instance Management ====================


@router.get("/config/instances", response_model=list[ConfigInstanceInfo])
async def list_instances() -> list[ConfigInstanceInfo]:
    """List all configured HA instances.

    Returns instance configurations with tokens masked for security.
    Includes both YAML-configured and dashboard-added instances.

    Returns:
        List of instance configurations
    """
    try:
        config_service = _get_config_service()
        instances = await config_service.get_instances()

        return [
            ConfigInstanceInfo(
                instance_id=inst.instance_id,
                url=inst.url,
                masked_token=inst.masked_token,
                bridge_enabled=inst.bridge_enabled,
                is_active=inst.is_active,
                source=inst.source,
                created_at=inst.created_at,
                updated_at=inst.updated_at,
            )
            for inst in instances
        ]

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.post("/config/instances", response_model=ConfigInstanceInfo)
async def add_instance(request: ConfigInstanceCreateRequest) -> ConfigInstanceInfo:
    """Add a new HA instance.

    Creates a new Home Assistant instance configuration.
    The token is encrypted before storage.

    Note: Adding an instance requires a service restart to
    establish the actual connection.

    Args:
        request: Instance configuration

    Returns:
        Created instance information
    """
    try:
        config_service = _get_config_service()
        instance = await config_service.add_instance(
            instance_id=request.instance_id,
            url=request.url,
            token=request.token,
            bridge_enabled=request.bridge_enabled,
            source="dashboard",
        )

        return ConfigInstanceInfo(
            instance_id=instance.instance_id,
            url=instance.url,
            masked_token=instance.masked_token,
            bridge_enabled=instance.bridge_enabled,
            is_active=instance.is_active,
            source=instance.source,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )

    except ConfigServiceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.put("/config/instances/{instance_id}", response_model=ConfigInstanceInfo)
async def update_instance(
    instance_id: str, request: ConfigInstanceUpdateRequest
) -> ConfigInstanceInfo:
    """Update an HA instance configuration.

    Updates the configuration for an existing instance.
    Only provided fields are updated.

    Note: Changing URL or token requires a service restart.

    Args:
        instance_id: Instance to update
        request: Fields to update

    Returns:
        Updated instance information
    """
    try:
        config_service = _get_config_service()
        instance = await config_service.update_instance(
            instance_id=instance_id,
            url=request.url,
            token=request.token,
            bridge_enabled=request.bridge_enabled,
            is_active=request.is_active,
        )

        return ConfigInstanceInfo(
            instance_id=instance.instance_id,
            url=instance.url,
            masked_token=instance.masked_token,
            bridge_enabled=instance.bridge_enabled,
            is_active=instance.is_active,
            source=instance.source,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )

    except ConfigServiceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.delete("/config/instances/{instance_id}")
async def delete_instance(instance_id: str) -> dict[str, Any]:
    """Delete an HA instance.

    Removes the instance configuration. Active connections
    are not affected until service restart.

    Args:
        instance_id: Instance to delete

    Returns:
        Deletion status
    """
    try:
        config_service = _get_config_service()
        deleted = await config_service.delete_instance(instance_id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

        return {
            "status": "deleted",
            "instance_id": instance_id,
            "message": "Instance deleted. Restart service to disconnect.",
        }

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.post("/config/instances/{instance_id}/test", response_model=ConfigInstanceTestResponse)
async def test_instance(instance_id: str) -> ConfigInstanceTestResponse:
    """Test connection to an existing HA instance.

    Tests the connection using stored credentials.

    Args:
        instance_id: Instance to test

    Returns:
        Connection test result
    """
    try:
        config_service = _get_config_service()

        # Get instance info
        instances = await config_service.get_instances()
        instance = next((i for i in instances if i.instance_id == instance_id), None)

        if not instance:
            raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

        # Get decrypted token
        token = await config_service.get_instance_token(instance_id)
        if not token:
            return ConfigInstanceTestResponse(
                success=False,
                message="Failed to decrypt token",
                version=None,
                location_name=None,
            )

        # Test connection
        return await _test_ha_connection(instance.url, token)

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.post("/config/instances/test", response_model=ConfigInstanceTestResponse)
async def test_new_instance(request: ConfigInstanceTestRequest) -> ConfigInstanceTestResponse:
    """Test connection to a new HA instance before saving.

    Tests the connection using provided credentials without
    storing them.

    Args:
        request: URL and token to test

    Returns:
        Connection test result
    """
    return await _test_ha_connection(request.url, request.token)


async def _test_ha_connection(url: str, token: str) -> ConfigInstanceTestResponse:
    """Test connection to Home Assistant.

    Args:
        url: Home Assistant URL
        token: Access token

    Returns:
        Connection test result
    """
    url = url.rstrip("/")

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            async with session.get(
                f"{url}/api/",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return ConfigInstanceTestResponse(
                        success=True,
                        message="Connection successful",
                        version=data.get("version"),
                        location_name=data.get("location_name"),
                    )
                elif response.status == 401:
                    return ConfigInstanceTestResponse(
                        success=False,
                        message="Authentication failed - invalid token",
                        version=None,
                        location_name=None,
                    )
                else:
                    return ConfigInstanceTestResponse(
                        success=False,
                        message=f"Connection failed with status {response.status}",
                        version=None,
                        location_name=None,
                    )

    except aiohttp.ClientConnectorError as e:
        return ConfigInstanceTestResponse(
            success=False,
            message=f"Connection failed: {e}",
            version=None,
            location_name=None,
        )
    except TimeoutError:
        return ConfigInstanceTestResponse(
            success=False,
            message="Connection timed out",
            version=None,
            location_name=None,
        )
    except Exception as e:
        return ConfigInstanceTestResponse(
            success=False,
            message=f"Connection error: {e}",
            version=None,
            location_name=None,
        )
