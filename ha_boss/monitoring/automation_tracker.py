"""Track automation executions for pattern analysis."""

import logging
from datetime import UTC, datetime

from ha_boss.core.database import AutomationExecution, AutomationServiceCall, Database

logger = logging.getLogger(__name__)


class AutomationTracker:
    """Tracks automation executions and service calls for pattern analysis.

    This tracker records automation runs and their service calls to enable
    usage-based optimization recommendations. Data is stored in the database
    for analysis by AutomationAnalyzer.
    """

    def __init__(self, instance_id: str, database: Database):
        """Initialize automation tracker.

        Args:
            instance_id: Home Assistant instance identifier
            database: Database instance for storing tracking data
        """
        self.instance_id = instance_id
        self.database = database
        logger.debug(f"[{instance_id}] AutomationTracker initialized")

    async def record_execution(
        self,
        automation_id: str,
        trigger_type: str | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """Record an automation execution.

        Args:
            automation_id: Automation entity ID (e.g., automation.bedroom_lights)
            trigger_type: Type of trigger that fired (e.g., state, time, event)
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error_message: Error message if execution failed
        """
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

            logger.debug(
                f"[{self.instance_id}] Recorded execution: {automation_id} "
                f"(trigger={trigger_type}, success={success})"
            )

        except Exception as e:
            logger.error(
                f"[{self.instance_id}] Failed to record automation execution "
                f"for {automation_id}: {e}",
                exc_info=True,
            )

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
                f"[{self.instance_id}] Failed to record service call "
                f"for {automation_id}: {e}",
                exc_info=True,
            )
