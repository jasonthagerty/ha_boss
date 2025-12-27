"""Main service orchestration for HA Boss."""

import asyncio
import logging
import signal
from datetime import UTC, datetime
from functools import partial
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.database import Database
from ha_boss.core.exceptions import (
    CircuitBreakerOpenError,
    DatabaseError,
)
from ha_boss.core.ha_client import create_ha_client
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.healing.heal_strategies import HealingManager
from ha_boss.healing.integration_manager import IntegrationDiscovery
from ha_boss.monitoring.health_monitor import HealthIssue, HealthMonitor
from ha_boss.monitoring.state_tracker import EntityState, StateTracker
from ha_boss.monitoring.websocket_client import WebSocketClient
from ha_boss.notifications.manager import NotificationManager

logger = logging.getLogger(__name__)


class ServiceState:
    """Service lifecycle states."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class HABossService:
    """Main service orchestration for HA Boss.

    Coordinates all MVP components into a continuously running service:
    - WebSocket monitoring
    - Health detection
    - Auto-healing with safety mechanisms
    - Notification escalation
    """

    def __init__(self, config: Config) -> None:
        """Initialize HA Boss service.

        Args:
            config: HA Boss configuration
        """
        self.config = config
        self.state = ServiceState.STOPPED

        # Core components (initialized in start())
        self.database: Database | None = None
        self.ha_client: Any = None
        self.websocket_client: WebSocketClient | None = None
        self.state_tracker: StateTracker | None = None
        self.health_monitor: HealthMonitor | None = None
        self.integration_discovery: IntegrationDiscovery | None = None
        self.healing_manager: HealingManager | None = None
        self.notification_manager: NotificationManager | None = None
        self.escalation_manager: NotificationEscalator | None = None
        self.pattern_collector: Any = None  # PatternCollector (Phase 2)

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()
        self._api_server: Any = None  # Uvicorn server instance

        # Statistics
        self.start_time: datetime | None = None
        self.health_checks_performed = 0
        self.healings_attempted = 0
        self.healings_succeeded = 0
        self.healings_failed = 0

    async def start(self) -> None:
        """Start the HA Boss service and all components.

        Initialization order:
        1. Database initialization
        2. Home Assistant client connection + test
        3. Notification manager
        4. Integration discovery
        5. State tracker with REST snapshot
        6. Health monitor
        7. Healing manager
        8. Escalation manager
        9. WebSocket connection and subscription
        10. Background monitoring tasks

        Raises:
            DatabaseError: Database initialization failed
            HomeAssistantConnectionError: Cannot connect to HA
            HomeAssistantAuthError: Authentication failed
        """
        if self.state != ServiceState.STOPPED:
            logger.warning(f"Service already started or starting (state: {self.state})")
            return

        logger.info("Starting HA Boss service...")
        self.state = ServiceState.STARTING
        self.start_time = datetime.now(UTC)

        try:
            # 1. Initialize database
            logger.info("Initializing database...")
            self.database = Database(self.config.database.path)
            await self.database.init_db()

            # Validate database schema version
            is_valid, message = await self.database.validate_version()
            if not is_valid:
                logger.error(f"Database schema version error: {message}")
                raise DatabaseError(message)
            logger.info(f"✓ Database initialized ({message})")

            # 2. Create Home Assistant client
            logger.info(f"Connecting to Home Assistant at {self.config.home_assistant.url}...")
            self.ha_client = await create_ha_client(self.config)

            # Test connection
            await self.ha_client.get_states()
            logger.info("✓ Home Assistant connection established")

            # 3. Initialize notification manager
            logger.info("Initializing notification manager...")
            self.notification_manager = NotificationManager(
                config=self.config,
                ha_client=self.ha_client,
            )
            logger.info("✓ Notification manager initialized")

            # 4. Discover integrations
            logger.info("Discovering integrations...")
            self.integration_discovery = IntegrationDiscovery(
                ha_client=self.ha_client,
                database=self.database,
                config=self.config,
            )
            # Attempt discovery but don't fail if it doesn't work
            try:
                await self.integration_discovery.discover_all()
                logger.info("✓ Integration discovery completed")
            except Exception as e:
                logger.warning(f"Integration discovery failed, continuing anyway: {e}")

            # 5. Initialize state tracker
            logger.info("Initializing state tracker...")
            self.state_tracker = StateTracker(
                database=self.database,
                on_state_updated=self._on_state_updated,
            )

            # Fetch initial state snapshot from REST API
            initial_states = await self.ha_client.get_states()
            await self.state_tracker.initialize(initial_states)
            logger.info(f"✓ State tracker initialized with {len(initial_states)} entities")

            # 6. Initialize health monitor
            logger.info("Initializing health monitor...")
            self.health_monitor = HealthMonitor(
                config=self.config,
                database=self.database,
                state_tracker=self.state_tracker,
                on_issue_detected=self._on_health_issue,
            )
            await self.health_monitor.start()
            logger.info("✓ Health monitor started")

            # 7. Initialize healing manager
            logger.info("Initializing healing manager...")
            self.healing_manager = HealingManager(
                config=self.config,
                database=self.database,
                ha_client=self.ha_client,
                integration_discovery=self.integration_discovery,
            )
            logger.info("✓ Healing manager initialized")

            # 8. Initialize escalation manager
            logger.info("Initializing escalation manager...")
            self.escalation_manager = NotificationEscalator(
                config=self.config,
                ha_client=self.ha_client,
            )
            logger.info("✓ Escalation manager initialized")

            # 8.5 Initialize pattern collector (Phase 2)
            if self.config.intelligence.pattern_collection_enabled:
                try:
                    from ha_boss.intelligence.pattern_collector import PatternCollector

                    logger.info("Initializing pattern collector...")
                    self.pattern_collector = PatternCollector(
                        database=self.database,
                        config=self.config,
                    )
                    logger.info("✓ Pattern collector initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize pattern collector: {e}")
                    logger.info("Continuing without pattern collection")

            # 9. Connect WebSocket
            logger.info("Connecting to Home Assistant WebSocket...")
            self.websocket_client = WebSocketClient(
                config=self.config,
                on_state_changed=self._on_websocket_state_changed,
            )
            await self.websocket_client.connect()
            await self.websocket_client.subscribe_events("state_changed")
            logger.info("✓ WebSocket connected and subscribed")

            # 10. Start background tasks
            logger.info("Starting background tasks...")
            self._start_background_tasks()

            # 11. Start API server if enabled
            if self.config.api.enabled:
                api_addr = f"{self.config.api.host}:{self.config.api.port}"
                logger.info(f"Starting API server on {api_addr}...")
                self._start_api_server()

            self.state = ServiceState.RUNNING
            logger.info("✅ HA Boss service started successfully")
            logger.info(
                f"Mode: {self.config.mode}, "
                f"Healing: {'enabled' if self.config.healing.enabled else 'disabled'}, "
                f"API: {'enabled' if self.config.api.enabled else 'disabled'}"
            )

        except Exception as e:
            self.state = ServiceState.ERROR
            logger.error(f"Failed to start service: {e}", exc_info=True)
            # Cleanup on failure
            await self._cleanup()
            raise

    def _start_background_tasks(self) -> None:
        """Start all background tasks."""
        # WebSocket receiver
        task = asyncio.create_task(self.websocket_client.start())  # type: ignore
        task.set_name("websocket_receiver")
        self._tasks.append(task)

        # Note: HealthMonitor runs its own internal monitoring loop
        # No need for separate periodic health check task here

        # Periodic REST snapshot validation (every 5 minutes)
        task = asyncio.create_task(self._periodic_snapshot_validation())
        task.set_name("periodic_snapshot_validation")
        self._tasks.append(task)

        logger.info(f"Started {len(self._tasks)} background tasks")

    def _start_api_server(self) -> None:
        """Start the FastAPI server in a background task."""
        task = asyncio.create_task(self._run_api_server())
        task.set_name("api_server")
        self._tasks.append(task)

        api_addr = f"{self.config.api.host}:{self.config.api.port}"
        logger.info(f"API server task started - docs at http://{api_addr}/docs")

    async def _run_api_server(self) -> None:
        """Run the uvicorn API server."""
        try:
            import uvicorn
            from pathlib import Path
            from fastapi import FastAPI, HTTPException
            from fastapi.middleware.cors import CORSMiddleware
            from fastapi.responses import FileResponse
            from fastapi.staticfiles import StaticFiles

            # Import and patch the global service getter
            import ha_boss.api.app as api_app

            api_app._service = self  # Set global service instance for API routes

            # Create FastAPI app with full configuration
            app = FastAPI(
                title="HA Boss API",
                description="""
## HA Boss REST API

A RESTful API for monitoring, managing, and analyzing Home Assistant instances.

### Features

- **Status Monitoring** - Real-time service status, uptime, and statistics
- **Entity Monitoring** - Track entity states and history
- **Pattern Analysis** - Integration reliability and failure analysis
- **Automation Management** - Analyze and generate automations with AI
- **Manual Healing** - Trigger integration reloads on demand

### Dashboard

Access the web dashboard at `/dashboard` for a visual interface.
                """,
                version="0.1.0",
                docs_url="/docs",
                redoc_url="/redoc",
                openapi_url="/openapi.json",
            )

            # Add CORS if enabled
            if self.config.api.cors_enabled:
                app.add_middleware(
                    CORSMiddleware,
                    allow_origins=self.config.api.cors_origins,
                    allow_credentials=True,
                    allow_methods=["*"],
                    allow_headers=["*"],
                )

            # Import and mount all routers (use global service instance)
            from ha_boss.api.routes import (
                automations,
                healing,
                monitoring,
                patterns,
                status,
            )

            # Add authentication dependency if enabled
            dependencies = []
            if self.config.api.auth_enabled:
                from fastapi import Depends
                from ha_boss.api.dependencies import verify_api_key

                dependencies = [Depends(verify_api_key)]
                logger.info("API authentication enabled")
            else:
                logger.info("API authentication disabled")

            # Register all routers
            app.include_router(
                status.router, prefix="/api", tags=["Status"], dependencies=dependencies
            )
            app.include_router(
                monitoring.router, prefix="/api", tags=["Monitoring"], dependencies=dependencies
            )
            app.include_router(
                patterns.router,
                prefix="/api",
                tags=["Pattern Analysis"],
                dependencies=dependencies,
            )
            app.include_router(
                automations.router,
                prefix="/api",
                tags=["Automations"],
                dependencies=dependencies,
            )
            app.include_router(
                healing.router, prefix="/api", tags=["Healing"], dependencies=dependencies
            )

            # Static file serving for dashboard
            static_dir = Path(__file__).parent.parent / "api" / "static"
            if static_dir.exists():
                app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
                logger.info(f"Serving static files from: {static_dir}")

                @app.get("/dashboard", include_in_schema=False)
                async def dashboard() -> FileResponse:
                    """Serve the API dashboard."""
                    dashboard_file = static_dir / "index.html"
                    if dashboard_file.exists():
                        return FileResponse(dashboard_file)
                    raise HTTPException(status_code=404, detail="Dashboard not found")

                logger.info("Dashboard available at: /dashboard")
            else:
                logger.warning(f"Static files directory not found at {static_dir}, dashboard unavailable")

            # Root endpoint
            @app.get("/", include_in_schema=False)
            async def root() -> dict[str, str]:
                """Root endpoint with links to docs and dashboard."""
                response = {
                    "message": "HA Boss API",
                    "docs": "/docs",
                    "redoc": "/redoc",
                    "openapi": "/openapi.json",
                }

                # Include dashboard link if static files exist
                if static_dir.exists():
                    response["dashboard"] = "/dashboard"

                return response

            # Create uvicorn config
            config = uvicorn.Config(
                app,
                host=self.config.api.host,
                port=self.config.api.port,
                log_level="warning",  # Reduce uvicorn noise
                access_log=False,
            )

            # Create and run server
            server = uvicorn.Server(config)
            self._api_server = server

            api_addr = f"{self.config.api.host}:{self.config.api.port}"
            logger.info(f"✓ API server running on http://{api_addr}")
            logger.info(f"  Health check: http://{api_addr}/api/health")
            logger.info(f"  API docs: http://{api_addr}/docs")
            if static_dir.exists():
                logger.info(f"  Dashboard: http://{api_addr}/dashboard")
            await server.serve()

        except ImportError as e:
            logger.error(f"Failed to start API server - missing dependencies: {e}")
            logger.info("Install with: pip install 'ha-boss[api]'")
        except Exception as e:
            logger.error(f"API server error: {e}", exc_info=True)

    async def _periodic_snapshot_validation(self) -> None:
        """Periodically validate state tracker cache against REST API snapshot."""
        interval = self.config.monitoring.snapshot_interval_seconds

        while not self._shutdown_event.is_set():
            try:
                if self.ha_client and self.state_tracker:
                    logger.debug("Fetching REST API snapshot for validation...")
                    states = await self.ha_client.get_states()

                    # Update state tracker with fresh data
                    for state_data in states:
                        entity_id = state_data.get("entity_id")
                        if entity_id:
                            await self.state_tracker.update_state(state_data)

                    logger.debug(f"Validated {len(states)} entities via REST snapshot")

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic snapshot validation: {e}", exc_info=True)

    async def _on_websocket_state_changed(self, event: dict[str, Any]) -> None:
        """Handle state_changed events from WebSocket.

        Args:
            event: WebSocket state_changed event data containing entity_id, new_state, old_state
        """
        try:
            # Update state tracker with full event data
            # event structure: {entity_id: "...", new_state: {...}, old_state: {...}}
            if self.state_tracker:
                await self.state_tracker.update_state(event)

        except Exception as e:
            logger.error(f"Error handling WebSocket state change: {e}", exc_info=True)

    async def _on_state_updated(
        self, new_state: EntityState, old_state: EntityState | None
    ) -> None:
        """Callback when entity state is updated.

        Args:
            new_state: New entity state
            old_state: Previous state (if any)
        """
        # Trigger health check for this specific entity
        if self.health_monitor:
            try:
                issue = await self.health_monitor.check_entity_now(new_state.entity_id)
                if issue:
                    logger.debug(
                        f"State update triggered health issue for {new_state.entity_id}: "
                        f"{issue.issue_type}"
                    )
            except Exception as e:
                logger.error(f"Error checking health for {new_state.entity_id}: {e}", exc_info=True)

    async def _on_health_issue(self, issue: HealthIssue) -> None:
        """Callback when health issue is detected.

        Args:
            issue: Detected health issue
        """
        logger.info(
            f"Health issue detected: {issue.entity_id} - {issue.issue_type} "
            f"(detected at {issue.detected_at})"
        )

        # Skip healing for recovery events
        if issue.issue_type == "recovered":
            logger.info(f"Entity {issue.entity_id} recovered automatically")
            return

        # Record unavailable event for pattern analysis (Phase 2)
        if self.pattern_collector and issue.issue_type in ("unavailable", "stale"):
            try:
                # Get integration info
                integration_id = None
                integration_domain = None
                if self.integration_discovery:
                    integration_id = self.integration_discovery.get_integration_for_entity(
                        issue.entity_id
                    )
                    if integration_id:
                        integration_domain = self.integration_discovery.get_domain(integration_id)

                await self.pattern_collector.record_entity_unavailable(
                    entity_id=issue.entity_id,
                    integration_id=integration_id,
                    integration_domain=integration_domain,
                    timestamp=issue.detected_at,
                    details=issue.details,
                )
            except Exception as e:
                logger.debug(f"Failed to record unavailable event: {e}")

        # Attempt auto-healing if enabled
        if self.config.healing.enabled and self.healing_manager:
            try:
                logger.info(f"Attempting auto-heal for {issue.entity_id}...")
                self.healings_attempted += 1

                success = await self.healing_manager.heal(issue)

                # Record healing attempt for pattern analysis (Phase 2)
                if self.pattern_collector:
                    try:
                        # Get integration info
                        integration_id = None
                        integration_domain = None
                        if self.integration_discovery:
                            integration_id = self.integration_discovery.get_integration_for_entity(
                                issue.entity_id
                            )
                            if integration_id:
                                integration_domain = self.integration_discovery.get_domain(
                                    integration_id
                                )

                        if success:
                            await self.pattern_collector.record_healing_attempt(
                                entity_id=issue.entity_id,
                                integration_id=integration_id,
                                integration_domain=integration_domain,
                                success=True,
                                timestamp=datetime.now(UTC),
                                details={"issue_type": issue.issue_type},
                            )
                        else:
                            await self.pattern_collector.record_healing_attempt(
                                entity_id=issue.entity_id,
                                integration_id=integration_id,
                                integration_domain=integration_domain,
                                success=False,
                                timestamp=datetime.now(UTC),
                                details={
                                    "issue_type": issue.issue_type,
                                    "max_attempts": self.config.healing.max_attempts,
                                },
                            )
                    except Exception as e:
                        logger.debug(f"Failed to record healing attempt: {e}")

                if success:
                    logger.info(f"✓ Successfully healed {issue.entity_id}")
                    self.healings_succeeded += 1
                else:
                    logger.warning(f"✗ Healing failed for {issue.entity_id}")
                    self.healings_failed += 1
                    # Escalate to notifications
                    if self.escalation_manager:
                        await self.escalation_manager.notify_healing_failure(
                            health_issue=issue,
                            error=Exception(
                                f"Healing failed after {self.config.healing.max_attempts} attempts"
                            ),
                            attempts=self.config.healing.max_attempts,
                        )

            except CircuitBreakerOpenError:
                logger.warning(f"Circuit breaker open, skipping heal attempt for {issue.entity_id}")
                # Escalate circuit breaker trip
                if self.escalation_manager and self.integration_discovery:
                    # Get integration name for notification
                    entry_id = self.integration_discovery.get_integration_for_entity(
                        issue.entity_id
                    )
                    integration_name = issue.entity_id  # Default to entity_id
                    if entry_id:
                        details = self.integration_discovery.get_integration_details(entry_id)
                        if details:
                            integration_name = (
                                details.get("title") or details.get("domain") or entry_id
                            )

                    # Calculate reset time
                    from datetime import timedelta

                    reset_time = datetime.now(UTC) + timedelta(
                        seconds=self.config.healing.circuit_breaker_reset_seconds
                    )

                    await self.escalation_manager.notify_circuit_breaker_open(
                        integration_name=integration_name,
                        failure_count=self.config.healing.circuit_breaker_threshold,
                        reset_time=reset_time,
                    )

            except Exception as e:
                logger.error(
                    f"Error during healing attempt for {issue.entity_id}: {e}", exc_info=True
                )
        else:
            logger.info("Auto-healing disabled, issue logged only")

    async def stop(self) -> None:
        """Gracefully stop the HA Boss service."""
        if self.state not in (ServiceState.RUNNING, ServiceState.STARTING):
            logger.warning(f"Service not running (state: {self.state})")
            return

        logger.info("Stopping HA Boss service...")
        self.state = ServiceState.STOPPING

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel all background tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # Cleanup components
        await self._cleanup()

        self.state = ServiceState.STOPPED
        logger.info("HA Boss service stopped")

    async def _cleanup(self) -> None:
        """Clean up all components."""
        # Stop API server
        if self._api_server:
            try:
                logger.info("Stopping API server...")
                self._api_server.should_exit = True
                await asyncio.sleep(0.1)  # Give it time to shutdown gracefully
            except Exception as e:
                logger.error(f"Error stopping API server: {e}")

        # Stop health monitor
        if self.health_monitor:
            try:
                await self.health_monitor.stop()
            except Exception as e:
                logger.error(f"Error stopping health monitor: {e}")

        # Stop WebSocket
        if self.websocket_client:
            try:
                await self.websocket_client.stop()
            except Exception as e:
                logger.error(f"Error stopping WebSocket: {e}")

        # Close database
        if self.database:
            try:
                await self.database.close()
            except Exception as e:
                logger.error(f"Error closing database: {e}")

        # Close HA client
        if self.ha_client:
            try:
                await self.ha_client.close()
            except Exception as e:
                logger.error(f"Error closing HA client: {e}")

    async def run_forever(self) -> None:
        """Run the service until interrupted.

        This is the main entry point for running the service in foreground mode.
        Sets up signal handlers and runs until SIGTERM or SIGINT.
        """
        # Set up signal handlers
        loop = asyncio.get_running_loop()

        def signal_handler(sig: signal.Signals) -> None:
            logger.info(f"Received signal {sig.name}, initiating shutdown...")
            asyncio.create_task(self.stop())

        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, partial(signal_handler, sig))

        # Start the service
        await self.start()

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        logger.info("Service run completed")

    def get_status(self) -> dict[str, Any]:
        """Get current service status.

        Returns:
            Dictionary with service status information
        """
        uptime_seconds = 0.0
        if self.start_time:
            uptime_seconds = (datetime.now(UTC) - self.start_time).total_seconds()

        success_rate = 0.0
        if self.healings_attempted > 0:
            success_rate = (self.healings_succeeded / self.healings_attempted) * 100

        return {
            "state": self.state,
            "mode": self.config.mode,
            "uptime_seconds": uptime_seconds,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "websocket_connected": (
                self.websocket_client.is_connected() if self.websocket_client else False
            ),
            "healing_enabled": self.config.healing.enabled,
            "statistics": {
                "health_checks_performed": self.health_checks_performed,
                "healings_attempted": self.healings_attempted,
                "healings_succeeded": self.healings_succeeded,
                "healings_failed": self.healings_failed,
                "healing_success_rate": success_rate,
            },
        }
