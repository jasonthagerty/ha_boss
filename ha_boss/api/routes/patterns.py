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
async def get_reliability_stats() -> list[IntegrationReliabilityResponse]:
    """Get integration reliability statistics.

    Returns reliability metrics for all integrations including:
    - Total entities per integration
    - Current unavailable entity count
    - Historical failure and success counts
    - Reliability percentage
    - Last failure timestamp

    Returns:
        List of integration reliability statistics

    Raises:
        HTTPException: Service not initialized or database unavailable (500)
    """
    try:
        service = get_service()

        if not service.database:
            raise HTTPException(status_code=500, detail="Database not initialized") from None

        # Use the reliability analyzer if available
        if service.pattern_collector and hasattr(service.pattern_collector, "analyzer"):
            analyzer = service.pattern_collector.analyzer
            stats = await analyzer.get_integration_reliability()

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
        async with service.database.async_session() as session:
            from sqlalchemy import func, select

            from ha_boss.core.database import HealthEvent, Integration

            stmt = (
                select(
                    Integration.name,
                    func.count(HealthEvent.id).label("failure_count"),
                    func.max(HealthEvent.detected_at).label("last_failure"),
                )
                .join(
                    HealthEvent,
                    HealthEvent.integration_id == Integration.id,
                    isouter=True,
                )
                .group_by(Integration.name)
            )

            result = await session.execute(stmt)
            rows = result.all()

        # Convert to response models
        reliability_list = []
        for row in rows:
            # Calculate basic stats
            reliability_list.append(
                IntegrationReliabilityResponse(
                    integration=row.name,
                    total_entities=0,  # Not available in basic query
                    unavailable_count=0,
                    failure_count=row.failure_count or 0,
                    success_count=0,
                    reliability_percent=0.0,
                    last_failure=row.last_failure,
                )
            )

        return reliability_list

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving reliability stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve reliability statistics"
        ) from None


@router.get("/patterns/failures", response_model=list[FailureEventResponse])
async def get_failure_events(
    limit: int = Query(50, ge=1, le=500, description="Maximum failures to return"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history (1-168)"),
) -> list[FailureEventResponse]:
    """Get failure event timeline.

    Returns a list of recent failure events including:
    - Entity and integration information
    - Failure timestamps
    - Resolution status and timestamps

    Args:
        limit: Maximum number of failures to return (1-500)
        hours: Hours of history to retrieve (default: 24, max: 168/7 days)

    Returns:
        List of failure events

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

        # Query database for failure events
        async with service.database.async_session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import HealthEvent, Integration

            stmt = (
                select(HealthEvent, Integration.name)
                .join(
                    Integration,
                    HealthEvent.integration_id == Integration.id,
                    isouter=True,
                )
                .where(
                    HealthEvent.detected_at >= start_time,
                    HealthEvent.detected_at <= end_time,
                )
                .order_by(HealthEvent.detected_at.desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            rows = result.all()

        # Convert to response models
        failures = []
        for event, integration_name in rows:
            failures.append(
                FailureEventResponse(
                    id=event.id,
                    entity_id=event.entity_id,
                    integration=integration_name,
                    state=event.state,
                    timestamp=event.detected_at,
                    resolved=event.resolved_at is not None,
                    resolution_time=event.resolved_at,
                )
            )

        return failures

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error retrieving failure events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve failure events") from None


@router.get("/patterns/summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
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
        days: Number of days to summarize (default: 7, max: 30)
        ai: Include AI-generated insights (requires AI configuration)

    Returns:
        Weekly summary statistics

    Raises:
        HTTPException: Service error (500)
    """
    try:
        service = get_service()

        if not service.database:
            raise HTTPException(status_code=500, detail="Database not initialized") from None

        # Calculate time range
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        # Query database for summary stats
        async with service.database.async_session() as session:
            from sqlalchemy import func, select

            from ha_boss.core.database import HealingAction, HealthEvent, Integration

            # Total failures
            failure_stmt = select(func.count(HealthEvent.id)).where(
                HealthEvent.detected_at >= start_date,
                HealthEvent.detected_at <= end_date,
            )
            failure_result = await session.execute(failure_stmt)
            total_failures = failure_result.scalar() or 0

            # Healing stats
            healing_stmt = select(
                func.count(HealingAction.id).label("total_healings"),
                func.sum(func.cast(HealingAction.success, func.Integer)).label(
                    "successful_healings"
                ),
            ).where(
                HealingAction.timestamp >= start_date,
                HealingAction.timestamp <= end_date,
            )
            healing_result = await session.execute(healing_stmt)
            healing_row = healing_result.first()

            total_healings = healing_row.total_healings or 0
            successful_healings = healing_row.successful_healings or 0
            success_rate = (
                (successful_healings / total_healings * 100) if total_healings > 0 else 0.0
            )

            # Top failing integrations
            top_failing_stmt = (
                select(Integration.name, func.count(HealthEvent.id).label("count"))
                .join(
                    HealthEvent,
                    HealthEvent.integration_id == Integration.id,
                )
                .where(
                    HealthEvent.detected_at >= start_date,
                    HealthEvent.detected_at <= end_date,
                )
                .group_by(Integration.name)
                .order_by(func.count(HealthEvent.id).desc())
                .limit(5)
            )
            top_failing_result = await session.execute(top_failing_stmt)
            top_failing_integrations = [row.name for row in top_failing_result]

        # Generate AI insights if requested
        ai_insights = None
        if (
            ai
            and service.pattern_collector
            and hasattr(service.pattern_collector, "summary_generator")
        ):
            try:
                summary_generator = service.pattern_collector.summary_generator
                ai_insights = await summary_generator.generate_summary(days=days)
            except Exception as e:
                logger.warning(f"Failed to generate AI insights: {e}")
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

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error generating weekly summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate weekly summary") from None
