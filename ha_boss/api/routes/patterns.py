"""Pattern analysis and reliability endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    FailureEventResponse,
    IntegrationReliabilityResponse,
    WeeklySummaryResponse,
)
from ha_boss.api.utils.instance_helpers import get_instance_ids

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/patterns/reliability", response_model=list[IntegrationReliabilityResponse])
async def get_reliability_stats(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
) -> list[IntegrationReliabilityResponse]:
    """Get integration reliability statistics.

    Returns reliability metrics for all integrations including:
    - Total entities per integration
    - Current unavailable entity count
    - Historical failure and success counts
    - Reliability percentage
    - Last failure timestamp

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")

    When instance_id is 'all', returns aggregated reliability statistics
    across all instances.

    Returns:
        List of integration reliability statistics

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Get list of instances to query
        instance_ids = get_instance_ids(service, instance_id)

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Aggregate reliability stats across all requested instances
        aggregated_stats: dict[str, dict] = {}

        for inst_id in instance_ids:
            pattern_collector = service.pattern_collectors.get(inst_id)

            if pattern_collector and hasattr(pattern_collector, "analyzer"):
                analyzer = pattern_collector.analyzer
                stats = await analyzer.get_integration_reliability(instance_id=inst_id)

                # Merge stats (aggregate by integration name)
                for integration, data in stats.items():
                    if integration not in aggregated_stats:
                        aggregated_stats[integration] = {
                            "total_entities": 0,
                            "unavailable_count": 0,
                            "failure_count": 0,
                            "success_count": 0,
                            "last_failure": None,
                        }

                    agg = aggregated_stats[integration]
                    agg["total_entities"] += data.get("total_entities", 0)
                    agg["unavailable_count"] += data.get("unavailable_count", 0)
                    agg["failure_count"] += data.get("failure_count", 0)
                    agg["success_count"] += data.get("success_count", 0)

                    # Keep most recent failure
                    new_failure = data.get("last_failure")
                    if new_failure:
                        if not agg["last_failure"] or new_failure > agg["last_failure"]:
                            agg["last_failure"] = new_failure

        # Convert to response models and calculate reliability percentages
        reliability_list = []
        for integration, data in aggregated_stats.items():
            total = data["failure_count"] + data["success_count"]
            reliability_percent = (data["success_count"] / total * 100) if total > 0 else 100.0
            reliability_list.append(
                IntegrationReliabilityResponse(
                    integration=integration,
                    total_entities=data["total_entities"],
                    unavailable_count=data["unavailable_count"],
                    failure_count=data["failure_count"],
                    success_count=data["success_count"],
                    reliability_percent=reliability_percent,
                    last_failure=data["last_failure"],
                )
            )

        return reliability_list

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving reliability stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve reliability statistics"
        ) from None


@router.get("/patterns/failures", response_model=list[FailureEventResponse])
async def get_failure_events(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
    limit: int = Query(50, ge=1, le=500, description="Maximum failures to return"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
) -> list[FailureEventResponse]:
    """Get failure event timeline.

    Returns a list of recent failure events including:
    - Entity and integration information
    - Failure timestamps
    - Resolution status and timestamps

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")
        limit: Maximum number of failures to return (1-500)
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    When instance_id is 'all', returns failure events from all instances.

    Returns:
        List of failure events

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

        # Query database for failure events
        async with service.database.async_session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import HealthEvent

            # Query failure events (SQLAlchemy dynamic attributes)
            stmt = (
                select(HealthEvent)
                .where(HealthEvent.timestamp >= start_time)
                .where(HealthEvent.timestamp <= end_time)
            )

            # Filter by instance(s)
            if len(instance_ids) == 1:
                stmt = stmt.where(HealthEvent.instance_id == instance_ids[0])
            else:
                stmt = stmt.where(HealthEvent.instance_id.in_(instance_ids))

            stmt = stmt.order_by(HealthEvent.timestamp.desc()).limit(limit)

            result = await session.execute(stmt)
            events = result.scalars().all()

        # Convert to response models
        failures = []
        for event in events:
            failures.append(
                FailureEventResponse(
                    id=event.id,
                    entity_id=event.entity_id,
                    integration="unknown",  # Not available in current schema
                    state=event.event_type,  # Use event_type as state
                    timestamp=event.timestamp,
                    resolved=False,  # Not tracked in current schema
                    resolution_time=None,
                    instance_id=event.instance_id if len(instance_ids) > 1 else None,
                )
            )

        return failures

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error retrieving failure events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve failure events") from None


@router.get("/patterns/summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    instance_id: str = Query("all", description="Instance ID or 'all' for aggregate"),
    days: int = Query(7, ge=1, le=30, description="Days to summarize (1-30)"),
    ai: bool = Query(False, description="Include AI-generated insights"),
) -> WeeklySummaryResponse:
    """Get weekly summary statistics.

    Returns aggregated statistics for the specified time period including:
    - Health check and failure counts
    - Healing attempt statistics and success rate
    - Top failing integrations
    - Optional AI-generated insights and recommendations

    Args:
        instance_id: Instance ID or 'all' for aggregate (default: "all")
        days: Number of days to summarize (default: 7, max: 30)
        ai: Include AI-generated insights (requires AI configuration)

    When instance_id is 'all', returns aggregated summary across all instances.

    Returns:
        Weekly summary statistics

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
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        # Query database for summary stats
        async with service.database.async_session() as session:
            from sqlalchemy import Integer, cast, func, select

            from ha_boss.core.database import HealingAction, HealthEvent

            # Total failures (type: ignore for SQLAlchemy dynamic attributes)
            failure_stmt = (
                select(func.count(HealthEvent.id))
                .where(HealthEvent.timestamp >= start_date)
                .where(HealthEvent.timestamp <= end_date)
            )

            # Filter by instance(s)
            if len(instance_ids) == 1:
                failure_stmt = failure_stmt.where(HealthEvent.instance_id == instance_ids[0])
            else:
                failure_stmt = failure_stmt.where(HealthEvent.instance_id.in_(instance_ids))

            failure_result = await session.execute(failure_stmt)
            total_failures = failure_result.scalar() or 0

            # Healing stats (type: ignore for SQLAlchemy dynamic attributes)
            healing_stmt = (
                select(
                    func.count(HealingAction.id).label("total_healings"),
                    func.sum(cast(HealingAction.success, Integer)).label(  # type: ignore[arg-type]
                        "successful_healings"
                    ),
                )
                .where(HealingAction.timestamp >= start_date)
                .where(HealingAction.timestamp <= end_date)
            )

            # Filter by instance(s)
            if len(instance_ids) == 1:
                healing_stmt = healing_stmt.where(HealingAction.instance_id == instance_ids[0])
            else:
                healing_stmt = healing_stmt.where(HealingAction.instance_id.in_(instance_ids))

            healing_result = await session.execute(healing_stmt)
            healing_row = healing_result.first()

            total_healings = healing_row.total_healings or 0
            successful_healings = healing_row.successful_healings or 0
            success_rate = (
                (successful_healings / total_healings * 100) if total_healings > 0 else 0.0
            )

            # Top failing integrations
            # Note: HealthEvent doesn't have integration_id in current schema
            # Return empty list until data model is updated
            top_failing_integrations: list[str] = []

        # Generate AI insights if requested (only for single instance)
        ai_insights = None
        if ai and len(instance_ids) == 1:
            pattern_collector = service.pattern_collectors.get(instance_ids[0])
            if pattern_collector and hasattr(pattern_collector, "summary_generator"):
                try:
                    summary_generator = pattern_collector.summary_generator
                    ai_insights = await summary_generator.generate_summary(
                        days=days, instance_id=instance_ids[0]
                    )
                except Exception as e:
                    logger.warning(f"[{instance_id}] Failed to generate AI insights: {e}")
                    ai_insights = None

        return WeeklySummaryResponse(
            start_date=start_date,
            end_date=end_date,
            total_health_checks=0,  # Not tracked separately
            total_failures=total_failures,
            total_healings=total_healings,
            success_rate=success_rate,
            top_failing_integrations=top_failing_integrations,
            ai_insights=ai_insights,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error generating weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate weekly summary") from None
