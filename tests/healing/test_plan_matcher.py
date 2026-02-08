"""Tests for healing plan matcher."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ha_boss.healing.cascade_orchestrator import HealingContext
from ha_boss.healing.plan_loader import PlanLoader
from ha_boss.healing.plan_matcher import PlanMatcher
from ha_boss.healing.plan_models import (
    HealingPlanDefinition,
    HealingStep,
    MatchCriteria,
    OnFailureConfig,
    TimeWindow,
)


def _make_plan(
    name: str,
    priority: int = 0,
    entity_patterns: list[str] | None = None,
    integration_domains: list[str] | None = None,
    failure_types: list[str] | None = None,
    time_window: TimeWindow | None = None,
    enabled: bool = True,
) -> HealingPlanDefinition:
    """Create a healing plan with default step.

    If no criteria are specified, defaults to failure_types=["unavailable"]
    to satisfy the MatchCriteria validator requiring at least one criterion.
    """
    ep = entity_patterns or []
    ids = integration_domains or []
    ft = failure_types if failure_types is not None else []
    # Ensure at least one criterion exists for Pydantic validation
    if not ep and not ids and not ft:
        ft = ["unavailable"]
    match_criteria = MatchCriteria(
        entity_patterns=ep,
        integration_domains=ids,
        failure_types=ft,
        time_window=time_window,
    )

    return HealingPlanDefinition(
        name=name,
        priority=priority,
        enabled=enabled,
        match=match_criteria,
        steps=[
            HealingStep(
                name="reload",
                level="integration",
                action="reload_integration",
            )
        ],
        on_failure=OnFailureConfig(),
    )


def _make_context(
    entities: list[str],
    automation_id: str = "test_auto",
    instance_id: str = "test_instance",
) -> HealingContext:
    """Create a healing context."""
    return HealingContext(
        automation_id=automation_id,
        instance_id=instance_id,
        execution_id=None,
        trigger_type="trigger_failure",
        failed_entities=entities,
    )


def _make_matcher(plans: list[HealingPlanDefinition]) -> PlanMatcher:
    """Create a plan matcher with mocked plan loader."""
    mock_loader = Mock(spec=PlanLoader)
    mock_loader.get_all_enabled_plans = AsyncMock(return_value=plans)
    return PlanMatcher(plan_loader=mock_loader)


class TestEntityPatternMatching:
    @pytest.mark.asyncio
    async def test_exact_entity_match(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.bedroom"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context)

        assert result == plan

    @pytest.mark.asyncio
    async def test_glob_pattern_match(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.zigbee_*"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.zigbee_lamp_1", "light.zigbee_lamp_2"])

        result = await matcher.find_matching_plan(context)

        assert result == plan

    @pytest.mark.asyncio
    async def test_no_pattern_match(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.bedroom"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.kitchen"])

        result = await matcher.find_matching_plan(context)

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_patterns_any_match(self) -> None:
        plan = _make_plan(
            "test",
            entity_patterns=["light.bedroom", "switch.garage"],
        )
        matcher = _make_matcher([plan])
        context = _make_context(["switch.garage", "light.kitchen"])

        result = await matcher.find_matching_plan(context)

        assert result == plan

    @pytest.mark.asyncio
    async def test_multiple_entities_any_match(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.bedroom"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.kitchen", "light.bedroom", "switch.garage"])

        result = await matcher.find_matching_plan(context)

        assert result == plan


class TestIntegrationDomainMatching:
    @pytest.mark.asyncio
    async def test_entity_matches_domain(self) -> None:
        plan = _make_plan("test", integration_domains=["zigbee2mqtt"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])
        entity_map = {"light.bedroom": "zigbee2mqtt"}

        result = await matcher.find_matching_plan(context, entity_integration_map=entity_map)

        assert result == plan

    @pytest.mark.asyncio
    async def test_entity_no_domain_match(self) -> None:
        plan = _make_plan("test", integration_domains=["zigbee2mqtt"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])
        entity_map = {"light.bedroom": "zwave"}

        result = await matcher.find_matching_plan(context, entity_integration_map=entity_map)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_integration_map_skips_check(self) -> None:
        plan = _make_plan("test", integration_domains=["zigbee2mqtt"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context, entity_integration_map=None)

        assert result == plan

    @pytest.mark.asyncio
    async def test_entity_not_in_map(self) -> None:
        plan = _make_plan("test", integration_domains=["zigbee2mqtt"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom", "light.kitchen"])
        entity_map = {"light.bedroom": "zwave"}

        result = await matcher.find_matching_plan(context, entity_integration_map=entity_map)

        assert result is None


class TestFailureTypeMatching:
    @pytest.mark.asyncio
    async def test_matching_failure_type(self) -> None:
        plan = _make_plan("test", failure_types=["unavailable"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context, failure_type="unavailable")

        assert result == plan

    @pytest.mark.asyncio
    async def test_non_matching_failure_type(self) -> None:
        plan = _make_plan("test", failure_types=["unavailable"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context, failure_type="timeout")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_failure_types_matches_all(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.*"], failure_types=[])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context, failure_type="timeout")

        assert result == plan


class TestTimeWindowMatching:
    @pytest.mark.asyncio
    async def test_within_time_window(self) -> None:
        plan = _make_plan("test", time_window=TimeWindow(start_hour=8, end_hour=18))
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        with patch("ha_boss.healing.plan_matcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 12, 0)
            result = await matcher.find_matching_plan(context)

        assert result == plan

    @pytest.mark.asyncio
    async def test_outside_time_window(self) -> None:
        plan = _make_plan("test", time_window=TimeWindow(start_hour=8, end_hour=18))
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        with patch("ha_boss.healing.plan_matcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 20, 0)
            result = await matcher.find_matching_plan(context)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_time_window_matches_all(self) -> None:
        plan = _make_plan("test", time_window=None)
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        with patch("ha_boss.healing.plan_matcher.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 3, 0)
            result = await matcher.find_matching_plan(context)

        assert result == plan


class TestPlanMatcherFindPlan:
    @pytest.mark.asyncio
    async def test_no_enabled_plans_returns_none(self) -> None:
        matcher = _make_matcher([])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context)

        assert result is None

    @pytest.mark.asyncio
    async def test_single_matching_plan(self) -> None:
        plan = _make_plan("test", entity_patterns=["light.*"])
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context)

        assert result == plan

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        low_priority = _make_plan("low", priority=10, entity_patterns=["light.*"])
        high_priority = _make_plan("high", priority=100, entity_patterns=["light.*"])
        matcher = _make_matcher([high_priority, low_priority])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context)

        assert result == high_priority

    @pytest.mark.asyncio
    async def test_no_matching_plan_returns_none(self) -> None:
        plan1 = _make_plan("test1", entity_patterns=["switch.*"])
        plan2 = _make_plan("test2", failure_types=["timeout"])
        matcher = _make_matcher([plan1, plan2])
        context = _make_context(["light.bedroom"])

        result = await matcher.find_matching_plan(context, failure_type="unavailable")

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_criteria_all_must_match(self) -> None:
        plan = _make_plan(
            "test",
            entity_patterns=["light.*"],
            failure_types=["unavailable"],
            integration_domains=["zigbee2mqtt"],
        )
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])
        entity_map = {"light.bedroom": "zigbee2mqtt"}

        result = await matcher.find_matching_plan(
            context,
            entity_integration_map=entity_map,
            failure_type="unavailable",
        )

        assert result == plan

    @pytest.mark.asyncio
    async def test_multiple_criteria_any_fails_no_match(self) -> None:
        plan = _make_plan(
            "test",
            entity_patterns=["light.*"],
            failure_types=["unavailable"],
            integration_domains=["zigbee2mqtt"],
        )
        matcher = _make_matcher([plan])
        context = _make_context(["light.bedroom"])
        entity_map = {"light.bedroom": "zwave"}

        result = await matcher.find_matching_plan(
            context,
            entity_integration_map=entity_map,
            failure_type="unavailable",
        )

        assert result is None


class TestMatchCriteriaToDict:
    def test_converts_to_dict(self) -> None:
        criteria = MatchCriteria(
            entity_patterns=["light.*"],
            integration_domains=["zigbee2mqtt"],
            failure_types=["unavailable"],
            time_window=TimeWindow(start_hour=8, end_hour=18),
        )

        result = PlanMatcher.match_criteria_to_dict(criteria)

        assert isinstance(result, dict)
        assert result["entity_patterns"] == ["light.*"]
        assert result["integration_domains"] == ["zigbee2mqtt"]
        assert result["failure_types"] == ["unavailable"]
        assert result["time_window"] == {"start_hour": 8, "end_hour": 18}
        assert result["device_manufacturers"] == []
