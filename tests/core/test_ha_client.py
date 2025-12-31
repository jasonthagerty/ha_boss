"""Tests for Home Assistant API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from ha_boss.core.config import Config, HomeAssistantConfig
from ha_boss.core.exceptions import (
    HomeAssistantAPIError,
    HomeAssistantAuthError,
    HomeAssistantConnectionError,
)
from ha_boss.core.ha_client import HomeAssistantClient, create_ha_client


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        )
    )


@pytest.fixture
def client(mock_config):
    """Create HA client instance."""
    instance = mock_config.home_assistant.get_default_instance()
    return HomeAssistantClient(instance, mock_config)


@pytest.mark.asyncio
async def test_client_init(mock_config):
    """Test client initialization."""
    instance = mock_config.home_assistant.get_default_instance()
    client = HomeAssistantClient(instance, mock_config)
    assert client.base_url == "http://homeassistant.local:8123"
    assert client.token == "test_token"
    assert client._session is None


@pytest.mark.asyncio
async def test_ensure_session(client):
    """Test session creation."""
    await client._ensure_session()
    assert client._session is not None
    assert not client._session.closed


@pytest.mark.asyncio
async def test_close_session(client):
    """Test session cleanup."""
    await client._ensure_session()
    assert client._session is not None

    await client.close()
    assert client._session is None


@pytest.mark.asyncio
async def test_context_manager(mock_config):
    """Test async context manager."""
    instance = mock_config.home_assistant.get_default_instance()
    async with HomeAssistantClient(instance, mock_config) as client:
        assert client._session is not None
        assert not client._session.closed

    # Session should be closed after context exit
    assert client._session is None


@pytest.mark.asyncio
async def test_check_connection_success(client):
    """Test successful connection check."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value={"message": "API running."})
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        result = await client.check_connection()
        assert result is True


@pytest.mark.asyncio
async def test_auth_error(client):
    """Test authentication error handling."""
    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    await client._ensure_session()
    client._session.request = MagicMock(return_value=mock_response)

    with pytest.raises(HomeAssistantAuthError) as exc_info:
        await client.check_connection()

    assert "Authentication failed" in str(exc_info.value)

    await client.close()


@pytest.mark.asyncio
async def test_not_found_error(client):
    """Test 404 error handling."""
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    await client._ensure_session()
    client._session.request = MagicMock(return_value=mock_response)

    with pytest.raises(HomeAssistantAPIError) as exc_info:
        await client._request("GET", "/api/nonexistent")

    assert "not found" in str(exc_info.value)

    await client.close()


@pytest.mark.asyncio
async def test_get_states(client):
    """Test getting all entity states."""
    mock_states = [
        {"entity_id": "sensor.temperature", "state": "20.5"},
        {"entity_id": "light.living_room", "state": "on"},
    ]

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value=mock_states)
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        states = await client.get_states()
        assert len(states) == 2
        assert states[0]["entity_id"] == "sensor.temperature"


@pytest.mark.asyncio
async def test_get_state(client):
    """Test getting specific entity state."""
    mock_state = {
        "entity_id": "sensor.temperature",
        "state": "20.5",
        "attributes": {"unit_of_measurement": "°C"},
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value=mock_state)
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        state = await client.get_state("sensor.temperature")
        assert state["entity_id"] == "sensor.temperature"
        assert state["state"] == "20.5"


@pytest.mark.asyncio
async def test_set_state(client):
    """Test setting entity state."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value={"entity_id": "sensor.test", "state": "42"})
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        result = await client.set_state("sensor.test", "42", attributes={"unit": "answer"})
        assert result["state"] == "42"


@pytest.mark.asyncio
async def test_call_service(client):
    """Test calling a service."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value=[])
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        await client.call_service("light", "turn_on", {"entity_id": "light.living_room"})

        # Verify the request was made to correct endpoint
        call_args = client._session.request.call_args
        assert "/api/services/light/turn_on" in str(call_args)


@pytest.mark.asyncio
async def test_reload_integration(client):
    """Test reloading integration."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value=[])
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        await client.reload_integration("abc123")

        # Verify correct service call
        call_args = client._session.request.call_args
        assert "/api/services/homeassistant/reload_config_entry" in str(call_args)


@pytest.mark.asyncio
async def test_create_persistent_notification(client):
    """Test creating notification."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.json = AsyncMock(return_value=[])
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        await client.create_persistent_notification(
            "Test message", title="Test Title", notification_id="test_id"
        )

        # Verify correct endpoint
        call_args = client._session.request.call_args
        assert "/api/services/persistent_notification/create" in str(call_args)


@pytest.mark.asyncio
async def test_retry_logic(client, caplog):
    """Test exponential backoff retry logic."""
    # Mock to fail twice then succeed
    call_count = 0

    async def mock_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ClientError("Connection failed")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content_type = "application/json"
        mock_response.json = AsyncMock(return_value={"message": "success"})
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mock_response_obj = AsyncMock()
    mock_response_obj.__aenter__ = mock_request
    mock_response_obj.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response_obj)

        # Should succeed after retries
        with patch("asyncio.sleep"):  # Speed up test
            result = await client._request("GET", "/api/")
            assert result["message"] == "success"
            assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhaustion(client):
    """Test retry exhaustion raises error."""
    mock_response = AsyncMock()
    mock_response.__aenter__ = AsyncMock(side_effect=ClientError("Connection failed"))
    mock_response.__aexit__ = AsyncMock()

    with patch.object(client, "_ensure_session"):
        client._session = AsyncMock()
        client._session.request = MagicMock(return_value=mock_response)

        with patch("asyncio.sleep"):  # Speed up test
            with pytest.raises(HomeAssistantConnectionError) as exc_info:
                await client._request("GET", "/api/")

            assert "Failed to connect" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_ha_client_success(mock_config):
    """Test successful client creation."""
    with patch.object(HomeAssistantClient, "check_connection", return_value=True):
        client = await create_ha_client(mock_config)
        assert client is not None
        await client.close()


@pytest.mark.asyncio
async def test_create_ha_client_failure(mock_config):
    """Test client creation with connection failure."""
    with patch.object(
        HomeAssistantClient, "check_connection", side_effect=HomeAssistantConnectionError("Failed")
    ):
        with patch.object(HomeAssistantClient, "close"):
            with pytest.raises(HomeAssistantConnectionError):
                await create_ha_client(mock_config)


@pytest.mark.asyncio
async def test_create_automation_success(client):
    """Test successful automation creation."""
    automation_config = {
        "alias": "Test Automation",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion"}],
        "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}],
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"alias": "Test Automation"})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.closed = False
    mock_session.post = MagicMock(return_value=mock_response)

    client._session = mock_session

    result = await client.create_automation(automation_config)

    assert "id" in result
    assert result["alias"] == "Test Automation"


@pytest.mark.asyncio
async def test_create_automation_missing_alias(client):
    """Test automation creation with missing alias."""
    automation_config = {
        "trigger": [{"platform": "state"}],
        "action": [{"service": "light.turn_on"}],
    }

    with pytest.raises(ValueError, match="alias"):
        await client.create_automation(automation_config)


@pytest.mark.asyncio
async def test_create_automation_missing_trigger(client):
    """Test automation creation with missing trigger."""
    automation_config = {
        "alias": "Test",
        "action": [{"service": "light.turn_on"}],
    }

    with pytest.raises(ValueError, match="trigger"):
        await client.create_automation(automation_config)


@pytest.mark.asyncio
async def test_create_automation_missing_action(client):
    """Test automation creation with missing action."""
    automation_config = {
        "alias": "Test",
        "trigger": [{"platform": "state"}],
    }

    with pytest.raises(ValueError, match="action"):
        await client.create_automation(automation_config)


@pytest.mark.asyncio
async def test_create_automation_invalid_config(client):
    """Test automation creation with invalid configuration."""
    automation_config = {
        "alias": "Test Automation",
        "trigger": [{"platform": "state"}],
        "action": [{"service": "light.turn_on"}],
    }

    mock_response = AsyncMock()
    mock_response.status = 400
    mock_response.text = AsyncMock(return_value="Invalid automation configuration")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.closed = False
    mock_session.post = MagicMock(return_value=mock_response)

    client._session = mock_session

    with pytest.raises(HomeAssistantAPIError, match="Invalid automation configuration"):
        await client.create_automation(automation_config)


@pytest.mark.asyncio
async def test_create_automation_api_error(client):
    """Test automation creation with API error."""
    automation_config = {
        "alias": "Test Automation",
        "trigger": [{"platform": "state"}],
        "action": [{"service": "light.turn_on"}],
    }

    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Internal server error")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.closed = False
    mock_session.post = MagicMock(return_value=mock_response)

    client._session = mock_session

    with pytest.raises(HomeAssistantAPIError, match="Failed to create automation"):
        await client.create_automation(automation_config)
