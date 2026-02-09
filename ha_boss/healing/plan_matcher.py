"""Match healing contexts to the best applicable healing plan.

Uses fnmatch glob patterns for entity matching, consistent with the
existing monitoring include/exclude patterns. Plans are evaluated in
priority order (highest first), and the first matching plan wins.
"""

import logging
from datetime import datetime
from fnmatch import fnmatch

from ha_boss.healing.cascade_orchestrator import HealingContext
from ha_boss.healing.plan_loader import PlanLoader
from ha_boss.healing.plan_models import HealingPlanDefinition, MatchCriteria

logger = logging.getLogger(__name__)


class PlanMatcher:
    """Match healing contexts to applicable healing plans.

    Evaluates enabled plans in priority order against the failure context.
    A plan matches if ANY entity matches AND the failure type matches
    (when criteria are specified).
    """

    def __init__(self, plan_loader: PlanLoader) -> None:
        """Initialize plan matcher.

        Args:
            plan_loader: Loader providing access to plan definitions
        """
        self.plan_loader = plan_loader

    async def find_matching_plan(
        self,
        context: HealingContext,
        entity_integration_map: dict[str, str] | None = None,
        failure_type: str = "unavailable",
    ) -> HealingPlanDefinition | None:
        """Find the best matching plan for a healing context.

        Plans are evaluated in priority order (highest first).
        Returns the first plan that matches all specified criteria.

        Args:
            context: Healing context with failed entities and metadata
            entity_integration_map: Optional mapping of entity_id -> integration domain
            failure_type: Type of failure (e.g., 'unavailable', 'unknown')

        Returns:
            Best matching plan or None if no plan matches
        """
        plans = await self.plan_loader.get_all_enabled_plans()

        if not plans:
            logger.debug("No enabled plans available")
            return None

        for plan in plans:
            if self._plan_matches(plan, context, entity_integration_map, failure_type):
                logger.info(
                    f"Plan '{plan.name}' (priority={plan.priority}) matches "
                    f"context for {context.automation_id} "
                    f"({len(context.failed_entities)} entities)"
                )
                return plan

        logger.debug(
            f"No plan matched for {context.automation_id} " f"(checked {len(plans)} plans)"
        )
        return None

    def _plan_matches(
        self,
        plan: HealingPlanDefinition,
        context: HealingContext,
        entity_integration_map: dict[str, str] | None,
        failure_type: str,
    ) -> bool:
        """Check if a plan matches the given context.

        A plan matches if ALL specified criteria are satisfied:
        - entity_patterns: at least one failed entity matches a pattern
        - integration_domains: at least one entity's integration matches
        - failure_types: the failure type is in the list
        - time_window: current hour is within the window

        Args:
            plan: Plan to check
            context: Healing context
            entity_integration_map: entity_id -> integration domain mapping
            failure_type: Failure type string

        Returns:
            True if plan matches
        """
        match = plan.match

        # Check failure types (if specified)
        if match.failure_types and failure_type not in match.failure_types:
            return False

        # Check entity patterns (if specified)
        if match.entity_patterns:
            if not self._any_entity_matches_patterns(
                context.failed_entities, match.entity_patterns
            ):
                return False

        # Check integration domains (if specified)
        if match.integration_domains and entity_integration_map:
            if not self._any_entity_matches_integrations(
                context.failed_entities,
                match.integration_domains,
                entity_integration_map,
            ):
                return False

        # Check time window (if specified)
        if match.time_window:
            current_hour = datetime.now().hour
            if not (match.time_window.start_hour <= current_hour < match.time_window.end_hour):
                return False

        return True

    @staticmethod
    def _any_entity_matches_patterns(entities: list[str], patterns: list[str]) -> bool:
        """Check if any entity matches any of the glob patterns.

        Args:
            entities: List of entity IDs
            patterns: List of fnmatch glob patterns

        Returns:
            True if at least one entity matches at least one pattern
        """
        return any(fnmatch(entity, pattern) for entity in entities for pattern in patterns)

    @staticmethod
    def _any_entity_matches_integrations(
        entities: list[str],
        domains: list[str],
        entity_integration_map: dict[str, str],
    ) -> bool:
        """Check if any entity belongs to a matching integration domain.

        Args:
            entities: List of entity IDs
            domains: List of integration domains
            entity_integration_map: entity_id -> domain mapping

        Returns:
            True if at least one entity's integration matches
        """
        for entity in entities:
            entity_domain = entity_integration_map.get(entity, "")
            if entity_domain in domains:
                return True
        return False

    @staticmethod
    def match_criteria_to_dict(criteria: MatchCriteria) -> dict[str, object]:
        """Convert match criteria to a dict for API responses.

        Args:
            criteria: Match criteria to convert

        Returns:
            Dictionary representation
        """
        return criteria.model_dump()
