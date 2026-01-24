"""Healing action endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import HealingActionResponse, HealingHistoryResponse
from ha_boss.api.utils.instance_helpers import get_instance_ids
from ha_boss.monitoring.health_monitor import HealthIssue

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/healing/{entity_id:path}", response_model=HealingActionResponse)
async def trigger_healing(
    entity_id: str = Path(..., description="Entity ID to heal"),
    instance_id: str = Query("default", description="Instance identifier"),
) -> HealingActionResponse:
    """Manually trigger healing for a specific entity in a specific instance.

    Attempts to heal the specified entity by reloading its integration.
    This bypasses normal grace periods and cooldowns.

    Args:
        entity_id: Entity ID to heal (e.g., 'sensor.temperature')
        instance_id: Instance identifier (default: "default")

    Returns:
        Healing action result

    Raises:
        HTTPException: Instance not found (404), entity not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists (use ha_clients as authoritative source)
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Get per-instance components
        healing_manager = service.healing_managers.get(instance_id)
        if not healing_manager:
            raise HTTPException(
                status_code=503, detail="Healing manager not initialized for this instance"
            ) from None

        integration_discovery = service.integration_discoveries.get(instance_id)
        if not integration_discovery:
            raise HTTPException(
                status_code=503, detail="Integration discovery not initialized for this instance"
            ) from None

        # Get entity state
        state_tracker = service.state_trackers.get(instance_id)
        if not state_tracker:
            raise HTTPException(
                status_code=503, detail="State tracker not initialized for this instance"
            ) from None

        entity_state = await state_tracker.get_state(entity_id)
        if not entity_state:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{entity_id}' not found in instance '{instance_id}'",
            )

        # Get integration for entity
        integration_name = integration_discovery.get_integration_for_entity(entity_id)

        # Attempt healing
        logger.info(f"[{instance_id}] Manual healing requested for entity: {entity_id}")

        try:
            # Create a health issue for manual healing
            health_issue = HealthIssue(
                entity_id=entity_id,
                issue_type="manual_heal",
                detected_at=datetime.now(UTC),
                details={"source": "api_manual_trigger"},
            )
            success = await healing_manager.heal(health_issue)

            return HealingActionResponse(
                entity_id=entity_id,
                integration=integration_name,
                action_type="integration_reload",
                success=success,
                timestamp=datetime.now(UTC),
                message="Healing successful" if success else "Healing failed",
            )

        except Exception as heal_error:
            logger.error(
                f"[{instance_id}] Healing failed for {entity_id}: {heal_error}", exc_info=True
            )
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
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error triggering healing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger healing") from None


@router.get("/healing/history", response_model=HealingHistoryResponse)
async def get_healing_history(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
    limit: int = Query(50, ge=1, le=500, description="Maximum actions to return"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
) -> HealingHistoryResponse:
    """Get healing action history.

    Returns a list of recent healing actions including:
    - Entity and integration information
    - Action type and success status
    - Timestamps

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")
        limit: Maximum number of actions to return (1-500)
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    When instance_id is 'all', returns healing actions from all instances.

    Returns:
        Healing action history with statistics

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Get list of instances to query
        instance_ids = get_instance_ids(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # Query database for healing actions
        async with service.database.async_session() as session:
            from sqlalchemy import func, select

            from ha_boss.core.database import HealingAction, Integration

            # Build base query
            stmt = (
                select(HealingAction, Integration.domain)  # type: ignore[attr-defined]
                .join(  # type: ignore[attr-defined]
                    Integration,
                    HealingAction.integration_id == Integration.entry_id,  # type: ignore[attr-defined]
                    isouter=True,
                )
                .where(  # type: ignore[attr-defined]
                    HealingAction.timestamp >= start_time,  # type: ignore[attr-defined]
                    HealingAction.timestamp <= end_time,  # type: ignore[attr-defined]
                )
            )

            # Filter by instance(s)
            if len(instance_ids) == 1:
                stmt = stmt.where(HealingAction.instance_id == instance_ids[0])  # type: ignore[attr-defined]
            else:
                stmt = stmt.where(HealingAction.instance_id.in_(instance_ids))  # type: ignore[attr-defined]

            stmt = stmt.order_by(HealingAction.timestamp.desc()).limit(limit)  # type: ignore[attr-defined]

            result = await session.execute(stmt)
            rows = result.all()

            # Get summary statistics
            from sqlalchemy import Integer, cast

            stats_stmt = select(  # type: ignore[attr-defined]
                func.count(HealingAction.id).label("total"),  # type: ignore[attr-defined]
                func.sum(cast(HealingAction.success, Integer)).label("success"),  # type: ignore[attr-defined, arg-type]
            ).where(  # type: ignore[attr-defined]
                HealingAction.timestamp >= start_time,  # type: ignore[attr-defined]
                HealingAction.timestamp <= end_time,  # type: ignore[attr-defined]
            )

            # Filter by instance(s)
            if len(instance_ids) == 1:
                stats_stmt = stats_stmt.where(HealingAction.instance_id == instance_ids[0])  # type: ignore[attr-defined]
            else:
                stats_stmt = stats_stmt.where(HealingAction.instance_id.in_(instance_ids))  # type: ignore[attr-defined]

            stats_result = await session.execute(stats_stmt)
            stats = stats_result.first()

        # Convert to response models
        actions = []
        for action, integration_domain in rows:
            actions.append(
                HealingActionResponse(
                    entity_id=action.entity_id,
                    integration=integration_domain or "unknown",
                    action_type=action.action,  # Use 'action' attribute
                    success=action.success,
                    timestamp=action.timestamp,
                    message=(
                        action.error if not action.success else "Success"
                    ),  # Use 'error' attribute
                    instance_id=action.instance_id if len(instance_ids) > 1 else None,
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

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving healing history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve healing history") from None
