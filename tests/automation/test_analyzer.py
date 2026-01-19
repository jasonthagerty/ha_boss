"""Tests for automation analyzer."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.automation.analyzer import (
    AnalysisResult,
    AutomationAnalyzer,
    Suggestion,
    SuggestionSeverity,
    UsageStatistics,
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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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
        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", llm_router=mock_llm_router
        )

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

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", llm_router=mock_llm_router
        )

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

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", llm_router=mock_llm_router
        )

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

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

    @pytest.mark.asyncio
    async def test_empty_attributes(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test handling of automation with empty attributes."""
        # Setup
        automation = {
            "entity_id": "automation.empty_attrs",
            "state": "on",
            "attributes": {},
        }
        mock_ha_client.get_state.return_value = automation

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

        # Execute
        result = await analyzer.analyze_automation("empty_attrs", include_ai=False)

        # Verify - should handle gracefully
        assert result is not None
        assert result.automation_id == "automation.empty_attrs"
        assert result.trigger_count == 0
        assert result.condition_count == 0
        assert result.action_count == 0
        # Should have "no triggers" and "no actions" suggestions
        assert any("no triggers" in s.title.lower() for s in result.suggestions)
        assert any("no actions" in s.title.lower() for s in result.suggestions)

    @pytest.mark.asyncio
    async def test_malformed_trigger_data(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test handling of malformed trigger data."""
        # Setup - trigger as string instead of dict/list
        automation = {
            "entity_id": "automation.malformed",
            "state": "on",
            "attributes": {
                "friendly_name": "Malformed",
                "trigger": "invalid",  # Should be list or dict
                "condition": None,  # Should be list or dict
                "action": 123,  # Should be list or dict
            },
        }
        mock_ha_client.get_state.return_value = automation

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

        # Execute - should not raise
        result = await analyzer.analyze_automation("malformed", include_ai=False)

        # Verify - should handle gracefully with 0 counts
        assert result is not None
        assert result.trigger_count == 0
        assert result.condition_count == 0
        assert result.action_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_analysis_without_ai(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test that analyze_all uses concurrent analysis when AI is disabled."""
        # Setup
        automations = [
            {
                "entity_id": f"automation.test_{i}",
                "state": "on",
                "attributes": {
                    "friendly_name": f"Test {i}",
                    "trigger": [{"platform": "state", "entity_id": "sensor.test"}],
                    "condition": [],
                    "action": [{"service": "test.test"}],
                },
            }
            for i in range(5)
        ]
        mock_ha_client.get_states.return_value = automations

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

        # Execute
        results = await analyzer.analyze_all(include_ai=False)

        # Verify
        assert len(results) == 5
        assert all(r.automation_id.startswith("automation.test_") for r in results)


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


class TestUsageStatistics:
    """Tests for UsageStatistics dataclass."""

    def test_default_values(self) -> None:
        """Test default values for UsageStatistics."""
        stats = UsageStatistics()
        assert stats.execution_count == 0
        assert stats.failure_count == 0
        assert stats.avg_duration_ms is None
        assert stats.service_call_count == 0
        assert stats.most_common_trigger is None
        assert stats.last_executed is None

    def test_custom_values(self) -> None:
        """Test UsageStatistics with custom values."""
        last_exec = datetime.now(UTC)
        stats = UsageStatistics(
            execution_count=100,
            failure_count=5,
            avg_duration_ms=2500.0,
            service_call_count=300,
            most_common_trigger="state",
            last_executed=last_exec,
        )
        assert stats.execution_count == 100
        assert stats.failure_count == 5
        assert stats.avg_duration_ms == 2500.0
        assert stats.service_call_count == 300
        assert stats.most_common_trigger == "state"
        assert stats.last_executed == last_exec


class TestGetUsageStatistics:
    """Tests for AutomationAnalyzer.get_usage_statistics()."""

    @pytest.mark.asyncio
    async def test_returns_none_when_database_unavailable(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test get_usage_statistics returns None when database is not set."""
        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=None
        )
        result = await analyzer.get_usage_statistics("automation.test")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_database_errors_gracefully(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test get_usage_statistics handles database errors gracefully."""
        # Create mock database that raises error
        mock_db = MagicMock()
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(side_effect=Exception("Database error"))
        context_manager.__aexit__ = AsyncMock()
        mock_db.async_session.return_value = context_manager

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=mock_db
        )

        result = await analyzer.get_usage_statistics("automation.test")

        # Should return None on error, not raise exception
        assert result is None


class TestUsageBasedSuggestions:
    """Tests for AutomationAnalyzer._usage_based_suggestions()."""

    @pytest.fixture
    def analyzer(self, mock_ha_client: AsyncMock, mock_config: MagicMock) -> AutomationAnalyzer:
        """Create analyzer for suggestion tests."""
        return AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")

    @pytest.fixture
    def base_analysis(self) -> AnalysisResult:
        """Create base analysis result for tests."""
        return AnalysisResult(
            automation_id="automation.test",
            friendly_name="Test Automation",
            state="on",
            trigger_count=1,
            condition_count=1,
            action_count=2,
        )

    def test_high_execution_frequency_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for high execution frequency."""
        # 4000 executions in 30 days = ~133/day (>100 threshold)
        usage = UsageStatistics(execution_count=4000, failure_count=0)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis, days=30)

        high_freq = [s for s in suggestions if "frequency" in s.title.lower()]
        assert len(high_freq) == 1
        assert high_freq[0].severity == SuggestionSeverity.WARNING
        assert "133" in high_freq[0].description  # ~133 executions/day

    def test_high_failure_rate_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for high failure rate."""
        # 15% failure rate (>10% threshold)
        usage = UsageStatistics(execution_count=100, failure_count=15)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        failure_sugg = [s for s in suggestions if "failure" in s.title.lower()]
        assert len(failure_sugg) == 1
        assert failure_sugg[0].severity == SuggestionSeverity.ERROR
        assert "15.0%" in failure_sugg[0].description

    def test_slow_execution_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for slow execution."""
        # 7000ms average (>5000ms threshold)
        usage = UsageStatistics(execution_count=50, failure_count=0, avg_duration_ms=7000.0)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        slow_sugg = [s for s in suggestions if "slow" in s.title.lower()]
        assert len(slow_sugg) == 1
        assert slow_sugg[0].severity == SuggestionSeverity.WARNING
        assert "7.0s" in slow_sugg[0].description

    def test_high_service_call_volume_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for high service call volume."""
        # 8 service calls per execution (>5 threshold)
        usage = UsageStatistics(execution_count=50, failure_count=0, service_call_count=400)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        call_sugg = [s for s in suggestions if "service call" in s.title.lower()]
        assert len(call_sugg) == 1
        assert call_sugg[0].severity == SuggestionSeverity.INFO
        assert "8.0" in call_sugg[0].description

    def test_inactive_automation_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for automation with no executions."""
        usage = UsageStatistics(execution_count=0, failure_count=0)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis, days=30)

        inactive_sugg = [s for s in suggestions if "never executed" in s.title.lower()]
        assert len(inactive_sugg) == 1
        assert inactive_sugg[0].severity == SuggestionSeverity.WARNING
        assert "30 days" in inactive_sugg[0].description

    def test_rarely_executed_suggestion(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test suggestion generated for rarely executed automation."""
        # Only 3 executions in period (<5 threshold)
        usage = UsageStatistics(execution_count=3, failure_count=0)

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis, days=7)

        rare_sugg = [s for s in suggestions if "rarely" in s.title.lower()]
        assert len(rare_sugg) == 1
        assert rare_sugg[0].severity == SuggestionSeverity.INFO
        assert "3 times" in rare_sugg[0].description
        assert "7 days" in rare_sugg[0].description

    def test_multiple_suggestions_generated(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test multiple suggestions can be generated simultaneously."""
        # High failure rate + slow execution
        usage = UsageStatistics(
            execution_count=100,
            failure_count=20,  # 20% failure rate
            avg_duration_ms=8000.0,  # 8 seconds
            service_call_count=100,  # 1 per execution (normal)
        )

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        # Should have both failure and slow suggestions
        assert len(suggestions) >= 2
        titles = [s.title.lower() for s in suggestions]
        assert any("failure" in t for t in titles)
        assert any("slow" in t for t in titles)

    def test_days_parameter_used_correctly(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test that days parameter affects suggestion messages."""
        usage = UsageStatistics(execution_count=0)

        # With 7 days
        suggestions_7 = analyzer._usage_based_suggestions(usage, base_analysis, days=7)
        assert any("7 days" in s.description for s in suggestions_7)

        # With 14 days
        suggestions_14 = analyzer._usage_based_suggestions(usage, base_analysis, days=14)
        assert any("14 days" in s.description for s in suggestions_14)

    def test_no_suggestions_for_healthy_automation(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test no suggestions for healthy automation usage."""
        # Normal usage: moderate executions, low failure rate, fast execution
        usage = UsageStatistics(
            execution_count=50,  # Moderate
            failure_count=1,  # 2% failure rate (below threshold)
            avg_duration_ms=500.0,  # Fast
            service_call_count=100,  # 2 per execution (normal)
        )

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        # Should have no usage-based suggestions
        assert len(suggestions) == 0

    def test_all_suggestions_have_usage_category(
        self, analyzer: AutomationAnalyzer, base_analysis: AnalysisResult
    ) -> None:
        """Test all generated suggestions have 'usage' category."""
        usage = UsageStatistics(
            execution_count=5000,  # High frequency
            failure_count=1000,  # High failure rate
            avg_duration_ms=10000.0,  # Slow
            service_call_count=50000,  # High service calls
        )

        suggestions = analyzer._usage_based_suggestions(usage, base_analysis)

        assert len(suggestions) > 0
        assert all(s.category == "usage" for s in suggestions)


class TestAnalyzeWithUsage:
    """Tests for AutomationAnalyzer.analyze_with_usage()."""

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_automation(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock
    ) -> None:
        """Test analyze_with_usage returns None for nonexistent automation."""
        mock_ha_client.get_state.return_value = None

        analyzer = AutomationAnalyzer(mock_ha_client, mock_config, instance_id="test")
        result = await analyzer.analyze_with_usage("automation.nonexistent", include_ai=False)

        assert result is None

    @pytest.mark.asyncio
    async def test_includes_usage_statistics_in_result(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test analyze_with_usage includes usage statistics."""
        mock_ha_client.get_state.return_value = sample_automation_state

        # Create usage stats to return from mocked method
        usage_stats = UsageStatistics(
            execution_count=25,
            failure_count=2,
            avg_duration_ms=1000.0,
            service_call_count=50,
            most_common_trigger="time",
            last_executed=datetime.now(UTC),
        )

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=MagicMock()
        )

        # Mock get_usage_statistics to return our stats
        with patch.object(analyzer, "get_usage_statistics", return_value=usage_stats):
            result = await analyzer.analyze_with_usage(
                "automation.bedroom_lights", include_ai=False
            )

        assert result is not None
        assert result.usage_stats is not None
        assert result.usage_stats.execution_count == 25
        assert result.usage_stats.failure_count == 2
        assert result.usage_stats.most_common_trigger == "time"

    @pytest.mark.asyncio
    async def test_works_without_database(
        self, mock_ha_client: AsyncMock, mock_config: MagicMock, sample_automation_state: dict
    ) -> None:
        """Test analyze_with_usage works without database."""
        mock_ha_client.get_state.return_value = sample_automation_state

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=None
        )
        result = await analyzer.analyze_with_usage("automation.bedroom_lights", include_ai=False)

        assert result is not None
        assert result.usage_stats is None
        # Should still have base analysis
        assert result.automation_id == "automation.bedroom_lights"

    @pytest.mark.asyncio
    async def test_adds_usage_based_suggestions(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test analyze_with_usage adds usage-based suggestions."""
        mock_ha_client.get_state.return_value = sample_automation_state

        # High failure rate to trigger suggestion
        usage_stats = UsageStatistics(
            execution_count=100,
            failure_count=20,  # 20% failure rate
            avg_duration_ms=500.0,
            service_call_count=100,
            most_common_trigger="state",
        )

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=MagicMock()
        )

        with patch.object(analyzer, "get_usage_statistics", return_value=usage_stats):
            result = await analyzer.analyze_with_usage(
                "automation.bedroom_lights", include_ai=False
            )

        assert result is not None
        # Should have usage-based failure rate suggestion
        usage_suggestions = [s for s in result.suggestions if s.category == "usage"]
        assert len(usage_suggestions) > 0
        assert any("failure" in s.title.lower() for s in usage_suggestions)

    @pytest.mark.asyncio
    async def test_respects_days_parameter(
        self,
        mock_ha_client: AsyncMock,
        mock_config: MagicMock,
        sample_automation_state: dict,
    ) -> None:
        """Test analyze_with_usage respects days parameter."""
        mock_ha_client.get_state.return_value = sample_automation_state

        # Zero executions to trigger "inactive" suggestion
        usage_stats = UsageStatistics(
            execution_count=0,
            failure_count=0,
        )

        analyzer = AutomationAnalyzer(
            mock_ha_client, mock_config, instance_id="test", database=MagicMock()
        )

        with patch.object(analyzer, "get_usage_statistics", return_value=usage_stats):
            result = await analyzer.analyze_with_usage(
                "automation.bedroom_lights", include_ai=False, days=7
            )

        assert result is not None
        # Suggestion should mention 7 days, not 30
        inactive_sugg = [s for s in result.suggestions if "never executed" in s.title.lower()]
        assert len(inactive_sugg) == 1
        assert "7 days" in inactive_sugg[0].description
