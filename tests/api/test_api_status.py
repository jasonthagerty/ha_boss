"""Tests for API status and health endpoints."""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ha_boss.api.app import create_app


@pytest.fixture
def mock_service():
    """Create a mock HA Boss service."""
    service = MagicMock()
    service.state = "running"
    service.start_time = datetime.now(UTC)
    service.health_checks_performed = 100
    service.healings_attempted = 10
    service.healings_succeeded = 8
    service.healings_failed = 2

    # Mock state tracker
    service.state_tracker = MagicMock()
    service.state_tracker.get_all_states = AsyncMock(return_value={"sensor.test": MagicMock()})

    # Mock other components
    service.ha_client = MagicMock()
    service.websocket_client = MagicMock()
    service.websocket_client.is_connected = MagicMock(return_value=True)
    service.database = MagicMock()

    # Mock config
    service.config = MagicMock()
    service.config.api.auth_enabled = False
    service.config.api.cors_enabled = True
    service.config.api.cors_origins = ["*"]

    return service


@pytest.fixture
def client(mock_service):
    """Create test client with mocked service."""
    with patch("ha_boss.api.app._service", mock_service):
        with patch("ha_boss.api.app.load_config") as mock_load_config:
            mock_load_config.return_value = mock_service.config
            app = create_app()
            return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns API info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "HA Boss API"
    assert "/docs" in data["docs"]
    assert "/redoc" in data["redoc"]


def test_status_endpoint(client, mock_service):
    """Test /api/status endpoint."""
    response = client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert data["state"] == "running"
    assert data["health_checks_performed"] == 100
    assert data["healings_attempted"] == 10
    assert data["healings_succeeded"] == 8
    assert data["healings_failed"] == 2
    assert data["monitored_entities"] == 1


def test_health_endpoint_healthy(client, mock_service):
    """Test /api/health endpoint when all components are healthy."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service_running"] is True
    assert data["ha_connected"] is True
    assert data["websocket_connected"] is True
    assert data["database_accessible"] is True


def test_health_endpoint_degraded(client, mock_service):
    """Test /api/health endpoint when service is degraded."""
    mock_service.websocket_client.is_connected.return_value = False

    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "degraded"
    assert data["service_running"] is True
    assert data["ha_connected"] is True
    assert data["websocket_connected"] is False


def test_health_endpoint_unhealthy(client, mock_service):
    """Test /api/health endpoint when service is unhealthy."""
    mock_service.state = "stopped"

    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["service_running"] is False
