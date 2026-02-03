"""Health monitoring for Home Assistant entities."""

import asyncio
import fnmatch
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.database import Database, HealthEvent
from ha_boss.core.exceptions import DatabaseError
from ha_boss.core.types import HealthIssue
from ha_boss.monitoring.state_tracker import EntityState, StateTracker

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Monitors entity health and detects issues.

    Tracks entity states and detects:
    - Unavailable entities (state = "unavailable")
    - Unknown entities (state = "unknown")
    - Stale entities (no updates for configured threshold)

    Respects grace periods to avoid false positives from transient issues.
    """

    def __init__(
        self,
        config: Config,
        database: Database,
        state_tracker: StateTracker,
        on_issue_detected: Callable[[HealthIssue], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Initialize health monitor.

        Args:
            config: HA Boss configuration
            database: Database manager
            state_tracker: State tracker for entity states
            on_issue_detected: Optional callback when issue detected
        """
        self.config = config
        self.database = database
        self.state_tracker = state_tracker
        self.on_issue_detected = on_issue_detected

        # Track when issues were first detected (for grace period)
        # entity_id -> (issue_type, first_detected_time)
        self._issue_tracker: dict[str, tuple[str, datetime]] = {}

        # Track previously reported issues to avoid duplicate notifications
        self._reported_issues: set[str] = set()  # entity_id

        # Monitoring task
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start health monitoring loop."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started")

    async def stop(self) -> None:
        """Stop health monitoring loop."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop - periodically checks entity health."""
        while self._running:
            try:
                await self._check_all_entities()
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}", exc_info=True)

            # Sleep until next check (use a fraction of grace period)
            check_interval = max(30, self.config.monitoring.grace_period_seconds // 2)
            await asyncio.sleep(check_interval)

    async def _check_all_entities(self) -> None:
        """Check health of all monitored entities."""
        all_states = await self.state_tracker.get_all_states()

        for entity_id, entity_state in all_states.items():
            # Skip entities excluded from monitoring
            if not self._should_monitor_entity(entity_id):
                continue

            await self._check_entity_health(entity_state)

    async def _check_entity_health(self, entity_state: EntityState) -> None:
        """Check health of a single entity.

        Args:
            entity_state: Current entity state
        """
        issue_type = self._detect_issue_type(entity_state)

        if issue_type:
            # Issue detected
            await self._handle_detected_issue(entity_state, issue_type)
        else:
            # Entity is healthy
            await self._handle_recovery(entity_state)

    def _detect_issue_type(self, entity_state: EntityState) -> str | None:
        """Detect what type of issue (if any) an entity has.

        Args:
            entity_state: Current entity state

        Returns:
            Issue type string or None if healthy
        """
        state = entity_state.state

        # Check for unavailable state
        if state == "unavailable":
            return "unavailable"

        # Check for unknown state
        if state == "unknown":
            return "unknown"

        # Check for stale state (no updates for threshold period)
        time_since_update = datetime.now(UTC) - entity_state.last_updated
        stale_threshold = timedelta(seconds=self.config.monitoring.stale_threshold_seconds)

        if time_since_update > stale_threshold:
            return "stale"

        return None

    async def _handle_detected_issue(self, entity_state: EntityState, issue_type: str) -> None:
        """Handle a detected health issue.

        Args:
            entity_state: Entity with issue
            issue_type: Type of issue detected
        """
        entity_id = entity_state.entity_id
        now = datetime.now(UTC)

        # Check if this is a new issue or continuation
        if entity_id in self._issue_tracker:
            tracked_type, first_detected = self._issue_tracker[entity_id]

            # If issue type changed, reset tracking
            if tracked_type != issue_type:
                self._issue_tracker[entity_id] = (issue_type, now)
                return

            # Check if grace period has elapsed
            time_in_issue = now - first_detected
            grace_period = timedelta(seconds=self.config.monitoring.grace_period_seconds)

            if time_in_issue < grace_period:
                # Still in grace period, don't report yet
                return

            # Grace period elapsed - report if not already reported
            if entity_id not in self._reported_issues:
                await self._report_issue(entity_state, issue_type, first_detected)
                self._reported_issues.add(entity_id)

        else:
            # New issue detected - start tracking
            self._issue_tracker[entity_id] = (issue_type, now)

    async def _handle_recovery(self, entity_state: EntityState) -> None:
        """Handle entity recovery from issue.

        Args:
            entity_state: Entity that has recovered
        """
        entity_id = entity_state.entity_id

        # Check if entity was previously in issue state
        if entity_id in self._issue_tracker:
            tracked_type, first_detected = self._issue_tracker[entity_id]

            # Remove from tracking
            del self._issue_tracker[entity_id]

            # If issue was reported, report recovery
            if entity_id in self._reported_issues:
                await self._report_recovery(entity_state, tracked_type)
                self._reported_issues.remove(entity_id)
            else:
                # Issue resolved during grace period - no action needed
                logger.debug(
                    f"Entity {entity_id} recovered from {tracked_type} during grace period"
                )

    async def _report_issue(
        self, entity_state: EntityState, issue_type: str, first_detected: datetime
    ) -> None:
        """Report a health issue after grace period.

        Args:
            entity_state: Entity with issue
            issue_type: Type of issue
            first_detected: When issue was first detected
        """
        entity_id = entity_state.entity_id

        logger.warning(
            f"Health issue detected for {entity_id}: {issue_type} "
            f"(first detected: {first_detected})"
        )

        # Create health issue object
        issue = HealthIssue(
            entity_id=entity_id,
            issue_type=issue_type,
            detected_at=first_detected,
            details={
                "state": entity_state.state,
                "last_updated": entity_state.last_updated.isoformat(),
                "grace_period_seconds": self.config.monitoring.grace_period_seconds,
            },
        )

        # Persist to database
        await self._persist_health_event(issue)

        # Call callback if registered
        if self.on_issue_detected:
            try:
                await self.on_issue_detected(issue)
            except Exception as e:
                logger.error(f"Error in issue_detected callback: {e}", exc_info=True)

    async def _report_recovery(self, entity_state: EntityState, previous_issue_type: str) -> None:
        """Report entity recovery from health issue.

        Args:
            entity_state: Entity that recovered
            previous_issue_type: Type of issue it recovered from
        """
        entity_id = entity_state.entity_id

        logger.info(f"Entity {entity_id} recovered from {previous_issue_type}")

        # Create recovery event
        issue = HealthIssue(
            entity_id=entity_id,
            issue_type="recovered",
            detected_at=datetime.now(UTC),
            details={
                "previous_issue": previous_issue_type,
                "current_state": entity_state.state,
                "last_updated": entity_state.last_updated.isoformat(),
            },
        )

        # Persist to database
        await self._persist_health_event(issue)

    async def _persist_health_event(self, issue: HealthIssue) -> None:
        """Persist health event to database.

        Args:
            issue: Health issue to persist
        """
        try:
            async with self.database.async_session() as session:
                event = HealthEvent(
                    instance_id=self.state_tracker.instance_id,
                    entity_id=issue.entity_id,
                    event_type=issue.issue_type,
                    timestamp=issue.detected_at,
                    details=issue.details,
                )
                session.add(event)
                await session.commit()

        except Exception as e:
            logger.error(
                f"Failed to persist health event for {issue.entity_id}: {e}", exc_info=True
            )
            raise DatabaseError(f"Failed to persist health event: {e}") from e

    def _should_monitor_entity(self, entity_id: str) -> bool:
        """Check if entity should be monitored based on include/exclude patterns.

        Args:
            entity_id: Entity identifier

        Returns:
            True if entity should be monitored
        """
        # Check exclude patterns first
        for pattern in self.config.monitoring.exclude:
            if fnmatch.fnmatch(entity_id, pattern):
                return False

        # If include list is empty, monitor all (except excluded)
        if not self.config.monitoring.include:
            return True

        # Check include patterns
        for pattern in self.config.monitoring.include:
            if fnmatch.fnmatch(entity_id, pattern):
                return True

        return False

    async def check_entity_now(self, entity_id: str) -> HealthIssue | None:
        """Manually check health of a specific entity (bypasses grace period).

        Args:
            entity_id: Entity identifier

        Returns:
            Health issue if detected, None if healthy
        """
        entity_state = await self.state_tracker.get_state(entity_id)
        if not entity_state:
            return None

        issue_type = self._detect_issue_type(entity_state)
        if not issue_type:
            return None

        return HealthIssue(
            entity_id=entity_id,
            issue_type=issue_type,
            detected_at=datetime.now(UTC),
            details={
                "state": entity_state.state,
                "last_updated": entity_state.last_updated.isoformat(),
            },
        )


async def create_health_monitor(
    config: Config,
    database: Database,
    state_tracker: StateTracker,
    on_issue_detected: Callable[[HealthIssue], Coroutine[Any, Any, None]] | None = None,
) -> HealthMonitor:
    """Create and start a health monitor.

    Args:
        config: HA Boss configuration
        database: Database manager
        state_tracker: State tracker for entity states
        on_issue_detected: Optional callback when issue detected

    Returns:
        Started health monitor
    """
    monitor = HealthMonitor(config, database, state_tracker, on_issue_detected=on_issue_detected)
    await monitor.start()
    return monitor
