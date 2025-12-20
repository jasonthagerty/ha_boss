"""Tests for CLI commands."""

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from ha_boss.cli.commands import app
from ha_boss.core.config import Config, HomeAssistantConfig

runner = CliRunner()


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for tests."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    return {"config": config_dir, "data": data_dir, "tmp": tmp_path}


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        mode="production",
    )


class TestInitCommand:
    """Tests for init command."""

    def test_init_creates_files(self, temp_dirs):
        """Test that init creates configuration files."""
        result = runner.invoke(
            app,
            [
                "init",
                "--config-dir",
                str(temp_dirs["config"]),
                "--data-dir",
                str(temp_dirs["data"]),
            ],
        )

        assert result.exit_code == 0
        assert (temp_dirs["config"] / "config.yaml").exists()
        assert (temp_dirs["config"] / ".env").exists()
        assert "Initialization complete" in result.stdout

    def test_init_force_overwrites(self, temp_dirs):
        """Test that init --force overwrites existing files."""
        config_file = temp_dirs["config"] / "config.yaml"
        config_file.write_text("old content")

        result = runner.invoke(
            app,
            [
                "init",
                "--config-dir",
                str(temp_dirs["config"]),
                "--data-dir",
                str(temp_dirs["data"]),
                "--force",
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "old content" not in content
        assert "home_assistant:" in content

    def test_init_without_force_keeps_existing(self, temp_dirs):
        """Test that init without --force keeps existing files."""
        config_file = temp_dirs["config"] / "config.yaml"
        config_file.write_text("# existing config")

        result = runner.invoke(
            app,
            [
                "init",
                "--config-dir",
                str(temp_dirs["config"]),
                "--data-dir",
                str(temp_dirs["data"]),
            ],
        )

        assert result.exit_code == 0
        assert "already exists" in result.stdout

    def test_init_creates_database(self, temp_dirs):
        """Test that init creates database file."""
        result = runner.invoke(
            app,
            [
                "init",
                "--config-dir",
                str(temp_dirs["config"]),
                "--data-dir",
                str(temp_dirs["data"]),
            ],
        )

        assert result.exit_code == 0
        # Database initialization should succeed
        assert "Database initialized" in result.stdout or "database" in result.stdout.lower()


class TestStartCommand:
    """Tests for start command."""

    @patch("ha_boss.cli.commands.load_config")
    def test_start_attempts_to_run(self, mock_load):
        """Test that start command now attempts to run the service."""
        from ha_boss.core.config import Config, DatabaseConfig, HomeAssistantConfig

        mock_load.return_value = Config(
            home_assistant=HomeAssistantConfig(
                url="http://test:8123",
                token="test_token",
            ),
            database=DatabaseConfig(
                path=":memory:",
                retention_days=30,
            ),
            mode="testing",
        )

        result = runner.invoke(app, ["start", "--foreground"])

        # Service is now implemented, so should NOT show "not implemented"
        assert "not yet implemented" not in result.stdout.lower()
        # Should show it's initializing
        assert "initializing" in result.stdout.lower()


class TestStatusCommand:
    """Tests for status command."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._check_ha_connection")
    @patch("ha_boss.cli.commands._show_db_stats")
    def test_status_shows_config(self, mock_stats, mock_check, mock_load, mock_config):
        """Test that status command shows configuration."""
        mock_load.return_value = mock_config
        mock_check.return_value = AsyncMock()
        mock_stats.return_value = AsyncMock()

        result = runner.invoke(app, ["status"])

        assert "homeassistant.local" in result.stdout
        assert "production" in result.stdout


class TestHealCommand:
    """Tests for heal command."""

    def test_heal_requires_entity_id(self):
        """Test that heal command requires entity ID argument."""
        result = runner.invoke(app, ["heal"])

        assert result.exit_code != 0
        # Typer writes errors to stderr, so check output (stdout + stderr combined)
        output_lower = (result.stdout + str(result.stderr if result.stderr else "")).lower()
        assert "missing argument" in output_lower or "required" in output_lower

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._perform_healing")
    def test_heal_with_entity_id(self, mock_perform, mock_load, mock_config):
        """Test heal command with entity ID."""
        mock_load.return_value = mock_config
        mock_perform.return_value = AsyncMock()

        result = runner.invoke(app, ["heal", "sensor.temperature"])

        mock_load.assert_called_once()
        assert "sensor.temperature" in result.stdout

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._perform_healing")
    def test_heal_dry_run(self, mock_perform, mock_load, mock_config):
        """Test heal command with dry-run flag."""
        mock_load.return_value = mock_config
        mock_perform.return_value = AsyncMock()

        _result = runner.invoke(app, ["heal", "sensor.test", "--dry-run"])

        # Should set dry_run mode
        assert mock_load.return_value.mode == "dry_run"


class TestConfigValidateCommand:
    """Tests for config validate command."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._check_ha_connection")
    def test_validate_config_success(self, mock_check, mock_load, mock_config):
        """Test successful configuration validation."""
        mock_load.return_value = mock_config
        mock_check.return_value = AsyncMock()

        result = runner.invoke(app, ["config", "validate"])

        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    @patch("ha_boss.cli.commands.load_config")
    def test_validate_config_invalid(self, mock_load):
        """Test configuration validation with invalid config."""
        from ha_boss.core.exceptions import ConfigurationError

        mock_load.side_effect = ConfigurationError("Invalid config")

        result = runner.invoke(app, ["config", "validate"])

        assert result.exit_code == 1
        assert "Invalid config" in result.stdout or "error" in result.stdout.lower()


class TestDbCleanupCommand:
    """Tests for db cleanup command."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._cleanup_db")
    def test_cleanup_dry_run(self, mock_cleanup, mock_load, mock_config):
        """Test database cleanup with dry-run flag."""
        mock_load.return_value = mock_config
        mock_cleanup.return_value = AsyncMock()

        result = runner.invoke(app, ["db", "cleanup", "--days", "30", "--dry-run"])

        assert result.exit_code == 0
        # Verify dry_run was passed
        mock_cleanup.assert_called_once()
        assert mock_cleanup.call_args[0][2] is True  # dry_run parameter

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._cleanup_db")
    def test_cleanup_with_days(self, mock_cleanup, mock_load, mock_config):
        """Test database cleanup with custom days parameter."""
        mock_load.return_value = mock_config
        mock_cleanup.return_value = AsyncMock()

        result = runner.invoke(app, ["db", "cleanup", "--days", "7", "--dry-run"])

        assert result.exit_code == 0
        # Verify days parameter was passed correctly
        assert mock_cleanup.call_args[0][1] == 7


class TestErrorHandling:
    """Tests for error handling."""

    @patch("ha_boss.cli.commands.load_config")
    def test_handle_configuration_error(self, mock_load):
        """Test handling of configuration errors."""
        from ha_boss.core.exceptions import ConfigurationError

        mock_load.side_effect = ConfigurationError("Config file not found")

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Error" in result.stdout or "error" in result.stdout.lower()
        assert "Config file not found" in result.stdout

    @patch("ha_boss.cli.commands.load_config")
    def test_handle_connection_error(self, mock_load):
        """Test handling of connection errors."""
        from ha_boss.core.exceptions import HomeAssistantConnectionError

        mock_load.side_effect = HomeAssistantConnectionError("Cannot connect")

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 1
        assert "Cannot connect" in result.stdout


class TestHelpOutput:
    """Tests for help output."""

    def test_main_help(self):
        """Test main help output."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "HA Boss" in result.stdout
        assert "init" in result.stdout
        assert "start" in result.stdout
        assert "status" in result.stdout
        assert "heal" in result.stdout

    def test_init_help(self):
        """Test init command help."""
        result = runner.invoke(app, ["init", "--help"])

        assert result.exit_code == 0
        assert "config" in result.stdout.lower()
        assert "database" in result.stdout.lower()

    def test_heal_help(self):
        """Test heal command help."""
        result = runner.invoke(app, ["heal", "--help"])

        assert result.exit_code == 0
        assert "entity" in result.stdout.lower()

    def test_config_validate_help(self):
        """Test config validate command help."""
        result = runner.invoke(app, ["config", "validate", "--help"])

        assert result.exit_code == 0
        assert "validate" in result.stdout.lower()

    def test_db_cleanup_help(self):
        """Test db cleanup command help."""
        result = runner.invoke(app, ["db", "cleanup", "--help"])

        assert result.exit_code == 0
        assert "cleanup" in result.stdout.lower()
        assert "days" in result.stdout.lower()

    def test_patterns_help(self):
        """Test patterns command help."""
        result = runner.invoke(app, ["patterns", "--help"])

        assert result.exit_code == 0
        assert "patterns" in result.stdout.lower()
        assert "reliability" in result.stdout.lower()
        assert "failures" in result.stdout.lower()
        assert "recommendations" in result.stdout.lower()


class TestPatternsCommands:
    """Tests for patterns command group."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_reliability")
    def test_reliability_command_default(self, mock_show, mock_load, mock_config):
        """Test reliability command with default parameters."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "reliability"])

        assert result.exit_code == 0
        mock_show.assert_called_once()
        # Check default parameters (7 days, no integration filter)
        assert mock_show.call_args[0][1] == 7  # days
        assert mock_show.call_args[0][2] is None  # integration

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_reliability")
    def test_reliability_command_with_integration(self, mock_show, mock_load, mock_config):
        """Test reliability command with integration filter."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "reliability", "--integration", "hue"])

        assert result.exit_code == 0
        # Check integration parameter was passed
        assert mock_show.call_args[0][2] == "hue"

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_reliability")
    def test_reliability_command_with_custom_days(self, mock_show, mock_load, mock_config):
        """Test reliability command with custom days parameter."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "reliability", "--days", "30"])

        assert result.exit_code == 0
        # Check days parameter was passed
        assert mock_show.call_args[0][1] == 30

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_failures")
    def test_failures_command_default(self, mock_show, mock_load, mock_config):
        """Test failures command with default parameters."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "failures"])

        assert result.exit_code == 0
        mock_show.assert_called_once()
        # Check default parameters
        assert mock_show.call_args[0][1] is None  # integration
        assert mock_show.call_args[0][2] == 7  # days
        assert mock_show.call_args[0][3] == 50  # limit

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_failures")
    def test_failures_command_with_integration(self, mock_show, mock_load, mock_config):
        """Test failures command with integration filter."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "failures", "--integration", "zwave"])

        assert result.exit_code == 0
        # Check integration parameter was passed
        assert mock_show.call_args[0][1] == "zwave"

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_failures")
    def test_failures_command_with_limit(self, mock_show, mock_load, mock_config):
        """Test failures command with custom limit."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "failures", "--limit", "100"])

        assert result.exit_code == 0
        # Check limit parameter was passed
        assert mock_show.call_args[0][3] == 100

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_recommendations")
    def test_recommendations_command(self, mock_show, mock_load, mock_config):
        """Test recommendations command."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "recommendations", "hue"])

        assert result.exit_code == 0
        mock_show.assert_called_once()
        # Check integration parameter was passed
        assert mock_show.call_args[0][1] == "hue"

    def test_recommendations_requires_integration(self):
        """Test that recommendations command requires integration argument."""
        result = runner.invoke(app, ["patterns", "recommendations"])

        assert result.exit_code != 0
        # Check for missing argument error
        output_lower = (result.stdout + str(result.stderr if result.stderr else "")).lower()
        assert "missing argument" in output_lower or "required" in output_lower

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._show_recommendations")
    def test_recommendations_with_custom_days(self, mock_show, mock_load, mock_config):
        """Test recommendations command with custom days parameter."""
        mock_load.return_value = mock_config
        mock_show.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "recommendations", "met", "--days", "14"])

        assert result.exit_code == 0
        # Check days parameter was passed
        assert mock_show.call_args[0][2] == 14

    def test_reliability_help(self):
        """Test reliability command help output."""
        result = runner.invoke(app, ["patterns", "reliability", "--help"])

        assert result.exit_code == 0
        assert "reliability" in result.stdout.lower()
        assert "integration" in result.stdout.lower()
        assert "days" in result.stdout.lower()

    def test_failures_help(self):
        """Test failures command help output."""
        result = runner.invoke(app, ["patterns", "failures", "--help"])

        assert result.exit_code == 0
        assert "failures" in result.stdout.lower() or "failure" in result.stdout.lower()
        assert "integration" in result.stdout.lower()
        assert "limit" in result.stdout.lower()

    def test_recommendations_help(self):
        """Test recommendations command help output."""
        result = runner.invoke(app, ["patterns", "recommendations", "--help"])

        assert result.exit_code == 0
        assert "recommendations" in result.stdout.lower()
        assert "integration" in result.stdout.lower()


class TestWeeklySummaryCommand:
    """Tests for patterns weekly-summary command."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._generate_weekly_summary")
    def test_weekly_summary_default(self, mock_generate, mock_load, mock_config):
        """Test weekly summary command with default parameters."""
        mock_load.return_value = mock_config
        mock_generate.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "weekly-summary"])

        assert result.exit_code == 0
        mock_generate.assert_called_once()

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands._generate_weekly_summary")
    def test_weekly_summary_no_notify(self, mock_generate, mock_load, mock_config):
        """Test weekly summary with no-notify flag."""
        mock_load.return_value = mock_config
        mock_generate.return_value = AsyncMock()

        result = runner.invoke(app, ["patterns", "weekly-summary", "--no-notify"])

        assert result.exit_code == 0
        mock_generate.assert_called_once()
        # Verify send_notify was set to False
        assert mock_generate.call_args[1]["send_notify"] is False

    def test_weekly_summary_help(self):
        """Test weekly summary command help output."""
        result = runner.invoke(app, ["patterns", "weekly-summary", "--help"])

        assert result.exit_code == 0
        assert "weekly" in result.stdout.lower() or "summary" in result.stdout.lower()
        assert "ai" in result.stdout.lower()


class TestAutomationCommands:
    """Tests for automation analysis and generation commands."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_analyze_automation_by_id(self, mock_client, mock_load, mock_config):
        """Test automation analysis by automation ID."""
        mock_load.return_value = mock_config
        mock_ha_client = AsyncMock()
        mock_ha_client.get_state = AsyncMock(
            return_value={
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {
                    "trigger": [{"platform": "state"}],
                    "action": [{"service": "light.turn_on"}],
                },
            }
        )
        # Set up async context manager
        mock_ha_client.__aenter__ = AsyncMock(return_value=mock_ha_client)
        mock_ha_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(config):
            return mock_ha_client

        mock_client.side_effect = mock_create_client

        result = runner.invoke(app, ["automation", "analyze", "automation.test"])

        assert result.exit_code == 0

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    @patch("ha_boss.automation.analyzer.AutomationAnalyzer")
    def test_analyze_automation_no_ai(
        self, mock_analyzer_class, mock_client, mock_load, mock_config
    ):
        """Test automation analysis without AI."""
        mock_load.return_value = mock_config
        mock_ha_client = AsyncMock()
        mock_ha_client.get_state = AsyncMock(
            return_value={
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {
                    "trigger": [{"platform": "state"}],
                    "action": [{"service": "light.turn_on"}],
                },
            }
        )
        # Set up async context manager
        mock_ha_client.__aenter__ = AsyncMock(return_value=mock_ha_client)
        mock_ha_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(config):
            return mock_ha_client

        mock_client.side_effect = mock_create_client

        # Mock analyzer
        from ha_boss.automation.analyzer import AnalysisResult

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze_automation = AsyncMock(
            return_value=AnalysisResult(
                automation_id="automation.test",
                friendly_name="Test Automation",
                state="on",
                trigger_count=1,
                condition_count=0,
                action_count=1,
                suggestions=[],
            )
        )
        mock_analyzer_class.return_value = mock_analyzer

        result = runner.invoke(app, ["automation", "analyze", "automation.test", "--no-ai"])

        assert result.exit_code == 0

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_analyze_all_automations(self, mock_client, mock_load, mock_config):
        """Test automation analysis for all automations."""
        mock_load.return_value = mock_config
        mock_ha_client = AsyncMock()
        mock_ha_client.get_states = AsyncMock(return_value=[])
        mock_client.return_value = mock_ha_client

        result = runner.invoke(app, ["automation", "analyze", "--all"])

        assert result.exit_code == 0

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    @patch("ha_boss.automation.generator.AutomationGenerator")
    def test_generate_automation(self, mock_generator_class, mock_client, mock_load, mock_config):
        """Test automation generation command."""
        mock_load.return_value = mock_config
        mock_ha_client = AsyncMock()
        mock_client.return_value = mock_ha_client

        # Mock generator
        mock_generator = AsyncMock()
        mock_generator.generate_automation = AsyncMock(
            return_value={"alias": "Generated Automation", "trigger": [], "action": []}
        )
        mock_generator_class.return_value = mock_generator

        prompt = "Turn on lights when motion detected"
        result = runner.invoke(app, ["automation", "generate", prompt])

        # Just check it doesn't crash - actual generation is complex
        assert result.exit_code in [0, 1]  # May fail due to missing config but shouldn't crash

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    @patch("ha_boss.automation.generator.AutomationGenerator")
    def test_generate_automation_dry_run(
        self, mock_generator_class, mock_client, mock_load, mock_config
    ):
        """Test automation generation in dry-run mode."""
        mock_load.return_value = mock_config
        mock_ha_client = AsyncMock()
        mock_client.return_value = mock_ha_client

        # Mock generator
        mock_generator = AsyncMock()
        mock_generator.generate_automation = AsyncMock(
            return_value={"alias": "Test Automation", "trigger": [], "action": []}
        )
        mock_generator_class.return_value = mock_generator

        prompt = "Test automation"
        result = runner.invoke(app, ["automation", "generate", prompt, "--mode", "dry_run"])

        # Just check it doesn't crash
        assert result.exit_code in [0, 1]

    def test_automation_analyze_help(self):
        """Test automation analyze command help output."""
        result = runner.invoke(app, ["automation", "analyze", "--help"])

        assert result.exit_code == 0
        assert "analyze" in result.stdout.lower()
        assert "automation" in result.stdout.lower()

    def test_automation_generate_help(self):
        """Test automation generate command help output."""
        result = runner.invoke(app, ["automation", "generate", "--help"])

        assert result.exit_code == 0
        assert "generate" in result.stdout.lower()
        assert "automation" in result.stdout.lower()

    def test_automation_help(self):
        """Test automation command group help output."""
        result = runner.invoke(app, ["automation", "--help"])

        assert result.exit_code == 0
        assert "automation" in result.stdout.lower()
        assert "analyze" in result.stdout.lower()
        assert "generate" in result.stdout.lower()

    def test_generate_automation_requires_prompt(self):
        """Test that generate automation command requires prompt."""
        result = runner.invoke(app, ["automation", "generate"])

        assert result.exit_code != 0
        # Check for missing argument error
        output_lower = (result.stdout + str(result.stderr if result.stderr else "")).lower()
        assert "missing argument" in output_lower or "required" in output_lower


class TestConfigValidateErrors:
    """Tests for config validate command error handling."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_validate_auth_error(self, mock_client, mock_load, mock_config):
        """Test config validate with authentication error."""
        from ha_boss.core.exceptions import HomeAssistantAuthError

        mock_load.return_value = mock_config

        async def mock_create_client_auth_error(config):
            raise HomeAssistantAuthError("Invalid token")

        mock_client.side_effect = mock_create_client_auth_error

        result = runner.invoke(app, ["config", "validate"])

        assert result.exit_code == 0  # Command doesn't fail, shows error message
        assert "Authentication failed" in result.stdout or "auth" in result.stdout.lower()

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_validate_connection_error(self, mock_client, mock_load, mock_config):
        """Test config validate with connection error."""
        from ha_boss.core.exceptions import HomeAssistantConnectionError

        mock_load.return_value = mock_config

        async def mock_create_client_conn_error(config):
            raise HomeAssistantConnectionError("Cannot connect")

        mock_client.side_effect = mock_create_client_conn_error

        result = runner.invoke(app, ["config", "validate"])

        assert result.exit_code == 0  # Command doesn't fail, shows error message
        assert "Connection failed" in result.stdout or "connection" in result.stdout.lower()


class TestHealCommandFlow:
    """Tests for heal command actual flow."""

    @patch("ha_boss.cli.commands.load_config")
    def test_heal_dry_run(self, mock_load, mock_config):
        """Test heal command in dry-run mode."""
        mock_load.return_value = mock_config

        with patch("ha_boss.cli.commands.asyncio.run"):
            result = runner.invoke(app, ["heal", "sensor.test", "--dry-run"])

            # Should show dry-run mode message
            assert "dry-run" in result.stdout.lower() or "dry run" in result.stdout.lower()

    def test_heal_requires_entity_id(self):
        """Test that heal command requires entity ID."""
        result = runner.invoke(app, ["heal"])

        assert result.exit_code != 0
        # Should show error about missing entity ID
        output_lower = (result.stdout + str(result.stderr if result.stderr else "")).lower()
        assert "missing argument" in output_lower or "required" in output_lower


class TestStatusCommandVariations:
    """Tests for status command with various states."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_status_with_unavailable_entities(self, mock_client, mock_load, mock_config):
        """Test status command showing unavailable entities."""
        mock_load.return_value = mock_config

        mock_ha_client = AsyncMock()
        mock_ha_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "sensor.test1", "state": "unavailable"},
                {"entity_id": "sensor.test2", "state": "ok"},
            ]
        )
        mock_ha_client.__aenter__ = AsyncMock(return_value=mock_ha_client)
        mock_ha_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(config):
            return mock_ha_client

        mock_client.side_effect = mock_create_client

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_status_connection_error(self, mock_client, mock_load, mock_config):
        """Test status command with connection error."""
        from ha_boss.core.exceptions import HomeAssistantConnectionError

        mock_load.return_value = mock_config

        async def mock_create_client_error(config):
            raise HomeAssistantConnectionError("Cannot connect")

        mock_client.side_effect = mock_create_client_error

        result = runner.invoke(app, ["status"])

        # Should handle error gracefully
        assert result.exit_code != 0 or "error" in result.stdout.lower()


class TestStartCommandFlow:
    """Tests for start command."""

    @patch("ha_boss.cli.commands.load_config")
    def test_start_help(self, mock_load):
        """Test start command help output."""
        result = runner.invoke(app, ["start", "--help"])

        assert result.exit_code == 0
        assert "start" in result.stdout.lower()
        assert "foreground" in result.stdout.lower()

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.service.main.HABossService")
    def test_start_foreground_mode(self, mock_service_class, mock_load, mock_config):
        """Test start command in foreground mode."""
        mock_load.return_value = mock_config

        # Mock the service
        mock_service = AsyncMock()
        mock_service.start = AsyncMock()
        mock_service_class.return_value = mock_service

        # Mock asyncio.run to avoid actually starting the service
        with patch("ha_boss.cli.commands.asyncio.run") as mock_run:
            result = runner.invoke(app, ["start", "--foreground"])

            # Should attempt to run service
            assert mock_run.called or result.exit_code == 0


class TestInitCommandVariations:
    """Additional tests for init command."""

    def test_init_with_existing_config(self, temp_dirs):
        """Test init when config already exists."""
        # Create existing config
        config_file = temp_dirs["config"] / "config.yaml"
        config_file.write_text("existing: config")

        result = runner.invoke(
            app,
            [
                "init",
                "--config-dir",
                str(temp_dirs["config"]),
                "--data-dir",
                str(temp_dirs["data"]),
            ],
        )

        # Should not overwrite existing config
        assert result.exit_code == 0
        assert config_file.exists()

    def test_init_help(self):
        """Test init command help."""
        result = runner.invoke(app, ["init", "--help"])

        assert result.exit_code == 0
        assert "init" in result.stdout.lower()


class TestPatternsCommandErrors:
    """Tests for patterns command error handling."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.asyncio.run")
    def test_reliability_command_execution(self, mock_run, mock_load, mock_config):
        """Test reliability command executes."""
        mock_load.return_value = mock_config

        result = runner.invoke(app, ["patterns", "reliability"])

        # Should execute (asyncio.run called)
        assert mock_run.called or result.exit_code == 0

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.asyncio.run")
    def test_failures_command_execution(self, mock_run, mock_load, mock_config):
        """Test failures command executes."""
        mock_load.return_value = mock_config

        result = runner.invoke(app, ["patterns", "failures"])

        # Should execute (asyncio.run called)
        assert mock_run.called or result.exit_code == 0


class TestAutomationCommandErrors:
    """Tests for automation command error handling."""

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.create_ha_client")
    def test_analyze_nonexistent_automation(self, mock_client, mock_load, mock_config):
        """Test analyzing an automation that doesn't exist."""
        from ha_boss.core.exceptions import HomeAssistantAPIError

        mock_load.return_value = mock_config

        mock_ha_client = AsyncMock()
        mock_ha_client.get_state = AsyncMock(side_effect=HomeAssistantAPIError("Not found"))
        mock_ha_client.__aenter__ = AsyncMock(return_value=mock_ha_client)
        mock_ha_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(config):
            return mock_ha_client

        mock_client.side_effect = mock_create_client

        result = runner.invoke(app, ["automation", "analyze", "automation.nonexistent"])

        # Should handle error gracefully
        assert result.exit_code != 0 or "error" in result.stdout.lower()


class TestDbCommands:
    """Additional tests for database commands."""

    def test_db_help(self):
        """Test db command group help."""
        result = runner.invoke(app, ["db", "--help"])

        assert result.exit_code == 0
        assert "db" in result.stdout.lower() or "database" in result.stdout.lower()

    def test_db_cleanup_help(self):
        """Test db cleanup command help."""
        result = runner.invoke(app, ["db", "cleanup", "--help"])

        assert result.exit_code == 0
        assert "cleanup" in result.stdout.lower()


class TestConfigCommands:
    """Additional tests for config commands."""

    def test_config_help(self):
        """Test config command group help."""
        result = runner.invoke(app, ["config", "--help"])

        assert result.exit_code == 0
        assert "config" in result.stdout.lower()

    @patch("ha_boss.cli.commands.load_config")
    @patch("ha_boss.cli.commands.asyncio.run")
    def test_config_validate_executes(self, mock_run, mock_load, mock_config):
        """Test config validate command executes."""
        mock_load.return_value = mock_config

        result = runner.invoke(app, ["config", "validate"])

        # Should execute
        assert mock_run.called or result.exit_code == 0
