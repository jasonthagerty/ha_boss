"""Tests for WebSocket functionality."""

from unittest.mock import MagicMock

import pytest
from fastapi import WebSocket

from ha_boss.api.websocket_manager import WebSocketManager


class TestWebSocketManager:
    """Test WebSocket manager functionality."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self) -> None:
        """Test connecting and disconnecting WebSocket clients."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)

        async def mock_send(data: dict) -> None:
            pass

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Check connection is tracked
        assert ws in manager._connections
        assert manager._connections[ws]["instance_id"] == "default"
        assert "default" in manager._instance_subscriptions
        assert ws in manager._instance_subscriptions["default"]

        # Disconnect
        await manager.disconnect(ws)

        # Check connection is removed
        assert ws not in manager._connections
        assert ws not in manager._instance_subscriptions.get("default", set())

    @pytest.mark.asyncio
    async def test_broadcast_entity_state(self) -> None:
        """Test broadcasting entity state changes."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)
        send_calls = []

        async def mock_send(data: dict) -> None:
            send_calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Broadcast entity state
        await manager.broadcast_entity_state(
            instance_id="default",
            entity_id="sensor.test",
            state={"state": "on", "last_updated": "2024-01-01T00:00:00Z"},
        )

        # Check message was sent
        assert len(send_calls) == 2  # 1 for connect, 1 for broadcast
        state_msg = send_calls[1]
        assert state_msg["type"] == "entity_state_changed"
        assert state_msg["instance_id"] == "default"
        assert state_msg["entity_id"] == "sensor.test"

    @pytest.mark.asyncio
    async def test_broadcast_health_status(self) -> None:
        """Test broadcasting health status updates."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)
        send_calls = []

        async def mock_send(data: dict) -> None:
            send_calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Broadcast health status
        await manager.broadcast_health_status(
            instance_id="default",
            health={
                "entity_id": "sensor.test",
                "issue_type": "unavailable",
                "detected_at": "2024-01-01T00:00:00Z",
            },
        )

        # Check message was sent
        assert len(send_calls) == 2  # 1 for connect, 1 for broadcast
        health_msg = send_calls[1]
        assert health_msg["type"] == "health_status"
        assert health_msg["instance_id"] == "default"

    @pytest.mark.asyncio
    async def test_broadcast_healing_action(self) -> None:
        """Test broadcasting healing actions."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)
        send_calls = []

        async def mock_send(data: dict) -> None:
            send_calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Update subscriptions to include healing
        await manager.update_subscription(ws, {"status", "entities", "health", "healing"})

        # Broadcast healing action
        await manager.broadcast_healing_action(
            instance_id="default",
            action={
                "entity_id": "sensor.test",
                "action": "heal",
                "success": True,
                "timestamp": "2024-01-01T00:00:00Z",
            },
        )

        # Check message was sent
        assert len(send_calls) == 2  # 1 for connect, 1 for broadcast
        action_msg = send_calls[1]
        assert action_msg["type"] == "healing_action"
        assert action_msg["instance_id"] == "default"

    @pytest.mark.asyncio
    async def test_broadcast_instance_connection(self) -> None:
        """Test broadcasting instance connection status."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)
        send_calls = []

        async def mock_send(data: dict) -> None:
            send_calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Broadcast instance connection
        await manager.broadcast_instance_connection(
            instance_id="default",
            connected=True,
        )

        # Check message was sent
        assert len(send_calls) == 2  # 1 for connect, 1 for broadcast
        conn_msg = send_calls[1]
        assert conn_msg["type"] == "instance_connection"
        assert conn_msg["instance_id"] == "default"
        assert conn_msg["connected"] is True

    @pytest.mark.asyncio
    async def test_instance_isolation(self) -> None:
        """Test that broadcasts only go to subscribed instances."""
        manager = WebSocketManager()

        # Mock WebSockets for different instances
        ws_default = MagicMock(spec=WebSocket)
        ws_home = MagicMock(spec=WebSocket)

        default_calls = []
        home_calls = []

        async def mock_send_default(data: dict) -> None:
            default_calls.append(data)

        async def mock_send_home(data: dict) -> None:
            home_calls.append(data)

        ws_default.send_json = mock_send_default
        ws_home.send_json = mock_send_home

        # Connect to different instances
        await manager.connect(ws_default, "default")
        await manager.connect(ws_home, "home")

        # Broadcast to default instance
        await manager.broadcast_entity_state(
            instance_id="default",
            entity_id="sensor.test",
            state={"state": "on"},
        )

        # Check only default received the message
        assert len(default_calls) == 2  # connect + broadcast
        assert len(home_calls) == 1  # only connect
        assert default_calls[1]["type"] == "entity_state_changed"

    @pytest.mark.asyncio
    async def test_update_subscription(self) -> None:
        """Test updating client subscriptions."""
        manager = WebSocketManager()

        # Mock WebSocket
        ws = MagicMock(spec=WebSocket)

        async def mock_send(data: dict) -> None:
            pass

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Update subscriptions
        await manager.update_subscription(ws, {"status", "entities"})

        # Check subscriptions were updated
        assert manager._connections[ws]["subscriptions"] == {"status", "entities"}
