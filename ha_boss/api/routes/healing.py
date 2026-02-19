"""Healing action endpoints."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy import func

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    AutomationHealthResponse,
    DeviceActionResponse,
    EntityActionResponse,
    HealingActionResponse,
    HealingCascadeResponse,
    HealingHistoryResponse,
    HealingStatisticsByLevel,
    HealingStatisticsResponse,
    SuppressedEntitiesResponse,
    SuppressedEntityResponse,
    SuppressionActionResponse,
)
from ha_boss.api.utils.instance_helpers import get_instance_ids
from ha_boss.core.database import (
    AutomationHealthStatus,
    DeviceHealingAction,
    Entity,
    EntityHealingAction,
    HealingCascadeExecution,
    HealthEvent,
)
from ha_boss.core.types import HealthIssue

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_instance_id(service: Any, instance_id: str) -> None:
    """Validate that instance_id exists.

    Args:
        service: HA Boss service instance
        instance_id: Instance ID to validate

    Raises:
        HTTPException: If instance not found
    """
    if instance_id not in service.ha_clients:
        available = list(service.ha_clients.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Instance '{instance_id}' not found. Available instances: {available}",
        )


def _calculate_success_rate(successes: int, total: int) -> float:
    """Calculate success rate percentage.

    Args:
        successes: Number of successful attempts
        total: Total number of attempts

    Returns:
        Success rate as percentage (0.0-100.0)
    """
    return (successes / total * 100) if total > 0 else 0.0


async def _fetch_cascade_actions(
    session: Any,
    instance_id: str,
    automation_id: str,
    execution_id: int,
) -> tuple[list[EntityHealingAction], list[DeviceHealingAction]]:
    """Fetch entity and device actions for a cascade.

    Args:
        session: Database session
        instance_id: Instance ID
        automation_id: Automation ID
        execution_id: Execution ID

    Returns:
        Tuple of (entity_actions, device_actions)
    """
    from sqlalchemy import select

    # Fetch entity-level actions
    entity_actions_stmt = select(EntityHealingAction).where(
        EntityHealingAction.instance_id == instance_id,
        EntityHealingAction.automation_id == automation_id,
        EntityHealingAction.execution_id == execution_id,
    )
    entity_actions_result = await session.execute(entity_actions_stmt)
    entity_actions = entity_actions_result.scalars().all()

    # Fetch device-level actions
    device_actions_stmt = select(DeviceHealingAction).where(
        DeviceHealingAction.instance_id == instance_id,
        DeviceHealingAction.automation_id == automation_id,
        DeviceHealingAction.execution_id == execution_id,
    )
    device_actions_result = await session.execute(device_actions_stmt)
    device_actions = device_actions_result.scalars().all()

    return entity_actions, device_actions


def _build_cascade_response(
    cascade: HealingCascadeExecution,
    entity_actions: list[EntityHealingAction],
    device_actions: list[DeviceHealingAction],
) -> HealingCascadeResponse:
    """Build a HealingCascadeResponse from cascade and actions.

    Args:
        cascade: Cascade execution record
        entity_actions: List of entity-level healing actions
        device_actions: List of device-level healing actions

    Returns:
        Complete cascade response with actions
    """
    return HealingCascadeResponse(
        id=cascade.id,
        instance_id=cascade.instance_id,
        automation_id=cascade.automation_id,
        execution_id=cascade.execution_id,
        trigger_type=cascade.trigger_type,
        routing_strategy=cascade.routing_strategy,
        entity_level_attempted=cascade.entity_level_attempted,
        entity_level_success=cascade.entity_level_success,
        device_level_attempted=cascade.device_level_attempted,
        device_level_success=cascade.device_level_success,
        integration_level_attempted=cascade.integration_level_attempted,
        integration_level_success=cascade.integration_level_success,
        final_success=cascade.final_success,
        total_duration_seconds=cascade.total_duration_seconds,
        created_at=cascade.created_at,
        completed_at=cascade.completed_at,
        plan_generation_suggested=getattr(cascade, "plan_generation_suggested", False),
        entity_actions=[
            EntityActionResponse(
                id=action.id,
                entity_id=action.entity_id,
                action_type=action.action_type,
                service_domain=action.service_domain,
                service_name=action.service_name,
                success=action.success,
                error_message=action.error_message,
                duration_seconds=action.duration_seconds,
            )
            for action in entity_actions
        ],
        device_actions=[
            DeviceActionResponse(
                id=action.id,
                device_id=action.device_id,
                action_type=action.action_type,
                success=action.success,
                error_message=action.error_message,
                duration_seconds=action.duration_seconds,
            )
            for action in device_actions
        ],
    )


# IMPORTANT: More specific routes must come BEFORE the catch-all route
# The /healing/{entity_id:path} route will match ANY path, so suppression
# endpoints must be defined first


@router.post("/healing/suppress/{entity_id:path}", response_model=SuppressionActionResponse)
async def suppress_healing(
    entity_id: str,
    instance_id: str = Query("default", description="Instance ID"),
) -> SuppressionActionResponse:
    """Suppress auto-healing for a specific entity.

    The entity will still be monitored, but healing attempts will be skipped.
    """
    try:
        service = get_service()

        logger.info(f"[{instance_id}] Suppression request for entity: {entity_id}")

        # Determine which instance to use
        if instance_id == "all":
            # For aggregate mode, require specific instance
            raise HTTPException(
                status_code=400,
                detail="Must specify a specific instance_id when suppressing healing",
            )

        # Verify instance exists
        if instance_id not in service.ha_clients:
            available = list(service.ha_clients.keys())
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {available}",
            )

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Find the entity
            stmt = select(Entity).where(
                Entity.instance_id == instance_id,
                Entity.entity_id == entity_id,
            )
            result = await session.execute(stmt)
            entity = result.scalar_one_or_none()

            if not entity:
                # Entity doesn't exist in DB yet - create it with suppression enabled
                # This allows users to preemptively suppress entities
                entity = Entity(
                    instance_id=instance_id,
                    entity_id=entity_id,
                    is_monitored=True,
                    healing_suppressed=True,
                )
                session.add(entity)
                logger.info(
                    f"[{instance_id}] Created entity record with healing suppressed: {entity_id}"
                )
            else:
                # Update existing entity
                entity.healing_suppressed = True
                logger.info(f"[{instance_id}] Healing suppressed for entity: {entity_id}")

            await session.commit()

            return SuppressionActionResponse(
                entity_id=entity_id,
                suppressed=True,
                message=f"Healing suppressed for {entity_id}",
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error suppressing healing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to suppress healing") from None


@router.delete("/healing/suppress/{entity_id:path}", response_model=SuppressionActionResponse)
async def unsuppress_healing(
    entity_id: str,
    instance_id: str = Query("default", description="Instance ID"),
) -> SuppressionActionResponse:
    """Remove healing suppression for a specific entity.

    Re-enables auto-healing for this entity.
    """
    try:
        service = get_service()

        logger.info(f"[{instance_id}] Unsuppression request for entity: {entity_id}")

        # Determine which instance to use
        if instance_id == "all":
            # For aggregate mode, require specific instance
            raise HTTPException(
                status_code=400,
                detail="Must specify a specific instance_id when unsuppressing healing",
            )

        # Verify instance exists
        if instance_id not in service.ha_clients:
            available = list(service.ha_clients.keys())
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {available}",
            )

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Find the entity
            stmt = select(Entity).where(
                Entity.instance_id == instance_id,
                Entity.entity_id == entity_id,
            )
            result = await session.execute(stmt)
            entity = result.scalar_one_or_none()

            if not entity:
                # Entity doesn't exist in DB - healing is already not suppressed
                logger.info(
                    f"[{instance_id}] Entity {entity_id} not in database, "
                    "healing already not suppressed"
                )
            else:
                # Update existing entity
                entity.healing_suppressed = False
                await session.commit()
                logger.info(f"[{instance_id}] Healing unsuppressed for entity: {entity_id}")

            return SuppressionActionResponse(
                entity_id=entity_id,
                suppressed=False,
                message=f"Healing enabled for {entity_id}",
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error unsuppressing healing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unsuppress healing") from None


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
    filter: str | None = Query(None, description="Filter by result: 'success' or 'failed'"),
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

            # Filter by success/failed if specified
            if filter == "success":
                stmt = stmt.where(HealingAction.success.is_(True))  # type: ignore[attr-defined]
            elif filter == "failed":
                stmt = stmt.where(HealingAction.success.is_(False))  # type: ignore[attr-defined]

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

        # Convert to response models with enhanced details
        actions = []
        async with service.database.async_session() as session:
            for action, integration_domain in rows:
                # Look up the trigger reason from the most recent HealthEvent for this entity
                # that occurred before or at the same time as the healing action
                trigger_reason = None
                try:
                    health_event_stmt = (
                        select(HealthEvent.event_type)
                        .where(
                            HealthEvent.entity_id == action.entity_id,
                            HealthEvent.instance_id == action.instance_id,
                            HealthEvent.timestamp <= action.timestamp,
                        )
                        .order_by(HealthEvent.timestamp.desc())
                        .limit(1)
                    )
                    health_result = await session.execute(health_event_stmt)
                    health_row = health_result.first()
                    if health_row:
                        trigger_reason = health_row[0]
                except Exception as e:
                    logger.debug(f"Could not fetch trigger reason: {e}")

                actions.append(
                    HealingActionResponse(
                        entity_id=action.entity_id,
                        integration=integration_domain or "unknown",
                        action_type=action.action,
                        success=action.success,
                        timestamp=action.timestamp,
                        message=(action.error if not action.success else "Success"),
                        instance_id=action.instance_id if len(instance_ids) > 1 else None,
                        trigger_reason=trigger_reason,
                        error_message=action.error if not action.success else None,
                        attempt_number=action.attempt_number,
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


@router.get("/healing/suppressed", response_model=SuppressedEntitiesResponse)
async def get_suppressed_entities(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
) -> SuppressedEntitiesResponse:
    """Get list of entities with suppressed healing.

    Returns entities where auto-healing has been disabled.
    """
    try:
        service = get_service()
        instance_ids = get_instance_ids(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Query entities with healing suppressed
            stmt = select(Entity).where(Entity.healing_suppressed.is_(True))

            if len(instance_ids) == 1:
                stmt = stmt.where(Entity.instance_id == instance_ids[0])
            else:
                stmt = stmt.where(Entity.instance_id.in_(instance_ids))

            stmt = stmt.order_by(Entity.entity_id)

            result = await session.execute(stmt)
            entities = result.scalars().all()

            suppressed_list = [
                SuppressedEntityResponse(
                    entity_id=entity.entity_id,
                    instance_id=entity.instance_id,
                    friendly_name=entity.friendly_name,
                    integration=entity.integration_id,
                    suppressed_since=entity.updated_at,
                )
                for entity in entities
            ]

        return SuppressedEntitiesResponse(
            entities=suppressed_list,
            total_count=len(suppressed_list),
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error getting suppressed entities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get suppressed entities") from None


@router.get("/healing/cascade/{cascade_id}", response_model=HealingCascadeResponse)
async def get_cascade_details(
    cascade_id: int = Path(..., description="Cascade execution ID"),
    instance_id: str = Query(..., description="Instance ID"),
) -> HealingCascadeResponse:
    """Get detailed information about a healing cascade execution.

    Retrieves complete cascade information including:
    - Which levels were attempted and their results
    - Entity-level healing actions
    - Device-level healing actions
    - Overall success and duration

    Args:
        cascade_id: Cascade execution ID
        instance_id: Instance identifier

    Returns:
        Detailed cascade execution information

    Raises:
        HTTPException: Cascade not found (404), instance not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        _validate_instance_id(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Fetch cascade execution
            stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.id == cascade_id,
                HealingCascadeExecution.instance_id == instance_id,
            )
            result = await session.execute(stmt)
            cascade = result.scalar_one_or_none()

            if not cascade:
                raise HTTPException(
                    status_code=404,
                    detail=f"Cascade execution {cascade_id} not found for instance {instance_id}",
                )

            # Fetch entity and device actions using helper function
            entity_actions, device_actions = await _fetch_cascade_actions(
                session, instance_id, cascade.automation_id, cascade.execution_id
            )

            # Build response using helper function
            return _build_cascade_response(cascade, entity_actions, device_actions)

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving cascade {cascade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve cascade details") from None


@router.get("/healing/cascades", response_model=list[HealingCascadeResponse])
async def list_cascades(
    instance_id: str = Query("all", description="Instance ID or 'all' for all instances"),
    limit: int = Query(20, ge=1, le=100, description="Maximum cascades to return"),
    plan_suggested_only: bool = Query(
        False, description="Only return cascades where AI plan generation was suggested"
    ),
) -> list[HealingCascadeResponse]:
    """List recent healing cascade executions.

    Returns recent cascade executions with their routing strategy and outcome.
    Use plan_suggested_only=true to find cascades that had no matching plan.

    Args:
        instance_id: Instance ID or 'all' for aggregate
        limit: Maximum results to return
        plan_suggested_only: If True, only return cascades where plan_generation_suggested is True

    Returns:
        List of cascade execution records

    Raises:
        HTTPException: Database not available (503) or error (500)
    """
    from sqlalchemy import desc, select

    service = get_service()
    if not service.database:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with service.database.async_session() as session:
            stmt = select(HealingCascadeExecution).order_by(
                desc(HealingCascadeExecution.created_at)
            )

            if instance_id != "all":
                stmt = stmt.where(HealingCascadeExecution.instance_id == instance_id)

            if plan_suggested_only:
                stmt = stmt.where(HealingCascadeExecution.plan_generation_suggested.is_(True))

            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            cascades = result.scalars().all()

            return [
                HealingCascadeResponse(
                    id=c.id,
                    instance_id=c.instance_id,
                    automation_id=c.automation_id,
                    execution_id=c.execution_id,
                    trigger_type=c.trigger_type,
                    routing_strategy=c.routing_strategy,
                    entity_level_attempted=c.entity_level_attempted,
                    entity_level_success=c.entity_level_success,
                    device_level_attempted=c.device_level_attempted,
                    device_level_success=c.device_level_success,
                    integration_level_attempted=c.integration_level_attempted,
                    integration_level_success=c.integration_level_success,
                    final_success=c.final_success,
                    total_duration_seconds=c.total_duration_seconds,
                    created_at=c.created_at,
                    completed_at=c.completed_at,
                    plan_generation_suggested=getattr(c, "plan_generation_suggested", False),
                    entity_actions=[],  # Not fetched for list view
                    device_actions=[],
                )
                for c in cascades
            ]

    except Exception as e:
        logger.error(f"Failed to fetch cascade list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch cascades: {e}") from e


@router.get("/healing/statistics", response_model=HealingStatisticsResponse)
async def get_healing_statistics(
    instance_id: str = Query(..., description="Instance ID"),
    start_date: datetime | None = Query(None, description="Start date for statistics (UTC)"),
    end_date: datetime | None = Query(None, description="End date for statistics (UTC)"),
) -> HealingStatisticsResponse:
    """Get healing statistics aggregated by level.

    Returns success rates and average durations for each healing level
    (entity, device, integration).

    Args:
        instance_id: Instance identifier
        start_date: Optional start date (defaults to 7 days ago)
        end_date: Optional end date (defaults to now)

    Returns:
        Healing statistics broken down by level

    Raises:
        HTTPException: Invalid date range (400), instance not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        _validate_instance_id(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Default time range: last 7 days
        if not end_date:
            end_date = datetime.now(UTC)
        if not start_date:
            start_date = end_date - timedelta(days=7)

        # Validate date range
        if start_date >= end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be before end_date",
            )

        async with service.database.async_session() as session:
            from sqlalchemy import Integer, case, cast, select

            # Calculate statistics per level using database aggregation
            stats_by_level: list[HealingStatisticsByLevel] = []

            for level in ["entity", "device", "integration"]:
                level_attempted_field = getattr(HealingCascadeExecution, f"{level}_level_attempted")
                level_success_field = getattr(HealingCascadeExecution, f"{level}_level_success")

                # Aggregate query for this level
                stats_stmt = select(
                    func.count(HealingCascadeExecution.id).label("total_attempts"),
                    func.sum(cast(level_success_field, Integer)).label("successful_attempts"),
                    func.avg(
                        case(
                            (
                                level_attempted_field.is_(True),
                                HealingCascadeExecution.total_duration_seconds,
                            ),
                            else_=None,
                        )
                    ).label("average_duration"),
                ).where(
                    HealingCascadeExecution.instance_id == instance_id,
                    HealingCascadeExecution.created_at >= start_date,
                    HealingCascadeExecution.created_at <= end_date,
                    level_attempted_field.is_(True),
                )

                stats_result = await session.execute(stats_stmt)
                stats = stats_result.first()

                if not stats:
                    # No data found - all zeros
                    stats_by_level.append(
                        HealingStatisticsByLevel(
                            level=level,  # type: ignore[arg-type]
                            total_attempts=0,
                            successful_attempts=0,
                            failed_attempts=0,
                            success_rate=0.0,
                            average_duration_seconds=None,
                        )
                    )
                    continue

                total_attempts = (
                    int(stats.total_attempts) if stats.total_attempts is not None else 0
                )
                successful_attempts = (
                    int(stats.successful_attempts) if stats.successful_attempts is not None else 0
                )
                failed_attempts = total_attempts - successful_attempts
                average_duration = (
                    float(stats.average_duration) if stats.average_duration is not None else None
                )

                # Calculate success rate using helper function
                success_rate = _calculate_success_rate(successful_attempts, total_attempts)

                stats_by_level.append(
                    HealingStatisticsByLevel(
                        level=level,  # type: ignore[arg-type]
                        total_attempts=total_attempts,
                        successful_attempts=successful_attempts,
                        failed_attempts=failed_attempts,
                        success_rate=success_rate,
                        average_duration_seconds=average_duration,
                    )
                )

            # Overall cascade statistics using database aggregation
            overall_stmt = select(
                func.count(HealingCascadeExecution.id).label("total_cascades"),
                func.sum(cast(HealingCascadeExecution.final_success, Integer)).label(
                    "successful_cascades"
                ),
            ).where(
                HealingCascadeExecution.instance_id == instance_id,
                HealingCascadeExecution.created_at >= start_date,
                HealingCascadeExecution.created_at <= end_date,
            )
            overall_result = await session.execute(overall_stmt)
            overall_stats = overall_result.first()

            total_cascades = (
                int(overall_stats.total_cascades)
                if overall_stats and overall_stats.total_cascades is not None
                else 0
            )
            successful_cascades_count = (
                int(overall_stats.successful_cascades)
                if overall_stats and overall_stats.successful_cascades is not None
                else 0
            )

            return HealingStatisticsResponse(
                instance_id=instance_id,
                time_range={"start_date": start_date, "end_date": end_date},
                statistics_by_level=stats_by_level,
                total_cascades=total_cascades,
                successful_cascades=successful_cascades_count,
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving healing statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve healing statistics"
        ) from None


@router.get("/automations/{automation_id}/health", response_model=AutomationHealthResponse)
async def get_automation_health(
    automation_id: str = Path(..., description="Automation ID"),
    instance_id: str = Query(..., description="Instance ID"),
) -> AutomationHealthResponse:
    """Get health and validation status for an automation.

    Returns consecutive success/failure counts, validation status,
    and reliability score.

    Args:
        automation_id: Automation ID
        instance_id: Instance identifier

    Returns:
        Automation health status and statistics

    Raises:
        HTTPException: Automation not found (404), instance not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        _validate_instance_id(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Fetch automation health status
            stmt = select(AutomationHealthStatus).where(
                AutomationHealthStatus.instance_id == instance_id,
                AutomationHealthStatus.automation_id == automation_id,
            )
            result = await session.execute(stmt)
            health_status = result.scalar_one_or_none()

            if not health_status:
                raise HTTPException(
                    status_code=404,
                    detail=f"Automation {automation_id} not found for instance {instance_id}",
                )

            # Calculate reliability score using helper function
            total_executions = health_status.total_executions
            total_successes = health_status.total_successes

            reliability_score = _calculate_success_rate(total_successes, total_executions)

            # Get last execution timestamps (from AutomationExecution table)
            from ha_boss.core.database import AutomationExecution

            # Last execution
            last_exec_stmt = (
                select(AutomationExecution.executed_at)
                .where(
                    AutomationExecution.instance_id == instance_id,
                    AutomationExecution.automation_id == automation_id,
                )
                .order_by(AutomationExecution.executed_at.desc())
                .limit(1)
            )
            last_exec_result = await session.execute(last_exec_stmt)
            last_execution_at = last_exec_result.scalar_one_or_none()

            # Last successful execution
            last_success_stmt = (
                select(AutomationExecution.executed_at)
                .where(
                    AutomationExecution.instance_id == instance_id,
                    AutomationExecution.automation_id == automation_id,
                    AutomationExecution.success.is_(True),
                )
                .order_by(AutomationExecution.executed_at.desc())
                .limit(1)
            )
            last_success_result = await session.execute(last_success_stmt)
            last_success_at = last_success_result.scalar_one_or_none()

            # Last failed execution
            last_failure_stmt = (
                select(AutomationExecution.executed_at)
                .where(
                    AutomationExecution.instance_id == instance_id,
                    AutomationExecution.automation_id == automation_id,
                    AutomationExecution.success.is_(False),
                )
                .order_by(AutomationExecution.executed_at.desc())
                .limit(1)
            )
            last_failure_result = await session.execute(last_failure_stmt)
            last_failure_at = last_failure_result.scalar_one_or_none()

            return AutomationHealthResponse(
                instance_id=instance_id,
                automation_id=automation_id,
                consecutive_successes=health_status.consecutive_successes,
                consecutive_failures=health_status.consecutive_failures,
                is_validated_healthy=health_status.is_validated_healthy,
                total_executions=total_executions,
                total_successes=total_successes,
                total_failures=health_status.total_failures,
                reliability_score=reliability_score,
                last_execution_at=last_execution_at,
                last_success_at=last_success_at,
                last_failure_at=last_failure_at,
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error retrieving automation health for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve automation health"
        ) from None


@router.post("/healing/cascade/{cascade_id}/retry", response_model=HealingCascadeResponse)
async def retry_failed_cascade(
    cascade_id: int = Path(..., description="Cascade execution ID to retry"),
    instance_id: str = Query(..., description="Instance ID"),
) -> HealingCascadeResponse:
    """Manually retry a failed healing cascade.

    Loads the original cascade context and triggers a new cascade execution
    with the same automation and failed entities.

    Args:
        cascade_id: Original cascade execution ID
        instance_id: Instance identifier

    Returns:
        New cascade execution information

    Raises:
        HTTPException: Cascade not found (404), already succeeded (400),
                      instance not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        _validate_instance_id(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Fetch original cascade
        async with service.database.async_session() as session:
            from sqlalchemy import select

            stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.id == cascade_id,
                HealingCascadeExecution.instance_id == instance_id,
            )
            result = await session.execute(stmt)
            original_cascade = result.scalar_one_or_none()

            if not original_cascade:
                raise HTTPException(
                    status_code=404,
                    detail=f"Cascade execution {cascade_id} not found for instance {instance_id}",
                )

            # Check if cascade already succeeded
            if original_cascade.final_success is True:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cascade {cascade_id} already succeeded, cannot retry",
                )

        # Get cascade orchestrator for this instance
        from ha_boss.healing.cascade_orchestrator import HealingContext

        cascade_orchestrator = service.cascade_orchestrators.get(instance_id)
        if not cascade_orchestrator:
            raise HTTPException(
                status_code=503,
                detail=f"Cascade orchestrator not available for instance {instance_id}",
            )

        # Build healing context from original cascade
        # Get timeout from config instead of hardcoding
        timeout_seconds = service.config.healing.cascade_timeout_seconds

        context = HealingContext(
            instance_id=instance_id,
            automation_id=original_cascade.automation_id,
            execution_id=original_cascade.execution_id,
            trigger_type=original_cascade.trigger_type,
            failed_entities=original_cascade.failed_entities or [],
            timeout_seconds=timeout_seconds,
        )

        # Execute new cascade
        logger.info(
            f"[{instance_id}] Retrying cascade {cascade_id} for automation {original_cascade.automation_id}"
        )
        new_cascade_id = await cascade_orchestrator.execute_cascade(context)

        # Fetch the new cascade execution record using the returned ID
        async with service.database.async_session() as session:
            from sqlalchemy import select

            new_cascade_stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.id == new_cascade_id,
                HealingCascadeExecution.instance_id == instance_id,
            )
            new_cascade_result = await session.execute(new_cascade_stmt)
            new_cascade = new_cascade_result.scalar_one_or_none()

            if not new_cascade:
                raise HTTPException(
                    status_code=500,
                    detail="New cascade execution record not found after retry",
                )

            # Fetch entity and device actions using helper function
            entity_actions, device_actions = await _fetch_cascade_actions(
                session, instance_id, new_cascade.automation_id, new_cascade.execution_id
            )

            # Build response using helper function
            return _build_cascade_response(new_cascade, entity_actions, device_actions)

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrying cascade {cascade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retry cascade") from None


@router.get("/healing/routing-metrics")
async def get_routing_metrics(
    instance_id: str = Query("default", description="Instance identifier"),
) -> dict[str, Any]:
    """Get pattern coverage and routing effectiveness metrics.

    Returns metrics about how well the intelligent routing and pattern
    learning systems are performing.
    """
    try:
        service = get_service()

        if instance_id not in service.cascade_orchestrators:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found or not initialized",
            )

        metrics = await service.cascade_orchestrators[instance_id].get_routing_metrics(
            instance_id=instance_id,
        )

        return metrics

    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error getting routing metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get routing metrics") from None
