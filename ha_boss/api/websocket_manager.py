"""WebSocket manager for real-time dashboard updates."""

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts real-time updates to dashboard clients.

    Handles client subscriptions per instance, connection lifecycle,
    and event broadcasting with proper error handling.
    """

    def __init__(self) -> None:
        """Initialize WebSocket manager."""
        # Active connections: {websocket: {"instance_id": str, "subscriptions": set}}
        self._connections: dict[WebSocket, dict[str, Any]] = {}

        # Instance subscriptions: {instance_id: set of websockets}
        self._instance_subscriptions: dict[str, set[WebSocket]] = defaultdict(set)

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, instance_id: str = "default") -> None:
        """Register a new WebSocket connection.

        Args:
            websocket: WebSocket connection to register
            instance_id: Instance to subscribe to (default: "default")
        """
        async with self._lock:
            await websocket.accept()

            # Register connection
            self._connections[websocket] = {
                "instance_id": instance_id,
                "subscriptions": {"status", "entities", "health"},
                "connected_at": datetime.now(UTC),
            }

            # Add to instance subscriptions
            self._instance_subscriptions[instance_id].add(websocket)

            logger.info(f"WebSocket connected: {id(websocket)} for instance '{instance_id}'")

            # Send welcome message
            await self._send_to_client(
                websocket,
                {
                    "type": "connected",
                    "instance_id": instance_id,
                    "subscriptions": list(self._connections[websocket]["subscriptions"]),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection.

        Args:
            websocket: WebSocket connection to unregister
        """
        async with self._lock:
            if websocket not in self._connections:
                return

            connection_info = self._connections[websocket]
            instance_id = connection_info["instance_id"]

            # Remove from instance subscriptions
            if instance_id in self._instance_subscriptions:
                self._instance_subscriptions[instance_id].discard(websocket)
                if not self._instance_subscriptions[instance_id]:
                    del self._instance_subscriptions[instance_id]

            # Remove connection
            del self._connections[websocket]

            logger.info(f"WebSocket disconnected: {id(websocket)} from instance '{instance_id}'")

    async def switch_instance(self, websocket: WebSocket, new_instance_id: str) -> None:
        """Atomically switch a WebSocket connection to a different instance.

        This method ensures no race condition occurs during instance switching
        by holding the lock throughout the entire operation. This prevents
        message loss or messages being sent to the wrong instance during the switch.

        Args:
            websocket: WebSocket connection to switch
            new_instance_id: New instance ID to switch to
        """
        async with self._lock:
            if websocket not in self._connections:
                logger.warning(f"Cannot switch instance for unknown websocket {id(websocket)}")
                return

            # Get current instance
            old_instance_id = self._connections[websocket]["instance_id"]

            # No-op if already on this instance
            if old_instance_id == new_instance_id:
                logger.debug(
                    f"WebSocket {id(websocket)} already on instance '{new_instance_id}', skipping switch"
                )
                return

            # Remove from old instance subscriptions
            if old_instance_id in self._instance_subscriptions:
                self._instance_subscriptions[old_instance_id].discard(websocket)
                if not self._instance_subscriptions[old_instance_id]:
                    del self._instance_subscriptions[old_instance_id]

            # Update instance_id in connection info
            self._connections[websocket]["instance_id"] = new_instance_id

            # Add to new instance subscriptions
            self._instance_subscriptions[new_instance_id].add(websocket)

            logger.info(
                f"WebSocket {id(websocket)} switched from instance '{old_instance_id}' to '{new_instance_id}'"
            )

        # Send confirmation message (outside of critical section to avoid deadlock)
        await self._send_to_client(
            websocket,
            {
                "type": "instance_switched",
                "old_instance_id": old_instance_id,
                "new_instance_id": new_instance_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def broadcast_to_instance(self, instance_id: str, message: dict[str, Any]) -> None:
        """Broadcast message to all clients subscribed to an instance.

        Args:
            instance_id: Instance identifier
            message: Message to broadcast
        """
        if instance_id not in self._instance_subscriptions:
            return

        # Get snapshot of clients (avoid holding lock during sends)
        async with self._lock:
            clients = list(self._instance_subscriptions[instance_id])

        # Broadcast to all clients
        disconnected = []
        for websocket in clients:
            success = await self._send_to_client(websocket, message)
            if not success:
                disconnected.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def broadcast_entity_state(
        self, instance_id: str, entity_id: str, state: dict[str, Any]
    ) -> None:
        """Broadcast entity state change to subscribed clients.

        Only sends to clients with 'entities' or '*' subscription.

        Args:
            instance_id: Instance identifier
            entity_id: Entity identifier
            state: Entity state data
        """
        message = {
            "type": "entity_state_changed",
            "instance_id": instance_id,
            "entity_id": entity_id,
            "state": state,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await self._broadcast_with_subscription_filter(
            instance_id, message, required_subscription="entities"
        )

    async def broadcast_health_status(self, instance_id: str, health: dict[str, Any]) -> None:
        """Broadcast health status change to subscribed clients.

        Only sends to clients with 'health' or '*' subscription.

        Args:
            instance_id: Instance identifier
            health: Health status data
        """
        message = {
            "type": "health_status",
            "instance_id": instance_id,
            "health": health,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await self._broadcast_with_subscription_filter(
            instance_id, message, required_subscription="health"
        )

    async def broadcast_healing_action(self, instance_id: str, action: dict[str, Any]) -> None:
        """Broadcast healing action to subscribed clients.

        Only sends to clients with 'healing' or '*' subscription.

        Args:
            instance_id: Instance identifier
            action: Healing action data
        """
        message = {
            "type": "healing_action",
            "instance_id": instance_id,
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await self._broadcast_with_subscription_filter(
            instance_id, message, required_subscription="healing"
        )

    async def broadcast_instance_connection(self, instance_id: str, connected: bool) -> None:
        """Broadcast instance connection status change to all clients.

        Connection status is critical - sent to all clients regardless of subscriptions.

        Args:
            instance_id: Instance identifier
            connected: Connection status
        """
        message = {
            "type": "instance_connection",
            "instance_id": instance_id,
            "connected": connected,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # No filtering - connection status is critical
        await self.broadcast_to_instance(instance_id, message)

    async def _broadcast_with_subscription_filter(
        self, instance_id: str, message: dict[str, Any], required_subscription: str
    ) -> None:
        """Broadcast message to clients with required subscription.

        Args:
            instance_id: Instance identifier
            message: Message to broadcast
            required_subscription: Subscription key required to receive message
                                 (clients with '*' always receive)
        """
        if instance_id not in self._instance_subscriptions:
            return

        # Get snapshot of clients (avoid holding lock during sends)
        async with self._lock:
            clients = list(self._instance_subscriptions[instance_id])

        # Filter clients by subscription and broadcast
        disconnected = []
        for websocket in clients:
            # Check if client has required subscription or wildcard
            subscriptions = self._connections[websocket]["subscriptions"]
            if required_subscription in subscriptions or "*" in subscriptions:
                success = await self._send_to_client(websocket, message)
                if not success:
                    disconnected.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def update_subscription(self, websocket: WebSocket, subscriptions: set[str]) -> None:
        """Update client subscriptions.

        Args:
            websocket: WebSocket connection
            subscriptions: New set of subscriptions
        """
        async with self._lock:
            if websocket in self._connections:
                self._connections[websocket]["subscriptions"] = subscriptions
                logger.debug(f"Updated subscriptions for {id(websocket)}: {subscriptions}")

    async def _send_to_client(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        """Send message to a specific client.

        Args:
            websocket: WebSocket connection
            message: Message to send

        Returns:
            True if sent successfully, False if client disconnected
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.warning(
                f"Failed to send message to {id(websocket)}: {e}. Marking for disconnect."
            )
            return False

    def get_connection_count(self) -> int:
        """Get total number of active connections.

        Returns:
            Number of active WebSocket connections
        """
        return len(self._connections)

    def get_instance_connection_count(self, instance_id: str) -> int:
        """Get number of connections for a specific instance.

        Args:
            instance_id: Instance identifier

        Returns:
            Number of connections subscribed to instance
        """
        return len(self._instance_subscriptions.get(instance_id, set()))


# Global WebSocket manager instance
_websocket_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """Get global WebSocket manager instance.

    Returns:
        WebSocket manager singleton
    """
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
