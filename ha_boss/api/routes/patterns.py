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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/patterns/reliability", response_model=list[IntegrationReliabilityResponse])
async def get_reliability_stats(
    instance_id: str = Query("default", description="Instance identifier"),
) -> list[IntegrationReliabilityResponse]:
    """Get integration reliability statistics for a specific instance.

    Returns reliability metrics for all integrations including:
    - Total entities per integration
    - Current unavailable entity count
    - Historical failure and success counts
    - Reliability percentage
    - Last failure timestamp

    Args:
        instance_id: Instance identifier (default: "default")

    Returns:
        List of integration reliability statistics for the specified instance

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

        # Get pattern collector for this instance
        pattern_collector = service.pattern_collectors.get(instance_id)

        # Use the reliability analyzer if available
        if pattern_collector and hasattr(pattern_collector, "analyzer"):
            analyzer = pattern_collector.analyzer
            stats = await analyzer.get_integration_reliability(instance_id=instance_id)

            # Convert to response models
            reliability_list = []
            for integration, data in stats.items():
                reliability_list.append(
                    IntegrationReliabilityResponse(
                        integration=integration,
                        total_entities=data.get("total_entities", 0),
                        unavailable_count=data.get("unavailable_count", 0),
                        failure_count=data.get("failure_count", 0),
                        success_count=data.get("success_count", 0),
                        reliability_percent=data.get("reliability_percent", 0.0),
                        last_failure=data.get("last_failure"),
                    )
                )

            return reliability_list

        # Fallback: query database directly if analyzer not available
        # Note: HealthEvent doesn't have integration_id in current schema
        # Return empty list until data model is updated
        return []

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving reliability stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve reliability statistics"
        ) from None


@router.get("/patterns/failures", response_model=list[FailureEventResponse])
async def get_failure_events(
    instance_id: str = Query("default", description="Instance identifier"),
    limit: int = Query(50, ge=1, le=500, description="Maximum failures to return"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
) -> list[FailureEventResponse]:
    """Get failure event timeline for a specific instance.

    Returns a list of recent failure events including:
    - Entity and integration information
    - Failure timestamps
    - Resolution status and timestamps

    Args:
        instance_id: Instance identifier (default: "default")
        limit: Maximum number of failures to return (1-500)
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    Returns:
        List of failure events for the specified instance

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.pattern_collectors:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.pattern_collectors.keys())}",
            ) from None

        if not service.database:
            raise HTTPException(status_code=503, detail="Database not initialized") from None

        # Calculate time range
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        # Query database for failure events for this instance
        async with service.database.async_session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import HealthEvent

            stmt = (
                select(HealthEvent)  # type: ignore[attr-defined]
                .where(  # type: ignore[attr-defined]
                    HealthEvent.instance_id == instance_id,  # type: ignore[attr-defined]
                    HealthEvent.timestamp >= start_time,  # type: ignore[attr-defined]
                    HealthEvent.timestamp <= end_time,  # type: ignore[attr-defined]
                )
                .order_by(HealthEvent.timestamp.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )

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
                )
            )

        return failures

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving failure events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve failure events") from None


@router.get("/patterns/summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    instance_id: str = Query("default", description="Instance identifier"),
    days: int = Query(7, ge=1, le=30, description="Days to summarize (1-30)"),
    ai: bool = Query(False, description="Include AI-generated insights"),
) -> WeeklySummaryResponse:
    """Get weekly summary statistics for a specific instance.

    Returns aggregated statistics for the specified time period including:
    - Health check and failure counts
    - Healing attempt statistics and success rate
    - Top failing integrations
    - Optional AI-generated insights and recommendations

    Args:
        instance_id: Instance identifier (default: "default")
        days: Number of days to summarize (default: 7, max: 30)
        ai: Include AI-generated insights (requires AI configuration)

    Returns:
        Weekly summary statistics for the specified instance

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

        # Get pattern collector for this instance (for AI summary generation)
        pattern_collector = service.pattern_collectors.get(instance_id)

        # Calculate time range
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        # Query database for summary stats for this instance
        async with service.database.async_session() as session:
            from sqlalchemy import func, select

            from ha_boss.core.database import HealingAction, HealthEvent

            # Total failures
            failure_stmt = select(func.count(HealthEvent.id)).where(  # type: ignore[attr-defined]
                HealthEvent.instance_id == instance_id,  # type: ignore[attr-defined]
                HealthEvent.timestamp >= start_date,  # type: ignore[attr-defined]
                HealthEvent.timestamp <= end_date,  # type: ignore[attr-defined]
            )
            failure_result = await session.execute(failure_stmt)
            total_failures = failure_result.scalar() or 0

            # Healing stats
            from sqlalchemy import Integer, cast

            healing_stmt = select(  # type: ignore[attr-defined]
                func.count(HealingAction.id).label("total_healings"),  # type: ignore[attr-defined]
                func.sum(cast(HealingAction.success, Integer)).label(  # type: ignore[attr-defined, arg-type]
                    "successful_healings"
                ),
            ).where(  # type: ignore[attr-defined]
                HealingAction.instance_id == instance_id,  # type: ignore[attr-defined]
                HealingAction.timestamp >= start_date,  # type: ignore[attr-defined]
                HealingAction.timestamp <= end_date,  # type: ignore[attr-defined]
            )
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

        # Generate AI insights if requested
        ai_insights = None
        if ai and pattern_collector and hasattr(pattern_collector, "summary_generator"):
            try:
                summary_generator = pattern_collector.summary_generator
                ai_insights = await summary_generator.generate_summary(
                    days=days, instance_id=instance_id
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
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error generating weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate weekly summary") from None
