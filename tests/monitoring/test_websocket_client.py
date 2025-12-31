"""Tests for Home Assistant WebSocket client."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig
from ha_boss.core.exceptions import (
    HomeAssistantAuthError,
    HomeAssistantConnectionError,
)
from ha_boss.monitoring.websocket_client import (
    WebSocketClient,
    create_websocket_client,
)


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
def ws_client(mock_config):
    """Create WebSocket client instance."""
    instance = mock_config.home_assistant.get_default_instance()
    return WebSocketClient(instance, mock_config)


@pytest.mark.asyncio
async def test_ws_client_init(mock_config):
    """Test WebSocket client initialization."""
    instance = mock_config.home_assistant.get_default_instance()
    client = WebSocketClient(instance, mock_config)
    assert client.ws_url == "ws://homeassistant.local:8123/api/websocket"
    assert client.token == "test_token"
    assert client._ws is None
    assert not client._running


@pytest.mark.asyncio
async def test_https_to_wss_conversion(mock_config):
    """Test HTTPS URL converts to WSS."""
    mock_config.home_assistant.instances[0].url = "https://homeassistant.local:8123"
    instance = mock_config.home_assistant.get_default_instance()
    client = WebSocketClient(instance, mock_config)
    assert client.ws_url == "wss://homeassistant.local:8123/api/websocket"


@pytest.mark.asyncio
async def test_connect_success(ws_client):
    """Test successful WebSocket connection and authentication."""
    mock_ws = AsyncMock()

    # Mock the authentication flow
    async def mock_recv():
        if not hasattr(mock_recv, "call_count"):
            mock_recv.call_count = 0
        mock_recv.call_count += 1
        if mock_recv.call_count == 1:
            return json.dumps({"type": "auth_required"})
        elif mock_recv.call_count == 2:
            return json.dumps({"type": "auth_ok", "ha_version": "2024.1.0"})

    mock_ws.recv = mock_recv
    mock_ws.send = AsyncMock()

    with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)):
        await ws_client.connect()

        assert ws_client._ws is not None
        # Verify auth message was sent
        calls = mock_ws.send.call_args_list
        assert len(calls) == 1
        auth_msg = json.loads(calls[0][0][0])
        assert auth_msg["type"] == "auth"
        assert auth_msg["access_token"] == "test_token"


@pytest.mark.asyncio
async def test_connect_auth_invalid(ws_client):
    """Test connection with invalid authentication."""
    mock_ws = AsyncMock()

    # Mock failed authentication
    async def mock_recv():
        if not hasattr(mock_recv, "call_count"):
            mock_recv.call_count = 0
        mock_recv.call_count += 1
        if mock_recv.call_count == 1:
            return json.dumps({"type": "auth_required"})
        elif mock_recv.call_count == 2:
            return json.dumps({"type": "auth_invalid", "message": "Invalid token"})

    mock_ws.recv = mock_recv
    mock_ws.send = AsyncMock()

    with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)):
        with pytest.raises(HomeAssistantAuthError) as exc_info:
            await ws_client.connect()

        assert "Authentication failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_connect_unexpected_message(ws_client):
    """Test connection with unexpected message."""
    mock_ws = AsyncMock()

    # Mock unexpected message instead of auth_required
    async def mock_recv():
        return json.dumps({"type": "unexpected_type"})

    mock_ws.recv = mock_recv

    with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)):
        with pytest.raises(HomeAssistantConnectionError) as exc_info:
            await ws_client.connect()

        assert "Expected auth_required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_subscribe_events(ws_client):
    """Test subscribing to events."""
    mock_ws = AsyncMock()
    ws_client._ws = mock_ws

    # Mock subscription success
    mock_ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "success": True, "type": "result"}))
    mock_ws.send = AsyncMock()

    await ws_client.subscribe_events("state_changed")

    # Verify subscription message
    calls = mock_ws.send.call_args_list
    assert len(calls) == 1
    sub_msg = json.loads(calls[0][0][0])
    assert sub_msg["type"] == "subscribe_events"
    assert sub_msg["event_type"] == "state_changed"


@pytest.mark.asyncio
async def test_subscribe_events_not_connected(ws_client):
    """Test subscribing when not connected."""
    with pytest.raises(HomeAssistantConnectionError) as exc_info:
        await ws_client.subscribe_events()

    assert "Not connected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_subscribe_events_failure(ws_client):
    """Test subscription failure."""
    mock_ws = AsyncMock()
    ws_client._ws = mock_ws

    # Mock subscription failure
    mock_ws.recv = AsyncMock(
        return_value=json.dumps({"id": 1, "success": False, "error": "Unknown event type"})
    )
    mock_ws.send = AsyncMock()

    with pytest.raises(HomeAssistantConnectionError) as exc_info:
        await ws_client.subscribe_events("invalid_event")

    assert "Failed to subscribe" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_state_changed_event(ws_client):
    """Test handling state_changed event."""
    callback_data = None

    async def on_state_changed(data):
        nonlocal callback_data
        callback_data = data

    ws_client.on_state_changed = on_state_changed

    event_message = {
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": "sensor.temperature",
                "new_state": {"state": "20.5"},
                "old_state": {"state": "20.0"},
            },
        },
    }

    await ws_client._handle_message(event_message)

    assert callback_data is not None
    assert callback_data["entity_id"] == "sensor.temperature"


@pytest.mark.asyncio
async def test_handle_pong_message(ws_client):
    """Test handling pong message."""
    # Pong messages should be silently ignored
    pong_message = {"type": "pong", "id": 1}
    await ws_client._handle_message(pong_message)
    # Should not raise any errors


@pytest.mark.asyncio
async def test_ping(ws_client):
    """Test ping functionality."""
    mock_ws = AsyncMock()
    ws_client._ws = mock_ws

    # Mock pong response
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps({"type": "pong", "id": 1}))

    result = await ws_client.ping()
    assert result is True

    # Verify ping was sent
    calls = mock_ws.send.call_args_list
    ping_msg = json.loads(calls[0][0][0])
    assert ping_msg["type"] == "ping"


@pytest.mark.asyncio
async def test_ping_timeout(ws_client):
    """Test ping timeout."""
    mock_ws = AsyncMock()
    ws_client._ws = mock_ws

    # Mock timeout
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(side_effect=TimeoutError())

    result = await ws_client.ping()
    assert result is False


@pytest.mark.asyncio
async def test_ping_not_connected(ws_client):
    """Test ping when not connected."""
    result = await ws_client.ping()
    assert result is False


@pytest.mark.asyncio
async def test_stop(ws_client):
    """Test stopping WebSocket client."""
    mock_ws = AsyncMock()
    ws_client._ws = mock_ws
    ws_client._running = True

    await ws_client.stop()

    assert not ws_client._running
    assert ws_client._ws is None
    mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_logic(ws_client):
    """Test reconnection with exponential backoff."""
    ws_client._running = True

    # Mock successful reconnection on second attempt
    attempt_count = 0

    async def mock_connect():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise HomeAssistantConnectionError("Connection failed")

    ws_client.connect = mock_connect
    ws_client.subscribe_events = AsyncMock()

    with patch("asyncio.sleep"):  # Speed up test
        with patch("asyncio.create_task"):  # Don't actually start listen loop
            await ws_client._reconnect()

    assert attempt_count == 2


@pytest.mark.asyncio
async def test_reconnect_exhaustion(ws_client):
    """Test reconnection failure after max retries."""
    ws_client._running = True
    ws_client.max_retries = 2

    # Always fail
    ws_client.connect = AsyncMock(side_effect=HomeAssistantConnectionError("Failed"))
    ws_client.subscribe_events = AsyncMock()

    with patch("asyncio.sleep"):  # Speed up test
        await ws_client._reconnect()

    # Should stop running after exhausting retries
    assert not ws_client._running


@pytest.mark.asyncio
async def test_create_websocket_client_success(mock_config):
    """Test successful client creation."""
    mock_ws = AsyncMock()

    # Mock the authentication and subscription flow
    async def mock_recv():
        if not hasattr(mock_recv, "call_count"):
            mock_recv.call_count = 0
        mock_recv.call_count += 1
        if mock_recv.call_count == 1:
            return json.dumps({"type": "auth_required"})
        elif mock_recv.call_count == 2:
            return json.dumps({"type": "auth_ok", "ha_version": "2024.1.0"})
        elif mock_recv.call_count == 3:
            return json.dumps({"id": 1, "success": True, "type": "result"})

    mock_ws.recv = mock_recv
    mock_ws.send = AsyncMock()
    mock_ws.close = AsyncMock()

    with patch("websockets.connect", new=AsyncMock(return_value=mock_ws)):
        with patch("asyncio.create_task"):  # Don't start listen loop
            client = await create_websocket_client(mock_config)
            assert client is not None
            assert client._running

            await client.stop()


@pytest.mark.asyncio
async def test_create_websocket_client_failure(mock_config):
    """Test client creation with connection failure."""
    with patch("websockets.connect", side_effect=Exception("Connection failed")):
        with pytest.raises(HomeAssistantConnectionError):
            await create_websocket_client(mock_config)


@pytest.mark.asyncio
async def test_callback_error_handling(ws_client):
    """Test that errors in callbacks don't crash the client."""

    async def failing_callback(data):
        raise ValueError("Callback error")

    ws_client.on_state_changed = failing_callback

    event_message = {
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {"entity_id": "sensor.test"},
        },
    }

    # Should not raise, just log
    await ws_client._handle_message(event_message)
