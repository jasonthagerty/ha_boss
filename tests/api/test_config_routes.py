"""Tests for configuration API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app
from ha_boss.core.config_service import ConfigService, ConfigSource, ConfigValue, SettingMetadata
from ha_boss.core.exceptions import ConfigServiceError


@pytest.fixture
def mock_service():
    """Create mock HABossService."""
    service = MagicMock()
    service.database = MagicMock()
    service.config = MagicMock()
    service.config.api = MagicMock()
    service.config.api.auth_enabled = False
    service.config.api.cors_enabled = False
    return service


@pytest.fixture
def mock_config_service():
    """Create mock ConfigService."""
    config_service = AsyncMock(spec=ConfigService)

    # Setup default return values
    config_service.get_all_config.return_value = {
        "healing.enabled": ConfigValue(
            key="healing.enabled",
            value=True,
            source=ConfigSource.DEFAULT,
            editable=True,
            requires_restart=False,
        ),
        "healing.max_attempts": ConfigValue(
            key="healing.max_attempts",
            value=3,
            source=ConfigSource.YAML,
            editable=True,
            requires_restart=False,
        ),
    }

    config_service.get_schema.return_value = {
        "healing.enabled": SettingMetadata(
            key="healing.enabled",
            label="Healing Enabled",
            description="Enable auto-healing",
            value_type="bool",
            section="healing",
        ),
        "healing.max_attempts": SettingMetadata(
            key="healing.max_attempts",
            label="Max Attempts",
            description="Maximum healing attempts",
            value_type="int",
            section="healing",
            min_value=1,
            max_value=10,
        ),
    }

    config_service.validate_config.return_value = []
    config_service.set_setting.return_value = ConfigValue(
        key="healing.enabled",
        value=False,
        source=ConfigSource.DATABASE,
        editable=True,
        requires_restart=False,
    )

    config_service.get_instances.return_value = []

    return config_service


@pytest.fixture
def client(mock_service, mock_config_service):
    """Create test client with mocked service."""
    # Inject mock config service before creating app
    mock_service._config_service = mock_config_service

    with patch("ha_boss.api.app._service", mock_service):
        with patch("ha_boss.api.app.get_service", return_value=mock_service):
            with patch("ha_boss.api.dependencies.get_service", return_value=mock_service):
                with patch("ha_boss.api.routes.config.get_service", return_value=mock_service):
                    with patch("ha_boss.api.app.load_config") as mock_load_config:
                        mock_load_config.return_value = mock_service.config
                        app = create_app()
                        yield TestClient(app)


class TestGetConfig:
    """Tests for GET /api/config endpoint."""

    def test_get_config_success(self, client, mock_config_service):
        """Test getting configuration successfully."""
        response = client.get("/api/config")

        assert response.status_code == 200
        data = response.json()

        assert "settings" in data
        assert "healing.enabled" in data["settings"]
        assert data["settings"]["healing.enabled"]["value"] is True
        assert data["settings"]["healing.enabled"]["source"] == "default"

    def test_get_config_shows_source(self, client, mock_config_service):
        """Test that config shows source information."""
        response = client.get("/api/config")
        data = response.json()

        assert data["settings"]["healing.max_attempts"]["source"] == "yaml"


class TestUpdateConfig:
    """Tests for PUT /api/config endpoint."""

    def test_update_config_success(self, client, mock_config_service):
        """Test updating configuration successfully."""
        response = client.put(
            "/api/config",
            json={"settings": {"healing.enabled": False}},
        )

        assert response.status_code == 200
        data = response.json()

        assert "updated" in data
        assert "healing.enabled" in data["updated"]

    def test_update_config_validation_error(self, client, mock_config_service):
        """Test that validation errors are returned."""
        mock_config_service.validate_config.return_value = ["Invalid value"]

        response = client.put(
            "/api/config",
            json={"settings": {"healing.max_attempts": 100}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == []
        assert "Invalid value" in data["errors"]


class TestGetConfigSchema:
    """Tests for GET /api/config/schema endpoint."""

    def test_get_schema_success(self, client, mock_config_service):
        """Test getting configuration schema."""
        response = client.get("/api/config/schema")

        assert response.status_code == 200
        data = response.json()

        assert "settings" in data
        assert "sections" in data
        assert "healing.enabled" in data["settings"]
        assert data["settings"]["healing.enabled"]["value_type"] == "bool"


class TestValidateConfig:
    """Tests for POST /api/config/validate endpoint."""

    def test_validate_config_valid(self, client, mock_config_service):
        """Test validating valid configuration."""
        mock_config_service.validate_config.return_value = []

        response = client.post(
            "/api/config/validate",
            json={"settings": {"healing.enabled": True}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_config_invalid(self, client, mock_config_service):
        """Test validating invalid configuration."""
        mock_config_service.validate_config.return_value = ["Value out of range"]

        response = client.post(
            "/api/config/validate",
            json={"settings": {"healing.max_attempts": 100}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "Value out of range" in data["errors"]


class TestConfigReload:
    """Tests for POST /api/config/reload endpoint."""

    def test_reload_config(self, client, mock_config_service):
        """Test requesting configuration reload."""
        response = client.post("/api/config/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reload_requested"


class TestInstanceManagement:
    """Tests for instance management endpoints."""

    def test_list_instances_empty(self, client, mock_config_service):
        """Test listing instances when none exist."""
        mock_config_service.get_instances.return_value = []

        response = client.get("/api/config/instances")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_instances_with_data(self, client, mock_config_service):
        """Test listing instances with data."""
        from datetime import UTC, datetime

        from ha_boss.core.config_service import InstanceInfo

        mock_config_service.get_instances.return_value = [
            InstanceInfo(
                instance_id="home",
                url="http://ha.local:8123",
                masked_token="eyJ...xxxx",
                bridge_enabled=True,
                is_active=True,
                source="dashboard",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ]

        response = client.get("/api/config/instances")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["instance_id"] == "home"
        assert data[0]["masked_token"] == "eyJ...xxxx"

    def test_add_instance_success(self, client, mock_config_service):
        """Test adding a new instance."""
        from datetime import UTC, datetime

        from ha_boss.core.config_service import InstanceInfo

        mock_config_service.add_instance.return_value = InstanceInfo(
            instance_id="new_instance",
            url="http://new.local:8123",
            masked_token="eyJ...yyyy",
            bridge_enabled=True,
            is_active=True,
            source="dashboard",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        response = client.post(
            "/api/config/instances",
            json={
                "instance_id": "new_instance",
                "url": "http://new.local:8123",
                "token": "secret_token",
                "bridge_enabled": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["instance_id"] == "new_instance"

    def test_add_instance_duplicate(self, client, mock_config_service):
        """Test adding duplicate instance returns error."""
        mock_config_service.add_instance.side_effect = ConfigServiceError(
            "Instance 'home' already exists"
        )

        response = client.post(
            "/api/config/instances",
            json={
                "instance_id": "home",
                "url": "http://ha.local:8123",
                "token": "token",
            },
        )

        assert response.status_code == 400

    def test_update_instance(self, client, mock_config_service):
        """Test updating an instance."""
        from datetime import UTC, datetime

        from ha_boss.core.config_service import InstanceInfo

        mock_config_service.update_instance.return_value = InstanceInfo(
            instance_id="home",
            url="http://new-url.local:8123",
            masked_token="eyJ...xxxx",
            bridge_enabled=False,
            is_active=True,
            source="dashboard",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        response = client.put(
            "/api/config/instances/home",
            json={"url": "http://new-url.local:8123", "bridge_enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "http://new-url.local:8123"
        assert data["bridge_enabled"] is False

    def test_update_nonexistent_instance(self, client, mock_config_service):
        """Test updating nonexistent instance returns 404."""
        mock_config_service.update_instance.side_effect = ConfigServiceError(
            "Instance 'nonexistent' not found"
        )

        response = client.put(
            "/api/config/instances/nonexistent",
            json={"url": "http://new.local:8123"},
        )

        assert response.status_code == 404

    def test_delete_instance(self, client, mock_config_service):
        """Test deleting an instance."""
        mock_config_service.delete_instance.return_value = True

        response = client.delete("/api/config/instances/home")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_delete_nonexistent_instance(self, client, mock_config_service):
        """Test deleting nonexistent instance returns 404."""
        mock_config_service.delete_instance.return_value = False

        response = client.delete("/api/config/instances/nonexistent")

        assert response.status_code == 404
