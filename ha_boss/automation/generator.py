"""Automation generator using Claude API for natural language to HA automation."""

import logging
import re
from dataclasses import dataclass
from typing import Any

import yaml

from ha_boss.core.config import Config
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


@dataclass
class GeneratedAutomation:
    """A generated automation with metadata."""

    automation_id: str
    alias: str
    description: str
    trigger: list[dict[str, Any]]
    condition: list[dict[str, Any]]
    action: list[dict[str, Any]]
    mode: str = "single"
    raw_yaml: str = ""
    validation_errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to Home Assistant automation format."""
        automation = {
            "alias": self.alias,
            "description": self.description,
            "trigger": self.trigger,
            "action": self.action,
            "mode": self.mode,
        }
        if self.condition:
            automation["condition"] = self.condition
        return automation

    @property
    def is_valid(self) -> bool:
        """Check if automation passed validation."""
        return not self.validation_errors


class AutomationGenerator:
    """Generates Home Assistant automations from natural language descriptions.

    Uses Claude API to translate natural language into properly structured
    Home Assistant automation YAML.
    """

    # System prompt for Claude
    SYSTEM_PROMPT = """You are an expert in Home Assistant automation YAML.
Your task is to generate valid Home Assistant automations from natural language descriptions.

Requirements:
1. Output ONLY valid YAML (no markdown, no explanations)
2. Use proper Home Assistant automation syntax
3. Include: alias, description, trigger, action, and optionally condition
4. Use realistic entity IDs (e.g., light.bedroom, binary_sensor.motion_kitchen)
5. Set appropriate mode (single, restart, queued, or parallel)
6. Add helpful comments in the YAML

Common patterns:
- Time triggers: platform: time, at: "HH:MM:SS"
- State triggers: platform: state, entity_id: sensor.x, to: "value"
- Motion triggers: platform: state, entity_id: binary_sensor.motion_x, to: "on"
- Sun triggers: platform: sun, event: sunset/sunrise
- Conditions: condition: state/time/sun/numeric_state
- Actions: service calls like light.turn_on, notify.notify, etc.

Always use best practices: meaningful aliases, clear descriptions, appropriate modes."""

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        config: Config,
        llm_router: LLMRouter,
    ) -> None:
        """Initialize automation generator.

        Args:
            ha_client: Home Assistant API client
            config: HA Boss configuration
            llm_router: LLM router (must have Claude API configured)
        """
        self.ha_client = ha_client
        self.config = config
        self.llm_router = llm_router

    async def generate_from_prompt(
        self,
        prompt: str,
        mode: str = "single",
    ) -> GeneratedAutomation | None:
        """Generate automation from natural language description.

        Args:
            prompt: Natural language description of desired automation
            mode: Automation mode (single, restart, queued, parallel)

        Returns:
            Generated automation object or None if generation failed
        """
        logger.info(f"Generating automation from prompt: {prompt[:100]}...")

        # Build the generation prompt
        generation_prompt = self._build_generation_prompt(prompt, mode)

        try:
            # Use Claude API (COMPLEX task) for automation generation
            yaml_response = await self.llm_router.generate(
                prompt=generation_prompt,
                complexity=TaskComplexity.COMPLEX,
                system_prompt=self.SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0.3,  # Lower temperature for more consistent output
            )

            if not yaml_response:
                logger.error("LLM returned no response")
                return None

            # Parse the YAML response
            automation = self._parse_yaml_response(yaml_response)
            if not automation:
                logger.error("Failed to parse LLM response as valid YAML")
                return None

            # Validate the automation structure
            validation_errors = self._validate_automation(automation)

            # Create GeneratedAutomation object
            automation_id = self._generate_automation_id(automation.get("alias", "automation"))

            generated = GeneratedAutomation(
                automation_id=automation_id,
                alias=automation.get("alias", "Generated Automation"),
                description=automation.get("description", ""),
                trigger=automation.get("trigger", []),
                condition=automation.get("condition", []),
                action=automation.get("action", []),
                mode=automation.get("mode", mode),
                raw_yaml=yaml_response,
                validation_errors=validation_errors if validation_errors else None,
            )

            if generated.is_valid:
                logger.info(f"Successfully generated automation: {generated.alias}")
            else:
                logger.warning(f"Generated automation has validation errors: {validation_errors}")

            return generated

        except Exception as e:
            logger.error(f"Error generating automation: {e}", exc_info=True)
            return None

    def _build_generation_prompt(self, prompt: str, mode: str) -> str:
        """Build the prompt for LLM generation."""
        return f"""Generate a Home Assistant automation for the following request:

{prompt}

Automation mode should be: {mode}

Output the complete automation as valid YAML only (no markdown, no explanations)."""

    def _parse_yaml_response(self, response: str) -> dict[str, Any] | None:
        """Parse YAML from LLM response, handling markdown code blocks."""
        try:
            # Remove markdown code blocks if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                # Extract content between ```yaml and ``` or ``` and ```
                match = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1)
                else:
                    # Try removing first and last lines
                    lines = cleaned.split("\n")
                    if len(lines) > 2:
                        cleaned = "\n".join(lines[1:-1])

            # Parse YAML
            automation = yaml.safe_load(cleaned)

            if not isinstance(automation, dict):
                logger.error(f"Parsed YAML is not a dict: {type(automation)}")
                return None

            return automation

        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML: {e}")
            logger.debug(f"Response was: {response}")
            return None

    def _validate_automation(self, automation: dict[str, Any]) -> list[str]:
        """Validate automation structure.

        Args:
            automation: Automation dictionary to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Required fields
        if "alias" not in automation:
            errors.append("Missing required field: alias")

        if "trigger" not in automation or not automation["trigger"]:
            errors.append("Missing or empty required field: trigger")
        elif not isinstance(automation["trigger"], list):
            errors.append("Field 'trigger' must be a list")

        if "action" not in automation or not automation["action"]:
            errors.append("Missing or empty required field: action")
        elif not isinstance(automation["action"], list):
            errors.append("Field 'action' must be a list")

        # Optional fields validation
        if "condition" in automation and not isinstance(automation["condition"], list):
            errors.append("Field 'condition' must be a list")

        # Validate mode if present
        if "mode" in automation:
            valid_modes = ["single", "restart", "queued", "parallel"]
            if automation["mode"] not in valid_modes:
                errors.append(f"Invalid mode '{automation['mode']}'. Must be one of: {valid_modes}")

        # Validate triggers have platform
        triggers = automation.get("trigger", [])
        for i, trigger in enumerate(triggers):
            if not isinstance(trigger, dict):
                errors.append(f"Trigger {i} must be a dict")
            elif "platform" not in trigger:
                errors.append(f"Trigger {i} missing required field: platform")

        # Validate actions have service or other valid action type
        actions = automation.get("action", [])
        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"Action {i} must be a dict")
            else:
                # Actions can be: service, delay, wait_template, wait_for_trigger,
                # repeat, choose, if, variables, etc.
                valid_action_keys = {
                    "service",
                    "delay",
                    "wait_template",
                    "wait_for_trigger",
                    "repeat",
                    "choose",
                    "if",
                    "event",
                    "device_id",
                    "scene",
                    "variables",
                }
                if not any(key in action for key in valid_action_keys):
                    errors.append(f"Action {i} must contain one of: {', '.join(valid_action_keys)}")

        return errors

    def _generate_automation_id(self, alias: str) -> str:
        """Generate automation entity ID from alias.

        Args:
            alias: Human-readable alias

        Returns:
            Entity ID in format automation.snake_case_name
        """
        # Convert to lowercase, replace spaces/special chars with underscore
        entity_name = re.sub(r"[^a-z0-9]+", "_", alias.lower())
        # Remove leading/trailing underscores
        entity_name = entity_name.strip("_")
        # Ensure it starts with automation.
        return f"automation.{entity_name}"

    async def create_in_ha(
        self,
        automation: GeneratedAutomation,
    ) -> bool:
        """Create automation in Home Assistant.

        Note: This uses the automation.reload service after writing to the
        config file. In a production setup, you would want to integrate with
        HA's automation storage system or use the UI's automation editor API.

        For MVP, this logs the automation and provides instructions.

        Args:
            automation: Generated automation to create

        Returns:
            True if creation successful, False otherwise
        """
        if not automation.is_valid:
            logger.error("Cannot create invalid automation")
            return False

        try:
            # For MVP: Log the automation YAML for manual creation
            # In production, this would integrate with HA's .storage/automations
            # or use the automation editor API
            automation_yaml = yaml.dump(
                automation.to_dict(),
                default_flow_style=False,
                sort_keys=False,
            )

            logger.info(f"Generated automation YAML:\n{automation_yaml}")
            logger.info(
                "To create this automation in Home Assistant:\n"
                "1. Go to Configuration -> Automations\n"
                "2. Click '+ Add Automation'\n"
                "3. Click '...' menu -> 'Edit in YAML'\n"
                "4. Paste the YAML above\n"
                "5. Save"
            )

            # TODO: Implement actual creation via HA API
            # This would require either:
            # 1. Writing to .storage/automations file (requires file access)
            # 2. Using automation editor API (if available)
            # 3. Using a custom integration that exposes automation.create service

            return True

        except Exception as e:
            logger.error(f"Error creating automation: {e}", exc_info=True)
            return False

    def format_automation_preview(self, automation: GeneratedAutomation) -> str:
        """Format automation for preview display.

        Args:
            automation: Generated automation

        Returns:
            Formatted string for display
        """
        lines = [
            "=" * 60,
            f"Automation: {automation.alias}",
            "=" * 60,
            "",
            f"Description: {automation.description}",
            f"ID: {automation.automation_id}",
            f"Mode: {automation.mode}",
            "",
            "YAML:",
            "-" * 60,
            automation.raw_yaml,
            "-" * 60,
            "",
        ]

        if automation.validation_errors:
            lines.extend(
                [
                    "⚠️  VALIDATION ERRORS:",
                    *[f"  - {error}" for error in automation.validation_errors],
                    "",
                ]
            )
        else:
            lines.append("✓ Validation: PASSED")
            lines.append("")

        lines.extend(
            [
                f"Triggers: {len(automation.trigger)}",
                f"Conditions: {len(automation.condition)}",
                f"Actions: {len(automation.action)}",
                "",
            ]
        )

        return "\n".join(lines)
