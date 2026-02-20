"""Tests for cascade orchestrator plan-based routing integration."""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.healing.cascade_orchestrator import (
    ROUTING_STRATEGY_PLAN,
    ROUTING_STRATEGY_SEQUENTIAL,
    CascadeOrchestrator,
    HealingContext,
)
from ha_boss.healing.entity_healer import EntityHealingResult


# Minimal stand-in dataclasses matching plan_executor signatures.
# The real modules live on separate PR branches; these avoid import deps.
@dataclass
class StepResult:
    step_name: str
    level: str
    action: str
    success: bool
    duration_seconds: float
    error_message: str | None = None


@dataclass
class PlanExecutionResult:
    plan_name: str
    success: bool
    steps_attempted: list[StepResult] = field(default_factory=list)
    steps_succeeded: int = 0
    steps_failed: int = 0
    total_duration_seconds: float = 0.0
    error_message: str | None = None


def _make_entity_result(
    entity_id: str = "light.test1", success: bool = True
) -> EntityHealingResult:
    return EntityHealingResult(
        entity_id=entity_id,
        success=success,
        actions_attempted=["retry_service_call"],
        final_action="retry_service_call" if success else None,
        error_message=None,
        total_duration_seconds=0.5,
    )


def _make_orchestrator(
    plan_matcher: MagicMock | None = None,
    plan_executor: AsyncMock | None = None,
) -> CascadeOrchestrator:
    """Create orchestrator with all healer mocks and optional plan components."""
    return CascadeOrchestrator(
        database=MagicMock(),
        entity_healer=AsyncMock(),
        device_healer=AsyncMock(),
        integration_healer=AsyncMock(),
        escalator=AsyncMock(),
        plan_matcher=plan_matcher,
        plan_executor=plan_executor,
    )


def _make_context() -> HealingContext:
    return HealingContext(
        instance_id="test",
        automation_id="automation.test",
        execution_id=1,
        trigger_type="outcome_failure",
        failed_entities=["light.test1", "light.test2"],
        timeout_seconds=120.0,
    )


def _make_plan_mock(name: str = "test_plan") -> MagicMock:
    """Create a mock plan. Sets .name as an attribute (not the MagicMock internal name)."""
    plan = MagicMock()
    plan.name = name
    return plan


def _success_plan_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        plan_name="test_plan",
        success=True,
        steps_attempted=[
            StepResult(
                step_name="retry",
                level="entity",
                action="retry_service_call",
                success=True,
                duration_seconds=0.5,
            ),
        ],
        steps_succeeded=1,
        total_duration_seconds=1.5,
    )


def _failure_plan_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        plan_name="test_plan",
        success=False,
        steps_attempted=[
            StepResult(
                step_name="retry",
                level="entity",
                action="retry_service_call",
                success=False,
                duration_seconds=0.5,
                error_message="Failed",
            ),
        ],
        steps_failed=1,
        total_duration_seconds=0.5,
        error_message="Plan execution failed",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_with_no_plan_components() -> None:
    """Orchestrator without plan_matcher/plan_executor works normally."""
    orchestrator = _make_orchestrator(plan_matcher=None, plan_executor=None)
    orchestrator.entity_healer.heal.return_value = _make_entity_result()

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock, return_value=None
        ),
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=False)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
    assert orchestrator.entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_matches_and_succeeds() -> None:
    """Plan matches and executes successfully → routing_strategy='plan'."""
    plan_matcher = MagicMock()
    plan_executor = AsyncMock()
    mock_plan = _make_plan_mock("test_plan")

    plan_matcher.find_matching_plan = AsyncMock(return_value=mock_plan)
    plan_executor.execute_plan.return_value = _success_plan_result()

    orchestrator = _make_orchestrator(plan_matcher=plan_matcher, plan_executor=plan_executor)

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=True)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_PLAN
    assert result.successful_strategy == "plan:test_plan"
    assert result.entity_results == {"light.test1": True, "light.test2": True}
    assert result.total_duration_seconds == 1.5

    plan_executor.execute_plan.assert_called_once()
    call_kw = plan_executor.execute_plan.call_args.kwargs
    assert call_kw["plan"] is mock_plan
    assert call_kw["cascade_execution_id"] == 1

    # Healers should NOT be called when plan succeeds
    orchestrator.entity_healer.heal.assert_not_called()
    orchestrator.device_healer.heal.assert_not_called()


@pytest.mark.asyncio
async def test_plan_routing_matches_but_fails_falls_through() -> None:
    """Plan matches but fails → falls through to sequential cascade."""
    plan_matcher = MagicMock()
    plan_executor = AsyncMock()
    mock_plan = _make_plan_mock()

    plan_matcher.find_matching_plan = AsyncMock(return_value=mock_plan)
    plan_executor.execute_plan.return_value = _failure_plan_result()

    orchestrator = _make_orchestrator(plan_matcher=plan_matcher, plan_executor=plan_executor)
    orchestrator.entity_healer.heal.return_value = _make_entity_result()

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock, return_value=None
        ),
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=False)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
    assert plan_executor.execute_plan.called
    assert orchestrator.entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_no_match() -> None:
    """No plan matches → falls through to existing routing."""
    plan_matcher = MagicMock()
    plan_executor = AsyncMock()

    plan_matcher.find_matching_plan = AsyncMock(return_value=None)

    orchestrator = _make_orchestrator(plan_matcher=plan_matcher, plan_executor=plan_executor)
    orchestrator.entity_healer.heal.return_value = _make_entity_result()

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock, return_value=None
        ),
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=False)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
    plan_matcher.find_matching_plan.assert_called_once()
    plan_executor.execute_plan.assert_not_called()
    assert orchestrator.entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_exception_falls_through() -> None:
    """Plan matcher throws exception → falls through gracefully."""
    plan_matcher = MagicMock()
    plan_executor = AsyncMock()

    plan_matcher.find_matching_plan = AsyncMock(side_effect=RuntimeError("Plan matching failed"))

    orchestrator = _make_orchestrator(plan_matcher=plan_matcher, plan_executor=plan_executor)
    orchestrator.entity_healer.heal.return_value = _make_entity_result()

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock, return_value=None
        ),
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=False)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_SEQUENTIAL
    assert orchestrator.entity_healer.heal.called


@pytest.mark.asyncio
async def test_plan_routing_before_intelligent() -> None:
    """Plan routing is checked before intelligent routing."""
    plan_matcher = MagicMock()
    plan_executor = AsyncMock()
    mock_plan = _make_plan_mock("test_plan")

    plan_matcher.find_matching_plan = AsyncMock(return_value=mock_plan)
    plan_executor.execute_plan.return_value = _success_plan_result()

    orchestrator = _make_orchestrator(plan_matcher=plan_matcher, plan_executor=plan_executor)

    with (
        patch.object(
            orchestrator, "_create_cascade_record", new_callable=AsyncMock, return_value=1
        ),
        patch.object(orchestrator, "_finalize_cascade_record", new_callable=AsyncMock),
        patch.object(
            orchestrator, "_get_matching_pattern", new_callable=AsyncMock, return_value=None
        ) as mock_pattern_lookup,
    ):
        result = await orchestrator.execute_cascade(_make_context(), use_intelligent_routing=True)

    assert result.success is True
    assert result.routing_strategy == ROUTING_STRATEGY_PLAN
    # Intelligent routing should NOT be called when plan succeeds
    mock_pattern_lookup.assert_not_called()
    orchestrator.entity_healer.heal.assert_not_called()
    orchestrator.device_healer.heal.assert_not_called()
