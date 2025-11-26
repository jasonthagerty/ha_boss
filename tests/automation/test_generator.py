"""Tests for automation generator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.generator import AutomationGenerator, GeneratedAutomation


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock configuration."""
    config = MagicMock()
    config.intelligence.claude_enabled = True
    config.intelligence.claude_api_key = "test_key"
    config.intelligence.claude_model = "claude-3-5-sonnet-20241022"
    config.intelligence.ollama_enabled = False
    return config


@pytest.fixture
def mock_ha_client() -> AsyncMock:
    """Create mock Home Assistant client."""
    return AsyncMock()


@pytest.fixture
def mock_llm_router() -> AsyncMock:
    """Create mock LLM router."""
    router = AsyncMock()
    return router


@pytest.fixture
def valid_automation_yaml() -> str:
    """Create valid automation YAML response."""
    return """alias: "Bedroom Lights on Motion"
description: "Turn on bedroom lights when motion detected after sunset"
trigger:
  - platform: state
    entity_id: binary_sensor.bedroom_motion
    to: "on"
condition:
  - condition: sun
    after: sunset
action:
  - service: light.turn_on
    target:
      entity_id: light.bedroom
    data:
      brightness_pct: 80
mode: single
"""


@pytest.fixture
def valid_automation_with_markdown() -> str:
    """Create valid automation YAML wrapped in markdown."""
    return """```yaml
alias: "Test Automation"
description: "Test description"
trigger:
  - platform: time
    at: "22:00:00"
action:
  - service: light.turn_off
    target:
      area_id: living_room
mode: single
```"""


class TestGeneratedAutomation:
    """Tests for GeneratedAutomation dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test automation",
            trigger=[{"platform": "time", "at": "10:00"}],
            condition=[],
            action=[{"service": "test.test"}],
            mode="single",
        )

        result = automation.to_dict()

        assert result["alias"] == "Test"
        assert result["description"] == "Test automation"
        assert result["trigger"] == [{"platform": "time", "at": "10:00"}]
        assert result["action"] == [{"service": "test.test"}]
        assert result["mode"] == "single"
        assert "condition" not in result  # Empty conditions not included

    def test_to_dict_with_conditions(self) -> None:
        """Test conversion with conditions."""
        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test",
            trigger=[{"platform": "time", "at": "10:00"}],
            condition=[{"condition": "state", "entity_id": "sun.sun", "state": "above_horizon"}],
            action=[{"service": "test.test"}],
        )

        result = automation.to_dict()

        assert "condition" in result
        assert len(result["condition"]) == 1

    def test_is_valid_true(self) -> None:
        """Test is_valid returns True when no errors."""
        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test",
            trigger=[],
            condition=[],
            action=[],
            validation_errors=None,
        )

        assert automation.is_valid is True

    def test_is_valid_false(self) -> None:
        """Test is_valid returns False with errors."""
        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test",
            trigger=[],
            condition=[],
            action=[],
            validation_errors=["Missing trigger"],
        )

        assert automation.is_valid is False


class TestAutomationGenerator:
    """Tests for AutomationGenerator class."""

    @pytest.mark.asyncio
    async def test_generate_from_prompt_success(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
        valid_automation_yaml: str,
    ) -> None:
        """Test successful automation generation."""
        mock_llm_router.generate.return_value = valid_automation_yaml

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Turn on lights when motion detected")

        assert result is not None
        assert result.alias == "Bedroom Lights on Motion"
        assert result.automation_id == "automation.bedroom_lights_on_motion"
        assert len(result.trigger) == 1
        assert result.trigger[0]["platform"] == "state"
        assert len(result.action) == 1
        assert result.is_valid
        mock_llm_router.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_from_prompt_with_markdown(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
        valid_automation_with_markdown: str,
    ) -> None:
        """Test parsing automation from markdown code block."""
        mock_llm_router.generate.return_value = valid_automation_with_markdown

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Test prompt")

        assert result is not None
        assert result.alias == "Test Automation"
        assert result.is_valid

    @pytest.mark.asyncio
    async def test_generate_from_prompt_llm_returns_none(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test handling when LLM returns None."""
        mock_llm_router.generate.return_value = None

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Test prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_from_prompt_invalid_yaml(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test handling of invalid YAML response."""
        mock_llm_router.generate.return_value = "This is not valid YAML: {["

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Test prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_from_prompt_exception(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test handling of exception during generation."""
        mock_llm_router.generate.side_effect = Exception("LLM error")

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Test prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_with_custom_mode(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
        valid_automation_yaml: str,
    ) -> None:
        """Test generation with custom mode."""
        mock_llm_router.generate.return_value = valid_automation_yaml

        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)
        result = await generator.generate_from_prompt("Test", mode="restart")

        assert result is not None
        # Mode from YAML takes precedence if present
        assert result.mode == "single"

    def test_validate_automation_valid(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation of valid automation."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "10:00"}],
            "action": [{"service": "light.turn_on"}],
        }

        errors = generator._validate_automation(automation)

        assert errors == []

    def test_validate_automation_missing_alias(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches missing alias."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "trigger": [{"platform": "time", "at": "10:00"}],
            "action": [{"service": "light.turn_on"}],
        }

        errors = generator._validate_automation(automation)

        assert "Missing required field: alias" in errors

    def test_validate_automation_missing_trigger(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches missing trigger."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "action": [{"service": "light.turn_on"}],
        }

        errors = generator._validate_automation(automation)

        assert any("trigger" in error.lower() for error in errors)

    def test_validate_automation_empty_trigger(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches empty trigger list."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [],
            "action": [{"service": "light.turn_on"}],
        }

        errors = generator._validate_automation(automation)

        assert any("trigger" in error.lower() for error in errors)

    def test_validate_automation_missing_action(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches missing action."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "10:00"}],
        }

        errors = generator._validate_automation(automation)

        assert any("action" in error.lower() for error in errors)

    def test_validate_automation_invalid_mode(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches invalid mode."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "10:00"}],
            "action": [{"service": "light.turn_on"}],
            "mode": "invalid_mode",
        }

        errors = generator._validate_automation(automation)

        assert any("mode" in error.lower() for error in errors)

    def test_validate_automation_trigger_without_platform(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches trigger without platform."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [{"at": "10:00"}],  # Missing platform
            "action": [{"service": "light.turn_on"}],
        }

        errors = generator._validate_automation(automation)

        assert any("platform" in error.lower() for error in errors)

    def test_validate_automation_action_without_valid_type(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test validation catches action without valid type."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = {
            "alias": "Test",
            "trigger": [{"platform": "time", "at": "10:00"}],
            "action": [{"invalid_key": "value"}],
        }

        errors = generator._validate_automation(automation)

        assert any("action" in error.lower() for error in errors)

    def test_generate_automation_id(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test automation ID generation from alias."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        assert generator._generate_automation_id("Bedroom Lights") == "automation.bedroom_lights"
        assert generator._generate_automation_id("Turn On @ Sunset") == "automation.turn_on_sunset"
        assert (
            generator._generate_automation_id("Test - Multiple -- Dashes")
            == "automation.test_multiple_dashes"
        )

    @pytest.mark.asyncio
    async def test_create_in_ha_invalid_automation(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test create_in_ha rejects invalid automation."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        invalid_automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test",
            trigger=[],
            condition=[],
            action=[],
            validation_errors=["Missing trigger"],
        )

        result = await generator.create_in_ha(invalid_automation)

        assert result is False

    @pytest.mark.asyncio
    async def test_create_in_ha_valid_automation(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test create_in_ha with valid automation (MVP logs only)."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        valid_automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test automation",
            trigger=[{"platform": "time", "at": "10:00"}],
            condition=[],
            action=[{"service": "light.turn_on"}],
            validation_errors=None,
        )

        result = await generator.create_in_ha(valid_automation)

        # MVP implementation logs instructions, returns True
        assert result is True

    def test_format_automation_preview(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test automation preview formatting."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test Automation",
            description="Test description",
            trigger=[{"platform": "time", "at": "10:00"}],
            condition=[],
            action=[{"service": "light.turn_on"}],
            mode="single",
            raw_yaml="alias: Test\ntrigger: []",
            validation_errors=None,
        )

        preview = generator.format_automation_preview(automation)

        assert "Test Automation" in preview
        assert "automation.test" in preview
        assert "single" in preview
        assert "Triggers: 1" in preview
        assert "Actions: 1" in preview
        assert "PASSED" in preview

    def test_format_automation_preview_with_errors(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test automation preview with validation errors."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        automation = GeneratedAutomation(
            automation_id="automation.test",
            alias="Test",
            description="Test",
            trigger=[],
            condition=[],
            action=[],
            raw_yaml="test",
            validation_errors=["Missing trigger", "Missing action"],
        )

        preview = generator.format_automation_preview(automation)

        assert "VALIDATION ERRORS" in preview
        assert "Missing trigger" in preview
        assert "Missing action" in preview

    def test_parse_yaml_response_with_list(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test parsing YAML that returns a list instead of dict."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        yaml_list = """
- item1
- item2
"""

        result = generator._parse_yaml_response(yaml_list)

        assert result is None  # Should reject non-dict responses

    def test_build_generation_prompt(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        mock_llm_router: AsyncMock,
    ) -> None:
        """Test generation prompt construction."""
        generator = AutomationGenerator(mock_ha_client, mock_config, mock_llm_router)

        prompt = generator._build_generation_prompt("Turn on lights", "restart")

        assert "Turn on lights" in prompt
        assert "restart" in prompt
        assert "YAML" in prompt
