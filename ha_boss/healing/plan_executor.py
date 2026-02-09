"""Execute healing plans using existing healer infrastructure.

Runs plan steps in sequence, delegating to the appropriate healer
(entity, device, or integration) based on each step's level. Records
execution results in the database for tracking and analysis.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from ha_boss.core.database import Database, HealingPlan, HealingPlanExecution
from ha_boss.healing.cascade_orchestrator import HealingContext
from ha_boss.healing.device_healer import DeviceHealer
from ha_boss.healing.entity_healer import EntityHealer
from ha_boss.healing.plan_models import HealingPlanDefinition, HealingStep

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of executing a single plan step."""

    step_name: str
    level: str
    action: str
    success: bool
    duration_seconds: float
    error_message: str | None = None


@dataclass
class PlanExecutionResult:
    """Result of executing a complete healing plan."""

    plan_name: str
    success: bool
    steps_attempted: list[StepResult] = field(default_factory=list)
    steps_succeeded: int = 0
    steps_failed: int = 0
    total_duration_seconds: float = 0.0
    error_message: str | None = None


class PlanExecutor:
    """Execute healing plans using existing healer infrastructure.

    Each plan step is executed in order. If a step succeeds, execution
    stops early (the entity is healed). If a step fails, the next step
    is tried. After all steps, the overall result is recorded.
    """

    def __init__(
        self,
        database: Database,
        entity_healer: EntityHealer,
        device_healer: DeviceHealer,
    ) -> None:
        """Initialize plan executor.

        Args:
            database: Database for recording execution results
            entity_healer: Entity-level healer
            device_healer: Device-level healer
        """
        self.database = database
        self.entity_healer = entity_healer
        self.device_healer = device_healer

    async def execute_plan(
        self,
        plan: HealingPlanDefinition,
        context: HealingContext,
        cascade_execution_id: int | None = None,
    ) -> PlanExecutionResult:
        """Execute a healing plan for the given context.

        Steps are executed in order. Execution stops early on first
        successful step (entity is healed). Records results to database.

        Args:
            plan: Plan definition to execute
            context: Healing context with failed entities
            cascade_execution_id: Optional link to cascade execution

        Returns:
            PlanExecutionResult with step-by-step results
        """
        start_time = datetime.now(UTC)
        step_results: list[StepResult] = []
        steps_succeeded = 0
        steps_failed = 0
        overall_success = False

        logger.info(
            f"Executing plan '{plan.name}' for {context.automation_id} "
            f"({len(context.failed_entities)} entities, {len(plan.steps)} steps)"
        )

        for step in plan.steps:
            step_start = datetime.now(UTC)

            try:
                success = await asyncio.wait_for(
                    self._execute_step(step, context),
                    timeout=step.timeout_seconds,
                )
            except TimeoutError:
                success = False
                error_msg = f"Step '{step.name}' timed out after {step.timeout_seconds}s"
                logger.warning(error_msg)
                step_duration = step.timeout_seconds
                step_results.append(
                    StepResult(
                        step_name=step.name,
                        level=step.level,
                        action=step.action,
                        success=False,
                        duration_seconds=step_duration,
                        error_message=error_msg,
                    )
                )
                steps_failed += 1
                continue
            except Exception as e:
                success = False
                error_msg = f"Step '{step.name}' failed: {e}"
                logger.error(error_msg, exc_info=True)
                step_duration = (datetime.now(UTC) - step_start).total_seconds()
                step_results.append(
                    StepResult(
                        step_name=step.name,
                        level=step.level,
                        action=step.action,
                        success=False,
                        duration_seconds=step_duration,
                        error_message=error_msg,
                    )
                )
                steps_failed += 1
                continue

            step_duration = (datetime.now(UTC) - step_start).total_seconds()
            step_results.append(
                StepResult(
                    step_name=step.name,
                    level=step.level,
                    action=step.action,
                    success=success,
                    duration_seconds=step_duration,
                )
            )

            if success:
                steps_succeeded += 1
                overall_success = True
                logger.info(
                    f"Plan '{plan.name}' step '{step.name}' succeeded "
                    f"for {context.automation_id}"
                )
                break
            else:
                steps_failed += 1
                logger.info(
                    f"Plan '{plan.name}' step '{step.name}' failed "
                    f"for {context.automation_id}, trying next step"
                )

        total_duration = (datetime.now(UTC) - start_time).total_seconds()

        result = PlanExecutionResult(
            plan_name=plan.name,
            success=overall_success,
            steps_attempted=step_results,
            steps_succeeded=steps_succeeded,
            steps_failed=steps_failed,
            total_duration_seconds=total_duration,
        )

        # Record execution in database
        await self._record_execution(
            plan=plan,
            context=context,
            result=result,
            cascade_execution_id=cascade_execution_id,
            started_at=start_time,
        )

        logger.info(
            f"Plan '{plan.name}' execution {'succeeded' if overall_success else 'failed'} "
            f"for {context.automation_id} "
            f"({steps_succeeded} succeeded, {steps_failed} failed, "
            f"{total_duration:.1f}s total)"
        )

        return result

    async def _execute_step(self, step: HealingStep, context: HealingContext) -> bool:
        """Execute a single plan step.

        Delegates to the appropriate healer based on the step's level.

        Args:
            step: Step to execute
            context: Healing context

        Returns:
            True if step succeeded
        """
        if step.level == "entity":
            return await self._execute_entity_step(step, context)
        elif step.level == "device":
            return await self._execute_device_step(step, context)
        elif step.level == "integration":
            return await self._execute_integration_step(step, context)
        else:
            logger.error(f"Unknown step level: {step.level}")
            return False

    async def _execute_entity_step(self, step: HealingStep, context: HealingContext) -> bool:
        """Execute entity-level healing step.

        Heals each failed entity individually. Returns True if any entity
        was healed successfully.
        """
        any_success = False
        for entity_id in context.failed_entities:
            result = await self.entity_healer.heal(
                entity_id=entity_id,
                triggered_by=context.trigger_type,
                automation_id=context.automation_id,
                execution_id=context.execution_id,
            )
            if result.success:
                any_success = True
        return any_success

    async def _execute_device_step(self, step: HealingStep, context: HealingContext) -> bool:
        """Execute device-level healing step."""
        result = await self.device_healer.heal(
            entity_ids=context.failed_entities,
            triggered_by=context.trigger_type,
            automation_id=context.automation_id,
            execution_id=context.execution_id,
        )
        return result.success

    async def _execute_integration_step(self, step: HealingStep, context: HealingContext) -> bool:
        """Execute integration-level healing step.

        Uses entity healer's retry mechanism since integration reloads
        affect the same entities. The actual integration reload is
        triggered indirectly through the device healer which maps
        entities to their integration config entries.
        """
        # For integration-level steps, we use the device healer which
        # already has the integration reload capability when device-level
        # actions fail. This ensures consistent behavior.
        result = await self.device_healer.heal(
            entity_ids=context.failed_entities,
            triggered_by=context.trigger_type,
            automation_id=context.automation_id,
            execution_id=context.execution_id,
        )
        return result.success

    async def _record_execution(
        self,
        plan: HealingPlanDefinition,
        context: HealingContext,
        result: PlanExecutionResult,
        cascade_execution_id: int | None,
        started_at: datetime,
    ) -> None:
        """Record plan execution in database."""
        try:
            async with self.database.async_session() as session:
                # Look up plan_id from database
                plan_id = None
                db_result = await session.execute(
                    select(HealingPlan.id).where(HealingPlan.name == plan.name)
                )
                row = db_result.scalar_one_or_none()
                if row is not None:
                    plan_id = row

                execution = HealingPlanExecution(
                    plan_id=plan_id or 0,
                    plan_name=plan.name,
                    instance_id=context.instance_id,
                    automation_id=context.automation_id,
                    cascade_execution_id=cascade_execution_id,
                    target_entities=[{"entity_id": e} for e in context.failed_entities],
                    steps_attempted=[
                        {
                            "step_name": s.step_name,
                            "level": s.level,
                            "action": s.action,
                            "success": s.success,
                            "duration_seconds": s.duration_seconds,
                            "error_message": s.error_message,
                        }
                        for s in result.steps_attempted
                    ],
                    steps_succeeded=result.steps_succeeded,
                    steps_failed=result.steps_failed,
                    overall_success=result.success,
                    total_duration_seconds=result.total_duration_seconds,
                    created_at=started_at,
                    completed_at=datetime.now(UTC),
                )
                session.add(execution)
                await session.commit()

                # Update plan execution stats
                if plan_id is not None:
                    db_result2 = await session.execute(
                        select(HealingPlan).where(HealingPlan.id == plan_id)
                    )
                    db_plan = db_result2.scalar_one_or_none()
                    if db_plan:
                        db_plan.total_executions = (db_plan.total_executions or 0) + 1
                        if result.success:
                            db_plan.successful_executions = (db_plan.successful_executions or 0) + 1
                        else:
                            db_plan.failed_executions = (db_plan.failed_executions or 0) + 1
                        db_plan.last_executed_at = datetime.now(UTC)
                        await session.commit()

        except Exception as e:
            logger.error(
                f"Failed to record plan execution for '{plan.name}': {e}",
                exc_info=True,
            )
