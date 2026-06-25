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
    DatabaseError,
)
from ha_boss.core.types import HealthIssue
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.healing.integration_manager import IntegrationDiscovery
from ha_boss.monitoring.health_monitor import HealthMonitor
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
        self.integration_classifiers: dict[str, Any] = {}  # IntegrationClassifier (cloud detect)
        self.notification_managers: dict[str, NotificationManager] = {}
        self.escalation_managers: dict[str, NotificationEscalator] = {}
        self.pattern_collectors: dict[str, Any] = {}  # PatternCollector (Phase 2)
        self.out_of_scope_auditors: dict[str, Any] = {}  # OutOfScopeAuditor
        self.action_verifiers: dict[str, Any] = {}  # ActionVerifier

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()

        # Statistics (per instance)
        self.start_time: datetime | None = None
        self.health_checks_performed: dict[str, int] = {}
        self.healings_attempted: dict[str, int] = {}
        self.healings_succeeded: dict[str, int] = {}
        self.healings_failed: dict[str, int] = {}

        # WebSocket broadcast throttling (per instance, per entity)
        # Key: f"{instance_id}:{entity_id}", Value: last broadcast timestamp

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

        # Create callback wrapper to include instance_id
        async def on_state_updated_wrapper(
            new_state: EntityState, old_state: EntityState | None
        ) -> None:
            await self._on_state_updated(instance_id, new_state, old_state)

        self.state_trackers[instance_id] = StateTracker(
            instance_id=instance_id,
            database=self.database,
            # Wire in discovery so the tracker only caches (and the health monitor
            # only checks) entities that auto-discovery found in automations/scenes/
            # scripts. Without this the REST snapshot below loads ALL entities
            # unfiltered, the monitored set is effectively "everything", and
            # unreferenced cloud entities (PSN, Plex, Life360) get flagged when they
            # flap. integration_discovery feeds entity→integration mapping.
            entity_discovery=self.entity_discoveries.get(instance_id),
            integration_discovery=self.integration_discoveries.get(instance_id),
            on_state_updated=on_state_updated_wrapper,
        )

        # Fetch initial state from REST API
        states = await self.ha_clients[instance_id].get_states()
        for state_data in states:
            # Wrap REST API format in WebSocket event format
            event_data = {
                "entity_id": state_data.get("entity_id"),
                "new_state": state_data,
            }
            await self.state_trackers[instance_id].update_state(event_data)

        logger.info(f"[{instance_id}] ✓ State tracker initialized with {len(states)} entities")

        # 5b. Classify integrations by iot_class (cloud vs local) so the health
        # monitor can treat internet-dependent integrations (PSN, Plex, Life360)
        # gently. Best-effort: degrade to "no entity is cloud" if it fails.
        if self.config.monitoring.cloud_handling.enabled:
            try:
                from ha_boss.discovery.integration_classifier import IntegrationClassifier

                classifier = IntegrationClassifier(
                    ha_client=self.ha_clients[instance_id],
                    config=self.config,
                    database=self.database,
                    instance_id=instance_id,
                )
                await classifier.refresh()
                self.integration_classifiers[instance_id] = classifier
                logger.info(f"[{instance_id}] ✓ Integration classifier initialized")
            except Exception as e:
                logger.warning(
                    f"[{instance_id}] Integration classification failed, continuing without "
                    f"cloud handling: {e}"
                )
                self.integration_classifiers[instance_id] = None
        else:
            self.integration_classifiers[instance_id] = None

        # 6. Initialize health monitor
        logger.info(f"[{instance_id}] Initializing health monitor...")
        self.health_monitors[instance_id] = HealthMonitor(
            config=self.config,
            state_tracker=self.state_trackers[instance_id],
            database=self.database,
            on_issue_detected=lambda issue: self._on_health_issue(instance_id, issue),
            integration_classifier=self.integration_classifiers.get(instance_id),
        )
        await self.health_monitors[instance_id].start()
        logger.info(f"[{instance_id}] ✓ Health monitor started")

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

        # 9g. Initialize out-of-scope auditor (if enabled)
        if self.config.monitoring.out_of_scope_audit.enabled:
            try:
                from ha_boss.monitoring.out_of_scope_audit import OutOfScopeAuditor

                logger.info(f"[{instance_id}] Initializing out-of-scope auditor...")
                if self.database is None:
                    raise RuntimeError("Database must be initialized before creating auditor")
                self.out_of_scope_auditors[instance_id] = OutOfScopeAuditor(
                    ha_client=self.ha_clients[instance_id],
                    entity_discovery=self.entity_discoveries.get(instance_id),
                    integration_discovery=self.integration_discoveries.get(instance_id),
                    database=self.database,
                    notification_manager=self.notification_managers[instance_id],
                    config=self.config,
                    instance_id=instance_id,
                )
                logger.info(f"[{instance_id}] ✓ Out-of-scope auditor initialized")
            except Exception as e:
                logger.warning(
                    f"[{instance_id}] Failed to initialize out-of-scope auditor: {e}. "
                    "Audit feature disabled for this instance."
                )

        # 9h. Initialize action verifier (if enabled)
        if self.config.monitoring.action_verification.enabled:
            try:
                from ha_boss.monitoring.action_verifier import ActionVerifier

                logger.info(f"[{instance_id}] Initializing action verifier...")
                self.action_verifiers[instance_id] = ActionVerifier(
                    ha_client=self.ha_clients[instance_id],
                    notification_manager=self.notification_managers[instance_id],
                    config=self.config,
                    instance_id=instance_id,
                )
                logger.info(f"[{instance_id}] ✓ Action verifier initialized")
            except Exception as e:
                logger.warning(
                    f"[{instance_id}] Failed to initialize action verifier: {e}. "
                    "Action verification disabled for this instance."
                )

        # 10. Connect WebSocket
        logger.info(f"[{instance_id}] Connecting to Home Assistant WebSocket...")
        action_verifier = self.action_verifiers.get(instance_id)
        self.websocket_clients[instance_id] = WebSocketClient(
            instance=instance,
            config=self.config,
            entity_discovery=self.entity_discoveries.get(instance_id),
            on_state_changed=lambda event: self._on_websocket_state_changed(instance_id, event),
            on_service_call=(
                action_verifier.handle_service_call if action_verifier is not None else None
            ),
        )
        await self.websocket_clients[instance_id].start()

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
            # First check config file instances
            instances = self.config.home_assistant.instances

            # If no config instances, try to load from database (dashboard-configured)
            if not instances:
                logger.info(
                    "No instances in config, checking database for dashboard-configured instances..."
                )
                from ha_boss.core.config_service import ConfigService

                config_service = ConfigService(self.database)
                db_instances = await config_service.get_active_instances_for_startup()

                if db_instances:
                    logger.info(f"Found {len(db_instances)} instance(s) in database")
                    from ha_boss.core.config import HomeAssistantInstance

                    instances = [
                        HomeAssistantInstance(
                            instance_id=inst_id,
                            url=url,
                            token=token,
                            bridge_enabled=bridge_enabled,
                        )
                        for inst_id, url, token, bridge_enabled in db_instances
                    ]

            # If still no instances, start in API-only mode
            if not instances:
                logger.warning("No Home Assistant instances configured.")
                raise ValueError("No Home Assistant instances configured. Cannot start service.")

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

            self.state = ServiceState.RUNNING
            logger.info("✅ HA Boss service started successfully")
            logger.info(f"Mode: {self.config.mode}")

        except Exception as e:
            self.state = ServiceState.ERROR
            logger.error(f"Failed to start service: {e}", exc_info=True)
            # Cleanup on failure
            await self._cleanup()
            raise

    def _start_background_tasks(self) -> None:
        """Start all background tasks for all instances."""
        # Start tasks for each instance
        # Note: WebSocket is already started in _initialize_instance() via start()
        # which creates its own internal listening loop - no need to start again here
        for instance_id in self.websocket_clients:
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

            # Periodic out-of-scope audit (if enabled and interval > 0)
            auditor = self.out_of_scope_auditors.get(instance_id)
            audit_cfg = self.config.monitoring.out_of_scope_audit
            if auditor and audit_cfg.enabled and audit_cfg.interval_seconds > 0:
                task = asyncio.create_task(self._periodic_out_of_scope_audit(instance_id))
                task.set_name(f"periodic_out_of_scope_audit_{instance_id}")
                self._tasks.append(task)

        # Note: HealthMonitor runs its own internal monitoring loop (per instance)
        # No need for separate periodic health check task here

        logger.info(
            f"Started {len(self._tasks)} background tasks for {len(self.websocket_clients)} instance(s)"
        )

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

    async def _periodic_out_of_scope_audit(self, instance_id: str) -> None:
        """Periodically run the out-of-scope entity audit.

        Sleeps for the configured interval between runs so the first run
        happens after one full interval (startup is already busy).

        Args:
            instance_id: Home Assistant instance identifier
        """
        interval = self.config.monitoring.out_of_scope_audit.interval_seconds

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

            auditor = self.out_of_scope_auditors.get(instance_id)
            if auditor is None:
                break

            try:
                stats = await auditor.run_audit()
                logger.info(
                    f"[{instance_id}] Out-of-scope audit: "
                    f"{stats.get('new_count', 0)} new, "
                    f"{stats.get('chronic_count', 0)} chronic, "
                    f"{stats.get('recovered_count', 0)} recovered"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{instance_id}] Error in out-of-scope audit: {e}", exc_info=True)

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
        self, instance_id: str, new_state: EntityState, old_state: EntityState | None
    ) -> None:
        """Callback when entity state is updated.

        Args:
            instance_id: Home Assistant instance identifier
            new_state: New entity state
            old_state: Previous state (if any)
        """

        # Trigger health check for this specific entity on the correct instance
        health_monitor = self.health_monitors.get(instance_id)
        if health_monitor:
            try:
                issue = await health_monitor.check_entity_now(new_state.entity_id)
                if issue:
                    logger.debug(
                        f"[{instance_id}] State update triggered health issue for "
                        f"{new_state.entity_id}: {issue.issue_type}"
                    )
                    # Trigger healing for this issue
                    await self._on_health_issue(instance_id, issue)
            except Exception as e:
                logger.error(
                    f"[{instance_id}] Error checking health for {new_state.entity_id}: {e}",
                    exc_info=True,
                )

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
            # In monitor-and-notify mode, clear any prior issue-detected alert WITHOUT
            # emitting a recovery notification (a user who only enabled on_issue_detected
            # did not opt into recovery alerts; those remain tied to healing).
            escalation_manager = self.escalation_managers.get(instance_id)
            if escalation_manager and self.config.notifications.on_issue_detected:
                try:
                    await escalation_manager.dismiss_issue_detected(issue.entity_id)
                except Exception as e:
                    logger.debug(
                        f"[{instance_id}] Failed to clear issue-detected notification for "
                        f"{issue.entity_id}: {e}"
                    )
            return

        # Get instance components
        pattern_collector = self.pattern_collectors.get(instance_id)
        integration_discovery = self.integration_discoveries.get(instance_id)
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

        # Monitor-and-notify: alert on detection without reloading anything
        if escalation_manager and issue.issue_type in ("unavailable", "stale"):
            try:
                await escalation_manager.notify_issue_detected(issue)
            except Exception as e:
                logger.error(
                    f"[{instance_id}] Failed to send issue-detected notification for "
                    f"{issue.entity_id}: {e}"
                )

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

            # Cancel any pending action verification tasks
            action_verifier = self.action_verifiers.get(instance_id)
            if action_verifier:
                try:
                    await action_verifier.shutdown()
                except Exception as e:
                    logger.error(f"[{instance_id}] Error shutting down action verifier: {e}")

            # Remove new components from dictionaries
            self.out_of_scope_auditors.pop(instance_id, None)
            self.action_verifiers.pop(instance_id, None)

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
            "healing_enabled": False,
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
