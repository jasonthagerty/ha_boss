"""Home Assistant WebSocket client for real-time state monitoring."""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
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
        on_service_call: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        on_notification_action: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        on_connect_lost: Callable[[], Coroutine[Any, Any, None]] | None = None,
        on_connected: Callable[[str | None], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Initialize WebSocket client.

        Args:
            instance: Home Assistant instance configuration (URL, token, instance_id)
            config: HA Boss configuration for connection settings
            entity_discovery: Optional entity discovery service for reload event handling
            on_state_changed: Async callback for state_changed events
            on_service_call: Optional async callback invoked for every call_service event
                with the raw event data dict.  Called in addition to (not instead of)
                the existing reload-trigger and automation-tracking logic.
            on_notification_action: Optional async callback for
                mobile_app_notification_action events (companion-app action taps),
                receiving the event data dict. When set, the client also subscribes
                to those events.
            on_connect_lost: Optional async callback fired once when the connection has
                been lost for longer than config.websocket.reconnect_notify_after_seconds.
                Cleared on successful reconnect.
            on_connected: Optional async callback fired after every successful
                authentication (initial connect and each reconnect) with the HA
                version reported in the auth handshake. Reconnects follow HA
                restarts, so this is the natural hook for HA-update detection.
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
        self.on_service_call = on_service_call
        self.on_notification_action = on_notification_action
        self.on_connect_lost = on_connect_lost
        self.on_connected = on_connected

        # State
        self.ha_version: str | None = None  # From the last successful auth handshake
        self._ws: Any = None  # WebSocket connection
        self._message_id = 0
        self._running = False
        self._reconnect_task: asyncio.Task[None] | None = None
        # Reconnect tracking for lost-connection notification
        self._reconnect_started_at: datetime | None = None
        self._reconnect_notified: bool = False
        # Liveness: when any inbound message last arrived. A socket that is
        # "open" but silent is indistinguishable from a dead one without this,
        # so the staleness watchdog uses it to force a reconnect.
        self._last_message_at: datetime | None = None

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

            self.ha_version = auth_result.get("ha_version")
            self._last_message_at = datetime.now(UTC)
            logger.info(f"WebSocket connected successfully (HA version: {self.ha_version})")

            if self.on_connected:
                try:
                    await self.on_connected(self.ha_version)
                except Exception as e:
                    logger.error(f"Error in on_connected callback: {e}", exc_info=True)

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

        # Wait for the subscription confirmation, matched by message id.
        # An already-active subscription can deliver events before this one's
        # result arrives (events carry the originating subscribe command's id),
        # so loop until we see our own result and dispatch anything else instead
        # of mistaking it for the confirmation.
        while True:
            response = json.loads(await self._ws.recv())
            if response.get("type") == "result" and response.get("id") == message_id:
                if not response.get("success"):
                    raise HomeAssistantConnectionError(
                        f"Failed to subscribe to {event_type}: {response}"
                    )
                break
            # Not our result (e.g. an event from a prior subscription) — handle it
            # so it isn't dropped while we set up the remaining subscriptions.
            await self._handle_message(response)

        logger.info(f"Subscribed to {event_type} events")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: Parsed JSON message from WebSocket
        """
        msg_type = message.get("type")

        # Any inbound message proves the stream is alive — including the pong
        # the staleness watchdog probes with.
        self._last_message_at = datetime.now(UTC)

        if msg_type == "event":
            event = message.get("event", {})
            event_type = event.get("event_type")

            if event_type == "state_changed" and self.on_state_changed:
                try:
                    await self.on_state_changed(event.get("data", {}))
                except Exception as e:
                    logger.error(f"Error in state_changed callback: {e}", exc_info=True)

            elif event_type == "call_service":
                # Handle automation/scene/script reload events and track service calls
                await self._handle_service_call(event.get("data", {}))

            elif event_type == "mobile_app_notification_action" and self.on_notification_action:
                # Companion-app notification action tap (e.g. "Acknowledge")
                try:
                    await self.on_notification_action(event.get("data", {}))
                except Exception as e:
                    logger.error(f"Error in on_notification_action callback: {e}", exc_info=True)

        elif msg_type == "pong":
            # Response to ping, ignore
            pass
        else:
            logger.debug(f"Received message type: {msg_type}")

    async def _handle_service_call(self, data: dict[str, Any]) -> None:
        """Handle service call events for discovery refresh triggers and automation tracking.

        Args:
            data: Service call event data
        """
        domain = data.get("domain")
        service = data.get("service")

        # Handle discovery refresh triggers if entity_discovery is configured
        if self.entity_discovery:
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

        # Dispatch to optional action-verification callback (additive — runs after
        # existing reload and tracking logic above, never replaces them).
        if self.on_service_call:
            try:
                await self.on_service_call(data)
            except Exception as e:
                logger.error(f"Error in on_service_call callback: {e}", exc_info=True)

    async def _listen_loop(self) -> None:
        """Main message listening loop.

        **Any** exit from the message iterator means the event stream is dead and
        must be re-established. In particular the ``websockets`` async iterator
        swallows a normal closure (``ConnectionClosedOK``) and simply stops
        iterating without raising — which is exactly what Home Assistant sends
        when it shuts down for a restart or upgrade. Catching only
        ``WebSocketException`` therefore left the client silently dead with
        ``_running`` still True and no reconnect scheduled, so this loop treats
        a clean return the same as an error.
        """
        if not self._ws:
            return

        reason = "connection closed by server"
        try:
            async for message in self._ws:
                if not self._running:
                    return

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}", exc_info=True)

        except asyncio.CancelledError:
            raise
        except WebSocketException as e:
            reason = f"WebSocket error: {e}"
        except Exception as e:
            reason = f"unexpected listen-loop error: {e}"

        self._schedule_reconnect(reason)

    def _schedule_reconnect(self, reason: str) -> None:
        """Start the reconnect loop unless it is already running or we're stopping.

        Args:
            reason: Human-readable cause, logged so a silent death is never silent.
        """
        if not self._running:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return

        logger.warning(f"WebSocket connection lost ({reason}); reconnecting")
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def force_reconnect(self, reason: str) -> None:
        """Tear down the current socket and reconnect.

        Used by the staleness watchdog when the socket still looks open but no
        messages are arriving (a half-open connection the OS has not reaped).

        Args:
            reason: Human-readable cause, logged and used in the reconnect log line.
        """
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception as e:  # pragma: no cover - best-effort teardown
                logger.debug(f"Error closing stale WebSocket: {e}")

        self._schedule_reconnect(reason)

    async def send_ping(self) -> bool:
        """Send an application-level ping without consuming the reply.

        Unlike :meth:`ping`, this never calls ``recv()``, so it is safe to call
        while the listen loop owns the socket — the ``pong`` comes back through
        ``_handle_message`` and refreshes the liveness timestamp.

        Returns:
            True if the ping was written to the socket, False otherwise.
        """
        if not self._ws:
            return False

        try:
            await self._ws.send(json.dumps({"id": self._next_id(), "type": "ping"}))
            return True
        except Exception as e:
            logger.debug(f"Liveness ping failed to send: {e}")
            return False

    def seconds_since_last_message(self) -> float | None:
        """Seconds since any message last arrived, or None if nothing ever has."""
        if self._last_message_at is None:
            return None
        return (datetime.now(UTC) - self._last_message_at).total_seconds()

    async def _reconnect(self) -> None:
        """Reconnect with infinite exponential backoff (capped at max_reconnect_delay_seconds).

        Runs until the connection is re-established or stop() sets _running=False.
        Fires on_connect_lost once after reconnect_notify_after_seconds of continuous
        disconnection so the user is alerted to a persistent outage.
        """
        attempt = 0
        self._reconnect_started_at = datetime.now(UTC)
        self._reconnect_notified = False

        while self._running:
            attempt += 1
            delay = min(
                self.retry_base_delay * (2 ** (attempt - 1)),
                self.config.websocket.max_reconnect_delay_seconds,
            )
            logger.info(f"Attempting to reconnect (attempt {attempt}) in {delay:.0f}s...")
            await asyncio.sleep(delay)

            if not self._running:
                break

            # Fire lost-connection notification once after threshold has elapsed
            if (
                not self._reconnect_notified
                and self.on_connect_lost is not None
                and self._reconnect_started_at is not None
            ):
                elapsed = (datetime.now(UTC) - self._reconnect_started_at).total_seconds()
                if elapsed >= self.config.websocket.reconnect_notify_after_seconds:
                    try:
                        await self.on_connect_lost()
                    except Exception as e:
                        logger.error(f"Error in on_connect_lost callback: {e}", exc_info=True)
                    self._reconnect_notified = True

            try:
                await self.connect()
                await self._resubscribe()
                logger.info("Reconnection successful")
                self._reconnect_started_at = None
                self._reconnect_notified = False
                asyncio.create_task(self._listen_loop())
                return

            except Exception as e:
                logger.error(f"Reconnection attempt {attempt} failed: {e}")

    async def _resubscribe(self) -> None:
        """Re-subscribe to all required event types after (re)connect."""
        await self.subscribe_events()  # state_changed (always)
        # call_service: needed for discovery refresh triggers and action verification
        if self.entity_discovery or self.on_service_call:
            await self.subscribe_events("call_service")
        # companion-app notification action taps (acknowledge)
        if self.on_notification_action:
            await self.subscribe_events("mobile_app_notification_action")

    async def start(self) -> None:
        """Start WebSocket client and begin listening for events.

        This will connect, authenticate, subscribe to events, and start
        the message listening loop.
        """
        self._running = True

        await self.connect()
        await self._resubscribe()

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

        # A reconnect in flight means the stream is down, whatever the socket says.
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return False

        # websockets >= 10 exposes close_code (None while open); older releases
        # exposed a .closed bool. Check both — the previous implementation read
        # only .closed and fell through to "assume connected" on the AttributeError
        # modern websockets raises, so it reported True for a dead socket.
        close_code = getattr(self._ws, "close_code", None)
        if close_code is not None:
            return False

        closed = getattr(self._ws, "closed", None)
        if closed is not None:
            return not bool(closed)

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
