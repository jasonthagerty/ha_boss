"""Healing plan anonymizer for community sharing.

Removes personally-identifying information from healing plans before
sharing them with the community. Replaces specific entity IDs with
domain-level glob patterns.
"""

import logging
from copy import deepcopy

import yaml

from ha_boss.healing.plan_models import HealingPlanDefinition, MatchCriteria

logger = logging.getLogger(__name__)


class PlanAnonymizer:
    """Anonymizes healing plans for safe community sharing.

    Replaces specific entity IDs with domain-level glob patterns,
    generalizes descriptions, and preserves all other generic fields.
    Does not mutate the input plan.

    Example:
        >>> anonymizer = PlanAnonymizer()
        >>> plan = HealingPlanDefinition(...)  # with light.jasons_bedroom in patterns
        >>> anon_plan = anonymizer.anonymize(plan)
        >>> print(anon_plan.match.entity_patterns)  # ["light.*"]
    """

    def anonymize(self, plan: HealingPlanDefinition) -> HealingPlanDefinition:
        """Return a new anonymized copy of the plan.

        Anonymization rules:
        - entity_patterns: specific IDs (no '*') are replaced with 'domain.*'
        - description: replaced with a generic description
        - name, tags, integration_domains, failure_types: kept as-is
        - steps, on_failure: kept as-is

        Args:
            plan: The healing plan to anonymize

        Returns:
            A new HealingPlanDefinition with personal data removed
        """
        # Anonymize entity patterns
        anon_patterns = [self._anonymize_entity_pattern(p) for p in plan.match.entity_patterns]

        # Build anonymized match criteria
        anon_match = MatchCriteria(
            entity_patterns=anon_patterns,
            integration_domains=list(plan.match.integration_domains),
            failure_types=list(plan.match.failure_types),
            device_manufacturers=list(plan.match.device_manufacturers),
            time_window=plan.match.time_window,
        )

        # Build generic description
        anon_description = self._generalize_description(plan)

        # Build new plan (deep copy steps and other mutable fields)
        return HealingPlanDefinition(
            name=plan.name,
            version=plan.version,
            description=anon_description,
            enabled=plan.enabled,
            priority=plan.priority,
            match=anon_match,
            steps=deepcopy(plan.steps),
            on_failure=deepcopy(plan.on_failure),
            tags=list(plan.tags),
        )

    def _anonymize_entity_pattern(self, pattern: str) -> str:
        """Anonymize a single entity pattern.

        Patterns already containing '*' are returned unchanged (already generic).
        Specific entity IDs like 'light.jasons_bedroom' become 'light.*'.

        Args:
            pattern: fnmatch glob pattern or specific entity ID

        Returns:
            Anonymized pattern
        """
        if "*" in pattern:
            return pattern

        # Split on first '.' to get domain
        if "." in pattern:
            domain = pattern.split(".")[0]
            return f"{domain}.*"

        # No domain separator — return as-is (invalid entity ID, keep safe)
        return pattern

    def _generalize_description(self, plan: HealingPlanDefinition) -> str:
        """Generate a generic description from plan metadata.

        Args:
            plan: The plan to generate description for

        Returns:
            Generic description string
        """
        parts = []

        if plan.match.integration_domains:
            domains = ", ".join(plan.match.integration_domains)
            parts.append(f"Heals {domains} integration failures")
        elif plan.match.failure_types:
            types = ", ".join(plan.match.failure_types)
            parts.append(f"Heals {types} entity failures")
        else:
            parts.append("Heals entity failures")

        if plan.match.failure_types:
            types = ", ".join(plan.match.failure_types)
            parts.append(f"when entities become {types}")

        return " ".join(parts) + "."

    def plan_to_yaml(self, plan: HealingPlanDefinition) -> str:
        """Serialize a healing plan to YAML string.

        Args:
            plan: The plan to serialize

        Returns:
            YAML string representation of the plan
        """
        data = plan.model_dump(exclude_none=True)
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
