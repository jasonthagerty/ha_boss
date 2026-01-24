"""Tests for configuration management."""

import os
from unittest.mock import patch

import pytest
import yaml

from ha_boss.core.config import Config, load_config
from ha_boss.core.exceptions import ConfigurationError


def test_config_defaults():
    """Test configuration with default values."""
    config_data = {
        "home_assistant": {
            "url": "http://homeassistant.local:8123",
            "token": "test_token_123",
        }
    }

    config = Config(**config_data)

    # Legacy url/token should be converted to instances
    assert len(config.home_assistant.instances) == 1
    assert config.home_assistant.instances[0].url == "http://homeassistant.local:8123"
    assert config.home_assistant.instances[0].token == "test_token_123"
    assert config.home_assistant.instances[0].instance_id == "default"
    assert config.mode == "production"
    assert config.monitoring.grace_period_seconds == 300
    assert config.healing.enabled is True
    assert config.is_production is True
    assert config.is_dry_run is False


def test_config_url_trailing_slash():
    """Test that URL trailing slash is removed."""
    config_data = {
        "home_assistant": {
            "url": "http://homeassistant.local:8123/",
            "token": "test_token",
        }
    }

    config = Config(**config_data)
    assert config.home_assistant.instances[0].url == "http://homeassistant.local:8123"


def test_config_placeholder_token_ignored():
    """Test that placeholder token results in empty instances list.

    When env var placeholders aren't substituted, they're treated as
    unset - allowing instances to be configured via the dashboard instead.
    """
    config = Config(
        home_assistant={
            "url": "http://homeassistant.local:8123",
            "token": "${HA_TOKEN}",  # Not substituted - will be ignored
        }
    )
    # Placeholder token is ignored, resulting in empty instances
    # (both url AND token must be valid to create an instance)
    assert config.home_assistant.instances == []
    # URL is valid so it's kept, token placeholder is cleared
    assert config.home_assistant.url == "http://homeassistant.local:8123"
    assert config.home_assistant.token is None


def test_config_both_placeholders_ignored():
    """Test that both placeholders result in empty instances list."""
    config = Config(
        home_assistant={
            "url": "${HA_URL}",
            "token": "${HA_TOKEN}",
        }
    )
    # Both are placeholders, so both get cleared
    assert config.home_assistant.instances == []
    assert config.home_assistant.url is None
    assert config.home_assistant.token is None


def test_config_custom_values():
    """Test configuration with custom values."""
    config_data = {
        "home_assistant": {
            "url": "http://localhost:8123",
            "token": "custom_token",
        },
        "mode": "dry_run",
        "monitoring": {
            "grace_period_seconds": 600,
        },
        "healing": {
            "enabled": False,
            "max_attempts": 5,
        },
    }

    config = Config(**config_data)

    assert config.mode == "dry_run"
    assert config.is_dry_run is True
    assert config.monitoring.grace_period_seconds == 600
    assert config.healing.enabled is False
    assert config.healing.max_attempts == 5


def test_load_config_success(tmp_path):
    """Test loading configuration from YAML file."""
    config_file = tmp_path / "config.yaml"
    config_data = {
        "home_assistant": {
            "url": "http://homeassistant.local:8123",
            "token": "test_token",
        },
        "mode": "testing",
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = load_config(config_file)

    assert config.home_assistant.instances[0].url == "http://homeassistant.local:8123"
    assert config.mode == "testing"


def test_load_config_env_substitution(tmp_path):
    """Test environment variable substitution in config."""
    config_file = tmp_path / "config.yaml"
    config_data = {
        "home_assistant": {
            "url": "${TEST_HA_URL}",
            "token": "${TEST_HA_TOKEN}",
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    with patch.dict(
        os.environ,
        {"TEST_HA_URL": "http://test:8123", "TEST_HA_TOKEN": "env_token"},
    ):
        config = load_config(config_file)

        assert config.home_assistant.instances[0].url == "http://test:8123"
        assert config.home_assistant.instances[0].token == "env_token"


def test_load_config_file_not_found():
    """Test error when config file doesn't exist."""
    with pytest.raises(ConfigurationError, match="not found"):
        load_config("/nonexistent/config.yaml")


def test_load_config_invalid_yaml(tmp_path):
    """Test error with invalid YAML."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("invalid: yaml: syntax [")

    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        load_config(config_file)


def test_load_config_missing_required_fields(tmp_path, monkeypatch):
    """Test error when required fields are missing."""
    # Clear environment variables that might provide defaults
    monkeypatch.delenv("HOME_ASSISTANT__URL", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT__TOKEN", raising=False)

    # Create empty .env file in tmp_path to prevent loading from project root
    env_file = tmp_path / ".env"
    env_file.write_text("")

    # Change to tmp directory so BaseSettings loads the empty .env
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / "config.yaml"
    config_data = {"mode": "production"}  # Missing home_assistant

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    with pytest.raises(ConfigurationError, match="Invalid configuration"):
        load_config(config_file)
