"""Tests for healing plan Pydantic models."""

import pytest
from pydantic import ValidationError

from ha_boss.healing.plan_models import (
    HealingPlanDefinition,
    HealingStep,
    MatchCriteria,
    OnFailureConfig,
    TimeWindow,
)


class TestTimeWindow:
    """Tests for TimeWindow model."""

    def test_default_values(self):
        tw = TimeWindow()
        assert tw.start_hour == 0
        assert tw.end_hour == 24

    def test_custom_values(self):
        tw = TimeWindow(start_hour=8, end_hour=20)
        assert tw.start_hour == 8
        assert tw.end_hour == 20

    def test_invalid_hour(self):
        with pytest.raises(ValidationError):
            TimeWindow(start_hour=25)


class TestMatchCriteria:
    """Tests for MatchCriteria model."""

    def test_entity_patterns(self):
        mc = MatchCriteria(entity_patterns=["light.zigbee_*"])
        assert mc.has_any_criteria()

    def test_integration_domains(self):
        mc = MatchCriteria(integration_domains=["zha"])
        assert mc.has_any_criteria()

    def test_failure_types(self):
        mc = MatchCriteria(failure_types=["unavailable"])
        assert mc.has_any_criteria()

    def test_no_criteria(self):
        mc = MatchCriteria()
        assert not mc.has_any_criteria()

    def test_multiple_criteria(self):
        mc = MatchCriteria(
            entity_patterns=["light.*"],
            integration_domains=["zha"],
            failure_types=["unavailable", "unknown"],
        )
        assert mc.has_any_criteria()


class TestHealingStep:
    """Tests for HealingStep model."""

    def test_valid_step(self):
        step = HealingStep(
            name="retry",
            level="entity",
            action="retry_service_call",
        )
        assert step.name == "retry"
        assert step.level == "entity"
        assert step.timeout_seconds == 30.0

    def test_all_levels(self):
        for level in ["entity", "device", "integration"]:
            step = HealingStep(name="test", level=level, action="test")
            assert step.level == level

    def test_invalid_level(self):
        with pytest.raises(ValidationError, match="Invalid level"):
            HealingStep(name="test", level="invalid", action="test")

    def test_custom_params(self):
        step = HealingStep(
            name="retry",
            level="entity",
            action="retry_service_call",
            params={"max_attempts": 3, "base_delay_seconds": 1.0},
            timeout_seconds=15.0,
        )
        assert step.params["max_attempts"] == 3
        assert step.timeout_seconds == 15.0


class TestOnFailureConfig:
    """Tests for OnFailureConfig model."""

    def test_defaults(self):
        ofc = OnFailureConfig()
        assert ofc.escalate is True
        assert ofc.cooldown_seconds == 600

    def test_custom(self):
        ofc = OnFailureConfig(escalate=False, cooldown_seconds=300)
        assert ofc.escalate is False
        assert ofc.cooldown_seconds == 300


class TestHealingPlanDefinition:
    """Tests for HealingPlanDefinition model."""

    def test_valid_plan(self):
        plan = HealingPlanDefinition(
            name="zigbee_offline",
            description="Fix zigbee devices",
            priority=10,
            match=MatchCriteria(
                entity_patterns=["light.zigbee_*"],
                integration_domains=["zha"],
                failure_types=["unavailable"],
            ),
            steps=[
                HealingStep(name="retry", level="entity", action="retry_service_call"),
                HealingStep(name="reconnect", level="device", action="reconnect"),
            ],
            tags=["zigbee"],
        )
        assert plan.name == "zigbee_offline"
        assert len(plan.steps) == 2
        assert plan.enabled is True
        assert plan.version == 1

    def test_minimal_plan(self):
        plan = HealingPlanDefinition(
            name="minimal",
            match=MatchCriteria(failure_types=["unavailable"]),
            steps=[HealingStep(name="reload", level="integration", action="reload_integration")],
        )
        assert plan.name == "minimal"
        assert plan.description == ""
        assert plan.priority == 0

    def test_no_match_criteria_fails(self):
        with pytest.raises(ValidationError, match="at least one"):
            HealingPlanDefinition(
                name="bad",
                match=MatchCriteria(),
                steps=[HealingStep(name="test", level="entity", action="test")],
            )

    def test_no_steps_fails(self):
        with pytest.raises(ValidationError):
            HealingPlanDefinition(
                name="bad",
                match=MatchCriteria(failure_types=["unavailable"]),
                steps=[],
            )

    def test_plan_from_dict(self):
        """Test creating plan from dict (simulates YAML loading)."""
        data = {
            "name": "test_plan",
            "version": 1,
            "description": "A test plan",
            "enabled": True,
            "priority": 5,
            "match": {
                "entity_patterns": ["sensor.*"],
                "failure_types": ["unavailable"],
            },
            "steps": [
                {
                    "name": "retry",
                    "level": "entity",
                    "action": "retry_service_call",
                    "params": {"max_attempts": 3},
                    "timeout_seconds": 15,
                },
            ],
            "on_failure": {"escalate": True, "cooldown_seconds": 300},
            "tags": ["test"],
        }
        plan = HealingPlanDefinition(**data)
        assert plan.name == "test_plan"
        assert plan.priority == 5
        assert plan.steps[0].params["max_attempts"] == 3
        assert plan.on_failure.cooldown_seconds == 300
