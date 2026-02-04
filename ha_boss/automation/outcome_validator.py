"""Outcome validation service for automations.

This module validates whether automation executions achieved their desired
outcomes by comparing expected states to actual states within a time window.
Implements pattern learning to improve confidence scores over time.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

if TYPE_CHECKING:
    from ha_boss.automation.health_tracker import AutomationHealthTracker
    from ha_boss.healing.cascade_orchestrator import (
        CascadeOrchestrator,
        CascadeResult,
    )
    from ha_boss.intelligence.llm_router import LLMRouter

from ha_boss.core.config import Config
from ha_boss.core.database import (
    AutomationDesiredState,
    AutomationExecution,
    AutomationOutcomePattern,
    AutomationOutcomeValidation,
    Database,
)
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.cascade_orchestrator import HealingContext

logger = logging.getLogger(__name__)


@dataclass
class EntityValidationResult:
    """Validation result for a single entity."""

    entity_id: str
    desired_state: str
    desired_attributes: dict[str, Any] | None
    actual_state: str | None
    actual_attributes: dict[str, Any] | None
    achieved: bool
    time_to_achievement_ms: int | None = None


@dataclass
class ValidationResult:
    """Overall validation result for an automation execution."""

    execution_id: int
    automation_id: str
    instance_id: str
    overall_success: bool
    entity_results: dict[str, EntityValidationResult] = field(default_factory=dict)
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class OutcomeValidator:
    """Validates automation execution outcomes and learns patterns.

    This service compares desired automation outcomes (from DesiredStateInference)
    to actual entity states after execution. Results are stored for pattern
    learning and confidence score refinement.

    Example:
        >>> validator = OutcomeValidator(database, ha_client, "default")
        >>> result = await validator.validate_execution(
        ...     execution_id=123,
        ...     validation_window_seconds=5.0
        ... )
        >>> if result.overall_success:
        ...     print("All entities reached desired states")
        >>> else:
        ...     for entity_id, entity_result in result.entity_results.items():
        ...         if not entity_result.achieved:
        ...             print(f"{entity_id} failed: {entity_result.actual_state}")
    """

    # Tolerance for numeric attribute comparison (percentage)
    NUMERIC_TOLERANCE_PERCENT = 5.0
    # Minimum absolute tolerance (handles zero values)
    NUMERIC_TOLERANCE_MIN = 1.0

    def __init__(
        self,
        database: Database,
        ha_client: HomeAssistantClient,
        instance_id: str = "default",
        llm_router: "LLMRouter | None" = None,
        cascade_orchestrator: "CascadeOrchestrator | None" = None,
        health_tracker: "AutomationHealthTracker | None" = None,
        config: Config | None = None,
    ) -> None:
        """Initialize outcome validator.

        Args:
            database: Database for querying desired states and storing results
            ha_client: Home Assistant client for querying state history
            instance_id: Home Assistant instance identifier
            llm_router: Optional LLM router for AI-powered failure analysis
            cascade_orchestrator: Optional cascade orchestrator for triggering healing
            health_tracker: Optional health tracker for recording execution results
            config: Optional configuration for healing timeouts and settings
        """
        self.database = database
        self.ha_client = ha_client
        self.instance_id = instance_id
        self.llm_router = llm_router
        self.cascade_orchestrator = cascade_orchestrator
        self.health_tracker = health_tracker
        self.config = config
        self._background_tasks: set[asyncio.Task] = set()

    async def validate_execution(
        self,
        execution_id: int,
        validation_window_seconds: float = 5.0,
    ) -> ValidationResult:
        """Validate automation execution outcomes.

        Queries desired states, compares to actual states within time window,
        stores validation results, and learns patterns from successful executions.

        Args:
            execution_id: ID of the AutomationExecution to validate
            validation_window_seconds: Time window after execution to check states

        Returns:
            ValidationResult with per-entity and overall success status

        Raises:
            ValueError: If execution_id not found in database
        """
        # Get execution record
        async with self.database.async_session() as session:
            result = await session.execute(
                select(AutomationExecution).where(AutomationExecution.id == execution_id)
            )
            execution = result.scalar_one_or_none()

            if not execution:
                raise ValueError(f"Execution ID {execution_id} not found")

            automation_id = execution.automation_id
            executed_at = execution.executed_at

        logger.info(
            f"Validating execution {execution_id} for {automation_id} "
            f"(executed at {executed_at})"
        )

        # Get desired states for this automation
        desired_states = await self._get_desired_states(automation_id)

        if not desired_states:
            logger.warning(f"No desired states found for {automation_id} - skipping validation")
            return ValidationResult(
                execution_id=execution_id,
                automation_id=automation_id,
                instance_id=self.instance_id,
                overall_success=False,
            )

        # Query actual states within validation window
        end_time = executed_at + timedelta(seconds=validation_window_seconds)
        entity_results = {}

        for desired in desired_states:
            entity_result = await self._validate_entity(
                entity_id=desired.entity_id,
                desired_state=desired.desired_state,
                desired_attributes=desired.desired_attributes,
                start_time=executed_at,
                end_time=end_time,
            )
            entity_results[desired.entity_id] = entity_result

        # Determine overall success
        overall_success = all(result.achieved for result in entity_results.values())

        validation_result = ValidationResult(
            execution_id=execution_id,
            automation_id=automation_id,
            instance_id=self.instance_id,
            overall_success=overall_success,
            entity_results=entity_results,
        )

        # Store validation results
        await self._store_validation_results(validation_result)

        # Learn patterns from successful validations
        if overall_success:
            await self._learn_patterns(automation_id, entity_results)

        # Record result in health tracker if configured
        if self.health_tracker:
            try:
                await self.health_tracker.record_execution_result(
                    instance_id=self.instance_id,
                    automation_id=automation_id,
                    success=validation_result.overall_success,
                )
            except Exception as e:
                logger.error(
                    f"Failed to record health status for {automation_id}: {e}",
                    exc_info=True,
                )

        # Trigger cascade orchestrator on validation failure
        if not validation_result.overall_success and self.cascade_orchestrator:
            task = asyncio.create_task(
                self._trigger_cascade_on_failure(automation_id, execution_id, validation_result)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        logger.info(
            f"Validation complete for {automation_id}: "
            f"overall_success={overall_success}, "
            f"entities={len(entity_results)}, "
            f"successful={sum(1 for r in entity_results.values() if r.achieved)}"
        )

        return validation_result

    async def cleanup(self) -> None:
        """Wait for all background cascade tasks to complete.

        This method should be called during service shutdown to ensure
        all background cascade operations complete gracefully.
        """
        if self._background_tasks:
            logger.debug(
                f"[{self.instance_id}] Waiting for {len(self._background_tasks)} "
                f"background cascade tasks to complete"
            )
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            logger.debug(f"[{self.instance_id}] All background cascade tasks completed")

    async def _get_desired_states(self, automation_id: str) -> list[AutomationDesiredState]:
        """Query desired states for an automation.

        Args:
            automation_id: Automation entity ID

        Returns:
            List of AutomationDesiredState records
        """
        async with self.database.async_session() as session:
            result = await session.execute(
                select(AutomationDesiredState).where(
                    AutomationDesiredState.instance_id == self.instance_id,
                    AutomationDesiredState.automation_id == automation_id,
                )
            )
            return list(result.scalars().all())

    async def _validate_entity(
        self,
        entity_id: str,
        desired_state: str,
        desired_attributes: dict[str, Any] | None,
        start_time: datetime,
        end_time: datetime,
    ) -> EntityValidationResult:
        """Validate a single entity's outcome.

        Args:
            entity_id: Entity to validate
            desired_state: Expected state
            desired_attributes: Expected attributes (optional)
            start_time: Start of validation window
            end_time: End of validation window

        Returns:
            EntityValidationResult with achieved status and timing
        """
        try:
            # Query HA history for this entity in the time window
            history = await self.ha_client.get_history(
                filter_entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
            )

            # History returns list of lists (grouped by entity)
            if not history or not history[0]:
                logger.debug(
                    f"No history found for {entity_id} in window " f"{start_time} to {end_time}"
                )
                return EntityValidationResult(
                    entity_id=entity_id,
                    desired_state=desired_state,
                    desired_attributes=desired_attributes,
                    actual_state=None,
                    actual_attributes=None,
                    achieved=False,
                )

            # Get the last state in the window
            entity_history = history[0]
            last_state = entity_history[-1]

            actual_state = last_state.get("state")
            actual_attributes = last_state.get("attributes", {})

            # Compare states
            state_matches = self._compare_states(desired_state, actual_state)
            attributes_match = self._compare_attributes(desired_attributes, actual_attributes)

            achieved = state_matches and attributes_match

            # Calculate time to achievement if successful
            time_to_achievement_ms = None
            if achieved and len(entity_history) > 0:
                # Find first matching state in history
                for state_entry in entity_history:
                    entry_state = state_entry.get("state")
                    entry_attributes = state_entry.get("attributes", {})

                    if self._compare_states(
                        desired_state, entry_state
                    ) and self._compare_attributes(desired_attributes, entry_attributes):
                        # Calculate time delta
                        last_changed = state_entry.get("last_changed")
                        if last_changed:
                            last_changed_dt = datetime.fromisoformat(
                                last_changed.replace("Z", "+00:00")
                            )
                            delta = last_changed_dt - start_time
                            time_to_achievement_ms = int(delta.total_seconds() * 1000)
                            break

            return EntityValidationResult(
                entity_id=entity_id,
                desired_state=desired_state,
                desired_attributes=desired_attributes,
                actual_state=actual_state,
                actual_attributes=actual_attributes,
                achieved=achieved,
                time_to_achievement_ms=time_to_achievement_ms,
            )

        except Exception as e:
            logger.error(
                f"Error validating entity {entity_id}: {e}",
                exc_info=True,
            )
            return EntityValidationResult(
                entity_id=entity_id,
                desired_state=desired_state,
                desired_attributes=desired_attributes,
                actual_state=None,
                actual_attributes=None,
                achieved=False,
            )

    def _compare_states(self, desired: str, actual: str | None) -> bool:
        """Compare desired and actual states.

        Args:
            desired: Desired state value
            actual: Actual state value

        Returns:
            True if states match
        """
        if actual is None:
            return False

        # Case-insensitive comparison
        return desired.lower() == actual.lower()

    def _compare_attributes(
        self,
        desired: dict[str, Any] | None,
        actual: dict[str, Any] | None,
    ) -> bool:
        """Compare desired and actual attributes with tolerance.

        Args:
            desired: Desired attributes dict
            actual: Actual attributes dict

        Returns:
            True if attributes match within tolerance
        """
        if desired is None:
            return True  # No attributes to validate

        if actual is None:
            return False  # Expected attributes but got none

        # Check each desired attribute
        for key, desired_value in desired.items():
            if key not in actual:
                logger.debug(f"Missing attribute: {key}")
                return False

            actual_value = actual[key]

            # Numeric comparison with tolerance
            if isinstance(desired_value, (int, float)) and isinstance(actual_value, (int, float)):
                # Use max of percentage-based and absolute minimum tolerance
                percentage_tolerance = abs(desired_value * self.NUMERIC_TOLERANCE_PERCENT / 100.0)
                tolerance = max(percentage_tolerance, self.NUMERIC_TOLERANCE_MIN)
                if abs(desired_value - actual_value) > tolerance:
                    logger.debug(
                        f"Attribute {key} mismatch: "
                        f"desired={desired_value}, actual={actual_value}, "
                        f"tolerance={tolerance}"
                    )
                    return False
            # Exact comparison for non-numeric values
            elif desired_value != actual_value:
                logger.debug(
                    f"Attribute {key} mismatch: " f"desired={desired_value}, actual={actual_value}"
                )
                return False

        return True

    async def _trigger_cascade_on_failure(
        self,
        automation_id: str,
        execution_id: int,
        validation_result: ValidationResult,
    ) -> "CascadeResult | None":
        """Trigger healing cascade when validation fails.

        Args:
            automation_id: Automation that failed validation
            execution_id: Execution ID
            validation_result: Validation results with failed entities

        Returns:
            CascadeResult if cascade was triggered, None if skipped
        """
        if not self.cascade_orchestrator:
            logger.debug(f"Cascade orchestrator not configured, skipping for {automation_id}")
            return None

        # Extract failed entities from validation result
        failed_entities = [
            entity_id
            for entity_id, entity_result in validation_result.entity_results.items()
            if not entity_result.achieved
        ]

        if not failed_entities:
            logger.debug(f"No failed entities to heal for {automation_id}")
            return None

        # Get cascade timeout from config with fallback to default
        timeout_seconds = 120.0  # Default
        if self.config and hasattr(self.config, "healing") and self.config.healing:
            timeout_seconds = getattr(
                self.config.healing, "cascade_timeout_seconds", 120.0
            )

        context = HealingContext(
            instance_id=self.instance_id,
            automation_id=automation_id,
            execution_id=execution_id,
            trigger_type="outcome_failure",
            failed_entities=failed_entities,
            timeout_seconds=timeout_seconds,
        )

        logger.info(
            f"Triggering healing cascade for {automation_id} "
            f"({len(failed_entities)} failed entities)"
        )

        try:
            result = await self.cascade_orchestrator.execute_cascade(
                context, use_intelligent_routing=True
            )
            logger.info(
                f"Cascade {'succeeded' if result.success else 'failed'} for {automation_id} "
                f"(strategy: {result.routing_strategy}, duration: {result.total_duration_seconds:.2f}s)"
            )
            return result
        except Exception as e:
            logger.error(f"Cascade execution failed for {automation_id}: {e}", exc_info=True)
            return None

    async def _store_validation_results(self, result: ValidationResult) -> None:
        """Store validation results in database.

        Args:
            result: ValidationResult to store
        """
        async with self.database.async_session() as session:
            try:
                for entity_id, entity_result in result.entity_results.items():
                    record = AutomationOutcomeValidation(
                        instance_id=result.instance_id,
                        execution_id=result.execution_id,
                        entity_id=entity_id,
                        desired_state=entity_result.desired_state,
                        desired_attributes=entity_result.desired_attributes,
                        actual_state=entity_result.actual_state,
                        actual_attributes=entity_result.actual_attributes,
                        achieved=entity_result.achieved,
                        time_to_achievement_ms=entity_result.time_to_achievement_ms,
                    )
                    session.add(record)

                await session.commit()
                logger.debug(
                    f"Stored {len(result.entity_results)} validation results "
                    f"for execution {result.execution_id}"
                )

            except Exception as e:
                logger.error(f"Error storing validation results: {e}", exc_info=True)
                await session.rollback()

    async def _learn_patterns(
        self,
        automation_id: str,
        entity_results: dict[str, EntityValidationResult],
    ) -> None:
        """Learn patterns from successful validations.

        Updates AutomationOutcomePattern occurrence counts and refines
        confidence scores in AutomationDesiredState.

        Args:
            automation_id: Automation that succeeded
            entity_results: Successful entity validation results
        """
        async with self.database.async_session() as session:
            try:
                for entity_id, entity_result in entity_results.items():
                    if not entity_result.achieved:
                        continue  # Only learn from successes

                    # Check if pattern exists
                    result = await session.execute(
                        select(AutomationOutcomePattern).where(
                            AutomationOutcomePattern.instance_id == self.instance_id,
                            AutomationOutcomePattern.automation_id == automation_id,
                            AutomationOutcomePattern.entity_id == entity_id,
                        )
                    )
                    pattern = result.scalar_one_or_none()

                    if pattern:
                        # Increment occurrence count
                        pattern.occurrence_count += 1
                        pattern.last_observed = datetime.now(UTC)
                        logger.debug(
                            f"Updated pattern for {automation_id}/{entity_id}: "
                            f"count={pattern.occurrence_count}"
                        )
                    else:
                        # Create new pattern
                        pattern = AutomationOutcomePattern(
                            instance_id=self.instance_id,
                            automation_id=automation_id,
                            entity_id=entity_id,
                            observed_state=entity_result.actual_state or "",
                            observed_attributes=entity_result.actual_attributes,
                            occurrence_count=1,
                        )
                        session.add(pattern)
                        logger.debug(f"Created new pattern for {automation_id}/{entity_id}")

                    # Update confidence in AutomationDesiredState
                    # Increase confidence based on pattern occurrence
                    new_confidence = min(1.0, 0.5 + (pattern.occurrence_count * 0.1))

                    await session.execute(
                        update(AutomationDesiredState)
                        .where(
                            AutomationDesiredState.instance_id == self.instance_id,
                            AutomationDesiredState.automation_id == automation_id,
                            AutomationDesiredState.entity_id == entity_id,
                        )
                        .values(confidence=new_confidence)
                    )

                await session.commit()
                logger.info(
                    f"Learned patterns for {automation_id}: "
                    f"{len([r for r in entity_results.values() if r.achieved])} entities"
                )

            except Exception as e:
                logger.error(f"Error learning patterns: {e}", exc_info=True)
                await session.rollback()

    async def analyze_failure(
        self,
        automation_id: str,
        validation_result: ValidationResult,
        automation_config: dict | None = None,
        user_description: str | None = None,
    ) -> dict:
        """Analyze automation failure using AI.

        Args:
            automation_id: Automation that failed
            validation_result: Outcome validation results
            automation_config: Automation YAML/configuration (optional)
            user_description: User's description of the failure (optional)

        Returns:
            dict with root_cause, suggested_healing, and healing_level

        Raises:
            ValueError: If LLM router is not configured
        """
        from ha_boss.intelligence.llm_router import TaskComplexity

        # Check if LLM router is available
        if self.llm_router is None:
            # Return basic analysis without AI
            logger.warning("LLM router not configured, returning basic failure analysis")
            return {
                "root_cause": "Unable to determine root cause (AI analysis not configured)",
                "suggested_healing": [
                    "Check if entities are available in Home Assistant",
                    "Verify integration is connected and operational",
                    "Review automation configuration for errors",
                ],
                "healing_level": "entity",
            }

        # Build context for AI analysis
        failed_entities = []
        for entity_id, entity_result in validation_result.entity_results.items():
            if not entity_result.achieved:
                failed_entities.append(
                    {
                        "entity_id": entity_id,
                        "desired_state": entity_result.desired_state or "unknown",
                        "actual_state": entity_result.actual_state or "unknown",
                        "desired_attributes": entity_result.desired_attributes,
                        "actual_attributes": entity_result.actual_attributes,
                    }
                )

        # Build prompt for AI
        prompt_parts = [
            "Analyze this Home Assistant automation failure:\n",
            f"Automation: {automation_id}\n",
        ]

        if user_description:
            prompt_parts.append(f"User reported: {user_description}\n")

        prompt_parts.append("\nFailed Entities:")
        for entity in failed_entities:
            prompt_parts.append(
                f"\n- {entity['entity_id']}: "
                f"Expected {entity['desired_state']}, got {entity['actual_state']}"
            )
            if entity["desired_attributes"] or entity["actual_attributes"]:
                prompt_parts.append("  Attributes mismatch")

        if automation_config:
            import yaml

            prompt_parts.append(f"\n\nAutomation Configuration:\n{yaml.dump(automation_config)}")

        prompt_parts.append(
            "\n\nProvide your analysis in JSON format with these fields:"
            "\n- root_cause: Brief explanation of why the automation failed"
            "\n- suggested_healing: List of 2-4 specific actions to fix the issue"
            "\n- healing_level: one of ['entity', 'device', 'integration']"
            "\n\nConsider common issues like:"
            "\n- Device not responding (network, power)"
            "\n- Integration offline or misconfigured"
            "\n- Entity unavailable or disabled"
            "\n- Timing issues (device boot time, service delays)"
            "\n- Configuration errors (wrong entity ID, attributes)"
        )

        prompt = "".join(prompt_parts)

        try:
            # Get AI analysis using injected LLM router
            response = await self.llm_router.generate(prompt, complexity=TaskComplexity.MODERATE)

            # Parse JSON response
            import json
            import re

            # Extract JSON from response (might be wrapped in markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group(1))
            else:
                # Try parsing entire response as JSON
                analysis = json.loads(response)

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing failure with AI: {e}", exc_info=True)
            # Return fallback analysis
            return {
                "root_cause": f"Analysis failed: {str(e)}",
                "suggested_healing": [
                    "Check entity availability in Home Assistant",
                    "Verify integration connectivity",
                    "Review automation logs for errors",
                ],
                "healing_level": "entity",
            }
