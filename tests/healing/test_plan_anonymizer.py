"""Tests for PlanAnonymizer."""


from ha_boss.healing.plan_anonymizer import PlanAnonymizer
from ha_boss.healing.plan_models import (
    HealingPlanDefinition,
    HealingStep,
    MatchCriteria,
)


def make_plan(
    name: str = "test_plan",
    entity_patterns: list[str] | None = None,
    integration_domains: list[str] | None = None,
    failure_types: list[str] | None = None,
    description: str = "My personal plan for Jason's bedroom",
    tags: list[str] | None = None,
) -> HealingPlanDefinition:
    """Helper to create a test plan."""
    return HealingPlanDefinition(
        name=name,
        description=description,
        match=MatchCriteria(
            entity_patterns=entity_patterns or ["light.jasons_bedroom"],
            integration_domains=integration_domains or [],
            failure_types=failure_types or ["unavailable"],
        ),
        steps=[
            HealingStep(
                name="reload",
                level="integration",
                action="reload_integration",
                timeout_seconds=30.0,
            )
        ],
        tags=tags or ["lights"],
    )


class TestPlanAnonymizer:
    def setup_method(self) -> None:
        self.anonymizer = PlanAnonymizer()

    def test_specific_entity_id_becomes_domain_glob(self) -> None:
        """Specific entity IDs like 'light.jasons_bedroom' → 'light.*'."""
        plan = make_plan(entity_patterns=["light.jasons_bedroom"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.entity_patterns == ["light.*"]

    def test_glob_pattern_with_star_is_unchanged(self) -> None:
        """Patterns already containing '*' are kept as-is."""
        plan = make_plan(entity_patterns=["light.zigbee_*", "sensor.*"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.entity_patterns == ["light.zigbee_*", "sensor.*"]

    def test_mixed_patterns(self) -> None:
        """Mix of specific and glob patterns are handled correctly."""
        plan = make_plan(entity_patterns=["light.bedroom", "light.zigbee_*", "sensor.jasons_temp"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.entity_patterns == ["light.*", "light.zigbee_*", "sensor.*"]

    def test_description_is_generalized(self) -> None:
        """Personal description is replaced with generic one."""
        plan = make_plan(description="Fix Jason's bedroom lights on 192.168.1.5")
        anon = self.anonymizer.anonymize(plan)
        assert "Jason" not in anon.description
        assert "192.168" not in anon.description
        assert len(anon.description) > 0

    def test_integration_domains_unchanged(self) -> None:
        """Integration domains are preserved (not personal data)."""
        plan = make_plan(integration_domains=["zha", "zigbee2mqtt"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.integration_domains == ["zha", "zigbee2mqtt"]

    def test_tags_unchanged(self) -> None:
        """Tags are preserved (already generic)."""
        plan = make_plan(tags=["lights", "zha", "critical"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.failure_types == ["unavailable"]
        assert anon.tags == ["lights", "zha", "critical"]

    def test_failure_types_unchanged(self) -> None:
        """Failure types are preserved."""
        plan = make_plan(failure_types=["unavailable", "unknown"])
        anon = self.anonymizer.anonymize(plan)
        assert anon.match.failure_types == ["unavailable", "unknown"]

    def test_name_preserved(self) -> None:
        """Plan name is preserved (already a safe identifier)."""
        plan = make_plan(name="zha_light_recovery")
        anon = self.anonymizer.anonymize(plan)
        assert anon.name == "zha_light_recovery"

    def test_input_not_mutated(self) -> None:
        """Anonymize does not mutate the input plan."""
        plan = make_plan(entity_patterns=["light.jasons_bedroom"])
        original_patterns = list(plan.match.entity_patterns)
        self.anonymizer.anonymize(plan)
        assert plan.match.entity_patterns == original_patterns

    def test_plan_to_yaml_is_valid_yaml(self) -> None:
        """plan_to_yaml produces parseable YAML."""
        import yaml as pyyaml

        plan = make_plan()
        anon = self.anonymizer.anonymize(plan)
        yaml_str = self.anonymizer.plan_to_yaml(anon)
        parsed = pyyaml.safe_load(yaml_str)
        assert parsed["name"] == plan.name
        assert "match" in parsed
        assert "steps" in parsed

    def test_description_includes_integration_domain(self) -> None:
        """Generic description mentions integration domain when present."""
        plan = make_plan(integration_domains=["zha"], failure_types=["unavailable"])
        anon = self.anonymizer.anonymize(plan)
        assert "zha" in anon.description.lower()
