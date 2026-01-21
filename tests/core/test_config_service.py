"""Tests for ConfigService."""

import os
from unittest.mock import patch

import pytest

from ha_boss.core.config_service import (
    EDITABLE_SETTINGS,
    ConfigService,
    ConfigSource,
    ConfigValue,
)
from ha_boss.core.database import Database
from ha_boss.core.exceptions import ConfigServiceError


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_config.db"
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
async def config_service(database, tmp_path):
    """Create ConfigService with test database."""
    # Set encryption key path to temp directory
    import ha_boss.core.encryption as enc_module

    enc_module._encryption = None
    enc_module.DEFAULT_KEY_PATH = tmp_path / ".encryption_key"

    yaml_config = {
        "monitoring": {"grace_period_seconds": 300},
        "healing": {"enabled": True, "max_attempts": 3},
        "logging": {"level": "INFO"},
    }
    return ConfigService(database=database, yaml_config=yaml_config)


class TestConfigService:
    """Tests for ConfigService class."""

    @pytest.mark.asyncio
    async def test_get_setting_from_yaml(self, config_service):
        """Test getting setting from YAML config."""
        value = await config_service.get_setting("monitoring.grace_period_seconds")
        assert value == 300

    @pytest.mark.asyncio
    async def test_get_setting_from_default(self, config_service):
        """Test getting setting from default when not in YAML."""
        # This setting isn't in our test yaml_config
        value = await config_service.get_setting("healing.cooldown_seconds")
        # Should return the Pydantic default
        assert isinstance(value, int)

    @pytest.mark.asyncio
    async def test_get_setting_from_env(self, config_service):
        """Test that environment variable overrides other sources."""
        with patch.dict(os.environ, {"HA_BOSS_HEALING_MAX_ATTEMPTS": "10"}):
            value = await config_service.get_setting("healing.max_attempts")
            assert value == 10

    @pytest.mark.asyncio
    async def test_set_and_get_setting(self, config_service):
        """Test setting and getting a value from database."""
        await config_service.set_setting("healing.max_attempts", 5)
        value = await config_service.get_setting("healing.max_attempts")
        assert value == 5

    @pytest.mark.asyncio
    async def test_set_setting_returns_config_value(self, config_service):
        """Test that set_setting returns ConfigValue."""
        result = await config_service.set_setting("healing.enabled", False)
        assert isinstance(result, ConfigValue)
        assert result.key == "healing.enabled"
        assert result.value is False
        assert result.source == ConfigSource.DATABASE

    @pytest.mark.asyncio
    async def test_set_invalid_setting_raises(self, config_service):
        """Test that setting invalid key raises error."""
        with pytest.raises(ConfigServiceError, match="not editable"):
            await config_service.set_setting("invalid.setting.key", "value")

    @pytest.mark.asyncio
    async def test_set_env_override_raises(self, config_service):
        """Test that setting env-overridden value raises error."""
        with patch.dict(os.environ, {"HA_BOSS_HEALING_MAX_ATTEMPTS": "10"}):
            with pytest.raises(ConfigServiceError, match="overridden by environment"):
                await config_service.set_setting("healing.max_attempts", 5)

    @pytest.mark.asyncio
    async def test_delete_setting(self, config_service):
        """Test deleting a setting reverts to YAML/default."""
        # Set in database
        await config_service.set_setting("healing.max_attempts", 10)
        assert await config_service.get_setting("healing.max_attempts") == 10

        # Delete from database
        deleted = await config_service.delete_setting("healing.max_attempts")
        assert deleted is True

        # Should revert to YAML value
        assert await config_service.get_setting("healing.max_attempts") == 3

    @pytest.mark.asyncio
    async def test_delete_nonexistent_setting(self, config_service):
        """Test deleting nonexistent setting returns False."""
        deleted = await config_service.delete_setting("healing.max_attempts")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_all_config(self, config_service):
        """Test getting all configuration."""
        all_config = await config_service.get_all_config()

        assert len(all_config) == len(EDITABLE_SETTINGS)
        assert "healing.enabled" in all_config
        assert "monitoring.grace_period_seconds" in all_config

    @pytest.mark.asyncio
    async def test_get_schema(self, config_service):
        """Test getting configuration schema."""
        schema = await config_service.get_schema()

        assert len(schema) == len(EDITABLE_SETTINGS)
        assert "healing.enabled" in schema

        healing_enabled = schema["healing.enabled"]
        assert healing_enabled.value_type == "bool"
        assert healing_enabled.section == "healing"

    @pytest.mark.asyncio
    async def test_validate_config_valid(self, config_service):
        """Test validating valid configuration."""
        errors = await config_service.validate_config(
            {"healing.max_attempts": 5, "healing.enabled": True}
        )
        assert errors == []

    @pytest.mark.asyncio
    async def test_validate_config_invalid_key(self, config_service):
        """Test validating with invalid key."""
        errors = await config_service.validate_config({"invalid.key": "value"})
        assert len(errors) == 1
        assert "Unknown setting" in errors[0]

    @pytest.mark.asyncio
    async def test_validate_config_out_of_range(self, config_service):
        """Test validating value out of range."""
        errors = await config_service.validate_config({"healing.max_attempts": 100})  # Max is 10
        assert len(errors) == 1
        assert "above maximum" in errors[0]

    @pytest.mark.asyncio
    async def test_validate_config_invalid_option(self, config_service):
        """Test validating invalid option value."""
        errors = await config_service.validate_config({"logging.level": "INVALID_LEVEL"})
        assert len(errors) == 1
        assert "not in allowed options" in errors[0]


class TestConfigServiceInstances:
    """Tests for instance management in ConfigService."""

    @pytest.mark.asyncio
    async def test_add_instance(self, config_service):
        """Test adding a new HA instance."""
        instance = await config_service.add_instance(
            instance_id="test_instance",
            url="http://homeassistant.local:8123",
            token="test_token_12345",
        )

        assert instance.instance_id == "test_instance"
        assert instance.url == "http://homeassistant.local:8123"
        assert instance.masked_token != "test_token_12345"  # Should be masked
        assert instance.is_active is True

    @pytest.mark.asyncio
    async def test_add_duplicate_instance_raises(self, config_service):
        """Test that adding duplicate instance raises error."""
        await config_service.add_instance(
            instance_id="test",
            url="http://ha.local:8123",
            token="token",
        )

        with pytest.raises(ConfigServiceError, match="already exists"):
            await config_service.add_instance(
                instance_id="test",
                url="http://other.local:8123",
                token="token2",
            )

    @pytest.mark.asyncio
    async def test_get_instances(self, config_service):
        """Test getting all instances."""
        await config_service.add_instance(
            instance_id="instance1",
            url="http://ha1.local:8123",
            token="token1",
        )
        await config_service.add_instance(
            instance_id="instance2",
            url="http://ha2.local:8123",
            token="token2",
        )

        instances = await config_service.get_instances()
        assert len(instances) == 2
        assert {i.instance_id for i in instances} == {"instance1", "instance2"}

    @pytest.mark.asyncio
    async def test_update_instance(self, config_service):
        """Test updating an instance."""
        await config_service.add_instance(
            instance_id="test",
            url="http://old.local:8123",
            token="old_token",
        )

        updated = await config_service.update_instance(
            instance_id="test",
            url="http://new.local:8123",
            is_active=False,
        )

        assert updated.url == "http://new.local:8123"
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_update_nonexistent_instance_raises(self, config_service):
        """Test updating nonexistent instance raises error."""
        with pytest.raises(ConfigServiceError, match="not found"):
            await config_service.update_instance(
                instance_id="nonexistent",
                url="http://ha.local:8123",
            )

    @pytest.mark.asyncio
    async def test_delete_instance(self, config_service):
        """Test deleting an instance."""
        await config_service.add_instance(
            instance_id="test",
            url="http://ha.local:8123",
            token="token",
        )

        deleted = await config_service.delete_instance("test")
        assert deleted is True

        instances = await config_service.get_instances()
        assert len(instances) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_instance(self, config_service):
        """Test deleting nonexistent instance returns False."""
        deleted = await config_service.delete_instance("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_instance_token(self, config_service):
        """Test getting decrypted token for instance."""
        await config_service.add_instance(
            instance_id="test",
            url="http://ha.local:8123",
            token="my_secret_token",
        )

        token = await config_service.get_instance_token("test")
        assert token == "my_secret_token"

    @pytest.mark.asyncio
    async def test_get_instance_token_nonexistent(self, config_service):
        """Test getting token for nonexistent instance returns None."""
        token = await config_service.get_instance_token("nonexistent")
        assert token is None


class TestConfigServiceValidation:
    """Tests for value validation in ConfigService."""

    @pytest.mark.asyncio
    async def test_validate_bool_from_string(self, config_service):
        """Test that string 'true' is converted to bool."""
        await config_service.set_setting("healing.enabled", "true")
        value = await config_service.get_setting("healing.enabled")
        assert value is True

    @pytest.mark.asyncio
    async def test_validate_int_from_string(self, config_service):
        """Test that string '5' is converted to int."""
        await config_service.set_setting("healing.max_attempts", "5")
        value = await config_service.get_setting("healing.max_attempts")
        assert value == 5

    @pytest.mark.asyncio
    async def test_validate_list_from_string(self, config_service):
        """Test that newline-separated string is converted to list."""
        await config_service.set_setting("monitoring.include", "sensor.*\nlight.*")
        value = await config_service.get_setting("monitoring.include")
        assert value == ["sensor.*", "light.*"]

    @pytest.mark.asyncio
    async def test_validate_list_from_comma_string(self, config_service):
        """Test that comma-separated string is converted to list."""
        await config_service.set_setting("monitoring.include", "sensor.*, light.*")
        value = await config_service.get_setting("monitoring.include")
        assert value == ["sensor.*", "light.*"]
