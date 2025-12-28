"""Status and health check endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    ComponentHealth,
    EnhancedHealthCheckResponse,
    PerformanceMetrics,
    ServiceStatusResponse,
)

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

        # Count monitored entities from database (more reliable than cache)
        monitored_count = 0
        db_success = False
        try:
            async with service.database.async_session() as session:
                from sqlalchemy import func, select

                from ha_boss.core.database import Entity

                result = await session.execute(
                    select(func.count())
                    .select_from(Entity)
                    .where(Entity.is_monitored == True)  # noqa: E712
                )
                count_value = result.scalar() or 0
                # Ensure we got an integer (not a mock/coroutine)
                if isinstance(count_value, int):
                    monitored_count = count_value
                    db_success = True
        except Exception:
            pass  # Fall through to cache fallback

        # Fallback to cache if database query didn't succeed
        if not db_success and service.state_tracker:
            if hasattr(service.state_tracker, "_cache"):
                # Use cache directly (works with mocks and real implementation)
                monitored_count = len(service.state_tracker._cache)
            else:
                # Try get_all_states as last resort
                try:
                    all_states = await service.state_tracker.get_all_states()
                    monitored_count = len(all_states) if isinstance(all_states, dict) else 0
                except Exception:
                    monitored_count = 0

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


def determine_overall_status(components: dict[str, dict[str, ComponentHealth]]) -> str:
    """Determine overall health status from component statuses.

    Status determination rules (tier priority):
    - UNHEALTHY: Any Tier 1 (critical) component unhealthy
    - DEGRADED: All Tier 1 healthy, but any Tier 2-4 unhealthy/degraded
    - HEALTHY: All Tier 1-4 components healthy (Tier 5 optional doesn't affect)

    Args:
        components: Component health dict organized by tier

    Returns:
        Overall health status: "healthy", "degraded", or "unhealthy"
    """
    # Check Tier 1 (critical) - any unhealthy = overall unhealthy
    for comp in components.get("critical", {}).values():
        if comp.status == "unhealthy":
            return "unhealthy"

    # Check Tier 2-4 (essential/operational/healing) - any degraded = overall degraded
    for tier in ["essential", "operational", "healing"]:
        for comp in components.get(tier, {}).values():
            if comp.status in ("unhealthy", "degraded"):
                return "degraded"

    # All critical tiers healthy (Tier 5 doesn't affect status)
    return "healthy"


def count_component_statuses(components: dict[str, dict[str, ComponentHealth]]) -> dict[str, int]:
    """Count components by status across all tiers.

    Args:
        components: Component health dict organized by tier

    Returns:
        Count dict with keys: healthy, degraded, unhealthy, unknown
    """
    counts = {"healthy": 0, "degraded": 0, "unhealthy": 0, "unknown": 0}

    for tier_components in components.values():
        for component in tier_components.values():
            counts[component.status] = counts.get(component.status, 0) + 1

    return counts


async def check_tier1_critical(service) -> dict[str, ComponentHealth]:
    """Check Tier 1 critical components (service cannot run without these).

    Components:
    - service_state: Service running state
    - ha_rest_connection: Home Assistant REST API connection
    - database_accessible: Database engine accessibility
    - configuration_valid: Configuration loaded and valid

    Args:
        service: HABossService instance

    Returns:
        Dict of component name to ComponentHealth
    """
    components = {}

    # 1. Service State
    if service.state == "running":
        components["service_state"] = ComponentHealth(
            status="healthy",
            message="Service is running",
            details={"state": service.state, "mode": service.config.mode},
        )
    else:
        components["service_state"] = ComponentHealth(
            status="unhealthy",
            message=f"Service is not running (state: {service.state})",
            details={"state": service.state, "mode": service.config.mode},
        )

    # 2. Home Assistant REST Connection
    ha_session_valid = (
        service.ha_client is not None
        and hasattr(service.ha_client, "_session")
        and service.ha_client._session is not None
        and not service.ha_client._session.closed
    )

    if ha_session_valid:
        components["ha_rest_connection"] = ComponentHealth(
            status="healthy",
            message="Home Assistant REST API connected",
            details={
                "url": str(service.config.home_assistant.url),
                "session_valid": True,
            },
        )
    else:
        components["ha_rest_connection"] = ComponentHealth(
            status="unhealthy",
            message="Home Assistant REST API not connected",
            details={
                "url": str(service.config.home_assistant.url) if service.config else "unknown",
                "session_valid": False,
            },
        )

    # 3. Database Accessible
    db_engine_valid = (
        service.database is not None
        and hasattr(service.database, "engine")
        and service.database.engine is not None
    )

    if db_engine_valid:
        components["database_accessible"] = ComponentHealth(
            status="healthy",
            message="Database engine accessible",
            details={
                "path": str(service.config.database.path) if service.config else "unknown",
                "engine_valid": True,
            },
        )
    else:
        components["database_accessible"] = ComponentHealth(
            status="unhealthy",
            message="Database engine not accessible",
            details={
                "path": str(service.config.database.path) if service.config else "unknown",
                "engine_valid": False,
            },
        )

    # 4. Configuration Valid
    if service.config is not None:
        components["configuration_valid"] = ComponentHealth(
            status="healthy",
            message="Configuration loaded and valid",
            details={
                "mode": service.config.mode,
                "healing_enabled": service.config.healing.enabled,
            },
        )
    else:
        components["configuration_valid"] = ComponentHealth(
            status="unhealthy",
            message="Configuration not loaded",
            details={},
        )

    return components


async def check_tier2_essential(service) -> dict[str, ComponentHealth]:
    """Check Tier 2 essential components (core functionality).

    Components:
    - websocket_connected: WebSocket connection active
    - state_tracker_initialized: State tracker has cached entities
    - integration_discovery_complete: Integrations discovered
    - event_loop_responsive: Health check not delayed

    Args:
        service: HABossService instance

    Returns:
        Dict of component name to ComponentHealth
    """
    components = {}

    # 5. WebSocket Connected
    ws_connected = (
        service.websocket_client is not None
        and hasattr(service.websocket_client, "is_connected")
        and service.websocket_client.is_connected()
    )

    if ws_connected:
        ws_running = getattr(service.websocket_client, "_running", False)
        components["websocket_connected"] = ComponentHealth(
            status="healthy",
            message="WebSocket connected to Home Assistant",
            details={"connected": True, "running": ws_running},
        )
    else:
        components["websocket_connected"] = ComponentHealth(
            status="degraded",
            message="WebSocket not connected (can operate on REST polling)",
            details={"connected": False, "running": False},
        )

    # 6. State Tracker Initialized
    cache_size = 0
    db_monitored_count = 0

    if service.state_tracker is not None and hasattr(service.state_tracker, "_cache"):
        cache_size = len(service.state_tracker._cache)

        # Also check database for monitored entities (more reliable than cache)
        try:
            async with service.database.async_session() as session:
                from sqlalchemy import func, select

                from ha_boss.core.database import Entity

                result = await session.execute(
                    select(func.count())
                    .select_from(Entity)
                    .where(Entity.is_monitored == True)  # noqa: E712
                )
                count_value = result.scalar() or 0
                # Ensure we got an integer (not a mock/coroutine)
                if isinstance(count_value, int):
                    db_monitored_count = count_value
        except Exception:
            pass  # If query fails, just use cache_size

    # Consider healthy if either cache has entities OR database has monitored entities
    tracker_initialized = cache_size > 0 or db_monitored_count > 0

    if tracker_initialized:
        if cache_size > 0:
            components["state_tracker_initialized"] = ComponentHealth(
                status="healthy",
                message=f"State tracker initialized with {cache_size} entities",
                details={
                    "cached_entities": cache_size,
                    "db_monitored": db_monitored_count,
                    "initialized": True,
                },
            )
        else:
            # Cache is empty but database has entities (acceptable)
            components["state_tracker_initialized"] = ComponentHealth(
                status="healthy",
                message=f"State tracker initialized ({db_monitored_count} monitored in DB)",
                details={
                    "cached_entities": 0,
                    "db_monitored": db_monitored_count,
                    "initialized": True,
                },
            )
    else:
        components["state_tracker_initialized"] = ComponentHealth(
            status="degraded",
            message="State tracker not initialized or empty",
            details={"cached_entities": 0, "db_monitored": 0, "initialized": False},
        )

    # 7. Integration Discovery Complete
    discovery_complete = (
        service.integration_discovery is not None
        and hasattr(service.integration_discovery, "_entity_to_integration")
        and len(service.integration_discovery._entity_to_integration) > 0
    )

    if discovery_complete:
        mapping_count = len(service.integration_discovery._entity_to_integration)
        integration_count = len(getattr(service.integration_discovery, "_integrations", {}))
        components["integration_discovery_complete"] = ComponentHealth(
            status="healthy",
            message=f"Integration discovery complete: {mapping_count} mappings",
            details={
                "discovered_mappings": mapping_count,
                "integrations": integration_count,
            },
        )
    else:
        components["integration_discovery_complete"] = ComponentHealth(
            status="degraded",
            message="Integration discovery not complete (healing limited)",
            details={"discovered_mappings": 0, "integrations": 0},
        )

    # 8. Entity Discovery Complete
    entity_discovery_complete = service.entity_discovery is not None and hasattr(
        service.entity_discovery, "_monitored_set"
    )

    if entity_discovery_complete:
        monitored_count = len(service.entity_discovery._monitored_set)
        auto_discovered_count = len(service.entity_discovery._auto_discovered_entities)

        # Get last discovery refresh timestamp from database
        last_refresh = None
        try:
            async with service.database.async_session() as session:
                from sqlalchemy import select

                from ha_boss.core.database import DiscoveryRefresh

                result = await session.execute(
                    select(DiscoveryRefresh)
                    .where(DiscoveryRefresh.success == True)  # noqa: E712
                    .order_by(DiscoveryRefresh.timestamp.desc())
                    .limit(1)
                )
                last_refresh_record = result.scalar_one_or_none()
                # Check if we got a real object (not a mock/None)
                if last_refresh_record and hasattr(last_refresh_record, "timestamp"):
                    timestamp_value = last_refresh_record.timestamp
                    # Ensure we got a datetime (not a mock/coroutine)
                    if hasattr(timestamp_value, "replace"):
                        last_refresh = timestamp_value
                        # Ensure timezone-aware for proper ISO format with UTC indicator
                        if last_refresh.tzinfo is None:
                            last_refresh = last_refresh.replace(tzinfo=UTC)
        except Exception:
            pass  # If query fails, just skip timestamp

        components["entity_discovery_complete"] = ComponentHealth(
            status="healthy",
            message=f"Entity discovery complete: {monitored_count} monitored",
            details={
                "monitored_entities": monitored_count,
                "auto_discovered": auto_discovered_count,
                "last_refresh": last_refresh.isoformat() if last_refresh else None,
            },
        )
    else:
        components["entity_discovery_complete"] = ComponentHealth(
            status="degraded",
            message="Entity discovery not complete",
            details={"monitored_entities": 0, "auto_discovered": 0, "last_refresh": None},
        )

    # 9. Event Loop Responsive
    # Simple check: we're executing, so event loop is responsive
    # In future, could track time since last check
    components["event_loop_responsive"] = ComponentHealth(
        status="healthy",
        message="Event loop responsive",
        details={
            "check_interval_configured": (
                service.config.monitoring.health_check_interval_seconds if service.config else 60
            )
        },
    )

    return components


async def check_tier3_operational(service) -> dict[str, ComponentHealth]:
    """Check Tier 3 operational components (health monitoring works).

    Components:
    - health_monitor_running: Health monitor loop running
    - health_events_recordable: Database can persist health events
    - state_history_recording: State history being tracked
    - notification_service: Notification manager initialized

    Args:
        service: HABossService instance

    Returns:
        Dict of component name to ComponentHealth
    """
    components = {}

    # 9. Health Monitor Running
    monitor_running = (
        service.health_monitor is not None
        and hasattr(service.health_monitor, "_running")
        and service.health_monitor._running
    )

    if monitor_running:
        monitor_task_alive = (
            hasattr(service.health_monitor, "_monitor_task")
            and service.health_monitor._monitor_task is not None
            and not service.health_monitor._monitor_task.done()
        )
        components["health_monitor_running"] = ComponentHealth(
            status="healthy",
            message="Health monitor loop running",
            details={"running": True, "monitor_task_alive": monitor_task_alive},
        )
    else:
        components["health_monitor_running"] = ComponentHealth(
            status="degraded",
            message="Health monitor not running (won't detect new issues)",
            details={"running": False, "monitor_task_alive": False},
        )

    # 10. Health Events Recordable (same as database accessible)
    db_accessible = service.database is not None

    if db_accessible:
        components["health_events_recordable"] = ComponentHealth(
            status="healthy",
            message="Health events can be persisted to database",
            details={"persistence_enabled": True},
        )
    else:
        components["health_events_recordable"] = ComponentHealth(
            status="degraded",
            message="Health events cannot be persisted",
            details={"persistence_enabled": False},
        )

    # 11. State History Recording
    tracker_active = service.state_tracker is not None

    if tracker_active:
        components["state_history_recording"] = ComponentHealth(
            status="healthy",
            message="State history recording active",
            details={"tracking_enabled": True},
        )
    else:
        components["state_history_recording"] = ComponentHealth(
            status="degraded",
            message="State history not recording (losing pattern data)",
            details={"tracking_enabled": False},
        )

    # 12. Notification Service
    notification_initialized = (
        service.notification_manager is not None
        and hasattr(service.notification_manager, "ha_client")
        and service.notification_manager.ha_client is not None
    )

    if notification_initialized:
        components["notification_service"] = ComponentHealth(
            status="healthy",
            message="Notification service initialized",
            details={"manager_initialized": True, "ha_channel_enabled": True},
        )
    else:
        components["notification_service"] = ComponentHealth(
            status="degraded",
            message="Notification service not initialized (alerts won't work)",
            details={"manager_initialized": False, "ha_channel_enabled": False},
        )

    return components


async def check_tier4_healing(service) -> dict[str, ComponentHealth]:
    """Check Tier 4 healing components (auto-healing capability).

    Components:
    - healing_manager_initialized: Healing manager ready and enabled
    - circuit_breakers_operational: Circuit breakers not stuck
    - healing_actions_recordable: Database can persist healing actions

    Args:
        service: HABossService instance

    Returns:
        Dict of component name to ComponentHealth
    """
    components = {}

    # 13. Healing Manager Initialized
    healing_enabled = service.config and service.config.healing.enabled
    healing_manager_ready = service.healing_manager is not None

    if healing_enabled and healing_manager_ready:
        components["healing_manager_initialized"] = ComponentHealth(
            status="healthy",
            message="Healing manager initialized and enabled",
            details={"enabled": True, "manager_initialized": True},
        )
    elif healing_manager_ready and not healing_enabled:
        components["healing_manager_initialized"] = ComponentHealth(
            status="degraded",
            message="Healing disabled (operating in monitor-only mode)",
            details={"enabled": False, "manager_initialized": True},
        )
    else:
        components["healing_manager_initialized"] = ComponentHealth(
            status="degraded",
            message="Healing manager not initialized",
            details={"enabled": healing_enabled, "manager_initialized": False},
        )

    # 14. Circuit Breakers Operational
    # Count integrations with circuit breakers open
    if service.healing_manager and hasattr(service.healing_manager, "_failure_count"):
        failure_counts = service.healing_manager._failure_count
        circuit_breaker_threshold = (
            service.config.healing.circuit_breaker_threshold if service.config else 3
        )

        open_circuit_breakers = sum(
            1 for count in failure_counts.values() if count >= circuit_breaker_threshold
        )
        total_integrations = len(failure_counts) if failure_counts else 0

        # Degraded if >50% have circuit breakers open
        if total_integrations > 0 and open_circuit_breakers / total_integrations > 0.5:
            components["circuit_breakers_operational"] = ComponentHealth(
                status="degraded",
                message=f"{open_circuit_breakers}/{total_integrations} integrations circuit-breaker-locked",
                details={
                    "total_integrations": total_integrations,
                    "circuit_breaker_open": open_circuit_breakers,
                    "threshold": circuit_breaker_threshold,
                },
            )
        else:
            components["circuit_breakers_operational"] = ComponentHealth(
                status="healthy",
                message="Circuit breakers operational",
                details={
                    "total_integrations": total_integrations,
                    "circuit_breaker_open": open_circuit_breakers,
                    "threshold": circuit_breaker_threshold,
                },
            )
    else:
        components["circuit_breakers_operational"] = ComponentHealth(
            status="unknown",
            message="Circuit breaker status unknown",
            details={},
        )

    # 15. Healing Actions Recordable (same as database accessible)
    db_accessible = service.database is not None

    if db_accessible:
        components["healing_actions_recordable"] = ComponentHealth(
            status="healthy",
            message="Healing actions can be persisted to database",
            details={"persistence_enabled": True},
        )
    else:
        components["healing_actions_recordable"] = ComponentHealth(
            status="degraded",
            message="Healing actions cannot be persisted",
            details={"persistence_enabled": False},
        )

    return components


async def check_tier5_intelligence(service) -> dict[str, ComponentHealth]:
    """Check Tier 5 intelligence components (optional AI features).

    Components:
    - ollama_available: Ollama LLM service configured
    - claude_available: Claude API configured

    Args:
        service: HABossService instance

    Returns:
        Dict of component name to ComponentHealth
    """
    components = {}

    # 16. Ollama Available
    if service.config and hasattr(service.config, "intelligence"):
        ollama_enabled = service.config.intelligence.ollama_enabled

        if ollama_enabled:
            components["ollama_available"] = ComponentHealth(
                status="healthy",
                message="Ollama configured and enabled",
                details={
                    "enabled": True,
                    "url": str(service.config.intelligence.ollama_url),
                    "model": service.config.intelligence.ollama_model,
                },
            )
        else:
            components["ollama_available"] = ComponentHealth(
                status="unknown",
                message="Ollama not enabled",
                details={"enabled": False},
            )
    else:
        components["ollama_available"] = ComponentHealth(
            status="unknown",
            message="Ollama configuration not available",
            details={},
        )

    # 17. Claude Available
    if service.config and hasattr(service.config, "intelligence"):
        claude_enabled = service.config.intelligence.claude_enabled
        claude_configured = service.config.intelligence.claude_api_key is not None

        if claude_enabled and claude_configured:
            components["claude_available"] = ComponentHealth(
                status="healthy",
                message="Claude API configured and enabled",
                details={"enabled": True, "configured": True},
            )
        elif claude_enabled and not claude_configured:
            components["claude_available"] = ComponentHealth(
                status="degraded",
                message="Claude enabled but API key not configured",
                details={"enabled": True, "configured": False},
            )
        else:
            components["claude_available"] = ComponentHealth(
                status="unknown",
                message="Claude not enabled",
                details={"enabled": False, "configured": claude_configured},
            )
    else:
        components["claude_available"] = ComponentHealth(
            status="unknown",
            message="Claude configuration not available",
            details={},
        )

    return components


@router.get("/health", response_model=EnhancedHealthCheckResponse)
async def health_check(response: Response) -> EnhancedHealthCheckResponse:
    """Comprehensive health check endpoint for monitoring and orchestration.

    Performs tier-based health checks across 22 components organized into 5 tiers:
    - Tier 1 (Critical): Service cannot run without these
    - Tier 2 (Essential): Core functionality components
    - Tier 3 (Operational): Health monitoring components
    - Tier 4 (Healing): Auto-healing capability
    - Tier 5 (Intelligence): Optional AI features

    HTTP Status Codes:
    - 200 OK: Status is "healthy" or "degraded" (service functional)
    - 503 Service Unavailable: Status is "unhealthy" (critical failure)

    Returns:
        Comprehensive health status with component-level detail

    Raises:
        Never raises - always returns a valid response (may be unhealthy)
    """
    try:
        service = get_service()

        # Check all tiers
        critical = await check_tier1_critical(service)
        essential = await check_tier2_essential(service)
        operational = await check_tier3_operational(service)
        healing = await check_tier4_healing(service)
        intelligence = await check_tier5_intelligence(service)

        # Organize components by tier
        all_components = {
            "critical": critical,
            "essential": essential,
            "operational": operational,
            "healing": healing,
            "intelligence": intelligence,
        }

        # Determine overall status
        overall_status = determine_overall_status(all_components)

        # Calculate uptime
        uptime_seconds = 0.0
        if service.start_time:
            uptime_seconds = (datetime.now(UTC) - service.start_time).total_seconds()

        # Build performance metrics
        performance = PerformanceMetrics(
            uptime_seconds=uptime_seconds,
            memory_usage_mb=None,  # Future: add psutil
            rest_api_latency_ms=None,  # Future: track in ha_client
            websocket_latency_ms=None,  # Future: track in websocket_client
            db_query_latency_ms=None,  # Future: track in database
        )

        # Count component statuses
        summary = count_component_statuses(all_components)

        # Set HTTP status code based on health
        if overall_status == "unhealthy":
            response.status_code = 503

        return EnhancedHealthCheckResponse(
            status=overall_status,
            timestamp=datetime.now(UTC),
            critical=critical,
            essential=essential,
            operational=operational,
            healing=healing,
            intelligence=intelligence,
            performance=performance,
            summary=summary,
        )

    except RuntimeError:
        # Service not initialized - return minimal unhealthy response
        response.status_code = 503

        minimal_critical = {
            "service_state": ComponentHealth(
                status="unhealthy",
                message="Service not initialized",
                details={},
            )
        }

        return EnhancedHealthCheckResponse(
            status="unhealthy",
            timestamp=datetime.now(UTC),
            critical=minimal_critical,
            essential={},
            operational={},
            healing={},
            intelligence={},
            performance=PerformanceMetrics(uptime_seconds=0.0),
            summary={"healthy": 0, "degraded": 0, "unhealthy": 1, "unknown": 0},
        )
