"""AI-powered desired state inference for automations.

This module analyzes Home Assistant automation configurations to infer
the desired entity states and attributes that automations are trying to achieve.
Uses LLM analysis to extract intent from automation actions.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from ha_boss.core.database import AutomationDesiredState, Database
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


@dataclass
class InferredState:
    """Represents an inferred desired state for an entity."""

    entity_id: str
    desired_state: str
    desired_attributes: dict[str, Any] | None = None
    confidence: float = 0.0


class DesiredStateInference:
    """Infers desired entity states from automation configurations using AI.

    This service analyzes automation actions to determine what states the
    automation intends to achieve for target entities. Uses LLM analysis
    for accurate inference with confidence scoring.

    Example:
        >>> inference = DesiredStateInference(llm_router, database, "default")
        >>> automation = {
        ...     "action": [
        ...         {
        ...             "service": "light.turn_on",
        ...             "target": {"entity_id": "light.bedroom"},
        ...             "data": {"brightness": 128}
        ...         }
        ...     ]
        ... }
        >>> states = await inference.infer_from_automation(
        ...     "automation.morning_routine", automation
        ... )
        >>> print(states[0].desired_state)  # "on"
        >>> print(states[0].confidence)  # 0.95
    """

    # System prompt for LLM state inference
    SYSTEM_PROMPT = """You are an expert at analyzing Home Assistant automations.
Your task is to extract the desired entity states from automation actions.

For each action in the automation:
1. Identify the target entity_id
2. Determine the desired state (on/off/playing/etc)
3. Extract relevant attributes (brightness, temperature, color, etc)
4. Assign a confidence score (0.0-1.0) based on clarity

Return a JSON array of desired states with this structure:
[
  {
    "entity_id": "light.bedroom",
    "desired_state": "on",
    "desired_attributes": {"brightness": 128, "color_temp": 300},
    "confidence": 0.95
  }
]

Confidence guidelines:
- 0.9-1.0: Direct service call with explicit state (light.turn_on)
- 0.7-0.9: Indirect but clear (toggle, set_value)
- 0.5-0.7: Ambiguous or conditional actions
- 0.0-0.5: Very uncertain or complex logic

CRITICAL: Return ONLY valid JSON, no explanations or markdown."""

    def __init__(
        self,
        llm_router: LLMRouter,
        database: Database | None = None,
        instance_id: str = "default",
    ) -> None:
        """Initialize desired state inference service.

        Args:
            llm_router: LLM router for AI analysis
            database: Optional database for caching inferred states
            instance_id: Home Assistant instance identifier
        """
        self.llm_router = llm_router
        self.database = database
        self.instance_id = instance_id

    async def infer_from_automation(
        self,
        automation_id: str,
        automation_config: dict[str, Any],
        use_cache: bool = True,
    ) -> list[InferredState]:
        """Infer desired states from automation configuration.

        Args:
            automation_id: Automation entity ID (e.g., "automation.morning_routine")
            automation_config: Automation configuration dict with 'action' key
            use_cache: If True, check database cache before re-inferring

        Returns:
            List of InferredState objects for each target entity

        Raises:
            ValueError: If automation_config is invalid or missing actions
        """
        # Validate automation config
        if not automation_config or "action" not in automation_config:
            raise ValueError("automation_config must contain 'action' key")

        actions = automation_config["action"]
        if not isinstance(actions, list):
            actions = [actions]

        if not actions:
            logger.warning(f"Automation {automation_id} has no actions")
            return []

        # Check cache if enabled
        if use_cache and self.database:
            cached = await self._get_cached_states(automation_id)
            if cached:
                logger.debug(f"Using cached inference for {automation_id} ({len(cached)} states)")
                return cached

        # Prepare prompt with automation actions
        prompt = self._build_inference_prompt(automation_id, actions)

        # Call LLM for inference
        logger.info(f"Inferring desired states for {automation_id} using LLM")
        response = await self.llm_router.generate(
            prompt=prompt,
            complexity=TaskComplexity.MODERATE,
            max_tokens=2048,
            temperature=0.3,  # Low temperature for consistent extraction
            system_prompt=self.SYSTEM_PROMPT,
        )

        if not response:
            logger.error(f"LLM failed to generate inference for {automation_id}")
            return []

        # Parse LLM response
        inferred_states = self._parse_llm_response(response)

        # Store in database if available
        if self.database and inferred_states:
            await self._store_inferred_states(automation_id, inferred_states)

        logger.info(f"Inferred {len(inferred_states)} desired states for {automation_id}")
        return inferred_states

    def _build_inference_prompt(self, automation_id: str, actions: list[dict[str, Any]]) -> str:
        """Build LLM prompt from automation actions.

        Args:
            automation_id: Automation identifier
            actions: List of automation action dictionaries

        Returns:
            Formatted prompt string
        """
        # Format actions as readable YAML-like structure
        actions_text = json.dumps(actions, indent=2)

        prompt = f"""Analyze this Home Assistant automation and extract desired entity states:

Automation ID: {automation_id}

Actions:
{actions_text}

Extract the desired state for each target entity. Return JSON only."""

        return prompt

    def _parse_llm_response(self, response: str) -> list[InferredState]:
        """Parse LLM JSON response into InferredState objects.

        Args:
            response: Raw LLM response text

        Returns:
            List of InferredState objects
        """
        try:
            # Try to extract JSON from response (handle markdown code blocks)
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(response)

            if not isinstance(data, list):
                logger.warning(f"LLM response is not a JSON array: {response[:100]}")
                return []

            # Convert to InferredState objects
            inferred_states = []
            for item in data:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item in response: {item}")
                    continue

                # Validate required fields
                if "entity_id" not in item or "desired_state" not in item:
                    logger.warning(f"Missing required fields in item: {item}")
                    continue

                # Clamp confidence to valid range
                confidence = float(item.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                inferred_states.append(
                    InferredState(
                        entity_id=item["entity_id"],
                        desired_state=item["desired_state"],
                        desired_attributes=item.get("desired_attributes"),
                        confidence=confidence,
                    )
                )

            return inferred_states

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Raw response: {response[:200]}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing LLM response: {e}", exc_info=True)
            return []

    async def _get_cached_states(self, automation_id: str) -> list[InferredState] | None:
        """Retrieve cached inferred states from database.

        Args:
            automation_id: Automation entity ID

        Returns:
            List of cached InferredState objects, or None if not cached
        """
        if not self.database:
            return None

        try:
            async with self.database.async_session() as session:
                from sqlalchemy import select

                stmt = select(AutomationDesiredState).where(
                    AutomationDesiredState.instance_id == self.instance_id,
                    AutomationDesiredState.automation_id == automation_id,
                    AutomationDesiredState.inference_method == "ai_analysis",
                )

                result = await session.execute(stmt)
                records = result.scalars().all()

                if not records:
                    return None

                # Convert DB records to InferredState objects
                return [
                    InferredState(
                        entity_id=record.entity_id,
                        desired_state=record.desired_state,
                        desired_attributes=record.desired_attributes,
                        confidence=record.confidence,
                    )
                    for record in records
                ]

        except Exception as e:
            logger.error(f"Error retrieving cached states: {e}", exc_info=True)
            return None

    async def _store_inferred_states(
        self, automation_id: str, inferred_states: list[InferredState]
    ) -> None:
        """Store inferred states in database.

        Args:
            automation_id: Automation entity ID
            inferred_states: List of InferredState objects to store
        """
        if not self.database:
            return

        try:
            async with self.database.async_session() as session:
                from sqlalchemy import delete

                # Delete existing inferred states for this automation
                delete_stmt = delete(AutomationDesiredState).where(
                    AutomationDesiredState.instance_id == self.instance_id,
                    AutomationDesiredState.automation_id == automation_id,
                    AutomationDesiredState.inference_method == "ai_analysis",
                )
                await session.execute(delete_stmt)

                # Insert new inferred states
                for state in inferred_states:
                    record = AutomationDesiredState(
                        instance_id=self.instance_id,
                        automation_id=automation_id,
                        entity_id=state.entity_id,
                        desired_state=state.desired_state,
                        desired_attributes=state.desired_attributes,
                        confidence=state.confidence,
                        inference_method="ai_analysis",
                    )
                    session.add(record)

                await session.commit()
                logger.debug(f"Stored {len(inferred_states)} inferred states for {automation_id}")

        except Exception as e:
            logger.error(f"Error storing inferred states: {e}", exc_info=True)
            await session.rollback()
