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

    Coordinates all MVP components for multiple Home Assistant instances:
    - Per-instance WebSocket monitoring
    - Per-instance Health detection
    - Per-instance Auto-healing with safety mechanisms
    - Per-instance Notification escalation
    - Shared database for all instances
    """

    def __init__(self, config: Config) -> None:
        """Initialize HA Boss service.

        Args:
            config: HA Boss configuration
        """
        self.config = config
        self.state = ServiceState.STOPPED

        # Shared components (initialized in start())
        self.database: Database | None = None

        # Per-instance components (keyed by instance_id)
        self.ha_clients: dict[str, Any] = {}
        self.websocket_clients: dict[str, WebSocketClient] = {}
        self.state_trackers: dict[str, StateTracker] = {}
        self.health_monitors: dict[str, HealthMonitor] = {}
        self.integration_discoveries: dict[str, IntegrationDiscovery] = {}
        self.entity_discoveries: dict[str, Any] = {}  # EntityDiscoveryService
        self.healing_managers: dict[str, HealingManager] = {}
        self.notification_managers: dict[str, NotificationManager] = {}
        self.escalation_managers: dict[str, NotificationEscalator] = {}
        self.pattern_collectors: dict[str, Any] = {}  # PatternCollector (Phase 2)

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()
        self._api_server: Any = None  # Uvicorn server instance

        # Statistics (per instance)
        self.start_time: datetime | None = None
        self.health_checks_performed: dict[str, int] = {}
        self.healings_attempted: dict[str, int] = {}
        self.healings_succeeded: dict[str, int] = {}
        self.healings_failed: dict[str, int] = {}

    def _get_default_instance_id(self) -> str:
        """Get the default instance ID (first instance or 'default').

        Returns:
            The default instance ID

        Raises:
            RuntimeError: If no instances are configured
        """
        if not self.ha_clients:
            raise RuntimeError("No instances configured")
        return list(self.ha_clients.keys())[0]

    # Backward compatibility properties for single-instance access
    @property
    def ha_client(self) -> Any:
        """Get the default HA client for backward compatibility."""
        return self.ha_clients.get(self._get_default_instance_id())

    @property
    def websocket_client(self) -> Any:
        """Get the default WebSocket client for backward compatibility."""
        return self.websocket_clients.get(self._get_default_instance_id())

    @property
    def state_tracker(self) -> Any:
        """Get the default state tracker for backward compatibility."""
        return self.state_trackers.get(self._get_default_instance_id())

    @property
    def health_monitor(self) -> Any:
        """Get the default health monitor for backward compatibility."""
        return self.health_monitors.get(self._get_default_instance_id())

    @property
    def healing_manager(self) -> Any:
        """Get the default healing manager for backward compatibility."""
        return self.healing_managers.get(self._get_default_instance_id())

    @property
    def integration_discovery(self) -> Any:
        """Get the default integration discovery for backward compatibility."""
        return self.integration_discoveries.get(self._get_default_instance_id())

    @property
    def entity_discovery(self) -> Any:
        """Get the default entity discovery for backward compatibility."""
        return self.entity_discoveries.get(self._get_default_instance_id())

    @property
    def pattern_collector(self) -> Any:
        """Get the default pattern collector for backward compatibility."""
        return self.pattern_collectors.get(self._get_default_instance_id())

    async def _initialize_instance(
        self, instance_id: str, url: str, token: str, bridge_enabled: bool
    ) -> None:
        """Initialize all components for a single Home Assistant instance.

        Args:
            instance_id: Unique identifier for this instance
            url: Home Assistant URL
            token: Long-lived access token
            bridge_enabled: Whether to try using HA Boss Bridge

        Raises:
            HomeAssistantConnectionError: Cannot connect to HA
            HomeAssistantAuthError: Authentication failed
        """
        logger.info(f"[{instance_id}] Initializing instance...")

        # Initialize statistics for this instance
        self.health_checks_performed[instance_id] = 0
        self.healings_attempted[instance_id] = 0
        self.healings_succeeded[instance_id] = 0
        self.healings_failed[instance_id] = 0

        # 1. Create Home Assistant client
        logger.info(f"[{instance_id}] Connecting to Home Assistant at {url}...")
        from ha_boss.core.config import HomeAssistantInstance
        from ha_boss.core.ha_client import HomeAssistantClient

        instance = HomeAssistantInstance(
            instance_id=instance_id, url=url, token=token, bridge_enabled=bridge_enabled
        )
        self.ha_clients[instance_id] = HomeAssistantClient(instance=instance, config=self.config)

        # Test connection
        await self.ha_clients[instance_id].get_states()
        logger.info(f"[{instance_id}] ✓ Home Assistant connection established")

        # 2. Initialize notification manager
        logger.info(f"[{instance_id}] Initializing notification manager...")
        self.notification_managers[instance_id] = NotificationManager(
            config=self.config,
            ha_client=self.ha_clients[instance_id],
        )
        logger.info(f"[{instance_id}] ✓ Notification manager initialized")

        # 3. Discover integrations
        logger.info(f"[{instance_id}] Discovering integrations...")
        self.integration_discoveries[instance_id] = IntegrationDiscovery(
            ha_client=self.ha_clients[instance_id],
            database=self.database,
            config=self.config,
        )
        # Attempt discovery but don't fail if it doesn't work
        try:
            await self.integration_discoveries[instance_id].discover_all()
            logger.info(f"[{instance_id}] ✓ Integration discovery completed")
        except Exception as e:
            logger.warning(f"[{instance_id}] Integration discovery failed, continuing anyway: {e}")

        # 4. Entity discovery from automations/scenes/scripts
        if self.config.monitoring.auto_discovery.enabled:
            try:
                from ha_boss.discovery.entity_discovery import EntityDiscoveryService

                logger.info(f"[{instance_id}] Initializing entity discovery...")
                self.entity_discoveries[instance_id] = EntityDiscoveryService(
                    ha_client=self.ha_clients[instance_id],
                    database=self.database,
                    config=self.config,
                    instance_id=instance_id,
                )

                # Run initial discovery
                stats = await self.entity_discoveries[instance_id].discover_and_refresh(
                    trigger_type="startup", trigger_source="service_init"
                )
                logger.info(
                    f"[{instance_id}] ✓ Entity discovery completed: "
                    f"{stats['automations_found']} automations, "
                    f"{stats['scenes_found']} scenes, {stats['scripts_found']} scripts, "
                    f"{stats['entities_discovered']} entities"
                )
            except Exception as e:
                logger.warning(
                    f"[{instance_id}] Entity discovery failed, continuing without it: {e}"
                )
                self.entity_discoveries[instance_id] = None
        else:
            logger.info(f"[{instance_id}] Entity auto-discovery disabled in configuration")
            self.entity_discoveries[instance_id] = None

        # 5. Initialize state tracker with REST snapshot
        logger.info(f"[{instance_id}] Initializing state tracker...")
        self.state_trackers[instance_id] = StateTracker(
            database=self.database,
            config=self.config,
            instance_id=instance_id,
        )

        # Fetch initial state from REST API
        states = await self.ha_clients[instance_id].get_states()
        for state_data in states:
            await self.state_trackers[instance_id].update_state(state_data)

        logger.info(f"[{instance_id}] ✓ State tracker initialized with {len(states)} entities")

        # 6. Initialize health monitor
        logger.info(f"[{instance_id}] Initializing health monitor...")
        self.health_monitors[instance_id] = HealthMonitor(
            config=self.config,
            state_tracker=self.state_trackers[instance_id],
            database=self.database,
            on_issue_detected=lambda issue: self._on_health_issue(instance_id, issue),
            instance_id=instance_id,
        )
        await self.health_monitors[instance_id].start()
        logger.info(f"[{instance_id}] ✓ Health monitor started")

        # 7. Initialize healing manager
        logger.info(f"[{instance_id}] Initializing healing manager...")
        self.healing_managers[instance_id] = HealingManager(
            config=self.config,
            database=self.database,
            ha_client=self.ha_clients[instance_id],
            integration_discovery=self.integration_discoveries[instance_id],
        )
        logger.info(f"[{instance_id}] ✓ Healing manager initialized")

        # 8. Initialize escalation manager
        logger.info(f"[{instance_id}] Initializing escalation manager...")
        self.escalation_managers[instance_id] = NotificationEscalator(
            config=self.config,
            ha_client=self.ha_clients[instance_id],
        )
        logger.info(f"[{instance_id}] ✓ Escalation manager initialized")

        # 9. Initialize pattern collector (Phase 2)
        if self.config.intelligence.pattern_collection_enabled:
            try:
                from ha_boss.intelligence.pattern_collector import PatternCollector

                logger.info(f"[{instance_id}] Initializing pattern collector...")
                self.pattern_collectors[instance_id] = PatternCollector(
                    instance_id=instance_id,
                    database=self.database,
                    config=self.config,
                )
                logger.info(f"[{instance_id}] ✓ Pattern collector initialized")
            except Exception as e:
                logger.warning(f"[{instance_id}] Failed to initialize pattern collector: {e}")
                logger.info(f"[{instance_id}] Continuing without pattern collection")

        # 10. Connect WebSocket
        logger.info(f"[{instance_id}] Connecting to Home Assistant WebSocket...")
        self.websocket_clients[instance_id] = WebSocketClient(
            config=self.config,
            entity_discovery=self.entity_discoveries.get(instance_id),
            on_state_changed=lambda event: self._on_websocket_state_changed(instance_id, event),
            url=url,
            token=token,
        )
        await self.websocket_clients[instance_id].connect()
        await self.websocket_clients[instance_id].subscribe_events("state_changed")

        # Subscribe to call_service events for discovery refresh triggers
        if self.entity_discoveries.get(instance_id):
            await self.websocket_clients[instance_id].subscribe_events("call_service")

        logger.info(f"[{instance_id}] ✓ WebSocket connected and subscribed")
        logger.info(f"[{instance_id}] ✅ Instance initialization complete")

    async def start(self) -> None:
        """Start the HA Boss service and all components.

        Initialization order:
        1. Database initialization
        2. Home Assistant client connection + test
        3. Notification manager
        4. Integration discovery
        5. Entity discovery (auto-discovery from automations/scenes/scripts)
        6. State tracker with REST snapshot (filtered by discovery)
        7. Health monitor
        8. Healing manager
        9. Escalation manager
        10. WebSocket connection and subscription
        11. Background monitoring tasks (including periodic discovery)

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
            # 1. Initialize database (shared across all instances)
            logger.info("Initializing database...")
            self.database = Database(self.config.database.path)
            await self.database.init_db()

            # Validate database schema version
            is_valid, message = await self.database.validate_version()
            if not is_valid:
                logger.error(f"Database schema version error: {message}")
                raise DatabaseError(message)
            logger.info(f"✓ Database initialized ({message})")

            # 2. Initialize all Home Assistant instances
            instances = self.config.home_assistant.instances
            if not instances:
                # Backward compatibility: Use legacy single-instance config
                logger.warning("No instances configured, using legacy single-instance mode")
                from ha_boss.core.config import HomeAssistantInstance

                instances = [
                    HomeAssistantInstance(
                        instance_id="default",
                        url=self.config.home_assistant.url,
                        token=self.config.home_assistant.token,
                        bridge_enabled=True,
                    )
                ]

            logger.info(f"Initializing {len(instances)} Home Assistant instance(s)...")

            # Initialize instances sequentially to avoid overwhelming resources
            for instance_config in instances:
                await self._initialize_instance(
                    instance_id=instance_config.instance_id,
                    url=instance_config.url,
                    token=instance_config.token,
                    bridge_enabled=instance_config.bridge_enabled,
                )

            logger.info(f"✅ All {len(instances)} instance(s) initialized successfully")

            # 3. Start background tasks
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
        """Start all background tasks for all instances."""
        # Start tasks for each instance
        for instance_id, websocket_client in self.websocket_clients.items():
            # WebSocket receiver
            task = asyncio.create_task(websocket_client.start())  # type: ignore
            task.set_name(f"websocket_receiver_{instance_id}")
            self._tasks.append(task)

            # Periodic REST snapshot validation (every 5 minutes)
            task = asyncio.create_task(self._periodic_snapshot_validation(instance_id))
            task.set_name(f"periodic_snapshot_validation_{instance_id}")
            self._tasks.append(task)

            # Periodic entity discovery refresh (if enabled and interval > 0)
            entity_discovery = self.entity_discoveries.get(instance_id)
            if (
                entity_discovery
                and self.config.monitoring.auto_discovery.refresh_interval_seconds > 0
            ):
                task = asyncio.create_task(
                    entity_discovery.start_periodic_refresh(
                        self.config.monitoring.auto_discovery.refresh_interval_seconds
                    )
                )
                task.set_name(f"periodic_discovery_refresh_{instance_id}")
                self._tasks.append(task)

        # Note: HealthMonitor runs its own internal monitoring loop (per instance)
        # No need for separate periodic health check task here

        logger.info(
            f"Started {len(self._tasks)} background tasks for {len(self.websocket_clients)} instance(s)"
        )

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
            from pathlib import Path

            import uvicorn
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
                discovery,
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
                discovery.router,
                prefix="/api",
                tags=["Discovery"],
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
                logger.warning(
                    f"Static files directory not found at {static_dir}, dashboard unavailable"
                )

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

    async def _periodic_snapshot_validation(self, instance_id: str) -> None:
        """Periodically validate state tracker cache against REST API snapshot.

        Args:
            instance_id: Home Assistant instance identifier
        """
        interval = self.config.monitoring.snapshot_interval_seconds

        while not self._shutdown_event.is_set():
            try:
                ha_client = self.ha_clients.get(instance_id)
                state_tracker = self.state_trackers.get(instance_id)

                if ha_client and state_tracker:
                    logger.debug(f"[{instance_id}] Fetching REST API snapshot for validation...")
                    states = await ha_client.get_states()

                    # Update state tracker with fresh data
                    for state_data in states:
                        entity_id = state_data.get("entity_id")
                        if entity_id:
                            await state_tracker.update_state(state_data)

                    logger.debug(
                        f"[{instance_id}] Validated {len(states)} entities via REST snapshot"
                    )

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"[{instance_id}] Error in periodic snapshot validation: {e}", exc_info=True
                )

    async def _on_websocket_state_changed(self, instance_id: str, event: dict[str, Any]) -> None:
        """Handle state_changed events from WebSocket.

        Args:
            instance_id: Home Assistant instance identifier
            event: WebSocket state_changed event data containing entity_id, new_state, old_state
        """
        try:
            # Update state tracker with full event data
            # event structure: {entity_id: "...", new_state: {...}, old_state: {...}}
            state_tracker = self.state_trackers.get(instance_id)
            if state_tracker:
                await state_tracker.update_state(event)

        except Exception as e:
            logger.error(
                f"[{instance_id}] Error handling WebSocket state change: {e}", exc_info=True
            )

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

    async def _on_health_issue(self, instance_id: str, issue: HealthIssue) -> None:
        """Callback when health issue is detected.

        Args:
            instance_id: Home Assistant instance identifier
            issue: Detected health issue
        """
        logger.info(
            f"[{instance_id}] Health issue detected: {issue.entity_id} - {issue.issue_type} "
            f"(detected at {issue.detected_at})"
        )

        # Skip healing for recovery events
        if issue.issue_type == "recovered":
            logger.info(f"[{instance_id}] Entity {issue.entity_id} recovered automatically")
            return

        # Get instance components
        pattern_collector = self.pattern_collectors.get(instance_id)
        integration_discovery = self.integration_discoveries.get(instance_id)
        healing_manager = self.healing_managers.get(instance_id)
        escalation_manager = self.escalation_managers.get(instance_id)

        # Record unavailable event for pattern analysis (Phase 2)
        if pattern_collector and issue.issue_type in ("unavailable", "stale"):
            try:
                # Get integration info
                integration_id = None
                integration_domain = None
                if integration_discovery:
                    integration_id = integration_discovery.get_integration_for_entity(
                        issue.entity_id
                    )
                    if integration_id:
                        integration_domain = integration_discovery.get_domain(integration_id)

                await pattern_collector.record_entity_unavailable(
                    entity_id=issue.entity_id,
                    integration_id=integration_id,
                    integration_domain=integration_domain,
                    timestamp=issue.detected_at,
                    details=issue.details,
                )
            except Exception as e:
                logger.debug(f"[{instance_id}] Failed to record unavailable event: {e}")

        # Attempt auto-healing if enabled
        if self.config.healing.enabled and healing_manager:
            try:
                logger.info(f"[{instance_id}] Attempting auto-heal for {issue.entity_id}...")
                self.healings_attempted[instance_id] = (
                    self.healings_attempted.get(instance_id, 0) + 1
                )

                success = await healing_manager.heal(issue)

                # Record healing attempt for pattern analysis (Phase 2)
                if pattern_collector:
                    try:
                        # Get integration info
                        integration_id = None
                        integration_domain = None
                        if integration_discovery:
                            integration_id = integration_discovery.get_integration_for_entity(
                                issue.entity_id
                            )
                            if integration_id:
                                integration_domain = integration_discovery.get_domain(
                                    integration_id
                                )

                        if success:
                            await pattern_collector.record_healing_attempt(
                                entity_id=issue.entity_id,
                                integration_id=integration_id,
                                integration_domain=integration_domain,
                                success=True,
                                timestamp=datetime.now(UTC),
                                details={"issue_type": issue.issue_type},
                            )
                        else:
                            await pattern_collector.record_healing_attempt(
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
                        logger.debug(f"[{instance_id}] Failed to record healing attempt: {e}")

                if success:
                    logger.info(f"[{instance_id}] ✓ Successfully healed {issue.entity_id}")
                    self.healings_succeeded[instance_id] = (
                        self.healings_succeeded.get(instance_id, 0) + 1
                    )
                else:
                    logger.warning(f"[{instance_id}] ✗ Healing failed for {issue.entity_id}")
                    self.healings_failed[instance_id] = self.healings_failed.get(instance_id, 0) + 1
                    # Escalate to notifications
                    if escalation_manager:
                        await escalation_manager.notify_healing_failure(
                            health_issue=issue,
                            error=Exception(
                                f"Healing failed after {self.config.healing.max_attempts} attempts"
                            ),
                            attempts=self.config.healing.max_attempts,
                        )

            except CircuitBreakerOpenError:
                logger.warning(
                    f"[{instance_id}] Circuit breaker open, skipping heal attempt for {issue.entity_id}"
                )
                # Escalate circuit breaker trip
                if escalation_manager and integration_discovery:
                    # Get integration name for notification
                    entry_id = integration_discovery.get_integration_for_entity(issue.entity_id)
                    integration_name = issue.entity_id  # Default to entity_id
                    if entry_id:
                        details = integration_discovery.get_integration_details(entry_id)
                        if details:
                            integration_name = (
                                details.get("title") or details.get("domain") or entry_id
                            )

                    # Calculate reset time
                    from datetime import timedelta

                    reset_time = datetime.now(UTC) + timedelta(
                        seconds=self.config.healing.circuit_breaker_reset_seconds
                    )

                    await escalation_manager.notify_circuit_breaker_open(
                        integration_name=integration_name,
                        failure_count=self.config.healing.circuit_breaker_threshold,
                        reset_time=reset_time,
                    )

            except Exception as e:
                logger.error(
                    f"[{instance_id}] Error during healing attempt for {issue.entity_id}: {e}",
                    exc_info=True,
                )
        else:
            logger.info(f"[{instance_id}] Auto-healing disabled, issue logged only")

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
        """Clean up all components for all instances."""
        # Stop API server (shared)
        if self._api_server:
            try:
                logger.info("Stopping API server...")
                self._api_server.should_exit = True
                await asyncio.sleep(0.1)  # Give it time to shutdown gracefully
            except Exception as e:
                logger.error(f"Error stopping API server: {e}")

        # Clean up each instance
        for instance_id in list(self.ha_clients.keys()):
            logger.info(f"[{instance_id}] Cleaning up instance components...")

            # Stop health monitor
            health_monitor = self.health_monitors.get(instance_id)
            if health_monitor:
                try:
                    await health_monitor.stop()
                except Exception as e:
                    logger.error(f"[{instance_id}] Error stopping health monitor: {e}")

            # Stop entity discovery periodic refresh
            entity_discovery = self.entity_discoveries.get(instance_id)
            if entity_discovery:
                try:
                    await entity_discovery.stop_periodic_refresh()
                except Exception as e:
                    logger.error(f"[{instance_id}] Error stopping entity discovery: {e}")

            # Stop WebSocket
            websocket_client = self.websocket_clients.get(instance_id)
            if websocket_client:
                try:
                    await websocket_client.stop()
                except Exception as e:
                    logger.error(f"[{instance_id}] Error stopping WebSocket: {e}")

            # Close HA client
            ha_client = self.ha_clients.get(instance_id)
            if ha_client:
                try:
                    await ha_client.close()
                except Exception as e:
                    logger.error(f"[{instance_id}] Error closing HA client: {e}")

        # Close database (shared)
        if self.database:
            try:
                await self.database.close()
            except Exception as e:
                logger.error(f"Error closing database: {e}")

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
            Dictionary with service status information including all instances
        """
        uptime_seconds = 0.0
        if self.start_time:
            uptime_seconds = (datetime.now(UTC) - self.start_time).total_seconds()

        # Aggregate statistics across all instances
        total_health_checks = sum(self.health_checks_performed.values())
        total_healings_attempted = sum(self.healings_attempted.values())
        total_healings_succeeded = sum(self.healings_succeeded.values())
        total_healings_failed = sum(self.healings_failed.values())

        success_rate = 0.0
        if total_healings_attempted > 0:
            success_rate = (total_healings_succeeded / total_healings_attempted) * 100

        # Per-instance status
        instances_status = {}
        for instance_id in self.ha_clients.keys():
            websocket_client = self.websocket_clients.get(instance_id)
            instance_healings_attempted = self.healings_attempted.get(instance_id, 0)
            instance_healings_succeeded = self.healings_succeeded.get(instance_id, 0)

            instance_success_rate = 0.0
            if instance_healings_attempted > 0:
                instance_success_rate = (
                    instance_healings_succeeded / instance_healings_attempted
                ) * 100

            instances_status[instance_id] = {
                "websocket_connected": (
                    websocket_client.is_connected() if websocket_client else False
                ),
                "health_checks_performed": self.health_checks_performed.get(instance_id, 0),
                "healings_attempted": instance_healings_attempted,
                "healings_succeeded": instance_healings_succeeded,
                "healings_failed": self.healings_failed.get(instance_id, 0),
                "healing_success_rate": instance_success_rate,
            }

        return {
            "state": self.state,
            "mode": self.config.mode,
            "uptime_seconds": uptime_seconds,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "healing_enabled": self.config.healing.enabled,
            "instance_count": len(self.ha_clients),
            "instances": instances_status,
            "statistics": {
                "health_checks_performed": total_health_checks,
                "healings_attempted": total_healings_attempted,
                "healings_succeeded": total_healings_succeeded,
                "healings_failed": total_healings_failed,
                "healing_success_rate": success_rate,
            },
        }
