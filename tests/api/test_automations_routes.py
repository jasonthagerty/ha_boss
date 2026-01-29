"""Tests for automation desired states API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app
from ha_boss.core.database import AutomationDesiredState


@pytest.fixture
def mock_desired_states():
    """Create mock desired states for testing."""
    return [
        AutomationDesiredState(
            id=1,
            instance_id="test_instance",
            automation_id="automation.test_lights",
            entity_id="light.bedroom",
            desired_state="on",
            desired_attributes={"brightness": 255, "color_temp": 370},
            confidence=0.95,
            inference_method="ai_analysis",
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        ),
        AutomationDesiredState(
            id=2,
            instance_id="test_instance",
            automation_id="automation.test_lights",
            entity_id="switch.fan",
            desired_state="on",
            desired_attributes=None,
            confidence=0.85,
            inference_method="ai_analysis",
            created_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC),
        ),
        AutomationDesiredState(
            id=3,
            instance_id="test_instance",
            automation_id="automation.test_lights",
            entity_id="light.living_room",
            desired_state="on",
            desired_attributes={"brightness": 180},
            confidence=1.0,
            inference_method="user_annotated",
            created_at=datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC),
        ),
    ]


@pytest.fixture
def mock_service(mock_desired_states):
    """Create a mock HA Boss service with database and config."""
    service = MagicMock()

    # Mock config
    service.config = MagicMock()
    service.config.api = MagicMock()
    service.config.api.auth_enabled = False  # Disable auth for testing
    service.config.home_assistant.instances = [
        MagicMock(instance_id="test_instance", url="http://ha:8123", token="test_token")
    ]
    service.config.intelligence = MagicMock()
    service.config.intelligence.ollama_enabled = True
    service.config.intelligence.claude_enabled = False

    # Mock HA clients (multi-instance)
    mock_ha_client = AsyncMock()
    service.ha_clients = {"test_instance": mock_ha_client}

    # Mock database with async session
    service.database = MagicMock()

    # Create mock session that returns our mock desired states sorted by confidence (as SQL would)
    sorted_states = sorted(mock_desired_states, key=lambda s: s.confidence, reverse=True)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sorted_states
    mock_result.scalar_one_or_none.return_value = mock_desired_states[0]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    service.database.async_session = MagicMock(return_value=mock_session)

    return service


@pytest.fixture
def client(mock_service):
    """Create test client with mocked service."""
    with patch("ha_boss.api.app._service", mock_service):
        with patch("ha_boss.api.app.get_service", return_value=mock_service):
            with patch("ha_boss.api.dependencies.get_service", return_value=mock_service):
                with patch("ha_boss.api.routes.automations.get_service", return_value=mock_service):
                    with patch("ha_boss.api.app.load_config") as mock_load_config:
                        mock_load_config.return_value = mock_service.config
                        app = create_app()
                        yield TestClient(app)


def test_list_desired_states_success(client, mock_desired_states):
    """Test GET /api/automations/{automation_id}/desired-states returns states sorted by confidence."""
    response = client.get(
        "/api/automations/automation.test_lights/desired-states",
        params={"instance_id": "test_instance"},
    )

    assert response.status_code == 200
    data = response.json()

    # Should return 3 states
    assert len(data) == 3

    # Should be sorted by confidence descending (user_annotated=1.0 first)
    assert data[0]["entity_id"] == "light.living_room"
    assert data[0]["confidence"] == 1.0
    assert data[0]["inference_method"] == "user_annotated"

    assert data[1]["entity_id"] == "light.bedroom"
    assert data[1]["confidence"] == 0.95

    assert data[2]["entity_id"] == "switch.fan"
    assert data[2]["confidence"] == 0.85


def test_list_desired_states_instance_not_found(client):
    """Test GET /api/automations/{automation_id}/desired-states with invalid instance_id."""
    response = client.get(
        "/api/automations/automation.test_lights/desired-states",
        params={"instance_id": "invalid_instance"},
    )

    assert response.status_code == 404
    assert "Instance 'invalid_instance' not found" in response.json()["detail"]


def test_create_desired_state_success(client, mock_service):
    """Test POST /api/automations/{automation_id}/desired-states creates user-annotated state."""
    request_data = {
        "entity_id": "light.kitchen",
        "desired_state": "on",
        "desired_attributes": {"brightness": 200},
    }

    mock_session = AsyncMock()
    # Mock execute to return a result with scalar_one_or_none that returns None (no existing state)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # Mock refresh to set timestamps
    def mock_refresh(obj):
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

    mock_session.refresh = AsyncMock(side_effect=mock_refresh)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_service.database.async_session = MagicMock(return_value=mock_session)

    response = client.post(
        "/api/automations/automation.test_lights/desired-states",
        params={"instance_id": "test_instance"},
        json=request_data,
    )

    assert response.status_code == 201
    data = response.json()

    assert data["entity_id"] == "light.kitchen"
    assert data["desired_state"] == "on"
    assert data["desired_attributes"] == {"brightness": 200}
    assert data["confidence"] == 1.0
    assert data["inference_method"] == "user_annotated"


def test_create_desired_state_instance_not_found(client):
    """Test POST /api/automations/{automation_id}/desired-states with invalid instance_id."""
    request_data = {"entity_id": "light.kitchen", "desired_state": "on", "desired_attributes": {}}

    response = client.post(
        "/api/automations/automation.test_lights/desired-states",
        params={"instance_id": "invalid_instance"},
        json=request_data,
    )

    assert response.status_code == 404
    assert "Instance 'invalid_instance' not found" in response.json()["detail"]


def test_update_desired_state_success(client, mock_service, mock_desired_states):
    """Test PUT /api/automations/{automation_id}/desired-states/{entity_id} updates state."""
    update_data = {
        "desired_state": "off",
        "desired_attributes": {"brightness": 100},
        "confidence": 0.9,
    }

    # Mock session to return existing state and allow update
    existing_state = mock_desired_states[0]
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_state
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_service.database.async_session = MagicMock(return_value=mock_session)

    response = client.put(
        "/api/automations/automation.test_lights/desired-states/light.bedroom",
        params={"instance_id": "test_instance"},
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["entity_id"] == "light.bedroom"
    # State should be updated (mocked object gets updated)
    assert existing_state.desired_state == "off"
    assert existing_state.desired_attributes == {"brightness": 100}
    assert existing_state.confidence == 0.9


def test_update_desired_state_not_found(client, mock_service):
    """Test PUT /api/automations/{automation_id}/desired-states/{entity_id} with non-existent state."""
    update_data = {"desired_state": "off"}

    # Mock session to return None (state not found)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_service.database.async_session = MagicMock(return_value=mock_session)

    response = client.put(
        "/api/automations/automation.test_lights/desired-states/light.nonexistent",
        params={"instance_id": "test_instance"},
        json=update_data,
    )

    assert response.status_code == 404
    assert "Desired state not found" in response.json()["detail"]


def test_update_desired_state_instance_not_found(client):
    """Test PUT /api/automations/{automation_id}/desired-states/{entity_id} with invalid instance."""
    update_data = {"desired_state": "off"}

    response = client.put(
        "/api/automations/automation.test_lights/desired-states/light.bedroom",
        params={"instance_id": "invalid_instance"},
        json=update_data,
    )

    assert response.status_code == 404
    assert "Instance 'invalid_instance' not found" in response.json()["detail"]


def test_delete_desired_state_success(client, mock_service, mock_desired_states):
    """Test DELETE /api/automations/{automation_id}/desired-states/{entity_id} removes state."""
    # Mock session to execute delete statement
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1  # One row deleted
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_service.database.async_session = MagicMock(return_value=mock_session)

    response = client.delete(
        "/api/automations/automation.test_lights/desired-states/light.bedroom",
        params={"instance_id": "test_instance"},
    )

    assert response.status_code == 204
    # Verify execute was called
    mock_session.execute.assert_called_once()


def test_delete_desired_state_not_found(client, mock_service):
    """Test DELETE /api/automations/{automation_id}/desired-states/{entity_id} with non-existent state."""
    # Mock session to execute delete but return no rows deleted
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 0  # No rows deleted
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_service.database.async_session = MagicMock(return_value=mock_session)

    response = client.delete(
        "/api/automations/automation.test_lights/desired-states/light.nonexistent",
        params={"instance_id": "test_instance"},
    )

    assert response.status_code == 404
    assert "Desired state not found" in response.json()["detail"]


def test_delete_desired_state_instance_not_found(client):
    """Test DELETE /api/automations/{automation_id}/desired-states/{entity_id} with invalid instance."""
    response = client.delete(
        "/api/automations/automation.test_lights/desired-states/light.bedroom",
        params={"instance_id": "invalid_instance"},
    )

    assert response.status_code == 404
    assert "Instance 'invalid_instance' not found" in response.json()["detail"]


def test_infer_states_success_with_save(client, mock_service):
    """Test POST /api/automations/{automation_id}/infer-states with save=true."""

    # Mock DesiredStateInference service - use objects instead of dicts
    class MockInferredState:
        def __init__(self, entity_id, desired_state, desired_attributes, confidence):
            self.entity_id = entity_id
            self.desired_state = desired_state
            self.desired_attributes = desired_attributes
            self.confidence = confidence

    mock_inference_result = [
        MockInferredState(
            entity_id="light.bedroom",
            desired_state="on",
            desired_attributes={"brightness": 255},
            confidence=0.95,
        ),
        MockInferredState(
            entity_id="switch.fan",
            desired_state="on",
            desired_attributes=None,
            confidence=0.85,
        ),
    ]

    # Setup mock ha_client to return automation state
    mock_ha_client = AsyncMock()
    mock_automation_state = MagicMock()
    mock_automation_state.get.return_value = {"action": [{"service": "light.turn_on"}]}
    mock_ha_client.get_state = AsyncMock(return_value=mock_automation_state)
    mock_service.ha_clients = {"test_instance": mock_ha_client}

    with patch(
        "ha_boss.automation.desired_state_inference.DesiredStateInference"
    ) as mock_dsi_class:
        mock_dsi = AsyncMock()
        mock_dsi.infer_from_automation = AsyncMock(return_value=mock_inference_result)
        mock_dsi_class.return_value = mock_dsi

        response = client.post(
            "/api/automations/automation.test_lights/infer-states",
            params={"instance_id": "test_instance", "save": True},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data) == 2
        assert data[0]["entity_id"] == "light.bedroom"
        assert data[0]["desired_state"] == "on"
        assert data[0]["confidence"] == 0.95

        # Verify DesiredStateInference was instantiated and called
        mock_dsi_class.assert_called_once()
        mock_dsi.infer_from_automation.assert_called_once_with(
            automation_id="automation.test_lights",
            automation_config={"action": [{"service": "light.turn_on"}]},
            use_cache=False,
        )


def test_infer_states_success_without_save(client, mock_service):
    """Test POST /api/automations/{automation_id}/infer-states with save=false."""
    # Mock fetching automation config from HA
    mock_automation_config = {
        "id": "test_lights",
        "alias": "Test Lights",
        "trigger": [{"platform": "state"}],
        "action": [{"service": "light.turn_on"}],
    }

    # Mock inference result as dict objects (as they come from the service)
    class MockInferredState:
        def __init__(self, entity_id, desired_state, desired_attributes, confidence):
            self.entity_id = entity_id
            self.desired_state = desired_state
            self.desired_attributes = desired_attributes
            self.confidence = confidence

    mock_inference_result = [
        MockInferredState(
            entity_id="light.bedroom",
            desired_state="on",
            desired_attributes={"brightness": 255},
            confidence=0.95,
        ),
    ]

    # Mock HA client - get_state returns a dict-like object with get method
    mock_ha_client = AsyncMock()
    mock_state = MagicMock()
    mock_state.get.return_value = {"id": "test_lights", **mock_automation_config}
    mock_ha_client.get_state = AsyncMock(return_value=mock_state)
    mock_service.ha_clients = {"test_instance": mock_ha_client}

    with patch(
        "ha_boss.automation.desired_state_inference.DesiredStateInference"
    ) as mock_dsi_class:
        mock_dsi = AsyncMock()
        mock_dsi.infer_from_automation = AsyncMock(return_value=mock_inference_result)
        mock_dsi_class.return_value = mock_dsi

        response = client.post(
            "/api/automations/automation.test_lights/infer-states",
            params={"instance_id": "test_instance", "save": False},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data) == 1
        assert data[0]["entity_id"] == "light.bedroom"

        # Verify automation config was fetched and passed
        mock_ha_client.get_state.assert_called_once_with("automation.test_lights")
        mock_dsi.infer_from_automation.assert_called_once()
        call_kwargs = mock_dsi.infer_from_automation.call_args[1]
        assert call_kwargs["automation_config"] is not None
        assert call_kwargs["use_cache"] is False


def test_infer_states_instance_not_found(client):
    """Test POST /api/automations/{automation_id}/infer-states with invalid instance_id."""
    response = client.post(
        "/api/automations/automation.test_lights/infer-states",
        params={"instance_id": "invalid_instance"},
    )

    assert response.status_code == 404
    assert "Instance 'invalid_instance' not found" in response.json()["detail"]


def test_infer_states_ai_not_configured(client, mock_service):
    """Test POST /api/automations/{automation_id}/infer-states when AI is not configured."""
    # Disable both Ollama and Claude
    mock_service.config.intelligence = MagicMock()
    mock_service.config.intelligence.ollama_enabled = False
    mock_service.config.intelligence.claude_enabled = False

    # Setup mock ha_client to return automation state
    mock_ha_client = AsyncMock()
    mock_automation_state = MagicMock()
    mock_automation_state.get.return_value = {"action": [{"service": "light.turn_on"}]}
    mock_ha_client.get_state = AsyncMock(return_value=mock_automation_state)
    mock_service.ha_clients = {"test_instance": mock_ha_client}

    response = client.post(
        "/api/automations/automation.test_lights/infer-states",
        params={"instance_id": "test_instance"},
    )

    assert response.status_code == 503
    assert "AI features not configured" in response.json()["detail"]


def test_infer_states_automation_not_found(client, mock_service):
    """Test POST /api/automations/{automation_id}/infer-states when automation doesn't exist."""
    # Mock HA client to raise exception (automation not found)
    from ha_boss.core.exceptions import HomeAssistantError

    mock_ha_client = AsyncMock()
    mock_ha_client.get_state = AsyncMock(side_effect=HomeAssistantError("Not found"))
    mock_service.ha_clients = {"test_instance": mock_ha_client}

    response = client.post(
        "/api/automations/automation.nonexistent/infer-states",
        params={"instance_id": "test_instance", "save": False},
    )

    assert response.status_code == 404
    assert (
        "Automation 'automation.nonexistent' not found or inaccessible" in response.json()["detail"]
    )


def test_infer_states_internal_error(client, mock_service):
    """Test POST /api/automations/{automation_id}/infer-states handles internal errors."""
    # Setup mock ha_client to return automation state
    mock_ha_client = AsyncMock()
    mock_automation_state = MagicMock()
    mock_automation_state.get.return_value = {"action": [{"service": "light.turn_on"}]}
    mock_ha_client.get_state = AsyncMock(return_value=mock_automation_state)
    mock_service.ha_clients = {"test_instance": mock_ha_client}

    with patch(
        "ha_boss.automation.desired_state_inference.DesiredStateInference"
    ) as mock_dsi_class:
        mock_dsi = AsyncMock()
        mock_dsi.infer_from_automation = AsyncMock(side_effect=Exception("Internal error"))
        mock_dsi_class.return_value = mock_dsi

        response = client.post(
            "/api/automations/automation.test_lights/infer-states",
            params={"instance_id": "test_instance"},
        )

        assert response.status_code == 500
        assert "Failed to infer desired states" in response.json()["detail"]
