"""Entity monitoring endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ha_boss.api.app import get_service
from ha_boss.api.models import EntityHistoryResponse, EntityStateResponse
from ha_boss.api.utils.instance_helpers import get_instance_ids, is_aggregate_mode
from ha_boss.core.database import Entity

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/entities", response_model=list[EntityStateResponse])
async def list_entities(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum entities to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[EntityStateResponse]:
    """List all monitored entities with current states.

    Returns a paginated list of entities being monitored by HA Boss,
    including their current state and last update timestamps.

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")
        limit: Maximum number of entities to return (1-1000)
        offset: Pagination offset

    When instance_id is 'all', returns entities from all instances.
    Each entity's instance_id field indicates which instance it belongs to.

    Returns:
        List of entity state information

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Get list of instances to query
        instance_ids = get_instance_ids(service, instance_id)
        aggregate = is_aggregate_mode(instance_id)

        # Query database for monitored entities
        async with service.database.async_session() as session:
            query = select(Entity).where(Entity.is_monitored == True)  # noqa: E712

            # Filter by instance(s)
            if len(instance_ids) == 1:
                query = query.where(Entity.instance_id == instance_ids[0])
            else:
                query = query.where(Entity.instance_id.in_(instance_ids))

            query = query.order_by(Entity.instance_id, Entity.entity_id).limit(limit).offset(offset)

            result = await session.execute(query)
            db_entities = result.scalars().all()

        # Convert to response models
        entities = []
        for db_entity in db_entities:
            # Try to get current state from cache first, fall back to database
            state_tracker = service.state_trackers.get(db_entity.instance_id)
            cached_state = None
            if state_tracker:
                cached_state = await state_tracker.get_state(db_entity.entity_id)

            if cached_state:
                entities.append(
                    EntityStateResponse(
                        entity_id=cached_state.entity_id,
                        state=cached_state.state,
                        attributes=cached_state.attributes,
                        last_changed=None,
                        last_updated=cached_state.last_updated,
                        monitored=True,
                        instance_id=db_entity.instance_id if aggregate else None,
                    )
                )
            else:
                # Use database values as fallback
                entities.append(
                    EntityStateResponse(
                        entity_id=db_entity.entity_id,
                        state=db_entity.last_state or "unknown",
                        attributes={},
                        last_changed=None,
                        last_updated=db_entity.last_seen,
                        monitored=True,
                        instance_id=db_entity.instance_id if aggregate else None,
                    )
                )

        return entities

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.get("/entities/{entity_id:path}", response_model=EntityStateResponse)
async def get_entity(
    entity_id: str, instance_id: str = Query("default", description="Instance identifier")
) -> EntityStateResponse:
    """Get current state of a specific entity for a specific instance.

    Args:
        entity_id: Entity ID (e.g., 'sensor.temperature')
        instance_id: Instance identifier (default: "default")

    Returns:
        Entity state information

    Raises:
        HTTPException: Instance or entity not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        state_tracker = service.state_trackers.get(instance_id)
        if not state_tracker:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.state_trackers.keys())}",
            ) from None

        # Get entity state
        state = await state_tracker.get_state(entity_id)

        if not state:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{entity_id}' not found in instance '{instance_id}'",
            ) from None

        return EntityStateResponse(
            entity_id=state.entity_id,
            state=state.state,
            attributes=state.attributes,
            last_changed=None,  # EntityState doesn't track last_changed
            last_updated=state.last_updated,
            monitored=True,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None


@router.get("/entities/{entity_id:path}/history", response_model=EntityHistoryResponse)
async def get_entity_history(
    entity_id: str,
    instance_id: str = Query("default", description="Instance identifier"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history to retrieve (1-168)"),
) -> EntityHistoryResponse:
    """Get state history for a specific entity in a specific instance.

    Args:
        entity_id: Entity ID (e.g., 'sensor.temperature')
        instance_id: Instance identifier (default: "default")
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    Returns:
        Entity state history for the specified instance

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists (use ha_clients as authoritative source)
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # Query database for entity history for this instance
        async with service.database.async_session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import StateHistory

            stmt = (
                select(StateHistory)
                .where(
                    StateHistory.entity_id == entity_id,
                    StateHistory.instance_id == instance_id,
                    StateHistory.timestamp >= start_time,
                    StateHistory.timestamp <= end_time,
                )
                .order_by(StateHistory.timestamp.desc())
            )

            result = await session.execute(stmt)
            history_records = result.scalars().all()

        if not history_records:
            # Entity exists but no history - still return empty history
            return EntityHistoryResponse(
                entity_id=entity_id,
                history=[],
                count=0,
            )

        # Convert to response format
        history = [
            {
                "state": record.new_state,
                "timestamp": record.timestamp,
                "attributes": {},  # StateHistory doesn't store attributes
            }
            for record in history_records
        ]

        return EntityHistoryResponse(
            entity_id=entity_id,
            history=history,
            count=len(history),
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving entity history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve entity history") from None
