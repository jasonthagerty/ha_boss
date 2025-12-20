"""Healing action endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import HealingActionResponse, HealingHistoryResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/healing/{entity_id:path}", response_model=HealingActionResponse)
async def trigger_healing(
    entity_id: str = Path(..., description="Entity ID to heal"),
) -> HealingActionResponse:
    """Manually trigger healing for a specific entity.

    Attempts to heal the specified entity by reloading its integration.
    This bypasses normal grace periods and cooldowns.

    Args:
        entity_id: Entity ID to heal (e.g., 'sensor.temperature')

    Returns:
        Healing action result

    Raises:
        HTTPException: Service error (500) or entity not found (404)
    """
    try:
        service = get_service()

        if not service.healing_manager:
            raise HTTPException(status_code=500, detail="Healing manager not initialized") from None

        if not service.integration_discovery:
            raise HTTPException(status_code=500, detail="Integration discovery not initialized") from None

        # Get entity state
        if not service.state_tracker:
            raise HTTPException(status_code=500, detail="State tracker not initialized") from None

        entity_state = service.state_tracker.get_entity_state(entity_id)
        if not entity_state:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

        # Get integration for entity
        integration_name = None
        integration = service.integration_discovery.get_integration_for_entity(entity_id)
        if integration:
            integration_name = integration.name

        # Attempt healing
        logger.info(f"Manual healing requested for entity: {entity_id}")

        try:
            success = await service.healing_manager.heal_entity(entity_id)

            return HealingActionResponse(
                entity_id=entity_id,
                integration=integration_name,
                action_type="integration_reload",
                success=success,
                timestamp=datetime.now(UTC),
                message="Healing successful" if success else "Healing failed",
            )

        except Exception as heal_error:
            logger.error(f"Healing failed for {entity_id}: {heal_error}", exc_info=True)
            return HealingActionResponse(
                entity_id=entity_id,
                integration=integration_name,
                action_type="integration_reload",
                success=False,
                timestamp=datetime.now(UTC),
                message=f"Healing failed: {str(heal_error)}",
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error triggering healing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger healing") from None


@router.get("/healing/history", response_model=HealingHistoryResponse)
async def get_healing_history(
    limit: int = Query(50, ge=1, le=500, description="Maximum actions to return"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
) -> HealingHistoryResponse:
    """Get healing action history.

    Returns a list of recent healing actions including:
    - Entity and integration information
    - Action type and success status
    - Timestamps

    Args:
        limit: Maximum number of actions to return (1-500)
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    Returns:
        Healing action history with statistics

    Raises:
        HTTPException: Service error (500)
    """
    try:
        service = get_service()

        if not service.database:
            raise HTTPException(status_code=500, detail="Database not initialized") from None

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # Query database for healing actions
        async with service.database.session() as session:
            from sqlalchemy import func, select

            from ha_boss.core.database import HealingActionModel, IntegrationModel

            # Get healing actions with integration names
            stmt = (
                select(HealingActionModel, IntegrationModel.name)
                .join(
                    IntegrationModel,
                    HealingActionModel.integration_id == IntegrationModel.id,
                    isouter=True,
                )
                .where(
                    HealingActionModel.timestamp >= start_time,
                    HealingActionModel.timestamp <= end_time,
                )
                .order_by(HealingActionModel.timestamp.desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            rows = result.all()

            # Get summary statistics
            stats_stmt = select(
                func.count(HealingActionModel.id).label("total"),
                func.sum(func.cast(HealingActionModel.success, func.Integer)).label("success"),
            ).where(
                HealingActionModel.timestamp >= start_time,
                HealingActionModel.timestamp <= end_time,
            )

            stats_result = await session.execute(stats_stmt)
            stats = stats_result.first()

        # Convert to response models
        actions = []
        for action, integration_name in rows:
            actions.append(
                HealingActionResponse(
                    entity_id=action.entity_id,
                    integration=integration_name,
                    action_type=action.action_type,
                    success=action.success,
                    timestamp=action.timestamp,
                    message=action.error_message if not action.success else "Success",
                )
            )

        total_count = stats.total or 0
        success_count = stats.success or 0
        failure_count = total_count - success_count

        return HealingHistoryResponse(
            actions=actions,
            total_count=total_count,
            success_count=success_count,
            failure_count=failure_count,
        )

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving healing history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve healing history") from None
