"""Instance helper functions for aggregate mode support."""

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from ha_boss.service import HABossService


def get_instance_ids(service: "HABossService", instance_id: str) -> list[str]:
    """Get list of instance IDs to query.

    When instance_id is "all", returns all configured instance IDs.
    Otherwise, validates the specific instance exists and returns it.

    Args:
        service: The HA Boss service
        instance_id: "all" for all instances, or specific instance_id

    Returns:
        List of instance IDs to query

    Raises:
        HTTPException 404 if specific instance not found
    """
    if instance_id == "all":
        return list(service.ha_clients.keys())

    if instance_id not in service.ha_clients:
        available = list(service.ha_clients.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Instance '{instance_id}' not found. Available instances: {available}",
        )

    return [instance_id]


def is_aggregate_mode(instance_id: str) -> bool:
    """Check if querying all instances (aggregate mode).

    Args:
        instance_id: The instance_id parameter value

    Returns:
        True if instance_id is "all", False otherwise
    """
    return instance_id == "all"
