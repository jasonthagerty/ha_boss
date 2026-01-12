"""Tests for WebSocket subscription filtering functionality."""

from unittest.mock import MagicMock

import pytest
from fastapi import WebSocket

from ha_boss.api.websocket_manager import WebSocketManager


class TestWebSocketSubscriptionFiltering:
    """Test WebSocket subscription filtering functionality."""

    @pytest.mark.asyncio
    async def test_subscription_filtering_entities(self) -> None:
        """Test that entity broadcasts respect subscription preferences."""
        manager = WebSocketManager()

        # Create two clients with different subscriptions
        ws_entities = MagicMock(spec=WebSocket)
        ws_healing = MagicMock(spec=WebSocket)

        entities_calls = []
        healing_calls = []

        async def mock_send_entities(data: dict) -> None:
            entities_calls.append(data)

        async def mock_send_healing(data: dict) -> None:
            healing_calls.append(data)

        ws_entities.send_json = mock_send_entities
        ws_healing.send_json = mock_send_healing

        # Connect both clients
        await manager.connect(ws_entities, "default")
        await manager.connect(ws_healing, "default")

        # Update subscriptions - entities only vs healing only
        await manager.update_subscription(ws_entities, {"entities"})
        await manager.update_subscription(ws_healing, {"healing"})

        # Broadcast entity state
        await manager.broadcast_entity_state(
            instance_id="default",
            entity_id="sensor.test",
            state={"state": "on"},
        )

        # Only entities client should receive the message
        assert len(entities_calls) == 2  # connect + entity state
        assert len(healing_calls) == 1  # only connect
        assert entities_calls[1]["type"] == "entity_state_changed"

    @pytest.mark.asyncio
    async def test_subscription_filtering_health(self) -> None:
        """Test that health broadcasts respect subscription preferences."""
        manager = WebSocketManager()

        # Create two clients with different subscriptions
        ws_health = MagicMock(spec=WebSocket)
        ws_entities = MagicMock(spec=WebSocket)

        health_calls = []
        entities_calls = []

        async def mock_send_health(data: dict) -> None:
            health_calls.append(data)

        async def mock_send_entities(data: dict) -> None:
            entities_calls.append(data)

        ws_health.send_json = mock_send_health
        ws_entities.send_json = mock_send_entities

        # Connect both clients
        await manager.connect(ws_health, "default")
        await manager.connect(ws_entities, "default")

        # Update subscriptions
        await manager.update_subscription(ws_health, {"health"})
        await manager.update_subscription(ws_entities, {"entities"})

        # Broadcast health status
        await manager.broadcast_health_status(
            instance_id="default",
            health={"entity_id": "sensor.test", "issue_type": "unavailable"},
        )

        # Only health client should receive the message
        assert len(health_calls) == 2  # connect + health status
        assert len(entities_calls) == 1  # only connect
        assert health_calls[1]["type"] == "health_status"

    @pytest.mark.asyncio
    async def test_subscription_filtering_healing(self) -> None:
        """Test that healing broadcasts respect subscription preferences."""
        manager = WebSocketManager()

        # Create two clients with different subscriptions
        ws_healing = MagicMock(spec=WebSocket)
        ws_health = MagicMock(spec=WebSocket)

        healing_calls = []
        health_calls = []

        async def mock_send_healing(data: dict) -> None:
            healing_calls.append(data)

        async def mock_send_health(data: dict) -> None:
            health_calls.append(data)

        ws_healing.send_json = mock_send_healing
        ws_health.send_json = mock_send_health

        # Connect both clients
        await manager.connect(ws_healing, "default")
        await manager.connect(ws_health, "default")

        # Update subscriptions
        await manager.update_subscription(ws_healing, {"healing"})
        await manager.update_subscription(ws_health, {"health"})

        # Broadcast healing action
        await manager.broadcast_healing_action(
            instance_id="default",
            action={"entity_id": "sensor.test", "action": "heal", "success": True},
        )

        # Only healing client should receive the message
        assert len(healing_calls) == 2  # connect + healing action
        assert len(health_calls) == 1  # only connect
        assert healing_calls[1]["type"] == "healing_action"

    @pytest.mark.asyncio
    async def test_subscription_wildcard(self) -> None:
        """Test that wildcard subscription '*' receives all messages."""
        manager = WebSocketManager()

        # Create client with wildcard subscription
        ws_wildcard = MagicMock(spec=WebSocket)
        ws_specific = MagicMock(spec=WebSocket)

        wildcard_calls = []
        specific_calls = []

        async def mock_send_wildcard(data: dict) -> None:
            wildcard_calls.append(data)

        async def mock_send_specific(data: dict) -> None:
            specific_calls.append(data)

        ws_wildcard.send_json = mock_send_wildcard
        ws_specific.send_json = mock_send_specific

        # Connect both clients
        await manager.connect(ws_wildcard, "default")
        await manager.connect(ws_specific, "default")

        # Update subscriptions - wildcard vs entities only
        await manager.update_subscription(ws_wildcard, {"*"})
        await manager.update_subscription(ws_specific, {"entities"})

        # Broadcast different message types
        await manager.broadcast_entity_state(
            instance_id="default", entity_id="sensor.test", state={"state": "on"}
        )
        await manager.broadcast_health_status(
            instance_id="default", health={"entity_id": "sensor.test"}
        )
        await manager.broadcast_healing_action(
            instance_id="default", action={"entity_id": "sensor.test"}
        )

        # Wildcard client should receive all messages
        assert len(wildcard_calls) == 4  # connect + 3 broadcasts
        assert len(specific_calls) == 2  # connect + entity state only

        # Verify wildcard got all types
        types = [call["type"] for call in wildcard_calls[1:]]
        assert "entity_state_changed" in types
        assert "health_status" in types
        assert "healing_action" in types

    @pytest.mark.asyncio
    async def test_connection_status_always_sent(self) -> None:
        """Test that connection status is sent regardless of subscriptions."""
        manager = WebSocketManager()

        # Create client with no connection subscription
        ws = MagicMock(spec=WebSocket)
        calls = []

        async def mock_send(data: dict) -> None:
            calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Update to very limited subscriptions (no connection-related)
        await manager.update_subscription(ws, {"entities"})

        # Broadcast connection status
        await manager.broadcast_instance_connection(instance_id="default", connected=False)

        # Should receive connection status despite not subscribing
        assert len(calls) == 2  # connect + connection status
        assert calls[1]["type"] == "instance_connection"
        assert calls[1]["connected"] is False

    @pytest.mark.asyncio
    async def test_multiple_subscriptions(self) -> None:
        """Test client with multiple subscriptions receives relevant messages."""
        manager = WebSocketManager()

        # Create client with multiple subscriptions
        ws = MagicMock(spec=WebSocket)
        calls = []

        async def mock_send(data: dict) -> None:
            calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Update to multiple subscriptions
        await manager.update_subscription(ws, {"entities", "healing"})

        # Broadcast different message types
        await manager.broadcast_entity_state(
            instance_id="default", entity_id="sensor.test", state={"state": "on"}
        )
        await manager.broadcast_health_status(
            instance_id="default", health={"entity_id": "sensor.test"}
        )
        await manager.broadcast_healing_action(
            instance_id="default", action={"entity_id": "sensor.test"}
        )

        # Should receive entity and healing messages, not health
        assert len(calls) == 3  # connect + entity + healing (no health)
        types = [call["type"] for call in calls[1:]]
        assert "entity_state_changed" in types
        assert "healing_action" in types
        assert "health_status" not in types

    @pytest.mark.asyncio
    async def test_empty_subscriptions(self) -> None:
        """Test client with empty subscriptions receives nothing except connection status."""
        manager = WebSocketManager()

        # Create client with empty subscriptions
        ws = MagicMock(spec=WebSocket)
        calls = []

        async def mock_send(data: dict) -> None:
            calls.append(data)

        ws.send_json = mock_send

        # Connect
        await manager.connect(ws, "default")

        # Update to empty subscriptions
        await manager.update_subscription(ws, set())

        # Broadcast different message types
        await manager.broadcast_entity_state(
            instance_id="default", entity_id="sensor.test", state={"state": "on"}
        )
        await manager.broadcast_health_status(
            instance_id="default", health={"entity_id": "sensor.test"}
        )
        await manager.broadcast_healing_action(
            instance_id="default", action={"entity_id": "sensor.test"}
        )
        await manager.broadcast_instance_connection(instance_id="default", connected=True)

        # Should only receive connect message and connection status (critical)
        assert len(calls) == 2  # connect + connection status
        assert calls[0]["type"] == "connected"
        assert calls[1]["type"] == "instance_connection"
