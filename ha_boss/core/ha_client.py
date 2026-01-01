"""Home Assistant API client wrapper."""

import asyncio
import logging
from datetime import datetime
from typing import Any, cast

import aiohttp

from ha_boss.core.config import Config, HomeAssistantInstance
from ha_boss.core.exceptions import (
    HomeAssistantAPIError,
    HomeAssistantAuthError,
    HomeAssistantConnectionError,
)

logger = logging.getLogger(__name__)


class HomeAssistantClient:
    """Client for interacting with Home Assistant REST API.

    Provides methods for common HA operations with built-in retry logic,
    error handling, and authentication.
    """

    def __init__(self, instance: HomeAssistantInstance, config: Config) -> None:
        """Initialize Home Assistant client.

        Args:
            instance: Home Assistant instance configuration (URL, token, instance_id)
            config: HA Boss configuration for REST settings
        """
        self.instance = instance
        self.instance_id = instance.instance_id
        self.base_url = instance.url
        self.token = instance.token
        self.timeout = config.rest.timeout_seconds
        self.max_retries = config.rest.retry_attempts
        self.retry_base_delay = config.rest.retry_base_delay_seconds

        # Session will be created in async context
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "HomeAssistantClient":
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self) -> None:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        """Make HTTP request to Home Assistant API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Optional JSON data for request body
            retry: Whether to retry on failure

        Returns:
            JSON response data

        Raises:
            HomeAssistantConnectionError: Connection failed
            HomeAssistantAuthError: Authentication failed (401)
            HomeAssistantAPIError: API returned error
        """
        await self._ensure_session()
        assert self._session is not None

        url = f"{self.base_url}{endpoint}"
        attempts = self.max_retries if retry else 1

        for attempt in range(1, attempts + 1):
            try:
                async with self._session.request(method, url, json=data) as response:
                    # Handle authentication errors
                    if response.status == 401:
                        raise HomeAssistantAuthError(
                            "Authentication failed. Check HA_TOKEN is valid."
                        )

                    # Handle not found
                    if response.status == 404:
                        raise HomeAssistantAPIError(f"API endpoint not found: {endpoint}")

                    # Raise for other HTTP errors
                    response.raise_for_status()

                    # Parse JSON response
                    if response.content_type == "application/json":
                        return await response.json()
                    else:
                        # Some endpoints return empty responses
                        return None

            except aiohttp.ClientError as e:
                # Connection errors
                if attempt < attempts:
                    delay = self.retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"Connection error (attempt {attempt}/{attempts}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    raise HomeAssistantConnectionError(
                        f"Failed to connect to Home Assistant at {self.base_url}: {e}"
                    ) from e

            except aiohttp.ClientResponseError as e:
                # HTTP errors (already handled 401 and 404 above)
                raise HomeAssistantAPIError(f"API request failed ({e.status}): {e.message}") from e

        # Should never reach here due to raises above
        raise HomeAssistantConnectionError("Request failed after all retries")

    async def check_connection(self) -> bool:
        """Check if connection to Home Assistant is working.

        Returns:
            True if connected and authenticated successfully

        Raises:
            HomeAssistantConnectionError: Cannot connect
            HomeAssistantAuthError: Invalid token
        """
        try:
            await self._request("GET", "/api/")
            return True
        except (HomeAssistantConnectionError, HomeAssistantAuthError):
            raise

    async def get_config(self) -> dict[str, Any]:
        """Get Home Assistant configuration.

        Returns:
            Configuration dictionary with version, location_name, etc.
        """
        return cast(dict[str, Any], await self._request("GET", "/api/config"))

    async def get_states(self) -> list[dict[str, Any]]:
        """Get all entity states.

        Returns:
            List of entity state dictionaries
        """
        return cast(list[dict[str, Any]], await self._request("GET", "/api/states"))

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        """Get state for specific entity.

        Args:
            entity_id: Entity ID (e.g., "sensor.temperature")

        Returns:
            Entity state dictionary

        Raises:
            HomeAssistantAPIError: Entity not found
        """
        return cast(dict[str, Any], await self._request("GET", f"/api/states/{entity_id}"))

    async def set_state(
        self,
        entity_id: str,
        state: str,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set state for an entity.

        Args:
            entity_id: Entity ID
            state: New state value
            attributes: Optional state attributes

        Returns:
            Updated entity state dictionary
        """
        data: dict[str, Any] = {"state": state}
        if attributes:
            data["attributes"] = attributes

        return cast(
            dict[str, Any], await self._request("POST", f"/api/states/{entity_id}", data=data)
        )

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., "homeassistant", "light")
            service: Service name (e.g., "reload_config_entry", "turn_on")
            service_data: Optional service_call data

        Returns:
            Service call response (may be None for some services)

        Example:
            # Reload integration
            await client.call_service(
                "homeassistant",
                "reload_config_entry",
                {"entry_id": "abc123"}
            )

            # Create notification
            await client.call_service(
                "persistent_notification",
                "create",
                {"title": "HA Boss", "message": "Hello!"}
            )
        """
        endpoint = f"/api/services/{domain}/{service}"
        return cast(
            list[dict[str, Any]] | None, await self._request("POST", endpoint, data=service_data)
        )

    async def get_services(self) -> dict[str, Any]:
        """Get all available services.

        Returns:
            Dictionary of services by domain
        """
        return cast(dict[str, Any], await self._request("GET", "/api/services"))

    async def get_history(
        self,
        filter_entity_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[list[dict[str, Any]]]:
        """Get state history.

        Args:
            filter_entity_id: Optional entity ID to filter
            start_time: Optional start time (ISO format)
            end_time: Optional end time (ISO format)

        Returns:
            History data grouped by entity
        """
        # Build endpoint with query parameters
        endpoint = "/api/history/period"

        if start_time:
            endpoint += f"/{start_time.isoformat()}"

        params = []
        if filter_entity_id:
            params.append(f"filter_entity_id={filter_entity_id}")
        if end_time:
            params.append(f"end_time={end_time.isoformat()}")

        if params:
            endpoint += "?" + "&".join(params)

        return cast(list[list[dict[str, Any]]], await self._request("GET", endpoint))

    async def get_error_log(self) -> str:
        """Get Home Assistant error log.

        Returns:
            Error log as string
        """
        await self._ensure_session()
        assert self._session is not None

        url = f"{self.base_url}/api/error_log"
        async with self._session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    async def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fire a custom event.

        Args:
            event_type: Event type name
            event_data: Optional event data

        Returns:
            Event response
        """
        endpoint = f"/api/events/{event_type}"
        return cast(dict[str, Any], await self._request("POST", endpoint, data=event_data))

    async def reload_integration(self, entry_id: str) -> None:
        """Reload a specific integration by entry ID.

        Args:
            entry_id: Integration config entry ID

        Raises:
            HomeAssistantAPIError: If reload fails
        """
        await self.call_service(
            "homeassistant",
            "reload_config_entry",
            {"entry_id": entry_id},
        )
        logger.info(f"Triggered reload for integration entry_id={entry_id}")

    async def reload_automations(self) -> None:
        """Reload all automations."""
        await self.call_service("automation", "reload")
        logger.info("Triggered automation reload")

    async def restart_homeassistant(self) -> None:
        """Restart Home Assistant (use with caution!)."""
        logger.warning("Triggering Home Assistant restart")
        await self.call_service("homeassistant", "restart")

    async def create_persistent_notification(
        self,
        message: str,
        title: str = "HA Boss",
        notification_id: str | None = None,
    ) -> None:
        """Create a persistent notification in Home Assistant UI.

        Args:
            message: Notification message
            title: Notification title (default: "HA Boss")
            notification_id: Optional notification ID (for updating/dismissing)
        """
        data: dict[str, Any] = {
            "message": message,
            "title": title,
        }
        if notification_id:
            data["notification_id"] = notification_id

        await self.call_service("persistent_notification", "create", data)

    async def create_automation(
        self,
        automation_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new automation in Home Assistant.

        Uses the automation editor API to create a new automation.

        Args:
            automation_config: Automation configuration dict containing:
                - alias: Automation name (required)
                - trigger: List of triggers (required)
                - action: List of actions (required)
                - condition: List of conditions (optional)
                - mode: Execution mode (optional, default: single)
                - description: Automation description (optional)

        Returns:
            Created automation data with ID

        Raises:
            HomeAssistantAPIError: If creation fails
            ValueError: If automation_config is invalid

        Example:
            >>> config = {
            ...     "alias": "Turn on lights",
            ...     "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion"}],
            ...     "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}]
            ... }
            >>> result = await client.create_automation(config)
            >>> print(result["id"])  # Automation ID
        """
        # Validate required fields
        if "alias" not in automation_config:
            raise ValueError("Automation must have an 'alias' field")
        if "trigger" not in automation_config:
            raise ValueError("Automation must have a 'trigger' field")
        if "action" not in automation_config:
            raise ValueError("Automation must have an 'action' field")

        # Generate a unique ID for the automation
        import time

        automation_id = str(int(time.time() * 1000))

        # Use the config/automation/config API to create the automation
        await self._ensure_session()
        assert self._session is not None

        url = f"{self.base_url}/api/config/automation/config/{automation_id}"
        async with self._session.post(url, json=automation_config) as response:
            if response.status == 200:
                result = await response.json()
                # Add the ID to the result
                result["id"] = automation_id
                return result
            elif response.status == 400:
                error_text = await response.text()
                raise HomeAssistantAPIError(f"Invalid automation configuration: {error_text}")
            else:
                error_text = await response.text()
                raise HomeAssistantAPIError(
                    f"Failed to create automation (HTTP {response.status}): {error_text}"
                )


async def create_ha_client(config: Config, instance_id: str | None = None) -> HomeAssistantClient:
    """Create and initialize Home Assistant client.

    Args:
        config: HA Boss configuration
        instance_id: Optional instance ID (defaults to first instance)

    Returns:
        Initialized HA client

    Raises:
        HomeAssistantConnectionError: Cannot connect to HA
        HomeAssistantAuthError: Invalid token
        ValueError: Instance ID not found
    """
    # Get instance configuration
    if instance_id:
        instance = config.home_assistant.get_instance(instance_id)
        if not instance:
            raise ValueError(f"Instance '{instance_id}' not found in configuration")
    else:
        instance = config.home_assistant.get_default_instance()

    client = HomeAssistantClient(instance, config)

    # Verify connection
    try:
        await client.check_connection()
        logger.info(
            f"Successfully connected to Home Assistant instance '{instance.instance_id}' at {instance.url}"
        )
    except Exception:
        await client.close()
        raise

    return client

