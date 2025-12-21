"""Tests for API status and health endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app


@pytest.fixture
def mock_service():
    """Create a mock HA Boss service with all components."""
    service = MagicMock()
    service.state = "running"
    service.start_time = datetime.now(UTC)
    service.health_checks_performed = 100
    service.healings_attempted = 10
    service.healings_succeeded = 8
    service.healings_failed = 2

    # Mock config
    service.config = MagicMock()
    service.config.mode = "production"
    service.config.api.auth_enabled = False
    service.config.api.cors_enabled = True
    service.config.api.cors_origins = ["*"]
    service.config.home_assistant.url = "http://homeassistant.local:8123"
    service.config.database.path = "data/ha_boss.db"
    service.config.monitoring.health_check_interval_seconds = 60
    service.config.healing.enabled = True
    service.config.healing.circuit_breaker_threshold = 3
    service.config.intelligence.ollama_enabled = True
    service.config.intelligence.ollama_url = "http://localhost:11434"
    service.config.intelligence.ollama_model = "llama3.1:8b"
    service.config.intelligence.claude_enabled = False
    service.config.intelligence.claude_api_key = None

    # Mock HA Client with session
    service.ha_client = MagicMock()
    service.ha_client._session = MagicMock()
    service.ha_client._session.closed = False

    # Mock WebSocket client
    service.websocket_client = MagicMock()
    service.websocket_client.is_connected = MagicMock(return_value=True)
    service.websocket_client._running = True

    # Mock database with engine
    service.database = MagicMock()
    service.database.engine = MagicMock()

    # Mock state tracker with cache
    service.state_tracker = MagicMock()
    service.state_tracker._cache = {"sensor.test": MagicMock(), "sensor.test2": MagicMock()}
    service.state_tracker.get_all_states = AsyncMock(
        return_value={"sensor.test": MagicMock(), "sensor.test2": MagicMock()}
    )

    # Mock integration discovery
    service.integration_discovery = MagicMock()
    service.integration_discovery._entity_to_integration = {
        "sensor.test": "sensor",
        "sensor.test2": "sensor",
    }
    service.integration_discovery._integrations = {"sensor": MagicMock()}

    # Mock health monitor
    service.health_monitor = MagicMock()
    service.health_monitor._running = True
    service.health_monitor._monitor_task = MagicMock()
    service.health_monitor._monitor_task.done = MagicMock(return_value=False)

    # Mock notification manager
    service.notification_manager = MagicMock()
    service.notification_manager.ha_client = MagicMock()

    # Mock healing manager
    service.healing_manager = MagicMock()
    service.healing_manager._failure_count = {}

    return service


@pytest.fixture
def client(mock_service):
    """Create test client with mocked service."""
    # Patch both the module-level _service and get_service function
    with patch("ha_boss.api.app._service", mock_service):
        with patch("ha_boss.api.app.get_service", return_value=mock_service):
            with patch("ha_boss.api.dependencies.get_service", return_value=mock_service):
                with patch("ha_boss.api.routes.status.get_service", return_value=mock_service):
                    with patch("ha_boss.api.app.load_config") as mock_load_config:
                        mock_load_config.return_value = mock_service.config
                        app = create_app()
                        yield TestClient(app)


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
    assert data["monitored_entities"] == 2  # Updated to match mock (sensor.test + sensor.test2)


def test_health_endpoint_healthy(client, mock_service):
    """Test /api/health endpoint when all components are healthy."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "2.0.0"
    assert "critical" in data
    assert "essential" in data
    assert "operational" in data
    assert "healing" in data
    assert "intelligence" in data
    assert "performance" in data
    assert "summary" in data

    # Check critical tier components
    assert data["critical"]["service_state"]["status"] == "healthy"
    assert data["critical"]["ha_rest_connection"]["status"] == "healthy"
    assert data["critical"]["database_accessible"]["status"] == "healthy"
    assert data["critical"]["configuration_valid"]["status"] == "healthy"

    # Check essential tier components
    assert data["essential"]["websocket_connected"]["status"] == "healthy"
    assert data["essential"]["state_tracker_initialized"]["status"] == "healthy"

    # Check summary
    assert data["summary"]["healthy"] > 0
    assert data["summary"]["unhealthy"] == 0


def test_health_endpoint_degraded(client, mock_service):
    """Test /api/health endpoint when service is degraded (WebSocket down)."""
    mock_service.websocket_client.is_connected.return_value = False

    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "degraded"

    # Critical tier should still be healthy
    assert data["critical"]["service_state"]["status"] == "healthy"
    assert data["critical"]["ha_rest_connection"]["status"] == "healthy"

    # Essential tier should have degraded component
    assert data["essential"]["websocket_connected"]["status"] == "degraded"


def test_health_endpoint_unhealthy(client, mock_service):
    """Test /api/health endpoint when service is unhealthy."""
    mock_service.state = "stopped"

    response = client.get("/api/health")
    assert response.status_code == 503  # Changed to 503 for unhealthy

    data = response.json()
    assert data["status"] == "unhealthy"

    # Critical tier should have unhealthy component
    assert data["critical"]["service_state"]["status"] == "unhealthy"


def test_health_tier_isolation(client, mock_service):
    """Test that Tier 5 (intelligence) doesn't affect overall health status."""
    # Disable intelligence components
    mock_service.config.intelligence.ollama_enabled = False
    mock_service.config.intelligence.claude_enabled = False

    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    # Should still be healthy even with Tier 5 components unknown/unavailable
    assert data["status"] == "healthy"

    # Intelligence components can be unknown
    assert data["intelligence"]["ollama_available"]["status"] in ("unknown", "degraded")
    assert data["intelligence"]["claude_available"]["status"] in ("unknown", "degraded")


def test_health_circuit_breaker_degradation(client, mock_service):
    """Test that high circuit breaker count causes degraded status."""
    # Mock >50% of integrations with circuit breakers open
    mock_service.healing_manager._failure_count = {
        "integration1": 5,  # Over threshold (3)
        "integration2": 5,  # Over threshold
        "integration3": 1,  # Under threshold
    }

    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "degraded"

    # Circuit breaker component should be degraded
    assert data["healing"]["circuit_breakers_operational"]["status"] == "degraded"


def test_health_response_structure(client, mock_service):
    """Test that health response has all required fields and structure."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()

    # Top-level fields
    assert "status" in data
    assert "timestamp" in data
    assert "version" in data

    # All tier fields present
    for tier in ["critical", "essential", "operational", "healing", "intelligence"]:
        assert tier in data
        assert isinstance(data[tier], dict)

        # Each component has required fields
        for _component_name, component in data[tier].items():
            assert "status" in component
            assert "message" in component
            assert "details" in component
            assert component["status"] in ("healthy", "degraded", "unhealthy", "unknown")

    # Performance and summary
    assert "performance" in data
    assert "uptime_seconds" in data["performance"]
    assert "summary" in data
    assert all(key in data["summary"] for key in ["healthy", "degraded", "unhealthy", "unknown"])


def test_health_component_details(client, mock_service):
    """Test that component details dicts are populated."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()

    # Check critical tier details
    assert "state" in data["critical"]["service_state"]["details"]
    assert "mode" in data["critical"]["service_state"]["details"]
    assert "url" in data["critical"]["ha_rest_connection"]["details"]
    assert "path" in data["critical"]["database_accessible"]["details"]

    # Check essential tier details
    assert "cached_entities" in data["essential"]["state_tracker_initialized"]["details"]
    assert "discovered_mappings" in data["essential"]["integration_discovery_complete"]["details"]


def test_health_summary_counts(client, mock_service):
    """Test that summary counts are calculated correctly."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()

    summary = data["summary"]
    total = summary["healthy"] + summary["degraded"] + summary["unhealthy"] + summary["unknown"]

    # Total should match number of components across all tiers
    tier_component_count = sum(
        len(data[tier])
        for tier in ["critical", "essential", "operational", "healing", "intelligence"]
    )
    assert total == tier_component_count

    # With healthy service, most should be healthy
    assert summary["healthy"] > summary["degraded"]
    assert summary["healthy"] > summary["unhealthy"]


def test_health_http_status_codes(client, mock_service):
    """Test HTTP status codes for different health states."""
    # Healthy = 200
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

    # Degraded = 200 (still functional)
    mock_service.websocket_client.is_connected.return_value = False
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"

    # Unhealthy = 503 (critical failure)
    mock_service.state = "stopped"
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_health_service_not_initialized(client):
    """Test health check when service is not initialized."""
    # Patch get_service to raise RuntimeError
    with patch(
        "ha_boss.api.routes.status.get_service", side_effect=RuntimeError("Service not initialized")
    ):
        response = client.get("/api/health")
        assert response.status_code == 503

        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["critical"]["service_state"]["status"] == "unhealthy"
        assert data["performance"]["uptime_seconds"] == 0.0
