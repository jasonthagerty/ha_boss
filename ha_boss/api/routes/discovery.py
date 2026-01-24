"""Entity discovery endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    AutomationDetailResponse,
    AutomationSummary,
    DiscoveryRefreshRequest,
    DiscoveryRefreshResponse,
    DiscoveryStatsResponse,
    EntityAutomationsResponse,
    EntityAutomationUsage,
)
from ha_boss.api.utils.instance_helpers import get_instance_ids, is_aggregate_mode
from ha_boss.core.database import (
    Automation,
    AutomationEntity,
    DiscoveryRefresh,
    Scene,
    SceneEntity,
    Script,
    ScriptEntity,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/discovery/refresh", response_model=DiscoveryRefreshResponse)
async def trigger_discovery_refresh(
    request: DiscoveryRefreshRequest = DiscoveryRefreshRequest(),
    instance_id: str = Query("default", description="Instance identifier"),
) -> DiscoveryRefreshResponse:
    """Trigger manual entity discovery refresh for a specific instance.

    Scans all enabled automations, scenes, and scripts to discover
    entities being used. Updates the monitored entity set.

    Args:
        request: Refresh request with optional trigger source
        instance_id: Instance identifier (default: "default")

    Returns:
        Discovery refresh results with statistics for the specified instance

    Raises:
        HTTPException: Instance not found (404), auto-discovery disabled (400), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists (use ha_clients as authoritative source)
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Get entity discovery for this instance
        entity_discovery = service.entity_discoveries.get(instance_id)
        if not entity_discovery:
            raise HTTPException(
                status_code=503, detail="Entity discovery not initialized"
            ) from None

        # Record start time
        start_time = datetime.now(UTC)

        # Trigger discovery refresh
        stats = await entity_discovery.discover_and_refresh(
            trigger_type="manual", trigger_source=request.trigger_source
        )

        # Calculate duration
        duration = (datetime.now(UTC) - start_time).total_seconds()

        return DiscoveryRefreshResponse(
            success=True,
            automations_found=stats["automations_found"],
            scenes_found=stats["scenes_found"],
            scripts_found=stats["scripts_found"],
            entities_discovered=stats["entities_discovered"],
            duration_seconds=duration,
            timestamp=start_time,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error during discovery refresh: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Discovery refresh failed") from None


@router.get("/discovery/stats", response_model=DiscoveryStatsResponse)
async def get_discovery_stats(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
) -> DiscoveryStatsResponse:
    """Get current discovery statistics.

    Returns statistics about discovered automations, scenes, scripts,
    and entities, along with refresh scheduling information.

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")

    When instance_id is 'all', returns aggregated statistics across all instances.

    Returns:
        Discovery statistics

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Get list of instances to query
        instance_ids = get_instance_ids(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Aggregate counts across all requested instances
        total_automations = 0
        enabled_automations = 0
        total_scenes = 0
        total_scripts = 0
        total_entities = 0
        monitored_count = 0
        last_refresh_record = None

        async with service.database.async_session() as session:
            for inst_id in instance_ids:
                # Count automations
                total_automations_result = await session.execute(
                    select(func.count(Automation.entity_id)).where(
                        Automation.instance_id == inst_id
                    )
                )
                total_automations += total_automations_result.scalar() or 0

                enabled_automations_result = await session.execute(
                    select(func.count(Automation.entity_id)).where(
                        Automation.state == "on", Automation.instance_id == inst_id
                    )
                )
                enabled_automations += enabled_automations_result.scalar() or 0

                # Count scenes
                total_scenes_result = await session.execute(
                    select(func.count(Scene.entity_id)).where(Scene.instance_id == inst_id)
                )
                total_scenes += total_scenes_result.scalar() or 0

                # Count scripts
                total_scripts_result = await session.execute(
                    select(func.count(Script.entity_id)).where(Script.instance_id == inst_id)
                )
                total_scripts += total_scripts_result.scalar() or 0

                # Count unique entities from junction tables
                automation_entities = await session.execute(
                    select(func.count(func.distinct(AutomationEntity.entity_id))).where(
                        AutomationEntity.instance_id == inst_id
                    )
                )
                scene_entities = await session.execute(
                    select(func.count(func.distinct(SceneEntity.entity_id))).where(
                        SceneEntity.instance_id == inst_id
                    )
                )
                script_entities = await session.execute(
                    select(func.count(func.distinct(ScriptEntity.entity_id))).where(
                        ScriptEntity.instance_id == inst_id
                    )
                )

                # Total unique entities (rough estimate - may have overlap)
                total_entities += (
                    (automation_entities.scalar() or 0)
                    + (scene_entities.scalar() or 0)
                    + (script_entities.scalar() or 0)
                )

                # Get last refresh timestamp (keep most recent across instances)
                refresh_result = await session.execute(
                    select(DiscoveryRefresh.timestamp)
                    .where(DiscoveryRefresh.instance_id == inst_id)
                    .order_by(DiscoveryRefresh.timestamp.desc())
                    .limit(1)
                )
                inst_last_refresh = refresh_result.scalar_one_or_none()
                if inst_last_refresh:
                    if not last_refresh_record or inst_last_refresh > last_refresh_record:
                        last_refresh_record = inst_last_refresh

                # Get monitored entity count from state tracker
                state_tracker = service.state_trackers.get(inst_id)
                if state_tracker:
                    all_states = await state_tracker.get_all_states()
                    monitored_count += len(all_states)

        # Calculate next refresh time
        next_refresh = None
        refresh_interval = service.config.monitoring.auto_discovery.refresh_interval_seconds
        if last_refresh_record and refresh_interval > 0:
            next_refresh = last_refresh_record + timedelta(seconds=refresh_interval)

        return DiscoveryStatsResponse(
            auto_discovery_enabled=service.config.monitoring.auto_discovery.enabled,
            total_automations=total_automations,
            enabled_automations=enabled_automations,
            total_scenes=total_scenes,
            total_scripts=total_scripts,
            total_entities=total_entities,
            monitored_entities=monitored_count,
            last_refresh=last_refresh_record,
            next_refresh=next_refresh,
            refresh_interval_seconds=refresh_interval,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error getting discovery stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get discovery stats") from None


@router.get("/automations", response_model=list[AutomationSummary])
async def list_automations(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
    state: str | None = Query(None, description="Filter by state (on/off)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum automations to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[AutomationSummary]:
    """List all discovered automations.

    Returns a paginated list of automations discovered by the auto-discovery
    system, with optional filtering by state.

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")
        state: Optional state filter (on/off)
        limit: Maximum number of automations to return (1-1000)
        offset: Pagination offset

    When instance_id is 'all', returns automations from all instances.

    Returns:
        List of automation summaries

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Get list of instances to query
        instance_ids = get_instance_ids(service, instance_id)
        aggregate = is_aggregate_mode(instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            # Build query
            query = select(Automation)

            # Filter by instance(s)
            if len(instance_ids) == 1:
                query = query.where(Automation.instance_id == instance_ids[0])
            else:
                query = query.where(Automation.instance_id.in_(instance_ids))

            # Apply state filter
            if state:
                query = query.where(Automation.state == state)

            # Apply ordering and pagination
            query = (
                query.order_by(Automation.instance_id, Automation.friendly_name)
                .limit(limit)
                .offset(offset)
            )

            # Execute query
            result = await session.execute(query)
            automations = result.scalars().all()

            # Optimize: Get all entity counts in single query (avoid N+1)
            entity_counts: dict[tuple[str, str], int] = {}
            if automations:
                automation_ids = [a.entity_id for a in automations]
                entity_counts_query = select(
                    AutomationEntity.instance_id,
                    AutomationEntity.automation_id,
                    func.count(func.distinct(AutomationEntity.entity_id)).label("entity_count"),
                ).where(AutomationEntity.automation_id.in_(automation_ids))

                # Filter by instance(s)
                if len(instance_ids) == 1:
                    entity_counts_query = entity_counts_query.where(
                        AutomationEntity.instance_id == instance_ids[0]
                    )
                else:
                    entity_counts_query = entity_counts_query.where(
                        AutomationEntity.instance_id.in_(instance_ids)
                    )

                entity_counts_query = entity_counts_query.group_by(
                    AutomationEntity.instance_id, AutomationEntity.automation_id
                )

                entity_counts_result = await session.execute(entity_counts_query)
                entity_counts = {
                    (row.instance_id, row.automation_id): row.entity_count
                    for row in entity_counts_result
                }

            # Build response with pre-fetched entity counts
            response = []
            for automation in automations:
                entity_count = entity_counts.get((automation.instance_id, automation.entity_id), 0)

                response.append(
                    AutomationSummary(
                        entity_id=automation.entity_id,
                        friendly_name=automation.friendly_name,
                        state=automation.state,
                        entity_count=entity_count,
                        discovered_at=automation.discovered_at,
                        instance_id=automation.instance_id if aggregate else None,
                    )
                )

            return response

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error listing automations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list automations") from None


@router.get("/automations/{automation_id:path}", response_model=AutomationDetailResponse)
async def get_automation_details(
    automation_id: str, instance_id: str = Query("default", description="Instance identifier")
) -> AutomationDetailResponse:
    """Get detailed information about a specific automation for a specific instance.

    Returns full automation details including all entities grouped by
    relationship type (trigger/condition/action).

    Args:
        automation_id: Automation entity ID (e.g., 'automation.bedroom_lights')
        instance_id: Instance identifier (default: "default")

    Returns:
        Detailed automation information with entities for the specified instance

    Raises:
        HTTPException: Instance or automation not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.state_trackers:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.state_trackers.keys())}",
            ) from None

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            # Get automation for this instance
            result = await session.execute(
                select(Automation).where(
                    Automation.entity_id == automation_id, Automation.instance_id == instance_id
                )
            )
            automation = result.scalar_one_or_none()

            if not automation:
                raise HTTPException(
                    status_code=404,
                    detail=f"Automation '{automation_id}' not found in instance '{instance_id}'",
                ) from None

            # Get entities grouped by relationship type for this instance
            entities_result = await session.execute(
                select(AutomationEntity).where(
                    AutomationEntity.automation_id == automation_id,
                    AutomationEntity.instance_id == instance_id,
                )
            )
            entity_records = entities_result.scalars().all()

            # Group entities by relationship type
            entities_by_type: dict[str, list[str]] = {
                "trigger": [],
                "condition": [],
                "action": [],
            }

            for record in entity_records:
                rel_type = record.relationship_type
                if rel_type in entities_by_type:
                    entities_by_type[rel_type].append(record.entity_id)

            # Count total unique entities
            unique_entities = set()
            for entities_list in entities_by_type.values():
                unique_entities.update(entities_list)

            return AutomationDetailResponse(
                entity_id=automation.entity_id,
                friendly_name=automation.friendly_name,
                state=automation.state,
                mode=automation.mode,
                discovered_at=automation.discovered_at,
                last_seen=automation.last_seen,
                entities=entities_by_type,
                entity_count=len(unique_entities),
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error getting automation details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get automation details") from None


@router.get("/entities/{entity_id:path}/usage", response_model=EntityAutomationsResponse)
async def get_entity_usage(
    entity_id: str, instance_id: str = Query("default", description="Instance identifier")
) -> EntityAutomationsResponse:
    """Get automation/scene/script usage for a specific entity in a specific instance.

    Returns all automations, scenes, and scripts that use this entity,
    enabling reverse-lookup queries.

    Args:
        entity_id: Entity ID (e.g., 'sensor.temperature')
        instance_id: Instance identifier (default: "default")

    Returns:
        Entity usage information across automations/scenes/scripts for the specified instance

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.state_trackers:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.state_trackers.keys())}",
            ) from None

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        async with service.database.async_session() as session:
            # Get automations using this entity in this instance
            automation_results = await session.execute(
                select(AutomationEntity, Automation)
                .join(Automation, AutomationEntity.automation_id == Automation.entity_id)
                .where(
                    AutomationEntity.entity_id == entity_id,
                    AutomationEntity.instance_id == instance_id,
                )
            )
            automation_records = automation_results.all()

            automations = [
                EntityAutomationUsage(
                    id=record.Automation.entity_id,
                    friendly_name=record.Automation.friendly_name,
                    type="automation",
                    relationship_type=record.AutomationEntity.relationship_type,
                )
                for record in automation_records
            ]

            # Get scenes using this entity in this instance
            scene_results = await session.execute(
                select(SceneEntity, Scene)
                .join(Scene, SceneEntity.scene_id == Scene.entity_id)
                .where(SceneEntity.entity_id == entity_id, SceneEntity.instance_id == instance_id)
            )
            scene_records = scene_results.all()

            scenes = [
                EntityAutomationUsage(
                    id=record.Scene.entity_id,
                    friendly_name=record.Scene.friendly_name,
                    type="scene",
                    relationship_type=None,
                )
                for record in scene_records
            ]

            # Get scripts using this entity in this instance
            script_results = await session.execute(
                select(ScriptEntity, Script)
                .join(Script, ScriptEntity.script_id == Script.entity_id)
                .where(ScriptEntity.entity_id == entity_id, ScriptEntity.instance_id == instance_id)
            )
            script_records = script_results.all()

            scripts = [
                EntityAutomationUsage(
                    id=record.Script.entity_id,
                    friendly_name=record.Script.friendly_name,
                    type="script",
                    relationship_type=None,
                )
                for record in script_records
            ]

            return EntityAutomationsResponse(
                entity_id=entity_id,
                automations=automations,
                scenes=scenes,
                scripts=scripts,
                total_usage=len(automations) + len(scenes) + len(scripts),
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error getting entity usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get entity usage") from None
