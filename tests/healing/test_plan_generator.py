"""Tests for PlanGenerator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.healing.plan_generator import PlanGenerator
from ha_boss.healing.plan_models import HealingPlanDefinition
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

VALID_YAML = """
name: test_zha_recovery
description: Recover ZHA entities
priority: 50
match:
  entity_patterns: ["light.*"]
  integration_domains: ["zha"]
  failure_types: ["unavailable"]
steps:
  - name: reload_integration
    level: integration
    action: reload_integration
    timeout_seconds: 30
tags: ["zha", "lights"]
"""

VALID_YAML_IN_BLOCK = f"```yaml\n{VALID_YAML}\n```"


def make_llm_router(return_value: str | None) -> LLMRouter:
    router = MagicMock(spec=LLMRouter)
    router.generate = AsyncMock(return_value=return_value)
    return router


@pytest.mark.asyncio
async def test_generate_plan_success() -> None:
    """Test successful plan generation with mocked LLM."""
    router = make_llm_router(VALID_YAML)
    generator = PlanGenerator(llm_router=router)

    plan = await generator.generate_plan(
        failed_entities=["light.bedroom"],
        failure_type="unavailable",
        integration_domain="zha",
    )

    assert plan is not None
    assert isinstance(plan, HealingPlanDefinition)
    assert plan.name == "test_zha_recovery"
    assert len(plan.steps) == 1
    router.generate.assert_called_once()


@pytest.mark.asyncio
async def test_generate_plan_success_with_yaml_code_block() -> None:
    """Test that YAML inside markdown code block is extracted correctly."""
    router = make_llm_router(VALID_YAML_IN_BLOCK)
    generator = PlanGenerator(llm_router=router)

    plan = await generator.generate_plan(
        failed_entities=["light.bedroom"],
        failure_type="unavailable",
    )

    assert plan is not None
    assert plan.name == "test_zha_recovery"


@pytest.mark.asyncio
async def test_generate_plan_retry_on_first_failure() -> None:
    """Test that generator retries once when first response fails validation."""
    invalid_yaml = "name: bad_plan\n# missing required fields"
    router = make_llm_router(None)
    # First call: invalid YAML; second call: valid YAML
    router.generate = AsyncMock(side_effect=[invalid_yaml, VALID_YAML])
    generator = PlanGenerator(llm_router=router)

    plan = await generator.generate_plan(
        failed_entities=["sensor.temp"],
        failure_type="unavailable",
    )

    assert plan is not None
    assert plan.name == "test_zha_recovery"
    assert router.generate.call_count == 2

    # Second call should include error context in prompt
    second_call_prompt = router.generate.call_args_list[1][1]["prompt"]
    assert "validation" in second_call_prompt.lower() or "failed" in second_call_prompt.lower()


@pytest.mark.asyncio
async def test_generate_plan_returns_none_when_llm_unavailable() -> None:
    """Test that None is returned when LLM returns None."""
    router = make_llm_router(None)
    generator = PlanGenerator(llm_router=router)

    plan = await generator.generate_plan(
        failed_entities=["light.bedroom"],
        failure_type="unavailable",
    )

    assert plan is None


@pytest.mark.asyncio
async def test_generate_plan_returns_none_after_max_retries() -> None:
    """Test that None is returned when YAML is invalid after max retries."""
    invalid_yaml = "not: valid: yaml: {missing}"
    router = make_llm_router(invalid_yaml)
    generator = PlanGenerator(llm_router=router)

    plan = await generator.generate_plan(
        failed_entities=["light.bedroom"],
        failure_type="unavailable",
    )

    assert plan is None
    assert router.generate.call_count == 2  # One initial + one retry


@pytest.mark.asyncio
async def test_generate_plan_prompt_includes_context() -> None:
    """Test that prompt includes entity IDs, failure type, and integration domain."""
    router = make_llm_router(VALID_YAML)
    generator = PlanGenerator(llm_router=router)

    await generator.generate_plan(
        failed_entities=["light.bedroom", "light.hallway"],
        failure_type="unavailable",
        integration_domain="zha",
        levels_already_tried=["entity"],
    )

    call_kwargs = router.generate.call_args[1]
    prompt = call_kwargs["prompt"]
    assert "light.bedroom" in prompt
    assert "light.hallway" in prompt
    assert "unavailable" in prompt
    assert "zha" in prompt
    assert "entity" in prompt
    assert call_kwargs["complexity"] == TaskComplexity.COMPLEX
    assert call_kwargs["temperature"] == 0.3
    assert call_kwargs["max_tokens"] == 2000
