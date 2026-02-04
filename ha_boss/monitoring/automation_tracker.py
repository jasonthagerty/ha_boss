"""Track automation executions for pattern analysis."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ha_boss.automation.outcome_validator import OutcomeValidator
from ha_boss.core.config import Config
from ha_boss.core.database import AutomationExecution, AutomationServiceCall, Database
from ha_boss.core.ha_client import HomeAssistantClient

if TYPE_CHECKING:
    from ha_boss.automation.health_tracker import AutomationHealthTracker
    from ha_boss.healing.cascade_orchestrator import CascadeOrchestrator

logger = logging.getLogger(__name__)


class AutomationTracker:
    """Tracks automation executions and service calls for pattern analysis.

    This tracker records automation runs and their service calls to enable
    usage-based optimization recommendations. Data is stored in the database
    for analysis by AutomationAnalyzer.
    """

    def __init__(
        self,
        instance_id: str,
        database: Database,
        ha_client: HomeAssistantClient | None = None,
        config: Config | None = None,
        cascade_orchestrator: "CascadeOrchestrator | None" = None,
        health_tracker: "AutomationHealthTracker | None" = None,
    ):
        """Initialize automation tracker.

        Args:
            instance_id: Home Assistant instance identifier
            database: Database instance for storing tracking data
            ha_client: Home Assistant client for outcome validation (optional)
            config: Configuration for outcome validation (optional)
            cascade_orchestrator: CascadeOrchestrator for cascading healing (optional)
            health_tracker: AutomationHealthTracker for health tracking (optional)
        """
        self.instance_id = instance_id
        self.database = database
        self.ha_client = ha_client
        self.config = config
        self.cascade_orchestrator = cascade_orchestrator
        self.health_tracker = health_tracker
        self._validators: list[OutcomeValidator] = []  # Track validators for cleanup
        logger.debug(f"[{instance_id}] AutomationTracker initialized")

    async def record_execution(
        self,
        automation_id: str,
        trigger_type: str | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> int | None:
        """Record an automation execution.

        Args:
            automation_id: Automation entity ID (e.g., automation.bedroom_lights)
            trigger_type: Type of trigger that fired (e.g., state, time, event)
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error_message: Error message if execution failed

        Returns:
            Execution ID if successful, None if failed
        """
        execution_id = None
        try:
            async with self.database.async_session() as session:
                execution = AutomationExecution(
                    instance_id=self.instance_id,
                    automation_id=automation_id,
                    executed_at=datetime.now(UTC),
                    trigger_type=trigger_type,
                    duration_ms=duration_ms,
                    success=success,
                    error_message=error_message,
                )
                session.add(execution)
                await session.commit()

                # Get the execution ID after commit
                await session.refresh(execution)
                execution_id = execution.id

            logger.debug(
                f"[{self.instance_id}] Recorded execution: {automation_id} "
                f"(id={execution_id}, trigger={trigger_type}, success={success})"
            )

            # Trigger outcome validation in background if enabled
            if (
                execution_id
                and success
                and self.config
                and self.config.outcome_validation.enabled
                and self.ha_client
            ):
                asyncio.create_task(self._validate_execution_outcome(execution_id))

        except Exception as e:
            logger.error(
                f"[{self.instance_id}] Failed to record automation execution "
                f"for {automation_id}: {e}",
                exc_info=True,
            )

        return execution_id

    async def record_service_call(
        self,
        automation_id: str,
        service_name: str,
        entity_id: str | None = None,
        response_time_ms: int | None = None,
        success: bool = True,
    ) -> None:
        """Record a service call made by an automation.

        Args:
            automation_id: Automation entity ID that made the call
            service_name: Service called (e.g., "light.turn_on")
            entity_id: Target entity if applicable
            response_time_ms: Service response time in milliseconds
            success: Whether call succeeded
        """
        try:
            async with self.database.async_session() as session:
                service_call = AutomationServiceCall(
                    instance_id=self.instance_id,
                    automation_id=automation_id,
                    service_name=service_name,
                    entity_id=entity_id,
                    called_at=datetime.now(UTC),
                    response_time_ms=response_time_ms,
                    success=success,
                )
                session.add(service_call)
                await session.commit()

            logger.debug(
                f"[{self.instance_id}] Recorded service call: "
                f"{automation_id} -> {service_name} "
                f"(entity={entity_id}, success={success})"
            )

        except Exception as e:
            logger.error(
                f"[{self.instance_id}] Failed to record service call " f"for {automation_id}: {e}",
                exc_info=True,
            )

    async def _validate_execution_outcome(self, execution_id: int) -> None:
        """Validate automation execution outcome (background task).

        This method runs in the background after an automation execution is recorded.
        It waits for states to settle, then validates whether the automation achieved
        its desired outcomes.

        Args:
            execution_id: ID of the AutomationExecution to validate
        """
        if not self.ha_client or not self.config:
            return

        # Wait for states to settle
        delay = self.config.outcome_validation.validation_delay_seconds
        await asyncio.sleep(delay)

        try:
            validator = OutcomeValidator(
                database=self.database,
                ha_client=self.ha_client,
                instance_id=self.instance_id,
                cascade_orchestrator=self.cascade_orchestrator,
                health_tracker=self.health_tracker,
                config=self.config,
            )
            # Track validator for cleanup
            self._validators.append(validator)

            result = await validator.validate_execution(
                execution_id=execution_id,
                validation_window_seconds=delay,
            )

            if result.overall_success:
                logger.debug(
                    f"[{self.instance_id}] Execution {execution_id} validated: "
                    f"{len(result.entity_results)} entities achieved desired states"
                )
            else:
                failed_entities = [
                    entity_id
                    for entity_id, entity_result in result.entity_results.items()
                    if not entity_result.achieved
                ]
                logger.warning(
                    f"[{self.instance_id}] Execution {execution_id} validation failed: "
                    f"{len(failed_entities)}/{len(result.entity_results)} entities "
                    f"did not achieve desired states ({', '.join(failed_entities[:3])})"
                )

        except Exception as e:
            logger.error(
                f"[{self.instance_id}] Outcome validation failed for execution "
                f"{execution_id}: {e}",
                exc_info=True,
            )

    async def cleanup(self) -> None:
        """Clean up all validators and their background tasks.

        This method should be called during service shutdown to ensure
        all background cascade tasks complete gracefully.
        """
        if self._validators:
            logger.debug(f"[{self.instance_id}] Cleaning up {len(self._validators)} validators")
            cleanup_tasks = [validator.cleanup() for validator in self._validators]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            self._validators.clear()
            logger.debug(f"[{self.instance_id}] Validator cleanup complete")
