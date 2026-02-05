"""Healing action endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, Query

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
                stmt = stmt.where(HealingAction.success == True)  # noqa: E712
            elif filter == "failed":
                stmt = stmt.where(HealingAction.success == False)  # noqa: E712

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
            stmt = select(Entity).where(Entity.healing_suppressed == True)  # noqa: E712

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
        HTTPException: Cascade not found (404) or service error (500)
    """
    try:
        service = get_service()

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

            # Fetch entity-level actions for this cascade
            entity_actions_stmt = select(EntityHealingAction).where(
                EntityHealingAction.instance_id == instance_id,
                EntityHealingAction.automation_id == cascade.automation_id,
                EntityHealingAction.execution_id == cascade.execution_id,
            )
            entity_actions_result = await session.execute(entity_actions_stmt)
            entity_actions = entity_actions_result.scalars().all()

            # Fetch device-level actions for this cascade
            device_actions_stmt = select(DeviceHealingAction).where(
                DeviceHealingAction.instance_id == instance_id,
                DeviceHealingAction.automation_id == cascade.automation_id,
                DeviceHealingAction.execution_id == cascade.execution_id,
            )
            device_actions_result = await session.execute(device_actions_stmt)
            device_actions = device_actions_result.scalars().all()

            # Build response
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

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving cascade {cascade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve cascade details") from None


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
        HTTPException: Service error (500)
    """
    try:
        service = get_service()

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Default time range: last 7 days
        if not end_date:
            end_date = datetime.now(UTC)
        if not start_date:
            start_date = end_date - timedelta(days=7)

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Get all cascades in time range
            cascades_stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.instance_id == instance_id,
                HealingCascadeExecution.created_at >= start_date,
                HealingCascadeExecution.created_at <= end_date,
            )
            cascades_result = await session.execute(cascades_stmt)
            cascades = cascades_result.scalars().all()

            # Calculate statistics per level
            stats_by_level: list[HealingStatisticsByLevel] = []

            for level in ["entity", "device", "integration"]:
                level_attempted_field = f"{level}_level_attempted"
                level_success_field = f"{level}_level_success"

                attempted_cascades = [
                    c for c in cascades if getattr(c, level_attempted_field, False)
                ]
                total_attempts = len(attempted_cascades)

                if total_attempts == 0:
                    # No attempts at this level
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

                successful_cascades = [
                    c for c in attempted_cascades if getattr(c, level_success_field, False) is True
                ]
                successful_attempts = len(successful_cascades)
                failed_attempts = total_attempts - successful_attempts

                # Calculate success rate
                success_rate = (
                    (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0.0
                )

                # Calculate average duration (only for cascades with duration)
                durations = [
                    c.total_duration_seconds
                    for c in attempted_cascades
                    if c.total_duration_seconds is not None
                ]
                average_duration = sum(durations) / len(durations) if durations else None

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

            # Overall cascade statistics
            total_cascades = len(cascades)
            successful_cascades = [c for c in cascades if c.final_success is True]
            successful_cascades_count = len(successful_cascades)

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
        HTTPException: Automation not found (404) or service error (500)
    """
    try:
        service = get_service()

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

            # Calculate reliability score
            total_executions = health_status.total_executions
            total_successes = health_status.total_successes

            reliability_score = (
                (total_successes / total_executions * 100) if total_executions > 0 else 0.0
            )

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
                    AutomationExecution.success == True,  # noqa: E712
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
                    AutomationExecution.success == False,  # noqa: E712
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
        HTTPException: Cascade not found (404), already succeeded (400), or service error (500)
    """
    try:
        service = get_service()

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
        context = HealingContext(
            instance_id=instance_id,
            automation_id=original_cascade.automation_id,
            execution_id=original_cascade.execution_id,
            trigger_type=original_cascade.trigger_type,
            failed_entities=original_cascade.failed_entities or [],
            timeout_seconds=120.0,
        )

        # Execute new cascade
        logger.info(
            f"[{instance_id}] Retrying cascade {cascade_id} for automation {original_cascade.automation_id}"
        )
        await cascade_orchestrator.execute_cascade(context)

        # Fetch the new cascade execution record
        async with service.database.async_session() as session:
            # Get the most recent cascade for this automation
            new_cascade_stmt = (
                select(HealingCascadeExecution)
                .where(
                    HealingCascadeExecution.instance_id == instance_id,
                    HealingCascadeExecution.automation_id == original_cascade.automation_id,
                )
                .order_by(HealingCascadeExecution.created_at.desc())
                .limit(1)
            )
            new_cascade_result = await session.execute(new_cascade_stmt)
            new_cascade = new_cascade_result.scalar_one_or_none()

            if not new_cascade:
                raise HTTPException(
                    status_code=500,
                    detail="New cascade execution record not found after retry",
                )

            # Fetch entity-level actions for new cascade
            entity_actions_stmt = select(EntityHealingAction).where(
                EntityHealingAction.instance_id == instance_id,
                EntityHealingAction.automation_id == new_cascade.automation_id,
                EntityHealingAction.execution_id == new_cascade.execution_id,
            )
            entity_actions_result = await session.execute(entity_actions_stmt)
            entity_actions = entity_actions_result.scalars().all()

            # Fetch device-level actions for new cascade
            device_actions_stmt = select(DeviceHealingAction).where(
                DeviceHealingAction.instance_id == instance_id,
                DeviceHealingAction.automation_id == new_cascade.automation_id,
                DeviceHealingAction.execution_id == new_cascade.execution_id,
            )
            device_actions_result = await session.execute(device_actions_stmt)
            device_actions = device_actions_result.scalars().all()

            # Build response
            return HealingCascadeResponse(
                id=new_cascade.id,
                instance_id=new_cascade.instance_id,
                automation_id=new_cascade.automation_id,
                execution_id=new_cascade.execution_id,
                trigger_type=new_cascade.trigger_type,
                routing_strategy=new_cascade.routing_strategy,
                entity_level_attempted=new_cascade.entity_level_attempted,
                entity_level_success=new_cascade.entity_level_success,
                device_level_attempted=new_cascade.device_level_attempted,
                device_level_success=new_cascade.device_level_success,
                integration_level_attempted=new_cascade.integration_level_attempted,
                integration_level_success=new_cascade.integration_level_success,
                final_success=new_cascade.final_success,
                total_duration_seconds=new_cascade.total_duration_seconds,
                created_at=new_cascade.created_at,
                completed_at=new_cascade.completed_at,
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

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrying cascade {cascade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retry cascade") from None
