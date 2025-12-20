"""Entity monitoring endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import EntityHistoryResponse, EntityStateResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/entities", response_model=list[EntityStateResponse])
async def list_entities(
    limit: int = Query(100, ge=1, le=1000, description="Maximum entities to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[EntityStateResponse]:
    """List all monitored entities with current states.

    Returns a paginated list of entities being monitored by HA Boss,
    including their current state and last update timestamps.

    Args:
        limit: Maximum number of entities to return (1-1000)
        offset: Pagination offset

    Returns:
        List of entity state information

    Raises:
        HTTPException: Service not initialized or state tracker unavailable (500)
    """
    try:
        service = get_service()

        if not service.state_tracker:
            raise HTTPException(status_code=500, detail="State tracker not initialized") from None

        # Get all entities from state tracker
        all_states = list(service.state_tracker._states.values())

        # Apply pagination
        paginated_states = all_states[offset : offset + limit]

        # Convert to response models
        entities = []
        for state in paginated_states:
            entities.append(
                EntityStateResponse(
                    entity_id=state.entity_id,
                    state=state.state,
                    attributes=state.attributes,
                    last_changed=state.last_changed,
                    last_updated=state.last_updated,
                    monitored=True,  # All entities in state tracker are monitored
                )
            )

        return entities

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/entities/{entity_id:path}", response_model=EntityStateResponse)
async def get_entity(entity_id: str) -> EntityStateResponse:
    """Get current state of a specific entity.

    Args:
        entity_id: Entity ID (e.g., 'sensor.temperature')

    Returns:
        Entity state information

    Raises:
        HTTPException: Entity not found (404) or service error (500)
    """
    try:
        service = get_service()

        if not service.state_tracker:
            raise HTTPException(status_code=500, detail="State tracker not initialized") from None

        # Get entity state
        state = service.state_tracker.get_entity_state(entity_id)

        if not state:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

        return EntityStateResponse(
            entity_id=state.entity_id,
            state=state.state,
            attributes=state.attributes,
            last_changed=state.last_changed,
            last_updated=state.last_updated,
            monitored=True,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/entities/{entity_id:path}/history", response_model=EntityHistoryResponse)
async def get_entity_history(
    entity_id: str,
    hours: int = Query(24, ge=1, le=168, description="Hours of history to retrieve (1-168)"),
) -> EntityHistoryResponse:
    """Get state history for a specific entity.

    Args:
        entity_id: Entity ID (e.g., 'sensor.temperature')
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    Returns:
        Entity state history

    Raises:
        HTTPException: Entity not found (404) or service error (500)
    """
    try:
        service = get_service()

        if not service.database:
            raise HTTPException(status_code=500, detail="Database not initialized") from None

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # Query database for entity history
        async with service.database.session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import EntityStateModel

            stmt = (
                select(EntityStateModel)
                .where(
                    EntityStateModel.entity_id == entity_id,
                    EntityStateModel.timestamp >= start_time,
                    EntityStateModel.timestamp <= end_time,
                )
                .order_by(EntityStateModel.timestamp.desc())
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
                "state": record.state,
                "timestamp": record.timestamp,
                "attributes": record.attributes or {},
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
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving entity history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve entity history") from None
