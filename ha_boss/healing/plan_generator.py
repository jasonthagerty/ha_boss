"""AI-powered healing plan generator.

Uses the LLM router to generate YAML-based healing plans on demand when no
existing plan matches a failure context.
"""

import logging
import re
from typing import Any

import yaml

from ha_boss.healing.plan_models import HealingPlanDefinition
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


class PlanGenerator:
    """Generates healing plans using AI when no existing plan matches.

    Uses the LLM router (preferring Claude for complex generation) to create
    validated YAML healing plans. Retries once on validation failure.

    Example:
        >>> generator = PlanGenerator(llm_router)
        >>> plan = await generator.generate_plan(
        ...     failed_entities=["light.bedroom", "light.hallway"],
        ...     failure_type="unavailable",
        ...     integration_domain="zha",
        ... )
        >>> print(plan.name)  # e.g., "zha_unavailable_recovery"
    """

    SYSTEM_PROMPT = """You are an expert at Home Assistant healing plans.
Generate a YAML healing plan for the given failure context.

Schema:
  name: unique_snake_case_name
  description: "What this plan fixes"
  priority: 0-100
  match:
    entity_patterns: ["domain.*"]   # fnmatch globs
    integration_domains: ["zha"]    # optional
    failure_types: ["unavailable"]  # optional
  steps:
    - name: step_name
      level: entity | device | integration
      action: retry_service_call | reconnect | reboot | rediscover | reload_integration
      timeout_seconds: 30
  tags: ["tag1"]

Return ONLY valid YAML, no explanation."""

    def __init__(self, llm_router: LLMRouter) -> None:
        """Initialize plan generator.

        Args:
            llm_router: LLM router for AI-powered generation
        """
        self.llm_router = llm_router

    def _build_prompt(
        self,
        failed_entities: list[str],
        failure_type: str,
        integration_domain: str | None,
        levels_already_tried: list[str] | None,
    ) -> str:
        """Build the generation prompt from failure context."""
        lines = [
            f"Failed entities: {', '.join(failed_entities)}",
            f"Failure type: {failure_type}",
        ]
        if integration_domain:
            lines.append(f"Integration domain: {integration_domain}")
        if levels_already_tried:
            lines.append(
                f"Levels already tried (avoid repeating): {', '.join(levels_already_tried)}"
            )

        lines.append("")
        lines.append("Generate a healing plan YAML that will resolve this failure.")
        return "\n".join(lines)

    def _extract_yaml_from_response(self, response: str) -> str:
        """Extract YAML content from LLM response, handling markdown code blocks."""
        response = response.strip()
        # Handle ```yaml blocks
        if "```yaml" in response:
            match = re.search(r"```yaml\s*(.*?)\s*```", response, re.DOTALL)
            if match:
                return match.group(1).strip()
        # Handle plain ``` blocks
        if "```" in response:
            match = re.search(r"```\s*(.*?)\s*```", response, re.DOTALL)
            if match:
                return match.group(1).strip()
        return response

    async def generate_plan(
        self,
        failed_entities: list[str],
        failure_type: str,
        integration_domain: str | None = None,
        levels_already_tried: list[str] | None = None,
    ) -> HealingPlanDefinition | None:
        """Generate a healing plan for the given failure context.

        Calls the LLM, extracts YAML, validates it. Retries once if validation fails.

        Args:
            failed_entities: List of entity IDs that failed
            failure_type: Type of failure (e.g., "unavailable", "unknown")
            integration_domain: Optional integration domain (e.g., "zha", "zigbee2mqtt")
            levels_already_tried: Healing levels already attempted (to avoid repeating)

        Returns:
            Validated HealingPlanDefinition, or None if generation failed
        """
        prompt = self._build_prompt(
            failed_entities, failure_type, integration_domain, levels_already_tried
        )

        logger.info(
            f"Generating healing plan for {len(failed_entities)} entities "
            f"(failure: {failure_type}, integration: {integration_domain})"
        )

        error_context: str | None = None

        for attempt in range(2):
            # Build full prompt (add error context on retry)
            full_prompt = prompt
            if error_context:
                full_prompt = (
                    f"{prompt}\n\nPrevious attempt failed validation: {error_context}\n"
                    "Please fix the YAML and try again."
                )

            response = await self.llm_router.generate(
                prompt=full_prompt,
                complexity=TaskComplexity.COMPLEX,
                max_tokens=2000,
                temperature=0.3,
                system_prompt=self.SYSTEM_PROMPT,
            )

            if response is None:
                logger.warning("LLM unavailable or returned None for plan generation")
                return None

            yaml_text = self._extract_yaml_from_response(response)

            try:
                data: Any = yaml.safe_load(yaml_text)
                plan = HealingPlanDefinition(**data)
                logger.info(f"Successfully generated healing plan '{plan.name}'")
                return plan
            except Exception as e:
                error_context = str(e)
                logger.warning(f"Plan generation attempt {attempt + 1} failed validation: {e}")

        logger.error("Plan generation failed after 2 attempts")
        return None
