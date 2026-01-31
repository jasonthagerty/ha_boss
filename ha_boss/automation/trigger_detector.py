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

        Args:
            automation_id: Automation ID
            state_change: State change event with initial and final states

        Returns:
            True if automation should have been triggered by state change

        Raises:
            ValueError: If automation_id or state_change is invalid
        """
        if not automation_id or not isinstance(automation_id, str):
            raise ValueError(f"Invalid automation_id: {automation_id}")

        if not state_change or not isinstance(state_change, dict):
            raise ValueError(f"Invalid state_change: {state_change}")

        try:
            # Get automation configuration
            desired_states = await self._get_automation_config(automation_id)

            if not desired_states:
                logger.debug(f"No desired states found for {automation_id}")
                return False

            # Check if any desired state changed
            final = state_change.get("final", {})

            for desired in desired_states:
                entity_id = desired.entity_id
                desired_state = desired.desired_state

                final_state = final.get(entity_id, {}).get("state")

                # Check if state transitioned to desired state
                if final_state and self._compare_states(desired_state, final_state):
                    # State reached desired value - trigger should have fired
                    return True

            return False

        except Exception as e:
            logger.error(
                f"Error validating trigger for {automation_id}: {e}",
                exc_info=True,
            )
            return False

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

            # Query states for all entities
            states: dict[str, dict[str, Any]] = {}
            for entity_id in entity_ids:
                try:
                    state = await self.ha_client.get_state(entity_id)
                    if state:
                        states[entity_id] = state
                except Exception as e:
                    logger.warning(f"Failed to get state for {entity_id}: {e}")
                    # Continue with other entities

            return states if states else None

        except Exception as e:
            logger.error(
                f"Error getting trigger entity states: {e}",
                exc_info=True,
            )
            return None

    async def _get_automation_config(self, automation_id: str) -> list[AutomationDesiredState]:
        """Get automation configuration from database.

        Args:
            automation_id: Automation entity ID

        Returns:
            List of desired states for the automation

        Raises:
            ValueError: If automation_id is invalid
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

        except Exception as e:
            logger.error(
                f"Error querying automation config for {automation_id}: {e}",
                exc_info=True,
            )
            return []

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

    def _compare_states(self, desired: str, actual: str | None) -> bool:
        """Compare desired and actual states.

        Args:
            desired: Desired state value
            actual: Actual state value

        Returns:
            True if states match (case-insensitive)
        """
        if actual is None:
            return False

        # Case-insensitive comparison
        return desired.lower() == actual.lower()
