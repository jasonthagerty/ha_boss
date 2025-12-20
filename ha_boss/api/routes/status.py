"""Status and health check endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from ha_boss.api.app import get_service
from ha_boss.api.models import HealthCheckResponse, ServiceStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status", response_model=ServiceStatusResponse)
async def get_status() -> ServiceStatusResponse:
    """Get current service status and statistics.

    Returns detailed information about the HA Boss service including:
    - Current state (running/stopped/error)
    - Uptime and start time
    - Health check and healing statistics
    - Number of monitored entities

    Returns:
        Service status information

    Raises:
        HTTPException: Service not initialized (500)
    """
    try:
        service = get_service()

        # Calculate uptime
        uptime_seconds = 0.0
        if service.start_time:
            uptime_seconds = (datetime.now(UTC) - service.start_time).total_seconds()

        # Count monitored entities
        monitored_count = 0
        if service.state_tracker:
            monitored_count = len(service.state_tracker._states)

        return ServiceStatusResponse(
            state=service.state,
            uptime_seconds=uptime_seconds,
            start_time=service.start_time,
            health_checks_performed=service.health_checks_performed,
            healings_attempted=service.healings_attempted,
            healings_succeeded=service.healings_succeeded,
            healings_failed=service.healings_failed,
            monitored_entities=monitored_count,
        )

    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint for monitoring and load balancers.

    Checks the status of critical components:
    - Service running state
    - Home Assistant connection
    - WebSocket connection
    - Database accessibility

    Returns:
        Health status (healthy/degraded/unhealthy) with component details

    Note:
        Returns 200 even if degraded to allow partial functionality monitoring.
        Check the 'status' field for actual health state.
    """
    try:
        service = get_service()

        # Check component health
        service_running = service.state == "running"
        ha_connected = service.ha_client is not None
        websocket_connected = (
            service.websocket_client is not None and service.websocket_client.is_connected
        )
        database_accessible = service.database is not None

        # Determine overall health status
        if all([service_running, ha_connected, websocket_connected, database_accessible]):
            status = "healthy"
        elif service_running and ha_connected:
            status = "degraded"
        else:
            status = "unhealthy"

        return HealthCheckResponse(
            status=status,
            service_running=service_running,
            ha_connected=ha_connected,
            websocket_connected=websocket_connected,
            database_accessible=database_accessible,
            timestamp=datetime.now(UTC),
        )

    except RuntimeError:
        # Service not initialized - unhealthy
        return HealthCheckResponse(
            status="unhealthy",
            service_running=False,
            ha_connected=False,
            websocket_connected=False,
            database_accessible=False,
            timestamp=datetime.now(UTC),
        )
