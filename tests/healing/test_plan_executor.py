"""Tests for plan executor module."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from ha_boss.core.database import Database
from ha_boss.healing.cascade_orchestrator import HealingContext
from ha_boss.healing.device_healer import DeviceHealer, DeviceHealingResult
from ha_boss.healing.entity_healer import EntityHealer, EntityHealingResult
from ha_boss.healing.plan_executor import PlanExecutionResult, PlanExecutor, StepResult
from ha_boss.healing.plan_models import (
    HealingPlanDefinition,
    HealingStep,
    MatchCriteria,
)


def _make_plan(steps: list[HealingStep]) -> HealingPlanDefinition:
    return HealingPlanDefinition(
        name="test_plan",
        description="Test plan",
        match=MatchCriteria(entity_patterns=["sensor.*"]),
        steps=steps,
    )


def _make_context(entities: list[str]) -> HealingContext:
    return HealingContext(
        instance_id="test_instance",
        automation_id="automation.test",
        execution_id=123,
        trigger_type="trigger_failure",
        failed_entities=entities,
    )


def _make_step(name: str, level: str, action: str, timeout_seconds: float = 30.0) -> HealingStep:
    return HealingStep(name=name, level=level, action=action, timeout_seconds=timeout_seconds)


class TestPlanExecutorStepExecution:
    @pytest.mark.asyncio
    async def test_entity_step_succeeds(self) -> None:
        db = Mock(spec=Database)
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=True,
                actions_attempted=["retry"],
                final_action="retry",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        step = _make_step("entity_retry", "entity", "retry")
        context = _make_context(["sensor.test"])

        success = await executor._execute_step(step, context)

        assert success is True
        entity_healer.heal.assert_awaited_once_with(
            entity_id="sensor.test",
            triggered_by="trigger_failure",
            automation_id="automation.test",
            execution_id=123,
        )

    @pytest.mark.asyncio
    async def test_entity_step_fails(self) -> None:
        db = Mock(spec=Database)
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=False,
                actions_attempted=["retry"],
                final_action=None,
                error_message="Entity still unavailable",
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        step = _make_step("entity_retry", "entity", "retry")
        context = _make_context(["sensor.test"])

        success = await executor._execute_step(step, context)

        assert success is False

    @pytest.mark.asyncio
    async def test_device_step_succeeds(self) -> None:
        db = Mock(spec=Database)
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=True,
                devices_healed=["dev1"],
                actions_attempted=["reconnect"],
                final_action="reconnect",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        step = _make_step("device_reconnect", "device", "reconnect")
        context = _make_context(["sensor.test"])

        success = await executor._execute_step(step, context)

        assert success is True
        device_healer.heal.assert_awaited_once_with(
            entity_ids=["sensor.test"],
            triggered_by="trigger_failure",
            automation_id="automation.test",
            execution_id=123,
        )

    @pytest.mark.asyncio
    async def test_device_step_fails(self) -> None:
        db = Mock(spec=Database)
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=False,
                devices_healed=[],
                actions_attempted=["reconnect"],
                final_action=None,
                error_message="Device unreachable",
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        step = _make_step("device_reconnect", "device", "reconnect")
        context = _make_context(["sensor.test"])

        success = await executor._execute_step(step, context)

        assert success is False

    @pytest.mark.asyncio
    async def test_integration_step_delegates_to_device_healer(self) -> None:
        db = Mock(spec=Database)
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=True,
                devices_healed=["dev1"],
                actions_attempted=["reload"],
                final_action="reload",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        step = _make_step("integration_reload", "integration", "reload")
        context = _make_context(["sensor.test"])

        success = await executor._execute_step(step, context)

        assert success is True
        device_healer.heal.assert_awaited_once()

    def test_unknown_level_validation(self) -> None:
        """Pydantic validates level at model creation time."""
        with pytest.raises(ValueError, match="Invalid level"):
            _make_step("invalid_step", "unknown_level", "action")


class TestPlanExecutorExecution:
    @pytest.mark.asyncio
    async def test_first_step_succeeds_stops_early(self) -> None:
        db = Mock(spec=Database)
        db.async_session = AsyncMock()
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=True,
                actions_attempted=["retry"],
                final_action="retry",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan(
            [
                _make_step("entity_retry", "entity", "retry"),
                _make_step("device_reconnect", "device", "reconnect"),
            ]
        )
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is True
        assert result.steps_succeeded == 1
        assert result.steps_failed == 0
        assert len(result.steps_attempted) == 1
        assert result.steps_attempted[0].step_name == "entity_retry"
        entity_healer.heal.assert_awaited_once()
        device_healer.heal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_through_to_second_step(self) -> None:
        db = Mock(spec=Database)
        db.async_session = AsyncMock()
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=False,
                actions_attempted=["retry"],
                final_action=None,
                error_message="Still unavailable",
                total_duration_seconds=1.0,
            )
        )

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=True,
                devices_healed=["dev1"],
                actions_attempted=["reconnect"],
                final_action="reconnect",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan(
            [
                _make_step("entity_retry", "entity", "retry"),
                _make_step("device_reconnect", "device", "reconnect"),
            ]
        )
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is True
        assert result.steps_succeeded == 1
        assert result.steps_failed == 1
        assert len(result.steps_attempted) == 2
        assert result.steps_attempted[0].success is False
        assert result.steps_attempted[1].success is True
        entity_healer.heal.assert_awaited_once()
        device_healer.heal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_steps_fail(self) -> None:
        db = Mock(spec=Database)
        db.async_session = AsyncMock()
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=False,
                actions_attempted=["retry"],
                final_action=None,
                error_message="Failed",
                total_duration_seconds=1.0,
            )
        )

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=False,
                devices_healed=[],
                actions_attempted=["reconnect"],
                final_action=None,
                error_message="Failed",
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan(
            [
                _make_step("entity_retry", "entity", "retry"),
                _make_step("device_reconnect", "device", "reconnect"),
            ]
        )
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is False
        assert result.steps_succeeded == 0
        assert result.steps_failed == 2
        assert len(result.steps_attempted) == 2

    @pytest.mark.asyncio
    async def test_step_timeout(self) -> None:
        db = Mock(spec=Database)
        db.async_session = AsyncMock()
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        async def slow_heal(*args, **kwargs):
            await asyncio.sleep(5.0)
            return EntityHealingResult(
                entity_id="sensor.test",
                success=True,
                actions_attempted=["retry"],
                final_action="retry",
                error_message=None,
                total_duration_seconds=5.0,
            )

        entity_healer.heal = AsyncMock(side_effect=slow_heal)

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan([_make_step("entity_retry", "entity", "retry", timeout_seconds=1)])
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is False
        assert result.steps_failed == 1
        assert "timed out" in result.steps_attempted[0].error_message

    @pytest.mark.asyncio
    async def test_step_exception_continues(self) -> None:
        db = Mock(spec=Database)
        db.async_session = AsyncMock()
        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(side_effect=RuntimeError("Healer error"))

        device_healer.heal = AsyncMock(
            return_value=DeviceHealingResult(
                devices_attempted=["dev1"],
                success=True,
                devices_healed=["dev1"],
                actions_attempted=["reconnect"],
                final_action="reconnect",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan(
            [
                _make_step("entity_retry", "entity", "retry"),
                _make_step("device_reconnect", "device", "reconnect"),
            ]
        )
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is True
        assert result.steps_failed == 1
        assert result.steps_succeeded == 1
        assert "Healer error" in result.steps_attempted[0].error_message

    @pytest.mark.asyncio
    async def test_records_to_database(self) -> None:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none = Mock(return_value=None)
        mock_session.commit = AsyncMock()

        db = Mock(spec=Database)
        db.async_session = Mock(return_value=mock_session)

        entity_healer = Mock(spec=EntityHealer)
        device_healer = Mock(spec=DeviceHealer)

        entity_healer.heal = AsyncMock(
            return_value=EntityHealingResult(
                entity_id="sensor.test",
                success=True,
                actions_attempted=["retry"],
                final_action="retry",
                error_message=None,
                total_duration_seconds=1.0,
            )
        )

        executor = PlanExecutor(db, entity_healer, device_healer)
        plan = _make_plan([_make_step("entity_retry", "entity", "retry")])
        context = _make_context(["sensor.test"])

        result = await executor.execute_plan(plan, context)

        assert result.success is True
        mock_session.add.assert_called_once()
        assert mock_session.commit.await_count >= 1


class TestPlanExecutionResult:
    def test_result_fields(self) -> None:
        result = PlanExecutionResult(
            plan_name="test_plan",
            success=True,
            steps_attempted=[
                StepResult(
                    step_name="step1",
                    level="entity",
                    action="retry",
                    success=True,
                    duration_seconds=1.5,
                )
            ],
            steps_succeeded=1,
            steps_failed=0,
            total_duration_seconds=2.0,
        )

        assert result.plan_name == "test_plan"
        assert result.success is True
        assert len(result.steps_attempted) == 1
        assert result.steps_succeeded == 1
        assert result.steps_failed == 0
        assert result.total_duration_seconds == 2.0
