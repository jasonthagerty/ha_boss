"""Trigger failure detection for automations.

This module detects when automation triggers fail to fire despite expected
state changes occurring. It monitors state changes after automation execution
and compares actual vs. expected trigger conditions.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ha_boss.core.database import AutomationDesiredState, Database
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class TriggerFailureContext:
    """Context for a detected trigger failure.

    Attributes:
        automation_id: ID of the automation that failed to trigger
        instance_id: Home Assistant instance identifier
        expected_trigger: Expected trigger conditions from automation config
        actual_state: Actual state changes that occurred
        timestamp: When the failure was detected
        detection_method: Method used to detect (state_change_monitoring)
    """

    automation_id: str
    instance_id: str
    expected_trigger: dict[str, Any]
    actual_state: dict[str, Any]
    timestamp: datetime
    detection_method: str = "state_change_monitoring"


class TriggerFailureDetector:
    """Detects when automation triggers fail to fire.

    Monitors state changes after automation execution and validates whether
    expected state transitions should have triggered the automation.

    Example:
        >>> detector = TriggerFailureDetector(database, ha_client, "default")
        >>> failure = await detector.monitor_state_changes(
        ...     automation_id="automation.my_automation",
        ...     expected_trigger={"entity_id": "sensor.temp", "above": 25},
        ...     validation_window=10
        ... )
        >>> if failure:
        ...     print(f"Trigger failed for {failure.automation_id}")
    """

    def __init__(
        self,
        database: Database,
        ha_client: HomeAssistantClient,
        instance_id: str = "default",
    ) -> None:
        """Initialize trigger failure detector.

        Args:
            database: Database for querying automation configurations
            ha_client: Home Assistant client for state queries
            instance_id: Home Assistant instance identifier
        """
        self.database = database
        self.ha_client = ha_client
        self.instance_id = instance_id

    async def monitor_state_changes(
        self,
        automation_id: str,
        expected_trigger: dict[str, Any],
        validation_window: int = 10,
    ) -> TriggerFailureContext | None:
        """Monitor for expected state changes within validation window.

        Waits for the specified validation window and collects all state
        changes for relevant entities. Validates whether the state changes
        should have triggered the automation.

        Args:
            automation_id: Automation to monitor
            expected_trigger: Expected trigger conditions from automation config
            validation_window: Seconds to wait for state changes (default: 10)

        Returns:
            TriggerFailureContext if trigger failed, None if successful or
            unable to determine

        Raises:
            ValueError: If automation_id is invalid
        """
        if not automation_id or not isinstance(automation_id, str):
            raise ValueError(f"Invalid automation_id: {automation_id}")

        if not expected_trigger or not isinstance(expected_trigger, dict):
            raise ValueError(f"Invalid expected_trigger: {expected_trigger}")

        if validation_window <= 0:
            raise ValueError(f"validation_window must be positive, got {validation_window}")

        try:
            logger.debug(
                f"Monitoring trigger for {automation_id} " f"with window={validation_window}s"
            )

            # Get initial states for entities in trigger
            initial_states = await self._get_trigger_entity_states(expected_trigger)

            if initial_states is None:
                logger.warning(
                    f"Could not get initial states for {automation_id}, "
                    "skipping trigger validation"
                )
                return None

            # Wait for the validation window
            await asyncio.sleep(validation_window)

            # Get final states after window
            final_states = await self._get_trigger_entity_states(expected_trigger)

            if final_states is None:
                logger.warning(
                    f"Could not get final states for {automation_id}, " "unable to validate trigger"
                )
                return None

            # Check if trigger should have fired
            trigger_should_fire = await self.validate_trigger_fired(
                automation_id,
                {"initial": initial_states, "final": final_states},
            )

            if trigger_should_fire:
                logger.warning(
                    f"Trigger failure detected for {automation_id}: "
                    f"state changes should have triggered automation but didn't"
                )
                return TriggerFailureContext(
                    automation_id=automation_id,
                    instance_id=self.instance_id,
                    expected_trigger=expected_trigger,
                    actual_state={"initial": initial_states, "final": final_states},
                    timestamp=datetime.now(UTC),
                    detection_method="state_change_monitoring",
                )

            logger.debug(
                f"Trigger validation passed for {automation_id}: "
                "state changes do not match expected trigger"
            )
            return None

        except TimeoutError:
            logger.error(f"Timeout waiting for state changes for {automation_id}")
            return None
        except Exception as e:
            logger.error(
                f"Error monitoring trigger for {automation_id}: {e}",
                exc_info=True,
            )
            return None

    async def validate_trigger_fired(
        self,
        automation_id: str,
        state_change: dict[str, Any],
    ) -> bool:
        """Check if state change should have triggered automation.

        This checks if the trigger CONDITION was met (the "IF" part),
        not if the desired outcome was achieved (the "THEN" part).

        Args:
            automation_id: Automation ID
            state_change: State change event with initial and final states

        Returns:
            True if automation should have been triggered by state change

        Raises:
            ValueError: If automation_id or state_change is invalid
            asyncio.TimeoutError: If database query times out
        """
        if not automation_id or not isinstance(automation_id, str):
            raise ValueError(f"Invalid automation_id: {automation_id}")

        if not state_change or not isinstance(state_change, dict):
            raise ValueError(f"Invalid state_change: {state_change}")

        # Get trigger configuration from database
        trigger_config = await self._get_trigger_config(automation_id)

        if not trigger_config:
            logger.debug(f"No trigger config found for {automation_id}")
            return False

        # Extract initial and final states
        initial = state_change.get("initial", {})
        final = state_change.get("final", {})

        # Check if state change matches trigger condition
        for trigger in trigger_config:
            platform = trigger.get("platform", "state")

            if platform == "state":
                if self._check_state_trigger(trigger, initial, final):
                    return True
            elif platform == "numeric_state":
                if self._check_numeric_trigger(trigger, initial, final):
                    return True

        return False

    def _check_state_trigger(
        self,
        trigger: dict[str, Any],
        initial: dict[str, dict[str, Any]],
        final: dict[str, dict[str, Any]],
    ) -> bool:
        """Check if state change matches state trigger condition.

        Args:
            trigger: State trigger configuration
            initial: Initial entity states
            final: Final entity states

        Returns:
            True if state change matches trigger condition
        """
        entity_id = trigger.get("entity_id")
        if not entity_id:
            return False

        # Get initial and final states for entity
        initial_state = initial.get(entity_id, {}).get("state")
        final_state = final.get(entity_id, {}).get("state")

        # Check 'to' condition (must transition TO this state)
        to_state = trigger.get("to")
        if to_state and not self._compare_states(to_state, final_state):
            return False

        # Check 'from' condition (must transition FROM this state)
        from_state = trigger.get("from")
        if from_state and not self._compare_states(from_state, initial_state):
            return False

        # If both 'to' and 'from' specified, both must match
        # If only 'to', just final state must match
        # If neither, any state change triggers
        return True

    def _check_numeric_trigger(
        self,
        trigger: dict[str, Any],
        initial: dict[str, dict[str, Any]],
        final: dict[str, dict[str, Any]],
    ) -> bool:
        """Check if state change matches numeric trigger condition.

        Args:
            trigger: Numeric trigger configuration
            initial: Initial entity states
            final: Final entity states

        Returns:
            True if numeric condition met
        """
        entity_id = trigger.get("entity_id")
        if not entity_id:
            return False

        # Get final numeric state
        final_state = final.get(entity_id, {}).get("state")
        if final_state is None:
            return False

        try:
            final_value = float(final_state)
        except (ValueError, TypeError):
            logger.debug(f"Cannot convert {final_state} to float for {entity_id}")
            return False

        # Check 'above' condition
        above = trigger.get("above")
        if above is not None:
            try:
                if final_value <= float(above):
                    return False
            except (ValueError, TypeError):
                logger.warning(f"Invalid 'above' value: {above}")
                return False

        # Check 'below' condition
        below = trigger.get("below")
        if below is not None:
            try:
                if final_value >= float(below):
                    return False
            except (ValueError, TypeError):
                logger.warning(f"Invalid 'below' value: {below}")
                return False

        return True

    async def _get_trigger_config(self, automation_id: str) -> list[dict[str, Any]]:
        """Get trigger configuration for automation.

        For now, this constructs trigger config from desired states.
        In the future, this could query actual automation YAML configs.

        Args:
            automation_id: Automation entity ID

        Returns:
            List of trigger configurations

        Raises:
            asyncio.TimeoutError: If database query times out
        """
        try:
            desired_states = await self._get_automation_config(automation_id)

            # Convert desired states to basic trigger configs
            triggers = []
            for desired in desired_states:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": desired.entity_id,
                        "to": desired.desired_state,
                    }
                )

            return triggers

        except TimeoutError:
            logger.error(f"Timeout getting trigger config for {automation_id}")
            raise

    async def _get_trigger_entity_states(
        self, expected_trigger: dict[str, Any]
    ) -> dict[str, dict[str, Any]] | None:
        """Get states for entities in trigger configuration.

        Args:
            expected_trigger: Trigger configuration dict

        Returns:
            Dict mapping entity_id to state dict, or None if unable to query

        Raises:
            ValueError: If trigger configuration is invalid
        """
        if not isinstance(expected_trigger, dict):
            raise ValueError(f"Invalid trigger: {expected_trigger}")

        try:
            # Extract entity IDs from trigger (supports various trigger formats)
            entity_ids = self._extract_entity_ids_from_trigger(expected_trigger)

            if not entity_ids:
                logger.debug("No entity IDs found in trigger")
                return None

            # Query states for all entities concurrently
            async def get_entity_state(entity_id: str) -> tuple[str, dict[str, Any] | None]:
                try:
                    state = await self.ha_client.get_state(entity_id)
                    return (entity_id, state)
                except Exception as e:
                    logger.warning(f"Failed to get state for {entity_id}: {e}")
                    return (entity_id, None)

            # Gather all state queries concurrently
            results = await asyncio.gather(*[get_entity_state(eid) for eid in entity_ids])

            # Build state dictionary from results
            states: dict[str, dict[str, Any]] = {}
            for entity_id, state in results:
                if state:
                    states[entity_id] = state

            return states if states else None

        except TimeoutError:
            logger.error("Timeout getting trigger entity states")
            raise
        except Exception as e:
            logger.error(
                f"Error getting trigger entity states: {e}",
                exc_info=True,
            )
            raise

    async def _get_automation_config(self, automation_id: str) -> list[AutomationDesiredState]:
        """Get automation configuration from database.

        Args:
            automation_id: Automation entity ID

        Returns:
            List of desired states for the automation

        Raises:
            ValueError: If automation_id is invalid
            asyncio.TimeoutError: If database query times out
        """
        if not automation_id or not isinstance(automation_id, str):
            raise ValueError(f"Invalid automation_id: {automation_id}")

        try:
            async with self.database.async_session() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(AutomationDesiredState).where(
                        AutomationDesiredState.instance_id == self.instance_id,
                        AutomationDesiredState.automation_id == automation_id,
                    )
                )
                return list(result.scalars().all())

        except TimeoutError:
            logger.error(f"Timeout querying automation config for {automation_id}")
            raise
        except Exception:
            logger.error(
                f"Database error querying automation config for {automation_id}",
                exc_info=True,
            )
            raise

    def _extract_entity_ids_from_trigger(self, trigger: dict[str, Any]) -> set[str]:
        """Extract entity IDs from trigger configuration.

        Supports common trigger formats:
        - entity_id: single or list
        - platform: state triggers with entity_id
        - for: numeric trigger with entity_id

        Args:
            trigger: Trigger configuration dict

        Returns:
            Set of entity IDs found in trigger
        """
        entity_ids: set[str] = set()

        if not isinstance(trigger, dict):
            return entity_ids

        # Direct entity_id field
        if "entity_id" in trigger:
            entity_id = trigger["entity_id"]
            if isinstance(entity_id, str):
                entity_ids.add(entity_id)
            elif isinstance(entity_id, list):
                entity_ids.update(e for e in entity_id if isinstance(e, str))

        # Nested in trigger_variables or other structures
        for _key, value in trigger.items():
            if isinstance(value, dict):
                entity_ids.update(self._extract_entity_ids_from_trigger(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        entity_ids.update(self._extract_entity_ids_from_trigger(item))

        return entity_ids

    def _compare_states(self, desired: str | None, actual: str | None) -> bool:
        """Compare desired and actual states.

        Args:
            desired: Desired state value
            actual: Actual state value

        Returns:
            True if states match (case-insensitive)
        """
        # Handle None cases
        if desired is None or actual is None:
            return False

        # Ensure both are strings
        if not isinstance(desired, str) or not isinstance(actual, str):
            return False

        # Case-insensitive comparison
        return desired.lower() == actual.lower()
