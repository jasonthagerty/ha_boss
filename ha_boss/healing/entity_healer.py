"""Entity-level healing strategies for automation failures.

This module implements Level 1 healing in the goal-oriented healing cascade.
Entity-level healing attempts to fix individual entity failures by:
1. Retrying the last service call with exponential backoff
2. Trying alternative parameters based on entity type
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ha_boss.core.database import AutomationServiceCall, Database, EntityHealingAction
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class EntityHealingResult:
    """Result of entity-level healing attempt."""

    entity_id: str
    success: bool
    actions_attempted: list[str]  # e.g., ["retry_service_call", "alternative_params"]
    final_action: str | None  # Which action succeeded (if any)
    error_message: str | None
    total_duration_seconds: float


class EntityHealer:
    """Entity-level healer - Level 1 in healing cascade.

    Attempts to heal entity-specific failures by retrying service calls
    or trying alternative parameters appropriate for the entity type.
    """

    def __init__(
        self,
        database: Database,
        ha_client: HomeAssistantClient,
        instance_id: str = "default",
        max_retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        """Initialize entity healer.

        Args:
            database: Database manager for recording actions
            ha_client: Home Assistant API client for service calls
            instance_id: Instance identifier for multi-instance setups
            max_retry_attempts: Maximum retry attempts per strategy
            retry_base_delay: Base delay in seconds for exponential backoff
        """
        self.database = database
        self.ha_client = ha_client
        self.instance_id = instance_id
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_delay = retry_base_delay

    async def heal(
        self,
        entity_id: str,
        triggered_by: str = "automation_failure",
        automation_id: str | None = None,
        execution_id: int | None = None,
    ) -> EntityHealingResult:
        """Attempt entity-level healing.

        Healing strategies (in order):
        1. Retry last service call with same parameters
        2. Try alternative parameters based on entity type

        Args:
            entity_id: Entity to heal
            triggered_by: What triggered healing (automation_failure, manual, pattern)
            automation_id: Optional automation ID context
            execution_id: Optional execution ID for linking

        Returns:
            EntityHealingResult with success status and actions taken
        """
        start_time = datetime.now(UTC)
        actions_attempted: list[str] = []
        final_action: str | None = None
        error_message: str | None = None

        logger.info(f"Starting entity-level healing for {entity_id} (triggered_by={triggered_by})")

        # Validate inputs
        if not entity_id or not entity_id.strip():
            return EntityHealingResult(
                entity_id=entity_id,
                success=False,
                actions_attempted=[],
                final_action=None,
                error_message="Invalid entity_id: cannot be empty",
                total_duration_seconds=0.0,
            )

        try:
            # Strategy 1: Get last service call and retry it
            last_service_call = await self._get_last_service_call(entity_id)

            if last_service_call:
                service_domain, service_name, service_data = last_service_call
                actions_attempted.append("retry_service_call")

                logger.info(f"Attempting retry of {service_domain}.{service_name} for {entity_id}")

                success = await self._retry_service_call(
                    entity_id=entity_id,
                    service_domain=service_domain,
                    service_name=service_name,
                    service_data=service_data,
                )

                if success:
                    final_action = "retry_service_call"
                    duration = (datetime.now(UTC) - start_time).total_seconds()
                    logger.info(f"Entity-level healing succeeded via retry for {entity_id}")
                    return EntityHealingResult(
                        entity_id=entity_id,
                        success=True,
                        actions_attempted=actions_attempted,
                        final_action=final_action,
                        error_message=None,
                        total_duration_seconds=duration,
                    )

                # Strategy 2: Try alternative parameters
                actions_attempted.append("alternative_params")
                logger.info(f"Retry failed, attempting alternative parameters for {entity_id}")

                success = await self._try_alternative_params(
                    entity_id=entity_id,
                    service_domain=service_domain,
                    service_name=service_name,
                    original_params=service_data,
                )

                if success:
                    final_action = "alternative_params"
                    duration = (datetime.now(UTC) - start_time).total_seconds()
                    logger.info(
                        f"Entity-level healing succeeded via alternative params for {entity_id}"
                    )
                    return EntityHealingResult(
                        entity_id=entity_id,
                        success=True,
                        actions_attempted=actions_attempted,
                        final_action=final_action,
                        error_message=None,
                        total_duration_seconds=duration,
                    )

                error_message = "All healing strategies failed"
            else:
                error_message = "No previous service call found for entity"
                logger.warning(f"Cannot heal {entity_id}: no service call history found")

        except Exception as e:
            error_message = f"Healing exception: {str(e)}"
            logger.error(f"Entity healing failed for {entity_id}: {e}", exc_info=True)

        duration = (datetime.now(UTC) - start_time).total_seconds()
        logger.info(
            f"Entity-level healing failed for {entity_id} after {len(actions_attempted)} strategies"
        )

        return EntityHealingResult(
            entity_id=entity_id,
            success=False,
            actions_attempted=actions_attempted,
            final_action=None,
            error_message=error_message,
            total_duration_seconds=duration,
        )

    async def _retry_service_call(
        self,
        entity_id: str,
        service_domain: str,
        service_name: str,
        service_data: dict[str, Any],
    ) -> bool:
        """Retry service call with exponential backoff.

        Logic:
        - Attempt up to max_retry_attempts times
        - Use exponential backoff: delay = base_delay * (2 ** attempt)
        - Record each attempt to database
        - Return True on success, False on failure

        Args:
            entity_id: Target entity
            service_domain: Service domain (e.g., "light")
            service_name: Service name (e.g., "turn_on")
            service_data: Service call data/parameters

        Returns:
            True if any retry succeeded, False otherwise
        """
        for attempt in range(self.max_retry_attempts):
            action_start = datetime.now(UTC)
            success = False
            error_message: str | None = None

            try:
                # Calculate delay for exponential backoff (skip delay on first attempt)
                if attempt > 0:
                    delay = self.retry_base_delay * (2**attempt)
                    logger.debug(f"Waiting {delay:.1f}s before retry attempt {attempt + 1}")
                    await asyncio.sleep(delay)

                # Attempt service call with timeout
                await asyncio.wait_for(
                    self.ha_client.call_service(
                        domain=service_domain,
                        service=service_name,
                        service_data=service_data,
                    ),
                    timeout=10.0,
                )

                success = True
                logger.info(
                    f"Service call retry succeeded on attempt {attempt + 1}/{self.max_retry_attempts}"
                )

            except TimeoutError:
                error_message = f"Service call timeout (attempt {attempt + 1})"
                logger.warning(f"{error_message} for {entity_id}")

            except Exception as e:
                error_message = f"Service call failed: {str(e)}"
                logger.warning(
                    f"Retry attempt {attempt + 1}/{self.max_retry_attempts} failed for {entity_id}: {e}"
                )

            # Record this retry attempt
            duration = (datetime.now(UTC) - action_start).total_seconds()
            await self._record_action(
                entity_id=entity_id,
                action_type="retry_service_call",
                service_domain=service_domain,
                service_name=service_name,
                service_data=service_data,
                triggered_by="automation_failure",
                automation_id=None,
                execution_id=None,
                success=success,
                error_message=error_message,
                duration_seconds=duration,
            )

            if success:
                return True

        return False

    async def _try_alternative_params(
        self,
        entity_id: str,
        service_domain: str,
        service_name: str,
        original_params: dict[str, Any],
    ) -> bool:
        """Try service call with alternative parameters.

        Entity-type specific alternatives:
        - light: Try brightness variations (50, 75, 100 if original failed)
        - climate: Try temp +/- 1 degree
        - cover: Try open/close/stop alternatives

        Args:
            entity_id: Target entity
            service_domain: Service domain
            service_name: Service name
            original_params: Original parameters that failed

        Returns:
            True if any alternative succeeded, False otherwise
        """
        alternatives = self._get_alternative_params(
            entity_id, service_domain, service_name, original_params
        )

        if not alternatives:
            logger.debug(f"No alternative parameters available for {entity_id}")
            return False

        logger.info(f"Trying {len(alternatives)} alternative parameter sets for {entity_id}")

        for alt_params in alternatives:
            action_start = datetime.now(UTC)
            success = False
            error_message: str | None = None

            try:
                # Attempt service call with alternative parameters
                await asyncio.wait_for(
                    self.ha_client.call_service(
                        domain=service_domain,
                        service=service_name,
                        service_data=alt_params,
                    ),
                    timeout=10.0,
                )

                success = True
                logger.info(f"Alternative parameters succeeded for {entity_id}: {alt_params}")

            except TimeoutError:
                error_message = "Service call timeout with alternative params"
                logger.debug(f"{error_message} for {entity_id}")

            except Exception as e:
                error_message = f"Alternative params failed: {str(e)}"
                logger.debug(f"Alternative failed for {entity_id}: {e}")

            # Record this alternative attempt
            duration = (datetime.now(UTC) - action_start).total_seconds()
            await self._record_action(
                entity_id=entity_id,
                action_type="alternative_params",
                service_domain=service_domain,
                service_name=service_name,
                service_data=alt_params,
                triggered_by="automation_failure",
                automation_id=None,
                execution_id=None,
                success=success,
                error_message=error_message,
                duration_seconds=duration,
            )

            if success:
                return True

        return False

    def _get_alternative_params(
        self,
        entity_id: str,
        service_domain: str,
        service_name: str,
        original_params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Generate alternative parameters based on entity type.

        Args:
            entity_id: Target entity
            service_domain: Service domain
            service_name: Service name
            original_params: Original parameters

        Returns:
            List of alternative parameter dictionaries to try
        """
        alternatives: list[dict[str, Any]] = []

        # Light entities - try brightness variations
        if service_domain == "light" and service_name in ("turn_on", "toggle"):
            # Create base params with entity_id
            base_params = {"entity_id": entity_id}

            # If original had brightness, try other brightness values
            if "brightness" in original_params or "brightness_pct" in original_params:
                for brightness in [50, 75, 100]:
                    alternatives.append({**base_params, "brightness_pct": brightness})
            else:
                # If no brightness specified, try with brightness
                alternatives.append({**base_params, "brightness_pct": 100})

        # Climate entities - try temperature variations
        elif service_domain == "climate" and service_name == "set_temperature":
            base_params = {"entity_id": entity_id}
            if "temperature" in original_params:
                original_temp = original_params["temperature"]
                # Try +/- 1 degree
                alternatives.append({**base_params, "temperature": original_temp + 1})
                alternatives.append({**base_params, "temperature": original_temp - 1})

        # Cover entities - try alternative actions
        elif service_domain == "cover":
            base_params = {"entity_id": entity_id}
            if service_name in ("open_cover", "close_cover"):
                # Try stop then retry original action
                alternatives.append({**base_params, "service": "stop_cover"})
            elif service_name == "set_cover_position":
                # Try standard positions
                alternatives.append({**base_params, "position": 0})
                alternatives.append({**base_params, "position": 50})
                alternatives.append({**base_params, "position": 100})

        # For switch and input_boolean, just return empty (retry is the only strategy)
        # These are simple on/off entities with no parameter variations

        return alternatives

    async def _record_action(
        self,
        entity_id: str,
        action_type: str,
        service_domain: str | None,
        service_name: str | None,
        service_data: dict[str, Any] | None,
        triggered_by: str,
        automation_id: str | None,
        execution_id: int | None,
        success: bool,
        error_message: str | None,
        duration_seconds: float,
    ) -> None:
        """Record healing action to database.

        Args:
            entity_id: Entity being healed
            action_type: Type of action ("retry_service_call", "alternative_params")
            service_domain: Service domain used
            service_name: Service name used
            service_data: Service call parameters
            triggered_by: What triggered healing
            automation_id: Optional automation ID
            execution_id: Optional execution ID
            success: Whether action succeeded
            error_message: Optional error message
            duration_seconds: Duration of action
        """
        async with self.database.async_session() as session:
            action = EntityHealingAction(
                instance_id=self.instance_id,
                entity_id=entity_id,
                action_type=action_type,
                service_domain=service_domain,
                service_name=service_name,
                service_data=service_data,
                triggered_by=triggered_by,
                automation_id=automation_id,
                execution_id=execution_id,
                success=success,
                error_message=error_message,
                duration_seconds=duration_seconds,
                created_at=datetime.now(UTC),
            )
            session.add(action)
            await session.commit()

    async def _get_last_service_call(
        self,
        entity_id: str,
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Get last service call for entity from automation_service_calls table.

        Args:
            entity_id: Entity to look up

        Returns:
            (service_domain, service_name, service_data) or None if not found

        Note:
            Service data is reconstructed from service_name and entity_id.
            The AutomationServiceCall table stores service_name as "domain.service"
            and doesn't store the full service_data dict.
        """
        async with self.database.async_session() as session:
            # Query for most recent service call for this entity
            result = await session.execute(
                select(AutomationServiceCall)
                .where(
                    AutomationServiceCall.instance_id == self.instance_id,
                    AutomationServiceCall.entity_id == entity_id,
                )
                .order_by(AutomationServiceCall.called_at.desc())
                .limit(1)
            )
            service_call = result.scalar_one_or_none()

            if not service_call:
                return None

            # Parse service_name which is stored as "domain.service"
            service_parts = service_call.service_name.split(".", 1)
            if len(service_parts) != 2:
                logger.warning(
                    f"Invalid service_name format: {service_call.service_name}, expected 'domain.service'"
                )
                return None

            service_domain = service_parts[0]
            service_name = service_parts[1]

            # Reconstruct basic service_data (just entity_id for now)
            # In a real scenario, we'd need to store more complete service_data
            service_data = {"entity_id": entity_id}

            logger.debug(
                f"Found last service call for {entity_id}: {service_domain}.{service_name}"
            )

            return (service_domain, service_name, service_data)
