"""Tests for API authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app


@pytest.fixture
def mock_service_with_auth():
    """Create a mock HA Boss service with authentication enabled."""
    service = MagicMock()
    service.state = "running"
    service.ha_client = MagicMock()
    service.state_tracker = MagicMock()
    service.state_tracker.get_all_states = AsyncMock(return_value={})
    service.websocket_client = MagicMock()
    service.websocket_client.is_connected = MagicMock(return_value=True)
    service.database = MagicMock()

    # Enable auth
    service.config = MagicMock()
    service.config.api.auth_enabled = True
    service.config.api.api_keys = ["test-key-123", "test-key-456"]
    service.config.api.cors_enabled = True
    service.config.api.cors_origins = ["*"]

    return service


@pytest.fixture
def client_with_auth(mock_service_with_auth):
    """Create test client with authentication enabled."""
    with patch("ha_boss.api.app._service", mock_service_with_auth):
        with patch("ha_boss.api.app.get_service", return_value=mock_service_with_auth):
            with patch("ha_boss.api.dependencies.get_service", return_value=mock_service_with_auth):
                with patch(
                    "ha_boss.api.routes.status.get_service", return_value=mock_service_with_auth
                ):
                    with patch("ha_boss.api.app.load_config") as mock_load_config:
                        mock_load_config.return_value = mock_service_with_auth.config
                        app = create_app()
                        yield TestClient(app)


def test_auth_required_no_key(client_with_auth):
    """Test that requests without API key are rejected when auth is enabled."""
    response = client_with_auth.get("/api/status")
    assert response.status_code == 401
    assert "API key required" in response.json()["detail"]


def test_auth_valid_key(client_with_auth):
    """Test that requests with valid API key are accepted."""
    response = client_with_auth.get("/api/status", headers={"X-API-Key": "test-key-123"})
    assert response.status_code == 200


def test_auth_invalid_key(client_with_auth):
    """Test that requests with invalid API key are rejected."""
    response = client_with_auth.get("/api/status", headers={"X-API-Key": "invalid-key"})
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]


def test_auth_disabled():
    """Test that requests work without API key when auth is disabled."""
    mock_service = MagicMock()
    mock_service.state = "running"
    mock_service.ha_client = MagicMock()
    mock_service.state_tracker = MagicMock()
    mock_service.state_tracker.get_all_states = AsyncMock(return_value={})
    mock_service.websocket_client = MagicMock()
    mock_service.websocket_client.is_connected = MagicMock(return_value=True)
    mock_service.database = MagicMock()

    # Disable auth
    mock_service.config = MagicMock()
    mock_service.config.api.auth_enabled = False
    mock_service.config.api.cors_enabled = True
    mock_service.config.api.cors_origins = ["*"]

    with patch("ha_boss.api.app._service", mock_service):
        with patch("ha_boss.api.app.get_service", return_value=mock_service):
            with patch("ha_boss.api.dependencies.get_service", return_value=mock_service):
                with patch("ha_boss.api.routes.status.get_service", return_value=mock_service):
                    with patch("ha_boss.api.app.load_config") as mock_load_config:
                        mock_load_config.return_value = mock_service.config
                        app = create_app()
                        client = TestClient(app)

                        # Request without auth should succeed
                        response = client.get("/api/status")
                        assert response.status_code == 200
