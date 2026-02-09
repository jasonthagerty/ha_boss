"""Tests for cascade orchestrator plan-based routing integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ha_boss.healing.plan_executor import PlanExecutionResult, StepResult
from ha_boss.healing.plan_matcher import PlanMatcher
from ha_boss.healing.plan_models import HealingPlanDefinition

from ha_boss.core.database import Database
from ha_boss.healing.cascade_orchestrator import (
    ROUTING_STRATEGY_PLAN,
    ROUTING_STRATEGY_SEQUENTIAL,
    CascadeOrchestrator,
    HealingContext,
)
from ha_boss.healing.device_healer import DeviceHealer
from ha_boss.healing.entity_healer import EntityHealer
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.healing.heal_strategies import HealingManager


@pytest.fixture
def mock_database() -> AsyncMock:
    """Create mock database."""
    db = AsyncMock(spec=Database)
    # Mock async context manager
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    db.async_session.return_value = session
    return db


@pytest.fixture
def mock_entity_healer() -> AsyncMock:
    """Create mock entity healer."""
    return AsyncMock(spec=EntityHealer)


@pytest.fixture
def mock_device_healer() -> AsyncMock:
    """Create mock device healer."""
    return AsyncMock(spec=DeviceHealer)


@pytest.fixture
def mock_integration_healer() -> AsyncMock:
    """Create mock integration healer."""
    return AsyncMock(spec=HealingManager)


@pytest.fixture
def mock_escalator() -> AsyncMock:
    """Create mock notification escalator."""
    return AsyncMock(spec=NotificationEscalator)


@pytest.fixture
def mock_plan_matcher() -> MagicMock:
    """Create mock plan matcher."""
    return MagicMock(spec=PlanMatcher)


@pytest.fixture
def mock_plan_executor() -> AsyncMock:
    """Create mock plan executor."""
    return AsyncMock()


@pytest.fixture
def healing_context() -> HealingContext:
    """Create healing context for tests."""
    return HealingContext(
        instance_id="test",
        automation_id="automation.test",
        execution_id=1,
        trigger_type="outcome_failure",
        failed_entities=["light.test1", "light.test2"],
        timeout_seconds=120.0,
    )


@pytest.fixture
def mock_plan() -> HealingPlanDefinition:
    """Create mock healing plan."""
    return MagicMock(spec=HealingPlanDefinition, name="test_plan")


@pytest.mark.asyncio
async def test_cascade_with_no_plan_components(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    healing_context: HealingContext,
) -> None:
    """Orchestrator without plan_matcher/plan_executor works normally."""
    # Create orchestrator WITHOUT plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=None,  # Explicitly None
        plan_executor=None,  # Explicitly None
    )

    # Mock the cascade record methods
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(orchestrator, "_get_matching_pattern", return_value=None),
    ):
        # Mock entity healing to succeed
        from ha_boss.healing.entity_healer import EntityHealingResult

        mock_entity_healer.heal.return_value = EntityHealingResult(
            success=True, final_action="retry_service_call"
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=False)

        # Should use sequential routing (no plan components available)
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
        assert mock_entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_matches_and_succeeds(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    mock_plan_matcher: MagicMock,
    mock_plan_executor: AsyncMock,
    healing_context: HealingContext,
    mock_plan: HealingPlanDefinition,
) -> None:
    """Plan matches, executes successfully, returns CascadeResult with routing_strategy='plan'."""
    # Setup plan matcher to return a plan
    mock_plan_matcher.find_matching_plan.return_value = mock_plan

    # Setup plan executor to return success
    plan_result = PlanExecutionResult(
        success=True,
        plan_name="test_plan",
        steps_attempted=2,
        steps_succeeded=2,
        total_duration_seconds=1.5,
        step_results=[
            StepResult(
                step_index=0,
                step_type="entity",
                success=True,
                duration_seconds=0.5,
                target="light.test1",
            ),
            StepResult(
                step_index=1,
                step_type="entity",
                success=True,
                duration_seconds=1.0,
                target="light.test2",
            ),
        ],
        error_message=None,
    )
    mock_plan_executor.execute_plan.return_value = plan_result

    # Create orchestrator WITH plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=mock_plan_matcher,
        plan_executor=mock_plan_executor,
    )

    # Mock the cascade record methods
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
    ):
        # Execute cascade
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=True)

        # Should use plan routing
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_PLAN
        assert result.successful_strategy == "plan:test_plan"
        assert result.entity_results == {"light.test1": True, "light.test2": True}
        assert result.total_duration_seconds == 1.5

        # Verify plan executor was called
        mock_plan_executor.execute_plan.assert_called_once()
        call_args = mock_plan_executor.execute_plan.call_args
        assert call_args.kwargs["plan"] == mock_plan
        assert call_args.kwargs["context"] == healing_context
        assert call_args.kwargs["cascade_execution_id"] == 1

        # Verify entity/device healers were NOT called (plan handled it)
        mock_entity_healer.heal.assert_not_called()
        mock_device_healer.heal.assert_not_called()


@pytest.mark.asyncio
async def test_plan_routing_matches_but_fails(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    mock_plan_matcher: MagicMock,
    mock_plan_executor: AsyncMock,
    healing_context: HealingContext,
    mock_plan: HealingPlanDefinition,
) -> None:
    """Plan matches but fails, falls through to intelligent/sequential routing."""
    # Setup plan matcher to return a plan
    mock_plan_matcher.find_matching_plan.return_value = mock_plan

    # Setup plan executor to return failure
    plan_result = PlanExecutionResult(
        success=False,
        plan_name="test_plan",
        steps_attempted=1,
        steps_succeeded=0,
        total_duration_seconds=0.5,
        step_results=[
            StepResult(
                step_index=0,
                step_type="entity",
                success=False,
                duration_seconds=0.5,
                target="light.test1",
                error="Failed to heal",
            )
        ],
        error_message="Plan execution failed",
    )
    mock_plan_executor.execute_plan.return_value = plan_result

    # Create orchestrator WITH plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=mock_plan_matcher,
        plan_executor=mock_plan_executor,
    )

    # Mock the cascade record methods
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(orchestrator, "_get_matching_pattern", return_value=None),
    ):
        # Mock entity healing to succeed
        from ha_boss.healing.entity_healer import EntityHealingResult

        mock_entity_healer.heal.return_value = EntityHealingResult(
            success=True, final_action="retry_service_call"
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=True)

        # Plan failed, should fall through to sequential routing
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
        assert mock_plan_executor.execute_plan.called
        assert mock_entity_healer.heal.called  # Falls through to entity healing


@pytest.mark.asyncio
async def test_plan_routing_no_match(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    mock_plan_matcher: MagicMock,
    mock_plan_executor: AsyncMock,
    healing_context: HealingContext,
) -> None:
    """No plan matches, falls through to existing routing."""
    # Setup plan matcher to return None (no match)
    mock_plan_matcher.find_matching_plan.return_value = None

    # Create orchestrator WITH plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=mock_plan_matcher,
        plan_executor=mock_plan_executor,
    )

    # Mock the cascade record methods
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(orchestrator, "_get_matching_pattern", return_value=None),
    ):
        # Mock entity healing to succeed
        from ha_boss.healing.entity_healer import EntityHealingResult

        mock_entity_healer.heal.return_value = EntityHealingResult(
            success=True, final_action="retry_service_call"
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=False)

        # No plan matched, should use sequential routing
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
        mock_plan_matcher.find_matching_plan.assert_called_once()
        mock_plan_executor.execute_plan.assert_not_called()
        assert mock_entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_exception_falls_through(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    mock_plan_matcher: MagicMock,
    mock_plan_executor: AsyncMock,
    healing_context: HealingContext,
) -> None:
    """Plan matcher throws exception, falls through gracefully."""
    # Setup plan matcher to raise exception
    mock_plan_matcher.find_matching_plan.side_effect = RuntimeError("Plan matching failed")

    # Create orchestrator WITH plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=mock_plan_matcher,
        plan_executor=mock_plan_executor,
    )

    # Mock the cascade record methods
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(orchestrator, "_get_matching_pattern", return_value=None),
    ):
        # Mock entity healing to succeed
        from ha_boss.healing.entity_healer import EntityHealingResult

        mock_entity_healer.heal.return_value = EntityHealingResult(
            success=True, final_action="retry_service_call"
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=False)

        # Exception should be caught, should fall through to sequential routing
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
        assert mock_entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_before_intelligent(
    mock_database: AsyncMock,
    mock_entity_healer: AsyncMock,
    mock_device_healer: AsyncMock,
    mock_integration_healer: AsyncMock,
    mock_escalator: AsyncMock,
    mock_plan_matcher: MagicMock,
    mock_plan_executor: AsyncMock,
    healing_context: HealingContext,
    mock_plan: HealingPlanDefinition,
) -> None:
    """Verify plan routing is checked before intelligent routing."""
    # Setup plan matcher to return a plan
    mock_plan_matcher.find_matching_plan.return_value = mock_plan

    # Setup plan executor to return success
    plan_result = PlanExecutionResult(
        success=True,
        plan_name="test_plan",
        steps_attempted=2,
        steps_succeeded=2,
        total_duration_seconds=1.5,
        step_results=[
            StepResult(
                step_index=0,
                step_type="entity",
                success=True,
                duration_seconds=0.5,
                target="light.test1",
            ),
            StepResult(
                step_index=1,
                step_type="entity",
                success=True,
                duration_seconds=1.0,
                target="light.test2",
            ),
        ],
        error_message=None,
    )
    mock_plan_executor.execute_plan.return_value = plan_result

    # Create orchestrator WITH plan components
    orchestrator = CascadeOrchestrator(
        database=mock_database,
        entity_healer=mock_entity_healer,
        device_healer=mock_device_healer,
        integration_healer=mock_integration_healer,
        escalator=mock_escalator,
        plan_matcher=mock_plan_matcher,
        plan_executor=mock_plan_executor,
    )

    # Mock the cascade record methods and pattern lookup
    with (
        patch.object(orchestrator, "_create_cascade_record", return_value=1),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock
        ) as mock_pattern_lookup,
    ):
        # Execute cascade with intelligent routing enabled
        result = await orchestrator.execute_cascade(healing_context, use_intelligent_routing=True)

        # Plan routing should succeed
        assert result.success is True
        assert result.routing_strategy == ROUTING_STRATEGY_PLAN

        # Intelligent routing pattern lookup should NOT be called
        mock_pattern_lookup.assert_not_called()

        # Entity/device healers should NOT be called
        mock_entity_healer.heal.assert_not_called()
        mock_device_healer.heal.assert_not_called()
