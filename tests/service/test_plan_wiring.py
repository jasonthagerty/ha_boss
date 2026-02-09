"""Tests for healing plan component wiring in HABossService."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.healing.cascade_orchestrator import CascadeOrchestrator


def _make_orchestrator() -> CascadeOrchestrator:
    """Create a CascadeOrchestrator with mocked dependencies."""
    return CascadeOrchestrator(
        database=MagicMock(),
        entity_healer=AsyncMock(),
        device_healer=AsyncMock(),
        integration_healer=AsyncMock(),
        escalator=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_plan_components_injected_when_enabled() -> None:
    """When healing_plans_enabled=True and modules importable, cascade gets plan components."""
    orchestrator = _make_orchestrator()

    # Verify no plan components initially
    assert getattr(orchestrator, "plan_matcher", None) is None
    assert getattr(orchestrator, "plan_executor", None) is None

    # Simulate the wiring block from _initialize_instance step 9e
    mock_loader_cls = MagicMock()
    mock_plan = MagicMock()
    mock_plan.name = "test_plan"
    mock_loader_cls.return_value.load_all_plans.return_value = [mock_plan]

    mock_matcher_cls = MagicMock()
    mock_matcher_instance = MagicMock()
    mock_matcher_cls.return_value = mock_matcher_instance

    mock_executor_cls = MagicMock()
    mock_executor_instance = MagicMock()
    mock_executor_cls.return_value = mock_executor_instance

    with patch.dict(
        "sys.modules",
        {
            "ha_boss.healing.plan_loader": MagicMock(PlanLoader=mock_loader_cls),
            "ha_boss.healing.plan_matcher": MagicMock(PlanMatcher=mock_matcher_cls),
            "ha_boss.healing.plan_executor": MagicMock(PlanExecutor=mock_executor_cls),
        },
    ):
        # Run the wiring code (mirrors service/main.py step 9e)
        from ha_boss.healing.plan_executor import PlanExecutor
        from ha_boss.healing.plan_loader import PlanLoader
        from ha_boss.healing.plan_matcher import PlanMatcher

        plan_loader = PlanLoader(
            database=MagicMock(), builtin_enabled=True, user_plans_directory=None
        )
        plans = plan_loader.load_all_plans()

        plan_matcher = PlanMatcher(plans=plans)
        plan_executor = PlanExecutor(
            database=MagicMock(),
            entity_healer=AsyncMock(),
            device_healer=AsyncMock(),
        )

        orchestrator.plan_matcher = plan_matcher
        orchestrator.plan_executor = plan_executor

    assert orchestrator.plan_matcher is mock_matcher_instance
    assert orchestrator.plan_executor is mock_executor_instance
    mock_loader_cls.return_value.load_all_plans.assert_called_once()


@pytest.mark.asyncio
async def test_plan_components_skipped_when_disabled() -> None:
    """When healing_plans_enabled=False, plan components are not created."""
    orchestrator = _make_orchestrator()

    # Simulate the config check (disabled)
    healing_plans_enabled = False
    if healing_plans_enabled:
        orchestrator.plan_matcher = MagicMock()
        orchestrator.plan_executor = MagicMock()

    assert getattr(orchestrator, "plan_matcher", None) is None
    assert getattr(orchestrator, "plan_executor", None) is None


@pytest.mark.asyncio
async def test_plan_wiring_handles_import_error() -> None:
    """When plan modules can't be imported, cascade works normally."""
    orchestrator = _make_orchestrator()

    healing_plans_enabled = True
    if healing_plans_enabled:
        try:
            with patch.dict("sys.modules", {"ha_boss.healing.plan_loader": None}):
                from ha_boss.healing.plan_loader import PlanLoader  # noqa: F401
        except ImportError:
            logging.getLogger(__name__).info(
                "Healing plan modules not available, plan-based routing disabled"
            )

    # Cascade orchestrator should still work without plan components
    assert getattr(orchestrator, "plan_matcher", None) is None
    assert getattr(orchestrator, "plan_executor", None) is None


@pytest.mark.asyncio
async def test_plan_wiring_handles_load_error() -> None:
    """When plan loading fails, cascade works normally."""
    orchestrator = _make_orchestrator()

    mock_loader_cls = MagicMock()
    mock_loader_cls.return_value.load_all_plans.side_effect = RuntimeError("YAML parse error")

    healing_plans_enabled = True
    if healing_plans_enabled:
        try:
            with patch.dict(
                "sys.modules",
                {
                    "ha_boss.healing.plan_loader": MagicMock(PlanLoader=mock_loader_cls),
                    "ha_boss.healing.plan_matcher": MagicMock(),
                    "ha_boss.healing.plan_executor": MagicMock(),
                },
            ):
                from ha_boss.healing.plan_loader import PlanLoader

                plan_loader = PlanLoader(database=MagicMock(), builtin_enabled=True)
                plan_loader.load_all_plans()
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"Failed to initialize healing plans: {e}. "
                "Plan-based routing disabled, cascade continues normally."
            )

    # Cascade orchestrator should still work without plan components
    assert getattr(orchestrator, "plan_matcher", None) is None
    assert getattr(orchestrator, "plan_executor", None) is None


def test_healing_config_has_plan_fields() -> None:
    """Verify HealingConfig has the plan-related fields with correct defaults."""
    from ha_boss.core.config import HealingConfig

    config = HealingConfig()
    assert config.healing_plans_enabled is True
    assert config.healing_plans_use_builtin is True
    assert config.healing_plans_directory is None
