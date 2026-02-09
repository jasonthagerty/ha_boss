"""Tests for built-in healing plan YAML files."""

from pathlib import Path

from ha_boss.healing.plan_loader import PlanLoader

PLANS_DIR = Path(__file__).parent.parent.parent / "ha_boss" / "healing" / "plans"


def test_zigbee_device_offline_plan() -> None:
    plan_file = PLANS_DIR / "zigbee_device_offline.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "zigbee_device_offline"
    assert plan.priority == 50
    assert plan.enabled is True
    assert len(plan.steps) == 3
    assert plan.match.has_any_criteria()
    assert "zigbee" in plan.tags
    assert "connectivity" in plan.tags


def test_zwave_device_offline_plan() -> None:
    plan_file = PLANS_DIR / "zwave_device_offline.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "zwave_device_offline"
    assert plan.priority == 50
    assert plan.enabled is True
    assert len(plan.steps) == 3
    assert plan.match.has_any_criteria()
    assert "zwave" in plan.tags
    assert "connectivity" in plan.tags


def test_wifi_device_offline_plan() -> None:
    plan_file = PLANS_DIR / "wifi_device_offline.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "wifi_device_offline"
    assert plan.priority == 40
    assert plan.enabled is True
    assert len(plan.steps) == 3
    assert plan.match.has_any_criteria()
    assert "wifi" in plan.tags
    assert "connectivity" in plan.tags


def test_sensor_stale_plan() -> None:
    plan_file = PLANS_DIR / "sensor_stale.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "sensor_stale"
    assert plan.priority == 30
    assert plan.enabled is True
    assert len(plan.steps) == 2
    assert plan.match.has_any_criteria()
    assert "sensor" in plan.tags
    assert "stale_data" in plan.tags


def test_climate_unavailable_plan() -> None:
    plan_file = PLANS_DIR / "climate_unavailable.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "climate_unavailable"
    assert plan.priority == 45
    assert plan.enabled is True
    assert len(plan.steps) == 3
    assert plan.match.has_any_criteria()
    assert "climate" in plan.tags
    assert "hvac" in plan.tags


def test_generic_unavailable_plan() -> None:
    plan_file = PLANS_DIR / "generic_unavailable.yaml"
    assert plan_file.exists(), f"Plan file not found: {plan_file}"

    plan = PlanLoader.load_plan_from_file(plan_file)

    assert plan.name == "generic_unavailable"
    assert plan.priority == 1
    assert plan.enabled is True
    assert len(plan.steps) == 2
    assert plan.match.has_any_criteria()
    assert "generic" in plan.tags
    assert "fallback" in plan.tags


def test_all_plans_have_unique_names() -> None:
    yaml_files = list(PLANS_DIR.glob("*.yaml"))
    assert len(yaml_files) >= 6, f"Expected at least 6 YAML files, found {len(yaml_files)}"

    plan_names = set()
    for plan_file in yaml_files:
        plan = PlanLoader.load_plan_from_file(plan_file)
        assert plan.name not in plan_names, f"Duplicate plan name found: {plan.name}"
        plan_names.add(plan.name)


def test_all_plans_have_match_criteria() -> None:
    yaml_files = list(PLANS_DIR.glob("*.yaml"))

    for plan_file in yaml_files:
        plan = PlanLoader.load_plan_from_file(plan_file)
        assert (
            plan.match.has_any_criteria()
        ), f"Plan {plan.name} in {plan_file.name} has no match criteria"


def test_all_plans_have_valid_step_levels() -> None:
    valid_levels = {"entity", "device", "integration"}
    yaml_files = list(PLANS_DIR.glob("*.yaml"))

    for plan_file in yaml_files:
        plan = PlanLoader.load_plan_from_file(plan_file)
        for step in plan.steps:
            assert (
                step.level in valid_levels
            ), f"Plan {plan.name} step {step.name} has invalid level: {step.level}"


def test_all_plans_have_positive_timeouts() -> None:
    yaml_files = list(PLANS_DIR.glob("*.yaml"))

    for plan_file in yaml_files:
        plan = PlanLoader.load_plan_from_file(plan_file)
        for step in plan.steps:
            assert step.timeout_seconds > 0, (
                f"Plan {plan.name} step {step.name} has invalid timeout: " f"{step.timeout_seconds}"
            )


def test_all_plans_have_on_failure_config() -> None:
    yaml_files = list(PLANS_DIR.glob("*.yaml"))

    for plan_file in yaml_files:
        plan = PlanLoader.load_plan_from_file(plan_file)
        assert plan.on_failure is not None, f"Plan {plan.name} missing on_failure config"
        assert isinstance(plan.on_failure.escalate, bool)
        assert plan.on_failure.cooldown_seconds > 0
