"""Healing cascade orchestrator for multi-level healing coordination.

This module implements the core orchestration logic for the goal-oriented healing
architecture. It coordinates healing attempts across three levels:
- Level 1: Entity-level healing (retry service calls, alternative params)
- Level 2: Device-level healing (reconnect, reboot, rediscover)
- Level 3: Integration-level healing (reload integration)

The orchestrator uses two routing strategies:
1. Intelligent routing: Pattern-based jump to proven healing level
2. Sequential cascade: Level 1 → Level 2 → Level 3 progression
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TypeVar

from sqlalchemy import and_, desc, select

from ha_boss.core.database import (
    AutomationOutcomePattern,
    Database,
    HealingCascadeExecution,
)
from ha_boss.core.types import HealthIssue
from ha_boss.healing.device_healer import DeviceHealer
from ha_boss.healing.entity_healer import EntityHealer, EntityHealingResult
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.healing.heal_strategies import HealingManager

# Type variable for generic concurrent healing
T = TypeVar("T")

logger = logging.getLogger(__name__)

# Constants for routing strategies
ROUTING_STRATEGY_SEQUENTIAL = "sequential"
ROUTING_STRATEGY_INTELLIGENT = "intelligent"

# Constants for issue types
ISSUE_TYPE_UNAVAILABLE = "unavailable"


class HealingLevel(Enum):
    """Healing levels in the cascade."""

    ENTITY = "entity"
    DEVICE = "device"
    INTEGRATION = "integration"


@dataclass
class HealingContext:
    """Context for a healing cascade execution."""

    instance_id: str
    automation_id: str
    execution_id: int | None
    trigger_type: str  # trigger_failure, outcome_failure
    failed_entities: list[str]
    timeout_seconds: float = 120.0  # Total cascade timeout


@dataclass
class CascadeResult:
    """Result of a healing cascade execution."""

    success: bool
    routing_strategy: str  # intelligent, sequential
    levels_attempted: list[HealingLevel]
    successful_level: HealingLevel | None
    successful_strategy: str | None  # e.g., "retry_service_call", "reconnect", "reload_integration"
    entity_results: dict[str, bool]  # entity_id -> success
    total_duration_seconds: float
    error_message: str | None = None
    matched_pattern_id: int | None = None


class CascadeOrchestrator:
    """Orchestrates multi-level healing cascade.

    Coordinates healing attempts across entity, device, and integration levels,
    using intelligent pattern-based routing when possible, falling back to
    sequential cascade execution.

    Pattern Learning:
        Patterns are learned from successful healing attempts and stored per automation.

        **LIMITATION**: Currently, patterns are recorded using the first failed entity as a
        representative. This is a known simplification that works well when all entities in
        an automation share the same healing strategy (e.g., all lights in a room, all sensors
        from the same integration), but may be less effective for heterogeneous entity failures
        (e.g., light + sensor + switch from different integrations).

        Future enhancement (Issue #210): Implement per-entity pattern matching to improve
        accuracy for mixed-entity scenarios.

    Database Transaction Lifecycle:
        For MVP simplicity, cascade execution records are created upfront and updated
        throughout the cascade. This means orphaned records may exist if the process crashes
        mid-cascade. This is acceptable for MVP as:
        - Records include timestamps for cleanup
        - Failed cascades still provide valuable debugging info
        - Transaction overhead would impact healing latency

        Future enhancement: Consider wrapping entire cascade in a single transaction with
        appropriate timeout handling if orphaned records become problematic.
    """

    def __init__(
        self,
        database: Database,
        entity_healer: EntityHealer,
        device_healer: DeviceHealer,
        integration_healer: HealingManager,
        escalator: NotificationEscalator,
        instance_id: str = "default",
        pattern_match_threshold: int = 2,
        max_concurrent_healings: int = 3,
    ) -> None:
        """Initialize cascade orchestrator.

        Args:
            database: Database manager for recording and pattern lookups
            entity_healer: Entity-level healer (Level 1)
            device_healer: Device-level healer (Level 2)
            integration_healer: Integration-level healer (Level 3)
            escalator: Notification escalator for complete failures
            instance_id: Instance identifier for multi-instance setups
            pattern_match_threshold: Minimum successful healing count for pattern matching
            max_concurrent_healings: Maximum concurrent entity healing operations
        """
        self.database = database
        if pattern_match_threshold < 1:
            raise ValueError("pattern_match_threshold must be >= 1")

        self.entity_healer = entity_healer
        self.device_healer = device_healer
        self.integration_healer = integration_healer
        self.escalator = escalator
        self.instance_id = instance_id
        self.pattern_match_threshold = pattern_match_threshold

        # Initialize concurrency control
        self.max_concurrent_healings = max_concurrent_healings
        self._healing_semaphore = asyncio.Semaphore(max_concurrent_healings)

    async def execute_cascade(
        self,
        context: HealingContext,
        use_intelligent_routing: bool = True,
    ) -> CascadeResult:
        """Execute healing cascade for failed entities.

        Routes healing to the appropriate level using pattern matching if available,
        otherwise executes sequential cascade Level 1→2→3.

        Args:
            context: Healing context with automation and entity info
            use_intelligent_routing: Whether to use pattern-based routing

        Returns:
            CascadeResult with outcome and metadata
        """
        start_time = datetime.now(UTC)
        cascade_exec_id: int | None = None
        success = False
        routing_strategy = ROUTING_STRATEGY_SEQUENTIAL

        try:
            # Create cascade execution record
            cascade_exec_id = await self._create_cascade_record(context)

            # Execute healing with timeout (single timeout point for entire cascade)
            result = await asyncio.wait_for(
                self._execute_healing_with_routing(
                    context, cascade_exec_id, use_intelligent_routing
                ),
                timeout=context.timeout_seconds,
            )

            success = result.success
            routing_strategy = result.routing_strategy
            return result

        except TimeoutError:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            logger.error(
                f"Cascade execution timed out after {duration:.2f}s for {context.automation_id}"
            )
            if cascade_exec_id:
                await self._finalize_cascade_record(
                    cascade_exec_id,
                    success=False,
                    duration=duration,
                    routing_strategy=routing_strategy,
                )
            return CascadeResult(
                success=False,
                routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
                levels_attempted=[],
                successful_level=None,
                successful_strategy=None,
                entity_results={},
                total_duration_seconds=duration,
                error_message="Cascade execution timed out",
            )
        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            logger.error(
                f"Cascade execution failed for {context.automation_id}: {e}", exc_info=True
            )
            if cascade_exec_id:
                await self._finalize_cascade_record(
                    cascade_exec_id,
                    success=False,
                    duration=duration,
                    routing_strategy=routing_strategy,
                )
            return CascadeResult(
                success=False,
                routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
                levels_attempted=[],
                successful_level=None,
                successful_strategy=None,
                entity_results={},
                total_duration_seconds=duration,
                error_message=f"Cascade execution exception: {str(e)}",
            )
        finally:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            if cascade_exec_id:
                await self._finalize_cascade_record(
                    cascade_exec_id,
                    success=success,
                    duration=duration,
                    routing_strategy=routing_strategy,
                )

    async def _heal_concurrently(
        self,
        items: list[str],
        heal_func: Callable[[str], Awaitable[T]],
    ) -> list[tuple[str, T | BaseException]]:
        """Execute healing concurrently with semaphore control.

        Generic method to heal multiple items (entities, integrations, etc.) concurrently
        while respecting the configured concurrency limit via semaphore.

        Args:
            items: List of items to heal (entity IDs, integration IDs, etc.)
            heal_func: Async function that takes an item ID and returns a result

        Returns:
            List of tuples (item_id, result or BaseException)
        """

        async def heal_with_semaphore(item_id: str) -> tuple[str, T]:
            """Heal a single item using semaphore for concurrency control."""
            async with self._healing_semaphore:
                result = await heal_func(item_id)
                return item_id, result

        tasks = [heal_with_semaphore(item_id) for item_id in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert results to consistent format
        processed_results: list[tuple[str, T | BaseException]] = []
        for i, result in enumerate(results):
            item_id = items[i]
            if isinstance(result, BaseException):
                # Exception caught by gather with return_exceptions=True
                processed_results.append((item_id, result))
            else:
                # result is tuple[str, T]
                result_tuple: tuple[str, T] = result  # type: ignore[assignment]
                _, heal_result = result_tuple
                processed_results.append((item_id, heal_result))

        return processed_results

    async def _execute_healing_with_routing(
        self,
        context: HealingContext,
        cascade_exec_id: int,
        use_intelligent_routing: bool,
    ) -> CascadeResult:
        """Execute healing with intelligent routing or sequential fallback.

        This method contains the routing logic and is wrapped by a single timeout
        in execute_cascade to avoid nested timeout handling.

        Args:
            context: Healing context
            cascade_exec_id: Cascade execution record ID
            use_intelligent_routing: Whether to try intelligent routing first

        Returns:
            CascadeResult with outcome
        """
        # Try intelligent routing first if enabled
        if use_intelligent_routing:
            pattern = await self._get_matching_pattern(context)
            if pattern:
                # Re-fetch pattern to avoid race condition (pattern may have been deleted/updated)
                pattern = await self._refetch_pattern(pattern.id)
                if pattern:
                    logger.info(
                        f"Found matching pattern for {context.automation_id}, "
                        f"routing to {pattern.successful_healing_level} level"
                    )
                    result = await self._execute_intelligent_healing(
                        context, pattern, cascade_exec_id
                    )
                    if result.success:
                        # Update pattern success count
                        await self._update_pattern_success(pattern.id)
                        return result
                else:
                    logger.warning(
                        "Pattern was deleted/updated after match, falling back to sequential"
                    )

        # Fall back to sequential cascade
        logger.info(
            f"Executing sequential cascade for {context.automation_id} "
            f"({len(context.failed_entities)} entities)"
        )
        result = await self._execute_sequential_cascade(context, cascade_exec_id)

        # Learn from successful healing
        if result.success and result.successful_level and result.successful_strategy:
            await self._record_successful_pattern(
                context, result.successful_level, result.successful_strategy
            )

        return result

    async def _execute_sequential_cascade(
        self,
        context: HealingContext,
        cascade_exec_id: int,
    ) -> CascadeResult:
        """Execute sequential cascade: Level 1 → Level 2 → Level 3.

        Attempts healing at each level, stopping on first success.
        Timeout is handled by the caller (execute_cascade).

        Args:
            context: Healing context
            cascade_exec_id: Cascade execution record ID

        Returns:
            CascadeResult with outcome
        """
        levels_attempted: list[HealingLevel] = []
        entity_results: dict[str, bool] = {}

        # Execute cascade levels (timeout handled by caller)
        return await self._execute_cascade_levels(
            context, cascade_exec_id, levels_attempted, entity_results
        )

    async def _execute_cascade_levels(
        self,
        context: HealingContext,
        cascade_exec_id: int,
        levels_attempted: list[HealingLevel],
        entity_results: dict[str, bool],
    ) -> CascadeResult:
        """Execute each level of the cascade."""
        start_time = datetime.now(UTC)

        # Level 1: Entity-level healing (concurrent)
        logger.info(f"Attempting Level 1 (entity) healing for {context.automation_id}")
        levels_attempted.append(HealingLevel.ENTITY)
        await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, attempted=True)

        entity_success = False
        final_action = None

        # Heal entities concurrently with semaphore control
        async def heal_entity(entity_id: str) -> EntityHealingResult:
            """Heal a single entity."""
            return await self.entity_healer.heal(
                entity_id=entity_id,
                triggered_by=context.trigger_type,
                automation_id=context.automation_id,
                execution_id=context.execution_id,
            )

        results = await self._heal_concurrently(context.failed_entities, heal_entity)

        for entity_id, result in results:
            if isinstance(result, BaseException):
                logger.error(f"Entity healing exception for {entity_id}: {result}")
                entity_results[entity_id] = False
            else:
                entity_results[entity_id] = result.success
                if result.success:
                    entity_success = True
                    final_action = result.final_action

        if entity_success:
            await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, success=True)
            duration = (datetime.now(UTC) - start_time).total_seconds()
            return CascadeResult(
                success=True,
                routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
                levels_attempted=levels_attempted,
                successful_level=HealingLevel.ENTITY,
                successful_strategy=final_action,
                entity_results=entity_results,
                total_duration_seconds=duration,
            )

        await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, success=False)

        # Level 2: Device-level healing
        logger.info(
            f"Level 1 failed, attempting Level 2 (device) healing for {context.automation_id}"
        )
        levels_attempted.append(HealingLevel.DEVICE)
        await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, attempted=True)

        device_result = await self.device_healer.heal(
            entity_ids=context.failed_entities,
            triggered_by=context.trigger_type,
            automation_id=context.automation_id,
            execution_id=context.execution_id,
        )

        if device_result.success:
            # Update entity results based on device healing
            for entity_id in context.failed_entities:
                entity_results[entity_id] = True

            await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, success=True)
            duration = (datetime.now(UTC) - start_time).total_seconds()
            return CascadeResult(
                success=True,
                routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
                levels_attempted=levels_attempted,
                successful_level=HealingLevel.DEVICE,
                successful_strategy=device_result.final_action,
                entity_results=entity_results,
                total_duration_seconds=duration,
            )

        await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, success=False)

        # Level 3: Integration-level healing
        logger.info(
            f"Level 2 failed, attempting Level 3 (integration) healing for {context.automation_id}"
        )
        levels_attempted.append(HealingLevel.INTEGRATION)
        await self._update_cascade_level(cascade_exec_id, HealingLevel.INTEGRATION, attempted=True)

        integration_success = await self._execute_integration_healing(
            context.failed_entities, entity_results
        )

        if integration_success:
            await self._update_cascade_level(
                cascade_exec_id, HealingLevel.INTEGRATION, success=True
            )
            duration = (datetime.now(UTC) - start_time).total_seconds()
            return CascadeResult(
                success=True,
                routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
                levels_attempted=levels_attempted,
                successful_level=HealingLevel.INTEGRATION,
                successful_strategy="reload_integration",
                entity_results=entity_results,
                total_duration_seconds=duration,
            )

        await self._update_cascade_level(cascade_exec_id, HealingLevel.INTEGRATION, success=False)

        # All levels failed - escalate to notification
        logger.warning(
            f"All healing levels failed for {context.automation_id}, escalating to notification"
        )
        duration = (datetime.now(UTC) - start_time).total_seconds()

        # Send failure notification for each failed entity
        for entity_id in context.failed_entities:
            try:
                health_issue = HealthIssue(
                    entity_id=entity_id,
                    issue_type=ISSUE_TYPE_UNAVAILABLE,
                    detected_at=datetime.now(UTC),
                    details={
                        "automation_id": context.automation_id,
                        "cascade_failure": True,
                        "levels_attempted": [level.value for level in levels_attempted],
                    },
                )
                await self.escalator.notify_healing_failure(health_issue)
            except Exception as e:
                logger.error(f"Failed to send escalation notification for {entity_id}: {e}")

        return CascadeResult(
            success=False,
            routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,
            levels_attempted=levels_attempted,
            successful_level=None,
            successful_strategy=None,
            entity_results=entity_results,
            total_duration_seconds=duration,
            error_message="All healing levels failed",
        )

    async def _execute_intelligent_healing(
        self,
        context: HealingContext,
        pattern: AutomationOutcomePattern,
        cascade_exec_id: int,
    ) -> CascadeResult:
        """Execute intelligent healing by jumping to proven level.

        Args:
            context: Healing context
            pattern: Matched pattern with successful healing history
            cascade_exec_id: Cascade execution record ID

        Returns:
            CascadeResult with outcome
        """
        start_time = datetime.now(UTC)
        levels_attempted: list[HealingLevel] = []
        entity_results: dict[str, bool] = {}

        if not pattern.successful_healing_level:
            # Pattern exists but no successful healing level recorded
            # Fall back to sequential
            return await self._execute_sequential_cascade(context, cascade_exec_id)

        target_level = HealingLevel(pattern.successful_healing_level)
        logger.info(
            f"Intelligent routing to {target_level.value} level based on pattern (success count: {pattern.healing_success_count})"
        )

        # Execute only the target level
        levels_attempted.append(target_level)

        if target_level == HealingLevel.ENTITY:
            await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, attempted=True)
            entity_success = False
            final_action = None

            # Heal entities concurrently with semaphore control
            async def heal_entity(entity_id: str) -> EntityHealingResult:
                """Heal a single entity."""
                return await self.entity_healer.heal(
                    entity_id=entity_id,
                    triggered_by=context.trigger_type,
                    automation_id=context.automation_id,
                    execution_id=context.execution_id,
                )

            results = await self._heal_concurrently(context.failed_entities, heal_entity)

            for entity_id, result in results:
                if isinstance(result, BaseException):
                    logger.error(f"Entity healing exception for {entity_id}: {result}")
                    entity_results[entity_id] = False
                else:
                    entity_results[entity_id] = result.success
                    if result.success:
                        entity_success = True
                        final_action = result.final_action

            if entity_success:
                await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, success=True)
                duration = (datetime.now(UTC) - start_time).total_seconds()
                return CascadeResult(
                    success=True,
                    routing_strategy=ROUTING_STRATEGY_INTELLIGENT,
                    levels_attempted=levels_attempted,
                    successful_level=HealingLevel.ENTITY,
                    successful_strategy=final_action,
                    entity_results=entity_results,
                    total_duration_seconds=duration,
                    matched_pattern_id=pattern.id,
                )
            await self._update_cascade_level(cascade_exec_id, HealingLevel.ENTITY, success=False)

        elif target_level == HealingLevel.DEVICE:
            await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, attempted=True)
            device_result = await self.device_healer.heal(
                entity_ids=context.failed_entities,
                triggered_by=context.trigger_type,
                automation_id=context.automation_id,
                execution_id=context.execution_id,
            )

            if device_result.success:
                for entity_id in context.failed_entities:
                    entity_results[entity_id] = True
                await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, success=True)
                duration = (datetime.now(UTC) - start_time).total_seconds()
                return CascadeResult(
                    success=True,
                    routing_strategy=ROUTING_STRATEGY_INTELLIGENT,
                    levels_attempted=levels_attempted,
                    successful_level=HealingLevel.DEVICE,
                    successful_strategy=device_result.final_action,
                    entity_results=entity_results,
                    total_duration_seconds=duration,
                    matched_pattern_id=pattern.id,
                )
            await self._update_cascade_level(cascade_exec_id, HealingLevel.DEVICE, success=False)

        elif target_level == HealingLevel.INTEGRATION:
            await self._update_cascade_level(
                cascade_exec_id, HealingLevel.INTEGRATION, attempted=True
            )
            integration_success = await self._execute_integration_healing(
                context.failed_entities, entity_results
            )

            if integration_success:
                await self._update_cascade_level(
                    cascade_exec_id, HealingLevel.INTEGRATION, success=True
                )
                duration = (datetime.now(UTC) - start_time).total_seconds()
                return CascadeResult(
                    success=True,
                    routing_strategy=ROUTING_STRATEGY_INTELLIGENT,
                    levels_attempted=levels_attempted,
                    successful_level=HealingLevel.INTEGRATION,
                    successful_strategy="reload_integration",
                    entity_results=entity_results,
                    total_duration_seconds=duration,
                    matched_pattern_id=pattern.id,
                )
            await self._update_cascade_level(
                cascade_exec_id, HealingLevel.INTEGRATION, success=False
            )

        # Intelligent routing failed, return failure
        # Caller will fall back to sequential cascade
        duration = (datetime.now(UTC) - start_time).total_seconds()
        return CascadeResult(
            success=False,
            routing_strategy=ROUTING_STRATEGY_INTELLIGENT,
            levels_attempted=levels_attempted,
            successful_level=None,
            successful_strategy=None,
            entity_results=entity_results,
            total_duration_seconds=duration,
            matched_pattern_id=pattern.id,
        )

    async def _refetch_pattern(self, pattern_id: int) -> AutomationOutcomePattern | None:
        """Re-fetch pattern by ID to avoid stale data race conditions.

        Args:
            pattern_id: Pattern ID to fetch

        Returns:
            Pattern if still exists, None if deleted
        """
        try:
            async with self.database.async_session() as session:
                stmt = select(AutomationOutcomePattern).where(
                    AutomationOutcomePattern.id == pattern_id
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Failed to refetch pattern {pattern_id}: {e}", exc_info=True)
            return None

    async def _get_matching_pattern(
        self,
        context: HealingContext,
    ) -> AutomationOutcomePattern | None:
        """Find matching healing pattern for automation.

        Looks for patterns where healing has succeeded multiple times for this
        automation, ordered by healing success count.

        Args:
            context: Healing context with automation info

        Returns:
            Matching pattern or None if no pattern found
        """
        try:
            async with self.database.async_session() as session:
                stmt = (
                    select(AutomationOutcomePattern)
                    .where(
                        and_(
                            AutomationOutcomePattern.instance_id == context.instance_id,
                            AutomationOutcomePattern.automation_id == context.automation_id,
                            AutomationOutcomePattern.healing_success_count
                            >= self.pattern_match_threshold,
                            AutomationOutcomePattern.successful_healing_level.isnot(None),
                        )
                    )
                    .order_by(desc(AutomationOutcomePattern.healing_success_count))
                    .limit(1)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Failed to query healing patterns: {e}", exc_info=True)
            return None

    async def _create_cascade_record(self, context: HealingContext) -> int:
        """Create cascade execution record in database.

        Args:
            context: Healing context

        Returns:
            Cascade execution record ID
        """
        try:
            async with self.database.async_session() as session:
                cascade_exec = HealingCascadeExecution(
                    instance_id=context.instance_id,
                    automation_id=context.automation_id,
                    execution_id=context.execution_id,
                    trigger_type=context.trigger_type,
                    failed_entities=context.failed_entities,
                    routing_strategy=ROUTING_STRATEGY_SEQUENTIAL,  # Will be updated if intelligent routing used
                    entity_level_attempted=False,
                    device_level_attempted=False,
                    integration_level_attempted=False,
                    created_at=datetime.now(UTC),
                )
                session.add(cascade_exec)
                await session.flush()
                cascade_id = cascade_exec.id
                await session.commit()
                return cascade_id

        except Exception as e:
            logger.error(f"Failed to create cascade record: {e}", exc_info=True)
            raise

    async def _execute_integration_healing(
        self, failed_entities: list[str], entity_results: dict[str, bool]
    ) -> bool:
        """Execute integration-level healing for failed entities.

        Args:
            failed_entities: List of entity IDs to heal
            entity_results: Dict to update with healing results

        Returns:
            True if any entity was successfully healed
        """
        integration_success = False

        # Heal integrations concurrently with semaphore control
        async def heal_integration(entity_id: str) -> bool:
            """Heal a single integration."""
            try:
                health_issue = HealthIssue(
                    entity_id=entity_id,
                    issue_type=ISSUE_TYPE_UNAVAILABLE,
                    detected_at=datetime.now(UTC),
                )
                return await self.integration_healer.heal(health_issue)
            except Exception as e:
                logger.error(f"Integration healing exception for {entity_id}: {e}")
                return False

        results = await self._heal_concurrently(failed_entities, heal_integration)

        for entity_id, result in results:
            if isinstance(result, BaseException):
                logger.error(f"Integration healing exception for {entity_id}: {result}")
                entity_results[entity_id] = False
            else:
                entity_results[entity_id] = result
                if result:
                    integration_success = True

        return integration_success

    async def _update_cascade_level(
        self,
        cascade_exec_id: int,
        level: HealingLevel,
        attempted: bool = False,
        success: bool | None = None,
    ) -> None:
        """Update cascade execution record for level attempt/result.

        Args:
            cascade_exec_id: Cascade execution record ID
            level: Healing level
            attempted: Whether level was attempted
            success: Whether level succeeded (None if only marking attempted)
        """
        try:
            async with self.database.async_session() as session:
                stmt = select(HealingCascadeExecution).where(
                    HealingCascadeExecution.id == cascade_exec_id
                )
                result = await session.execute(stmt)
                cascade_exec = result.scalar_one_or_none()

                if not cascade_exec:
                    logger.warning(f"Cascade execution {cascade_exec_id} not found")
                    return

                if level == HealingLevel.ENTITY:
                    if attempted:
                        cascade_exec.entity_level_attempted = True
                    if success is not None:
                        cascade_exec.entity_level_success = success
                elif level == HealingLevel.DEVICE:
                    if attempted:
                        cascade_exec.device_level_attempted = True
                    if success is not None:
                        cascade_exec.device_level_success = success
                elif level == HealingLevel.INTEGRATION:
                    if attempted:
                        cascade_exec.integration_level_attempted = True
                    if success is not None:
                        cascade_exec.integration_level_success = success

                await session.commit()

        except Exception as e:
            logger.error(f"Failed to update cascade level: {e}", exc_info=True)

    async def _finalize_cascade_record(
        self,
        cascade_exec_id: int,
        success: bool,
        duration: float,
        routing_strategy: str | None = None,
    ) -> None:
        """Finalize cascade execution record.

        Args:
            cascade_exec_id: Cascade execution record ID
            success: Overall cascade success
            duration: Total duration in seconds
            routing_strategy: Routing strategy used (intelligent or sequential)
        """
        try:
            async with self.database.async_session() as session:
                stmt = select(HealingCascadeExecution).where(
                    HealingCascadeExecution.id == cascade_exec_id
                )
                result = await session.execute(stmt)
                cascade_exec = result.scalar_one_or_none()

                if not cascade_exec:
                    logger.warning(f"Cascade execution {cascade_exec_id} not found")
                    return

                cascade_exec.final_success = success
                cascade_exec.total_duration_seconds = duration
                cascade_exec.completed_at = datetime.now(UTC)
                if routing_strategy:
                    cascade_exec.routing_strategy = routing_strategy

                await session.commit()

        except Exception as e:
            logger.error(f"Failed to finalize cascade record: {e}", exc_info=True)

    async def _record_successful_pattern(
        self,
        context: HealingContext,
        level: HealingLevel,
        strategy: str,
    ) -> None:
        """Record or update successful healing pattern.

        Note: This method currently records patterns only for the first failed entity
        as a representative for the automation. This is a simplification that works well
        when all entities in an automation typically share the same healing strategy.
        For heterogeneous entity failures, consider recording patterns per entity.

        Args:
            context: Healing context
            level: Successful healing level
            strategy: Successful healing strategy
        """
        try:
            async with self.database.async_session() as session:
                # Try to find existing pattern for the first failed entity
                # (we use first entity as representative for pattern matching)
                if not context.failed_entities:
                    return

                entity_id = context.failed_entities[0]

                stmt = select(AutomationOutcomePattern).where(
                    and_(
                        AutomationOutcomePattern.instance_id == context.instance_id,
                        AutomationOutcomePattern.automation_id == context.automation_id,
                        AutomationOutcomePattern.entity_id == entity_id,
                    )
                )
                result = await session.execute(stmt)
                pattern = result.scalar_one_or_none()

                if pattern:
                    # Update existing pattern
                    pattern.successful_healing_level = level.value
                    pattern.successful_healing_strategy = strategy
                    pattern.healing_success_count += 1
                    pattern.last_observed = datetime.now(UTC)
                else:
                    # Create new pattern
                    pattern = AutomationOutcomePattern(
                        instance_id=context.instance_id,
                        automation_id=context.automation_id,
                        entity_id=entity_id,
                        observed_state="unknown",  # We don't track state here
                        successful_healing_level=level.value,
                        successful_healing_strategy=strategy,
                        healing_success_count=1,
                        first_observed=datetime.now(UTC),
                        last_observed=datetime.now(UTC),
                    )
                    session.add(pattern)

                await session.commit()
                logger.info(
                    f"Recorded successful healing pattern for {context.automation_id}: "
                    f"{level.value}/{strategy} (count: {pattern.healing_success_count})"
                )

        except Exception as e:
            logger.error(f"Failed to record healing pattern: {e}", exc_info=True)

    async def _update_pattern_success(self, pattern_id: int) -> None:
        """Increment healing success count for pattern.

        Args:
            pattern_id: Pattern ID to update
        """
        try:
            async with self.database.async_session() as session:
                stmt = select(AutomationOutcomePattern).where(
                    AutomationOutcomePattern.id == pattern_id
                )
                result = await session.execute(stmt)
                pattern = result.scalar_one_or_none()

                if pattern:
                    pattern.healing_success_count += 1
                    pattern.last_observed = datetime.now(UTC)
                    await session.commit()

        except Exception as e:
            logger.error(f"Failed to update pattern success: {e}", exc_info=True)
