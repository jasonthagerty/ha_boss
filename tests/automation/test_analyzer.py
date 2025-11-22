"""Tests for automation analyzer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.analyzer import (
    AnalysisResult,
    AutomationAnalyzer,
    Suggestion,
    SuggestionSeverity,
)


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock configuration."""
    config = MagicMock()
    config.notifications.ai_enhanced = True
    config.intelligence.ollama_enabled = True
    config.intelligence.ollama_url = "http://localhost:11434"
    config.intelligence.ollama_model = "llama3.1:8b"
    config.intelligence.ollama_timeout_seconds = 30.0
    config.intelligence.claude_enabled = False
    config.intelligence.claude_api_key = None
    return config


@pytest.fixture
def mock_ha_client() -> AsyncMock:
    """Create mock Home Assistant client."""
    client = AsyncMock()
    return client


@pytest.fixture
def sample_automation_state() -> dict:
    """Create sample automation state."""
    return {
        "entity_id": "automation.bedroom_lights",
        "state": "on",
        "attributes": {
            "friendly_name": "Bedroom Lights Motion",
            "id": "bedroom_lights",
            "last_triggered": "2024-01-15T10:30:00+00:00",
            "mode": "single",
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": "binary_sensor.motion_bedroom",
                    "to": "on",
                }
            ],
            "condition": [
                {
                    "condition": "state",
                    "entity_id": "sun.sun",
                    "state": "below_horizon",
                }
            ],
            "action": [
                {
                    "service": "light.turn_on",
                    "target": {"entity_id": "light.bedroom"},
                }
            ],
        },
    }


@pytest.fixture
def automation_with_issues() -> dict:
    """Create automation with multiple issues."""
    return {
        "entity_id": "automation.problematic",
        "state": "on",
        "attributes": {
            "friendly_name": "Problematic Automation",
            "mode": "parallel",
            "trigger": [
                {"platform": "state", "entity_id": "sensor.temp1", "to": "on"},
                {"platform": "state", "entity_id": "sensor.temp2", "to": "on"},
                {"platform": "state", "entity_id": "sensor.temp3", "to": "on"},
            ],
            "condition": [
                {"condition": "state", "entity_id": "sun.sun", "state": "above_horizon"},
                {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"},
            ],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "light.1"}},
                {"delay": "00:00:05"},
                {"service": "light.turn_on", "target": {"entity_id": "light.2"}},
                {"delay": "00:00:05"},
                {"service": "light.turn_on", "target": {"entity_id": "light.3"}},
                {"delay": "00:00:05"},
                {"service": "light.turn_on", "target": {"entity_id": "light.4"}},
            ],
        },
    }


@pytest.fixture
def automation_no_actions() -> dict:
    """Create automation with no actions."""
    return {
        "entity_id": "automation.empty",
        "state": "on",
        "attributes": {
            "friendly_name": "Empty Automation",
            "mode": "single",
            "trigger": [{"platform": "state", "entity_id": "sensor.test", "to": "on"}],
            "condition": [],
            "action": [],
        },
    }


@pytest.fixture
def automation_with_restart() -> dict:
    """Create automation with risky restart action."""
    return {
        "entity_id": "automation.risky",
        "state": "on",
        "attributes": {
            "friendly_name": "Risky Automation",
            "mode": "single",
            "trigger": [{"platform": "time", "at": "03:00:00"}],
            "condition": [],
            "action": [{"service": "homeassistant.restart"}],
        },
    }


@pytest.fixture
def automation_with_good_practices() -> dict:
    """Create automation with good practices."""
    return {
        "entity_id": "automation.good",
        "state": "on",
        "attributes": {
            "friendly_name": "Good Automation",
            "mode": "queued",
            "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
            "condition": [{"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}],
            "action": [
                {
                    "choose": [
                        {
                            "conditions": [
                                {
                                    "condition": "state",
                                    "entity_id": "input_boolean.guests",
                                    "state": "on",
                                }
                            ],
                            "sequence": [
                                {"service": "light.turn_on", "target": {"entity_id": "light.guest"}}
                            ],
                        }
                    ],
                    "default": [
                        {"service": "light.turn_on", "target": {"entity_id": "light.main"}}
                    ],
                }
            ],
        },
    }


class TestAutomationAnalyzer:
    """Tests for AutomationAnalyzer class."""

    @pytest.mark.asyncio
    async def test_get_automations(self, mock_ha_client: AsyncMock, mock_config: MagicMock) -> None:
        """Test fetching automations from Home Assistant."""
        # Setup
        mock_ha_client.get_states.return_value = [
            {"entity_id": "automation.test1", "state": "on"},
            {"entity_id": "automation.test2", "state": "off"},
            {"entity_id": "light.living_room", "state": "on"},  # Not an automation
            {"entity_id": "automation.test3", "state": "on"},
        ]

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        automations = await analyzer.get_automations()

        # Verify
        assert len(automations) == 3
        assert all(a["entity_id"].startswith("automation.") for a in automations)

    @pytest.mark.asyncio
    async def test_analyze_automation_basic(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test basic automation analysis."""
        # Setup
        mock_ha_client.get_state.return_value = sample_automation_state

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("bedroom_lights", include_ai=False)

        # Verify
        assert result is not None
        assert result.automation_id == "automation.bedroom_lights"
        assert result.friendly_name == "Bedroom Lights Motion"
        assert result.state == "on"
        assert result.trigger_count == 1
        assert result.condition_count == 1
        assert result.action_count == 1

    @pytest.mark.asyncio
    async def test_analyze_automation_adds_prefix(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test that automation ID prefix is added if missing."""
        # Setup
        mock_ha_client.get_state.return_value = sample_automation_state

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute - pass without prefix
        result = await analyzer.analyze_automation("bedroom_lights", include_ai=False)

        # Verify - should have called with full entity_id
        mock_ha_client.get_state.assert_called_once_with("automation.bedroom_lights")
        assert result is not None

    @pytest.mark.asyncio
    async def test_analyze_automation_not_found(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test handling of automation not found."""
        # Setup
        mock_ha_client.get_state.side_effect = Exception("Entity not found")

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("nonexistent", include_ai=False)

        # Verify
        assert result is None

    @pytest.mark.asyncio
    async def test_static_analysis_multiple_triggers(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
    ) -> None:
        """Test detection of multiple state triggers."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_issues

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("problematic", include_ai=False)

        # Verify
        assert result is not None
        trigger_suggestions = [s for s in result.suggestions if s.category == "triggers"]
        assert any("combined" in s.title.lower() for s in trigger_suggestions)

    @pytest.mark.asyncio
    async def test_static_analysis_duplicate_conditions(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
    ) -> None:
        """Test detection of duplicate entity checks in conditions."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_issues

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("problematic", include_ai=False)

        # Verify
        assert result is not None
        condition_suggestions = [s for s in result.suggestions if s.category == "conditions"]
        assert any("redundant" in s.title.lower() for s in condition_suggestions)

    @pytest.mark.asyncio
    async def test_static_analysis_no_actions(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_no_actions: dict,
    ) -> None:
        """Test detection of no actions."""
        # Setup
        mock_ha_client.get_state.return_value = automation_no_actions

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("empty", include_ai=False)

        # Verify
        assert result is not None
        action_errors = [
            s
            for s in result.suggestions
            if s.category == "actions" and s.severity == SuggestionSeverity.ERROR
        ]
        assert len(action_errors) == 1
        assert "no actions" in action_errors[0].title.lower()

    @pytest.mark.asyncio
    async def test_static_analysis_risky_restart(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_restart: dict,
    ) -> None:
        """Test detection of risky restart action."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_restart

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("risky", include_ai=False)

        # Verify
        assert result is not None
        restart_errors = [
            s
            for s in result.suggestions
            if "restart" in s.title.lower() and s.severity == SuggestionSeverity.ERROR
        ]
        assert len(restart_errors) == 1

    @pytest.mark.asyncio
    async def test_static_analysis_multiple_delays(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
    ) -> None:
        """Test detection of multiple delays."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_issues

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("problematic", include_ai=False)

        # Verify
        assert result is not None
        delay_warnings = [s for s in result.suggestions if "delay" in s.title.lower()]
        assert len(delay_warnings) == 1
        assert delay_warnings[0].severity == SuggestionSeverity.WARNING

    @pytest.mark.asyncio
    async def test_static_analysis_good_practices(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_good_practices: dict,
    ) -> None:
        """Test detection of good practices."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_good_practices

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("good", include_ai=False)

        # Verify
        assert result is not None
        good_practices = [s for s in result.suggestions if s.severity == SuggestionSeverity.INFO]
        # Should detect queued mode and choose usage
        assert len(good_practices) >= 2
        assert any("queued" in s.title.lower() for s in good_practices)
        assert any("choose" in s.title.lower() for s in good_practices)

    @pytest.mark.asyncio
    async def test_has_issues_property(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
        automation_with_good_practices: dict,
    ) -> None:
        """Test has_issues property."""
        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Test automation with issues
        mock_ha_client.get_state.return_value = automation_with_issues
        result = await analyzer.analyze_automation("problematic", include_ai=False)
        assert result is not None
        assert result.has_issues is True

        # Test automation with good practices only
        mock_ha_client.get_state.return_value = automation_with_good_practices
        result = await analyzer.analyze_automation("good", include_ai=False)
        assert result is not None
        # Good practices (INFO) don't count as issues
        # But need to check if there are any warnings/errors
        issues_count = sum(
            1
            for s in result.suggestions
            if s.severity in (SuggestionSeverity.WARNING, SuggestionSeverity.ERROR)
        )
        assert result.has_issues == (issues_count > 0)

    @pytest.mark.asyncio
    async def test_analyze_all(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test analyzing all automations."""
        # Setup
        automation2 = sample_automation_state.copy()
        automation2["entity_id"] = "automation.kitchen_lights"
        automation2["attributes"] = sample_automation_state["attributes"].copy()
        automation2["attributes"]["friendly_name"] = "Kitchen Lights"

        mock_ha_client.get_states.return_value = [
            sample_automation_state,
            automation2,
            {"entity_id": "light.test", "state": "on"},  # Not an automation
        ]

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        results = await analyzer.analyze_all(include_ai=False)

        # Verify
        assert len(results) == 2
        assert results[0].automation_id == "automation.bedroom_lights"
        assert results[1].automation_id == "automation.kitchen_lights"

    @pytest.mark.asyncio
    async def test_ai_analysis_called_when_enabled(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test that AI analysis is called when enabled."""
        # Setup
        mock_ha_client.get_state.return_value = sample_automation_state

        mock_llm_router = AsyncMock()
        mock_llm_router.generate.return_value = "AI suggestion: Consider using wait_for_trigger."

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, mock_llm_router)

        # Execute
        result = await analyzer.analyze_automation("bedroom_lights", include_ai=True)

        # Verify
        assert result is not None
        assert result.ai_analysis is not None
        assert "AI suggestion" in result.ai_analysis
        mock_llm_router.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_analysis_skipped_when_disabled(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test that AI analysis is skipped when disabled."""
        # Setup
        mock_ha_client.get_state.return_value = sample_automation_state

        mock_llm_router = AsyncMock()

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, mock_llm_router)

        # Execute
        result = await analyzer.analyze_automation("bedroom_lights", include_ai=False)

        # Verify
        assert result is not None
        assert result.ai_analysis is None
        mock_llm_router.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_analysis_handles_error(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test that AI analysis errors are handled gracefully."""
        # Setup
        mock_ha_client.get_state.return_value = sample_automation_state

        mock_llm_router = AsyncMock()
        mock_llm_router.generate.side_effect = Exception("LLM error")

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, mock_llm_router)

        # Execute
        result = await analyzer.analyze_automation("bedroom_lights", include_ai=True)

        # Verify
        assert result is not None
        assert result.ai_analysis is None  # Error handled gracefully

    @pytest.mark.asyncio
    async def test_suggest_optimizations(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
    ) -> None:
        """Test suggest_optimizations convenience method."""
        # Setup
        mock_ha_client.get_state.return_value = automation_with_issues

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        suggestions = await analyzer.suggest_optimizations("problematic")

        # Verify
        assert len(suggestions) > 0
        assert all(isinstance(s, Suggestion) for s in suggestions)

    @pytest.mark.asyncio
    async def test_extract_triggers_dict(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test extraction when trigger is dict instead of list."""
        # Setup
        automation = {
            "entity_id": "automation.test",
            "state": "on",
            "attributes": {
                "friendly_name": "Test",
                "trigger": {"platform": "state", "entity_id": "sensor.test"},
                "condition": [],
                "action": [{"service": "test.test"}],
            },
        }
        mock_ha_client.get_state.return_value = automation

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("test", include_ai=False)

        # Verify
        assert result is not None
        assert result.trigger_count == 1

    @pytest.mark.asyncio
    async def test_no_triggers_info(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test detection of automation with no triggers."""
        # Setup
        automation = {
            "entity_id": "automation.manual",
            "state": "on",
            "attributes": {
                "friendly_name": "Manual Only",
                "trigger": [],
                "condition": [],
                "action": [{"service": "test.test"}],
            },
        }
        mock_ha_client.get_state.return_value = automation

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("manual", include_ai=False)

        # Verify
        assert result is not None
        no_trigger_info = [
            s
            for s in result.suggestions
            if "no triggers" in s.title.lower() and s.severity == SuggestionSeverity.INFO
        ]
        assert len(no_trigger_info) == 1

    @pytest.mark.asyncio
    async def test_parallel_mode_warning(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        automation_with_issues: dict,
    ) -> None:
        """Test detection of parallel mode with many actions."""
        # Setup - automation_with_issues has parallel mode and 7 actions
        mock_ha_client.get_state.return_value = automation_with_issues

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("problematic", include_ai=False)

        # Verify
        assert result is not None
        parallel_warnings = [s for s in result.suggestions if "parallel" in s.title.lower()]
        assert len(parallel_warnings) == 1

    @pytest.mark.asyncio
    async def test_complex_action_warning(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test detection of very long action sequences."""
        # Setup
        automation = {
            "entity_id": "automation.complex",
            "state": "on",
            "attributes": {
                "friendly_name": "Complex",
                "mode": "single",
                "trigger": [{"platform": "state", "entity_id": "sensor.test"}],
                "condition": [],
                "action": [
                    {"service": f"test.action_{i}"} for i in range(15)  # More than 10 actions
                ],
            },
        }
        mock_ha_client.get_state.return_value = automation

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config)

        # Execute
        result = await analyzer.analyze_automation("complex", include_ai=False)

        # Verify
        assert result is not None
        complex_warnings = [
            s
            for s in result.suggestions
            if "complex" in s.title.lower() and s.severity == SuggestionSeverity.WARNING
        ]
        assert len(complex_warnings) == 1


class TestAnalysisResult:
    """Tests for AnalysisResult dataclass."""

    def test_has_issues_with_error(self) -> None:
        """Test has_issues returns True with ERROR severity."""
        result = AnalysisResult(
            automation_id="test",
            friendly_name="Test",
            state="on",
            trigger_count=1,
            condition_count=0,
            action_count=1,
            suggestions=[
                Suggestion(
                    title="Error",
                    description="Test error",
                    severity=SuggestionSeverity.ERROR,
                    category="actions",
                )
            ],
        )
        assert result.has_issues is True

    def test_has_issues_with_warning(self) -> None:
        """Test has_issues returns True with WARNING severity."""
        result = AnalysisResult(
            automation_id="test",
            friendly_name="Test",
            state="on",
            trigger_count=1,
            condition_count=0,
            action_count=1,
            suggestions=[
                Suggestion(
                    title="Warning",
                    description="Test warning",
                    severity=SuggestionSeverity.WARNING,
                    category="triggers",
                )
            ],
        )
        assert result.has_issues is True

    def test_has_issues_info_only(self) -> None:
        """Test has_issues returns False with only INFO suggestions."""
        result = AnalysisResult(
            automation_id="test",
            friendly_name="Test",
            state="on",
            trigger_count=1,
            condition_count=0,
            action_count=1,
            suggestions=[
                Suggestion(
                    title="Info",
                    description="Test info",
                    severity=SuggestionSeverity.INFO,
                    category="structure",
                )
            ],
        )
        assert result.has_issues is False

    def test_has_issues_no_suggestions(self) -> None:
        """Test has_issues returns False with no suggestions."""
        result = AnalysisResult(
            automation_id="test",
            friendly_name="Test",
            state="on",
            trigger_count=1,
            condition_count=0,
            action_count=1,
        )
        assert result.has_issues is False


class TestSuggestion:
    """Tests for Suggestion dataclass."""

    def test_suggestion_creation(self) -> None:
        """Test creating a suggestion."""
        suggestion = Suggestion(
            title="Test Suggestion",
            description="This is a test",
            severity=SuggestionSeverity.WARNING,
            category="triggers",
        )
        assert suggestion.title == "Test Suggestion"
        assert suggestion.severity == SuggestionSeverity.WARNING
        assert suggestion.category == "triggers"


class TestSuggestionSeverity:
    """Tests for SuggestionSeverity enum."""

    def test_severity_values(self) -> None:
        """Test severity enum values."""
        assert SuggestionSeverity.INFO.value == "info"
        assert SuggestionSeverity.WARNING.value == "warning"
        assert SuggestionSeverity.ERROR.value == "error"
