"""Healing strategies for auto-healing failed integrations."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ha_boss.core.config import Config
from ha_boss.core.database import Database, Entity, HealingAction, Integration
from ha_boss.core.exceptions import (
    CircuitBreakerOpenError,
    HealingFailedError,
    IntegrationNotFoundError,
)
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.integration_manager import IntegrationDiscovery
from ha_boss.monitoring.health_monitor import HealthIssue

logger = logging.getLogger(__name__)


class HealingManager:
    """Manages auto-healing attempts with safety mechanisms.

    Features:
    - Circuit breaker: Stops retrying after threshold failures
    - Cooldown: Prevents rapid retry loops
    - Dry-run mode: Test without executing
    - Database tracking: Records all healing attempts
    - Escalation: Notifies when healing fails
    """

    def __init__(
        self,
        config: Config,
        database: Database,
        ha_client: HomeAssistantClient,
        integration_discovery: IntegrationDiscovery,
    ) -> None:
        """Initialize healing manager.

        Args:
            config: HA Boss configuration
            database: Database manager
            ha_client: Home Assistant API client
            integration_discovery: Integration discovery service
        """
        self.config = config
        self.database = database
        self.ha_client = ha_client
        self.integration_discovery = integration_discovery

        # Track last healing attempt per integration for cooldown
        # integration_id -> last_attempt_time
        self._last_attempt: dict[str, datetime] = {}

        # Track consecutive failures per integration (in-memory cache)
        # integration_id -> failure_count
        self._failure_count: dict[str, int] = {}

    async def heal(self, health_issue: HealthIssue) -> bool:
        """Attempt to heal a health issue.

        Args:
            health_issue: Health issue to heal

        Returns:
            True if healing was successful, False otherwise

        Raises:
            IntegrationNotFoundError: If entity's integration cannot be found
            CircuitBreakerOpenError: If circuit breaker is open for this integration
        """
        entity_id = health_issue.entity_id
        issue_type = health_issue.issue_type

        logger.info(f"Attempting to heal {entity_id} ({issue_type})")

        # Check if healing is suppressed for this entity
        if await self._is_healing_suppressed(entity_id):
            logger.info(f"Healing suppressed for {entity_id}, skipping (issue: {issue_type})")
            return False

        # Look up integration for this entity
        integration_id = self.integration_discovery.get_integration_for_entity(entity_id)
        if not integration_id:
            raise IntegrationNotFoundError(
                f"Cannot find integration for entity {entity_id}. "
                "Run integration discovery first."
            )

        integration_details = self.integration_discovery.get_integration_details(integration_id)
        integration_name = integration_details["title"] if integration_details else integration_id

        # Check circuit breaker
        await self._check_circuit_breaker(integration_id, integration_name)

        # Check cooldown
        await self._check_cooldown(integration_id, integration_name)

        # Get current attempt number
        attempt_number = await self._get_next_attempt_number(entity_id, integration_id)

        # Execute healing
        start_time = datetime.now(UTC)
        success = False
        error_message: str | None = None

        try:
            if self.config.is_dry_run:
                logger.info(
                    f"[DRY RUN] Would reload integration {integration_name} ({integration_id})"
                )
                # Simulate delay
                await asyncio.sleep(0.1)
                success = True
            else:
                # Actually perform the reload
                await self.ha_client.reload_integration(integration_id)
                success = True
                logger.info(
                    f"Successfully reloaded integration {integration_name} for entity {entity_id}"
                )

        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(
                f"Failed to reload integration {integration_name}: {e}",
                exc_info=True,
            )

        # Calculate duration
        duration = (datetime.now(UTC) - start_time).total_seconds()

        # Record attempt in database
        await self._record_healing_action(
            entity_id=entity_id,
            integration_id=integration_id,
            attempt_number=attempt_number,
            success=success,
            error=error_message,
            duration=duration,
        )

        # Update tracking
        self._last_attempt[integration_id] = datetime.now(UTC)

        if success:
            # Reset failure count on success
            self._failure_count[integration_id] = 0
            await self._update_integration_success(integration_id)
        else:
            # Increment failure count
            current_failures = self._failure_count.get(integration_id, 0) + 1
            self._failure_count[integration_id] = current_failures
            await self._update_integration_failure(integration_id, current_failures)

            # Check if we should open circuit breaker
            if current_failures >= self.config.healing.circuit_breaker_threshold:
                logger.warning(
                    f"Circuit breaker threshold reached for {integration_name} "
                    f"({current_failures} failures)"
                )
                await self._open_circuit_breaker(integration_id)

            raise HealingFailedError(
                f"Failed to heal {entity_id}: {error_message or 'Unknown error'}"
            )

        return success

    async def _check_circuit_breaker(self, integration_id: str, integration_name: str) -> None:
        """Check if circuit breaker is open for an integration.

        Args:
            integration_id: Integration entry ID
            integration_name: Human-readable integration name

        Raises:
            CircuitBreakerOpenError: If circuit breaker is open
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(Integration).where(
                    Integration.instance_id == self.ha_client.instance_id,
                    Integration.entry_id == integration_id,
                )
            )
            integration = result.scalar_one_or_none()

            if integration and integration.circuit_breaker_open_until:
                now = datetime.now(UTC)
                # SQLite doesn't preserve timezone, so add UTC if naive
                cb_until = integration.circuit_breaker_open_until
                if cb_until.tzinfo is None:
                    cb_until = cb_until.replace(tzinfo=UTC)
                if cb_until > now:
                    time_remaining = cb_until - now
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open for {integration_name}. "
                        f"Retry in {time_remaining.total_seconds():.0f} seconds."
                    )
                else:
                    # Circuit breaker timeout expired, reset it
                    logger.info(
                        f"Circuit breaker timeout expired for {integration_name}, resetting"
                    )
                    integration.circuit_breaker_open_until = None
                    integration.consecutive_failures = 0
                    await session.commit()

    async def _check_cooldown(self, integration_id: str, integration_name: str) -> None:
        """Check if cooldown period has passed since last attempt.

        Args:
            integration_id: Integration entry ID
            integration_name: Human-readable integration name

        Raises:
            HealingFailedError: If cooldown period has not passed
        """
        if integration_id in self._last_attempt:
            last_attempt = self._last_attempt[integration_id]
            cooldown = timedelta(seconds=self.config.healing.cooldown_seconds)
            time_since_last = datetime.now(UTC) - last_attempt

            if time_since_last < cooldown:
                time_remaining = cooldown - time_since_last
                raise HealingFailedError(
                    f"Cooldown active for {integration_name}. "
                    f"Retry in {time_remaining.total_seconds():.0f} seconds."
                )

    async def _get_next_attempt_number(self, entity_id: str, integration_id: str) -> int:
        """Get the next attempt number for this entity/integration.

        Args:
            entity_id: Entity ID
            integration_id: Integration entry ID

        Returns:
            Next attempt number (starts at 1)
        """
        async with self.database.async_session() as session:
            # Count previous attempts for this entity and integration
            result = await session.execute(
                select(HealingAction).where(
                    HealingAction.entity_id == entity_id,
                    HealingAction.integration_id == integration_id,
                )
            )
            previous_attempts = result.scalars().all()
            return len(previous_attempts) + 1

    async def _record_healing_action(
        self,
        entity_id: str,
        integration_id: str,
        attempt_number: int,
        success: bool,
        error: str | None,
        duration: float,
    ) -> None:
        """Record healing action to database.

        Args:
            entity_id: Entity ID that was healed
            integration_id: Integration that was reloaded
            attempt_number: Attempt number
            success: Whether healing succeeded
            error: Error message if failed
            duration: Duration in seconds
        """
        async with self.database.async_session() as session:
            action = HealingAction(
                instance_id=self.ha_client.instance_id,
                entity_id=entity_id,
                integration_id=integration_id,
                action="reload_integration",
                attempt_number=attempt_number,
                timestamp=datetime.now(UTC),
                success=success,
                error=error,
                duration_seconds=duration,
            )
            session.add(action)
            await session.commit()

    async def _update_integration_success(self, integration_id: str) -> None:
        """Update integration after successful healing.

        Args:
            integration_id: Integration entry ID
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(Integration).where(
                    Integration.instance_id == self.ha_client.instance_id,
                    Integration.entry_id == integration_id,
                )
            )
            integration = result.scalar_one_or_none()

            if integration:
                integration.last_successful_reload = datetime.now(UTC)
                integration.consecutive_failures = 0
                integration.circuit_breaker_open_until = None
                await session.commit()

    async def _update_integration_failure(self, integration_id: str, failure_count: int) -> None:
        """Update integration after failed healing.

        Args:
            integration_id: Integration entry ID
            failure_count: Current consecutive failure count
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(Integration).where(
                    Integration.instance_id == self.ha_client.instance_id,
                    Integration.entry_id == integration_id,
                )
            )
            integration = result.scalar_one_or_none()

            if integration:
                integration.consecutive_failures = failure_count
                await session.commit()

    async def _open_circuit_breaker(self, integration_id: str) -> None:
        """Open circuit breaker for an integration.

        Args:
            integration_id: Integration entry ID
        """
        reset_time = datetime.now(UTC) + timedelta(
            seconds=self.config.healing.circuit_breaker_reset_seconds
        )

        async with self.database.async_session() as session:
            result = await session.execute(
                select(Integration).where(
                    Integration.instance_id == self.ha_client.instance_id,
                    Integration.entry_id == integration_id,
                )
            )
            integration = result.scalar_one_or_none()

            if integration:
                integration.circuit_breaker_open_until = reset_time
                await session.commit()

                logger.warning(f"Circuit breaker opened for {integration.title} until {reset_time}")

    async def _is_healing_suppressed(self, entity_id: str) -> bool:
        """Check if healing is suppressed for an entity.

        Args:
            entity_id: Entity ID to check

        Returns:
            True if healing is suppressed, False otherwise
        """
        try:
            async with self.database.async_session() as session:
                result = await session.execute(
                    select(Entity.healing_suppressed).where(
                        Entity.instance_id == self.ha_client.instance_id,
                        Entity.entity_id == entity_id,
                    )
                )
                row = result.scalar_one_or_none()
                return bool(row) if row is not None else False
        except Exception as e:
            logger.warning(f"Error checking healing suppression for {entity_id}: {e}")
            return False

    async def can_heal(self, entity_id: str) -> tuple[bool, str]:
        """Check if entity can be healed (without attempting).

        Args:
            entity_id: Entity ID to check

        Returns:
            Tuple of (can_heal: bool, reason: str)
        """
        # Check if healing is suppressed
        if await self._is_healing_suppressed(entity_id):
            return False, "Healing is suppressed for this entity"

        # Check if integration is known
        integration_id = self.integration_discovery.get_integration_for_entity(entity_id)
        if not integration_id:
            return False, "Integration not found for entity"

        integration_details = self.integration_discovery.get_integration_details(integration_id)
        integration_name = integration_details["title"] if integration_details else integration_id

        # Check circuit breaker
        try:
            await self._check_circuit_breaker(integration_id, integration_name)
        except CircuitBreakerOpenError as e:
            return False, str(e)

        # Check cooldown
        if integration_id in self._last_attempt:
            last_attempt = self._last_attempt[integration_id]
            cooldown = timedelta(seconds=self.config.healing.cooldown_seconds)
            time_since_last = datetime.now(UTC) - last_attempt

            if time_since_last < cooldown:
                time_remaining = cooldown - time_since_last
                return False, f"Cooldown active ({time_remaining.total_seconds():.0f}s remaining)"

        return True, "Can heal"

    async def get_healing_stats(self, entity_id: str | None = None) -> dict[str, Any]:
        """Get healing statistics.

        Args:
            entity_id: Optional entity ID to filter by

        Returns:
            Dictionary with healing statistics
        """
        async with self.database.async_session() as session:
            query = select(HealingAction)
            if entity_id:
                query = query.where(HealingAction.entity_id == entity_id)

            result = await session.execute(query)
            actions = result.scalars().all()

            total_attempts = len(actions)
            successful = sum(1 for a in actions if a.success)
            failed = total_attempts - successful

            avg_duration = (
                sum(a.duration_seconds for a in actions if a.duration_seconds) / total_attempts
                if total_attempts > 0
                else 0.0
            )

            return {
                "total_attempts": total_attempts,
                "successful": successful,
                "failed": failed,
                "success_rate": (successful / total_attempts * 100) if total_attempts > 0 else 0.0,
                "avg_duration_seconds": avg_duration,
            }


async def create_healing_manager(
    config: Config,
    database: Database,
    ha_client: HomeAssistantClient,
    integration_discovery: IntegrationDiscovery,
) -> HealingManager:
    """Create a healing manager.

    Args:
        config: HA Boss configuration
        database: Database manager
        ha_client: Home Assistant API client
        integration_discovery: Integration discovery service

    Returns:
        Initialized healing manager
    """
    return HealingManager(config, database, ha_client, integration_discovery)
