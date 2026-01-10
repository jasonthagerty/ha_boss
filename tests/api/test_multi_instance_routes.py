"""Tests for multi-instance API functionality.

Tests that API routes properly support multiple Home Assistant instances:
- Instance listing endpoint
- Instance_id parameter handling
- Instance validation and 404 responses
- Per-instance component isolation
- Statistics separation between instances
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app


@pytest.fixture
def mock_multi_instance_service():
    """Create a mock HA Boss service with multiple instances configured."""
    service = MagicMock()
    service.state = "running"
    service.start_time = datetime.now(UTC)

    # Multi-instance statistics (separate dicts for each instance)
    service.health_checks_performed = {"default": 100, "home": 50, "vacation": 25}
    service.healings_attempted = {"default": 10, "home": 5, "vacation": 2}
    service.healings_succeeded = {"default": 8, "home": 4, "vacation": 2}
    service.healings_failed = {"default": 2, "home": 1, "vacation": 0}

    # Mock config
    service.config = MagicMock()
    service.config.api.auth_enabled = False
    service.config.api.cors_enabled = True
    service.config.api.cors_origins = ["*"]

    # Create multiple HA clients (one per instance)
    default_client = MagicMock()
    default_client._session = MagicMock()
    default_client._session.closed = False
    default_client.base_url = "http://ha-default:8123"

    home_client = MagicMock()
    home_client._session = MagicMock()
    home_client._session.closed = False
    home_client.base_url = "http://ha-home:8123"

    vacation_client = MagicMock()
    vacation_client._session = MagicMock()
    vacation_client._session.closed = False
    vacation_client.base_url = "http://ha-vacation:8123"

    service.ha_clients = {
        "default": default_client,
        "home": home_client,
        "vacation": vacation_client,
    }

    # Create multiple WebSocket clients
    default_ws = MagicMock()
    default_ws.is_connected = MagicMock(return_value=True)
    default_ws._running = True

    home_ws = MagicMock()
    home_ws.is_connected = MagicMock(return_value=True)
    home_ws._running = True

    vacation_ws = MagicMock()
    vacation_ws.is_connected = MagicMock(return_value=False)  # Disconnected instance
    vacation_ws._running = False

    service.websocket_clients = {
        "default": default_ws,
        "home": home_ws,
        "vacation": vacation_ws,
    }

    # Create multiple state trackers
    default_tracker = MagicMock()
    default_tracker._cache = {"sensor.temp": MagicMock()}
    default_tracker.get_all_states = AsyncMock(return_value={"sensor.temp": MagicMock()})

    home_tracker = MagicMock()
    home_tracker._cache = {"sensor.humidity": MagicMock()}
    home_tracker.get_all_states = AsyncMock(return_value={"sensor.humidity": MagicMock()})

    vacation_tracker = MagicMock()
    vacation_tracker._cache = {"sensor.motion": MagicMock()}
    vacation_tracker.get_all_states = AsyncMock(return_value={"sensor.motion": MagicMock()})

    service.state_trackers = {
        "default": default_tracker,
        "home": home_tracker,
        "vacation": vacation_tracker,
    }

    # Create per-instance components
    service.health_monitors = {
        "default": MagicMock(_running=True),
        "home": MagicMock(_running=True),
        "vacation": MagicMock(_running=True),
    }

    service.healing_managers = {
        "default": MagicMock(_failure_count={}),
        "home": MagicMock(_failure_count={}),
        "vacation": MagicMock(_failure_count={}),
    }

    service.notification_managers = {
        "default": MagicMock(),
        "home": MagicMock(),
        "vacation": MagicMock(),
    }

    service.integration_discoveries = {
        "default": MagicMock(),
        "home": MagicMock(),
        "vacation": MagicMock(),
    }

    service.entity_discoveries = {
        "default": MagicMock(),
        "home": MagicMock(),
        "vacation": MagicMock(),
    }

    service.pattern_collectors = {
        "default": MagicMock(),
        "home": MagicMock(),
        "vacation": MagicMock(),
    }

    # Mock database
    service.database = MagicMock()
    service.database.engine = MagicMock()

    return service


@pytest.fixture
def multi_instance_client(mock_multi_instance_service):
    """Create test client with multi-instance service."""
    with patch("ha_boss.api.app._service", mock_multi_instance_service):
        with patch("ha_boss.api.app.get_service", return_value=mock_multi_instance_service):
            with patch(
                "ha_boss.api.dependencies.get_service", return_value=mock_multi_instance_service
            ):
                with patch(
                    "ha_boss.api.routes.status.get_service",
                    return_value=mock_multi_instance_service,
                ):
                    with patch(
                        "ha_boss.api.routes.monitoring.get_service",
                        return_value=mock_multi_instance_service,
                    ):
                        with patch("ha_boss.api.app.load_config") as mock_load_config:
                            mock_load_config.return_value = mock_multi_instance_service.config
                            app = create_app()
                            yield TestClient(app)


# ==================== Instance Listing Tests ====================


def test_list_instances_returns_all_configured(multi_instance_client):
    """Test that GET /api/instances returns all configured instances."""
    response = multi_instance_client.get("/api/instances")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 3
    assert isinstance(data, list)

    # Check instance IDs are present
    instance_ids = [inst["instance_id"] for inst in data]
    assert "default" in instance_ids
    assert "home" in instance_ids
    assert "vacation" in instance_ids


def test_list_instances_includes_connection_state(multi_instance_client):
    """Test that instance list includes connection state."""
    response = multi_instance_client.get("/api/instances")
    assert response.status_code == 200

    data = response.json()
    instances_by_id = {inst["instance_id"]: inst for inst in data}

    # Check default and home are connected
    assert instances_by_id["default"]["websocket_connected"] is True
    assert instances_by_id["default"]["state"] == "connected"

    assert instances_by_id["home"]["websocket_connected"] is True
    assert instances_by_id["home"]["state"] == "connected"

    # Check vacation is disconnected
    assert instances_by_id["vacation"]["websocket_connected"] is False
    assert instances_by_id["vacation"]["state"] == "disconnected"


def test_list_instances_includes_urls(multi_instance_client):
    """Test that instance list includes HA URLs."""
    response = multi_instance_client.get("/api/instances")
    assert response.status_code == 200

    data = response.json()
    instances_by_id = {inst["instance_id"]: inst for inst in data}

    assert instances_by_id["default"]["url"] == "http://ha-default:8123"
    assert instances_by_id["home"]["url"] == "http://ha-home:8123"
    assert instances_by_id["vacation"]["url"] == "http://ha-vacation:8123"


# ==================== Instance Parameter Tests ====================


def test_status_endpoint_defaults_to_default_instance(multi_instance_client):
    """Test that /api/status without instance_id uses default instance."""
    response = multi_instance_client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    # Should show statistics for default instance
    assert data["health_checks_performed"] == 100
    assert data["healings_attempted"] == 10


def test_status_endpoint_accepts_instance_id_parameter(multi_instance_client):
    """Test that /api/status accepts instance_id parameter."""
    response = multi_instance_client.get("/api/status?instance_id=home")
    assert response.status_code == 200

    data = response.json()
    # Should show statistics for home instance
    assert data["health_checks_performed"] == 50
    assert data["healings_attempted"] == 5


def test_status_endpoint_returns_404_for_invalid_instance(multi_instance_client):
    """Test that /api/status returns 404 for non-existent instance."""
    response = multi_instance_client.get("/api/status?instance_id=nonexistent")
    assert response.status_code == 404

    data = response.json()
    assert "nonexistent" in data["detail"]
    assert "Available instances" in data["detail"]


def test_multiple_instances_have_different_statistics(multi_instance_client):
    """Test that different instances have independent statistics."""
    # Get default instance stats
    default_response = multi_instance_client.get("/api/status?instance_id=default")
    assert default_response.status_code == 200
    default_data = default_response.json()

    # Get home instance stats
    home_response = multi_instance_client.get("/api/status?instance_id=home")
    assert home_response.status_code == 200
    home_data = home_response.json()

    # Get vacation instance stats
    vacation_response = multi_instance_client.get("/api/status?instance_id=vacation")
    assert vacation_response.status_code == 200
    vacation_data = vacation_response.json()

    # Verify statistics are different for each instance
    assert default_data["health_checks_performed"] == 100
    assert home_data["health_checks_performed"] == 50
    assert vacation_data["health_checks_performed"] == 25

    assert default_data["healings_attempted"] == 10
    assert home_data["healings_attempted"] == 5
    assert vacation_data["healings_attempted"] == 2


# ==================== Component Isolation Tests ====================


def test_health_endpoint_validates_instance_exists(multi_instance_client):
    """Test that /api/health validates instance exists."""
    # Valid instance
    response = multi_instance_client.get("/api/health?instance_id=home")
    assert response.status_code == 200

    # Invalid instance
    response = multi_instance_client.get("/api/health?instance_id=invalid")
    assert response.status_code == 404


def test_health_endpoint_checks_per_instance_components(multi_instance_client):
    """Test that /api/health checks components for specified instance."""
    response = multi_instance_client.get("/api/health?instance_id=default")
    assert response.status_code == 200

    data = response.json()
    # Should check components for default instance
    assert data["status"] in ["healthy", "degraded", "unhealthy"]


# ==================== Error Message Consistency Tests ====================


def test_error_messages_list_available_instances(multi_instance_client):
    """Test that 404 errors list available instances."""
    response = multi_instance_client.get("/api/status?instance_id=invalid")
    assert response.status_code == 404

    data = response.json()
    detail = data["detail"]

    # Should list all available instances
    assert "default" in detail
    assert "home" in detail
    assert "vacation" in detail


def test_all_endpoints_use_consistent_validation(multi_instance_client):
    """Test that all endpoints use consistent instance validation."""
    endpoints_to_test = [
        "/api/status?instance_id=invalid",
        "/api/health?instance_id=invalid",
    ]

    for endpoint in endpoints_to_test:
        response = multi_instance_client.get(endpoint)
        assert response.status_code == 404, f"Endpoint {endpoint} should return 404"

        data = response.json()
        # All should use ha_clients.keys() for available instances
        assert "Available instances" in data["detail"] or "not found" in data["detail"]


# ==================== Backward Compatibility Tests ====================


def test_backward_compatibility_no_instance_param(multi_instance_client):
    """Test that omitting instance_id parameter works (backward compatibility)."""
    # These should all default to "default" instance
    endpoints = [
        "/api/status",
        "/api/health",
        "/api/instances",
    ]

    for endpoint in endpoints:
        response = multi_instance_client.get(endpoint)
        # Should not fail - defaults to "default" instance or lists all
        assert response.status_code in [200, 503], f"Endpoint {endpoint} failed"


def test_explicit_default_instance_same_as_omitted(multi_instance_client):
    """Test that explicit instance_id=default gives same result as omitting it."""
    # Get status without instance_id
    response_implicit = multi_instance_client.get("/api/status")
    assert response_implicit.status_code == 200
    data_implicit = response_implicit.json()

    # Get status with explicit instance_id=default
    response_explicit = multi_instance_client.get("/api/status?instance_id=default")
    assert response_explicit.status_code == 200
    data_explicit = response_explicit.json()

    # Both should return same data
    assert data_implicit["health_checks_performed"] == data_explicit["health_checks_performed"]
    assert data_implicit["healings_attempted"] == data_explicit["healings_attempted"]
