"""Home Assistant WebSocket client for real-time state monitoring."""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import websockets
from websockets.exceptions import WebSocketException

from ha_boss.core.config import Config, HomeAssistantInstance
from ha_boss.core.exceptions import (
    HomeAssistantAuthError,
    HomeAssistantConnectionError,
)

if TYPE_CHECKING:
    from ha_boss.discovery.entity_discovery import EntityDiscoveryService

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for Home Assistant real-time state monitoring.

    Provides automatic reconnection, authentication, and event subscription
    for monitoring state changes in real-time.
    """

    def __init__(
        self,
        instance: HomeAssistantInstance,
        config: Config,
        entity_discovery: "EntityDiscoveryService | None" = None,
        on_state_changed: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Initialize WebSocket client.

        Args:
            instance: Home Assistant instance configuration (URL, token, instance_id)
            config: HA Boss configuration for connection settings
            entity_discovery: Optional entity discovery service for reload event handling
            on_state_changed: Async callback for state_changed events
        """
        # Build WebSocket URL from HTTP URL
        ws_url = instance.url.replace("http://", "ws://").replace("https://", "wss://")
        self.ws_url = f"{ws_url}/api/websocket"
        self.token = instance.token
        self.instance = instance
        self.instance_id = instance.instance_id
        self.config = config
        self.entity_discovery = entity_discovery

        # Connection settings
        self.max_retries = config.rest.retry_attempts
        self.retry_base_delay = config.rest.retry_base_delay_seconds

        # Callbacks
        self.on_state_changed = on_state_changed

        # State
        self._ws: Any = None  # WebSocket connection
        self._message_id = 0
        self._running = False
        self._reconnect_task: asyncio.Task[None] | None = None

    def _next_id(self) -> int:
        """Get next message ID for requests."""
        self._message_id += 1
        return self._message_id

    async def connect(self) -> None:
        """Connect to Home Assistant WebSocket API.

        Raises:
            HomeAssistantConnectionError: Connection failed
            HomeAssistantAuthError: Authentication failed
        """
        try:
            logger.info(f"Connecting to WebSocket at {self.ws_url}")
            self._ws = await websockets.connect(self.ws_url)

            # Step 1: Receive auth_required
            auth_required = json.loads(await self._ws.recv())
            if auth_required.get("type") != "auth_required":
                raise HomeAssistantConnectionError(
                    f"Expected auth_required, got: {auth_required.get('type')}"
                )

            # Step 2: Send auth message
            await self._ws.send(json.dumps({"type": "auth", "access_token": self.token}))

            # Step 3: Receive auth result
            auth_result = json.loads(await self._ws.recv())
            if auth_result.get("type") == "auth_invalid":
                raise HomeAssistantAuthError(f"Authentication failed: {auth_result.get('message')}")
            elif auth_result.get("type") != "auth_ok":
                raise HomeAssistantConnectionError(
                    f"Unexpected auth response: {auth_result.get('type')}"
                )

            logger.info(
                f"WebSocket connected successfully (HA version: {auth_result.get('ha_version')})"
            )

        except (HomeAssistantAuthError, HomeAssistantConnectionError):
            # Re-raise our own exceptions without wrapping
            raise
        except WebSocketException as e:
            raise HomeAssistantConnectionError(f"WebSocket connection failed: {e}") from e
        except Exception as e:
            raise HomeAssistantConnectionError(
                f"Unexpected error during WebSocket connection: {e}"
            ) from e

    async def subscribe_events(self, event_type: str = "state_changed") -> None:
        """Subscribe to Home Assistant events.

        Args:
            event_type: Event type to subscribe to (default: state_changed)

        Raises:
            HomeAssistantConnectionError: Not connected
        """
        if not self._ws:
            raise HomeAssistantConnectionError("Not connected to WebSocket")

        message_id = self._next_id()
        subscribe_msg = {
            "id": message_id,
            "type": "subscribe_events",
            "event_type": event_type,
        }

        await self._ws.send(json.dumps(subscribe_msg))

        # Wait for subscription confirmation
        response = json.loads(await self._ws.recv())
        if not response.get("success"):
            raise HomeAssistantConnectionError(f"Failed to subscribe to {event_type}: {response}")

        logger.info(f"Subscribed to {event_type} events")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: Parsed JSON message from WebSocket
        """
        msg_type = message.get("type")

        if msg_type == "event":
            event = message.get("event", {})
            event_type = event.get("event_type")

            if event_type == "state_changed" and self.on_state_changed:
                try:
                    await self.on_state_changed(event.get("data", {}))
                except Exception as e:
                    logger.error(f"Error in state_changed callback: {e}", exc_info=True)

            elif event_type == "call_service":
                # Handle automation/scene/script reload events
                await self._handle_service_call(event.get("data", {}))

        elif msg_type == "pong":
            # Response to ping, ignore
            pass
        else:
            logger.debug(f"Received message type: {msg_type}")

    async def _handle_service_call(self, data: dict[str, Any]) -> None:
        """Handle service call events for discovery refresh triggers.

        Args:
            data: Service call event data
        """
        if not self.entity_discovery:
            return

        domain = data.get("domain")
        service = data.get("service")

        # Check for automation/scene/script reload services
        if domain == "automation" and service == "reload":
            if self.config.monitoring.auto_discovery.refresh_on_automation_reload:
                logger.info("Automation reload detected, triggering discovery refresh")
                try:
                    await self.entity_discovery.discover_and_refresh(
                        trigger_type="event", trigger_source="automation_reload"
                    )
                except Exception as e:
                    logger.error(f"Discovery refresh failed after automation reload: {e}")

        elif domain == "scene" and service == "reload":
            if self.config.monitoring.auto_discovery.refresh_on_scene_reload:
                logger.info("Scene reload detected, triggering discovery refresh")
                try:
                    await self.entity_discovery.discover_and_refresh(
                        trigger_type="event", trigger_source="scene_reload"
                    )
                except Exception as e:
                    logger.error(f"Discovery refresh failed after scene reload: {e}")

        elif domain == "script" and service == "reload":
            if self.config.monitoring.auto_discovery.refresh_on_script_reload:
                logger.info("Script reload detected, triggering discovery refresh")
                try:
                    await self.entity_discovery.discover_and_refresh(
                        trigger_type="event", trigger_source="script_reload"
                    )
                except Exception as e:
                    logger.error(f"Discovery refresh failed after script reload: {e}")

    async def _listen_loop(self) -> None:
        """Main message listening loop."""
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if not self._running:
                    break

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}", exc_info=True)

        except WebSocketException as e:
            if self._running:
                logger.warning(f"WebSocket connection lost: {e}")
                # Trigger reconnection
                if self._reconnect_task is None or self._reconnect_task.done():
                    self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        attempt = 0
        while self._running and attempt < self.max_retries:
            attempt += 1
            delay = self.retry_base_delay * (2 ** (attempt - 1))

            logger.info(
                f"Attempting to reconnect (attempt {attempt}/{self.max_retries}) " f"in {delay}s..."
            )
            await asyncio.sleep(delay)

            try:
                await self.connect()
                await self.subscribe_events()  # Subscribe to state_changed

                # Also subscribe to call_service events for discovery refresh triggers
                if self.entity_discovery:
                    await self.subscribe_events("call_service")

                logger.info("Reconnection successful")

                # Restart listen loop
                asyncio.create_task(self._listen_loop())
                return

            except Exception as e:
                logger.error(f"Reconnection attempt {attempt} failed: {e}")

        if self._running:
            logger.error("Failed to reconnect after all retry attempts")
            self._running = False

    async def start(self) -> None:
        """Start WebSocket client and begin listening for events.

        This will connect, authenticate, subscribe to events, and start
        the message listening loop.
        """
        self._running = True

        await self.connect()
        await self.subscribe_events()  # Subscribe to state_changed

        # Also subscribe to call_service events for discovery refresh triggers
        if self.entity_discovery:
            await self.subscribe_events("call_service")

        # Start listening loop
        asyncio.create_task(self._listen_loop())
        logger.info("WebSocket client started")

    async def stop(self) -> None:
        """Stop WebSocket client and close connection."""
        self._running = False

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("WebSocket client stopped")

    async def ping(self) -> bool:
        """Send ping to check connection health.

        Returns:
            True if connection is alive, False otherwise
        """
        if not self._ws:
            return False

        try:
            message_id = self._next_id()
            await self._ws.send(json.dumps({"id": message_id, "type": "ping"}))

            # Wait for pong response (with timeout)
            response = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            data = json.loads(response)
            is_pong = data.get("type") == "pong" and data.get("id") == message_id
            return bool(is_pong)

        except (TimeoutError, WebSocketException, json.JSONDecodeError):
            return False

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected.

        Returns:
            True if connected, False otherwise
        """
        # Check if client is running (most reliable indicator)
        if not self._running:
            return False

        # Check if websocket object exists
        if self._ws is None:
            return False

        # websockets library uses .closed attribute (True if connection is closed)
        try:
            return not self._ws.closed
        except AttributeError:
            # Fallback: if _running is True and _ws exists, assume connected
            return True


async def create_websocket_client(
    config: Config,
    on_state_changed: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
) -> WebSocketClient:
    """Create and start WebSocket client.

    Args:
        config: HA Boss configuration
        on_state_changed: Async callback for state_changed events

    Returns:
        Started WebSocket client

    Raises:
        HomeAssistantConnectionError: Connection failed
        HomeAssistantAuthError: Authentication failed
    """
    instance = config.home_assistant.get_default_instance()
    client = WebSocketClient(instance, config, on_state_changed=on_state_changed)

    try:
        await client.start()
        logger.info("WebSocket client created and started successfully")
    except Exception:
        await client.stop()
        raise

    return client
