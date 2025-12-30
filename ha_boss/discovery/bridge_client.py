"""Client for HA Boss Bridge API with auto-detection."""

import logging
from typing import Any

import aiohttp

from ha_boss.core.config import HomeAssistantInstance
from ha_boss.core.exceptions import HomeAssistantConnectionError

logger = logging.getLogger(__name__)


class BridgeClient:
    """Client for HA Boss Bridge integration.

    Handles auto-detection of bridge availability and fetching full automation/scene/script
    configurations when available.
    """

    BRIDGE_BASE_PATH = "/api/ha_boss_bridge"
    AUTOMATIONS_ENDPOINT = f"{BRIDGE_BASE_PATH}/automations"
    SCENES_ENDPOINT = f"{BRIDGE_BASE_PATH}/scenes"
    SCRIPTS_ENDPOINT = f"{BRIDGE_BASE_PATH}/scripts"

    def __init__(self, instance: HomeAssistantInstance, session: aiohttp.ClientSession):
        """Initialize bridge client.

        Args:
            instance: Home Assistant instance configuration
            session: Shared aiohttp session for requests
        """
        self.instance = instance
        self.session = session
        self._is_available: bool | None = None  # Cache availability status

    async def is_available(self) -> bool:
        """Check if HA Boss Bridge is installed and available.

        Returns:
            True if bridge is available, False otherwise
        """
        # Return cached result if already checked
        if self._is_available is not None:
            return self._is_available

        # Skip check if bridge is disabled in config
        if not self.instance.bridge_enabled:
            logger.info(
                "Bridge disabled for instance %s (config: bridge_enabled=false)",
                self.instance.instance_id,
            )
            self._is_available = False
            return False

        # Try to hit the automations endpoint
        url = f"{self.instance.url}{self.AUTOMATIONS_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self.instance.token}"}

        try:
            async with self.session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    # Bridge is available and responding
                    logger.info("HA Boss Bridge detected on instance %s", self.instance.instance_id)
                    self._is_available = True
                    return True
                elif response.status == 404:
                    # Bridge not installed
                    logger.info(
                        "HA Boss Bridge not found on instance %s (404 - integration not installed)",
                        self.instance.instance_id,
                    )
                    self._is_available = False
                    return False
                elif response.status == 403:
                    # Bridge installed but user not admin
                    logger.warning(
                        "HA Boss Bridge found but user not admin on instance %s (403 Forbidden)",
                        self.instance.instance_id,
                    )
                    self._is_available = False
                    return False
                else:
                    # Unexpected status
                    logger.warning(
                        "Unexpected status %d from bridge on instance %s",
                        response.status,
                        self.instance.instance_id,
                    )
                    self._is_available = False
                    return False

        except aiohttp.ClientError as e:
            logger.debug(
                "Bridge not available on instance %s: %s",
                self.instance.instance_id,
                str(e),
            )
            self._is_available = False
            return False

    async def get_automations(self) -> list[dict[str, Any]]:
        """Fetch full automation configurations from bridge.

        Returns:
            List of automation configs with trigger/condition/action

        Raises:
            HomeAssistantConnectionError: If bridge is unavailable or request fails
        """
        if not await self.is_available():
            raise HomeAssistantConnectionError(
                f"Bridge not available on instance {self.instance.instance_id}"
            )

        url = f"{self.instance.url}{self.AUTOMATIONS_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self.instance.token}"}

        try:
            async with self.session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HomeAssistantConnectionError(
                        f"Bridge automations request failed: {response.status} - {error_text}"
                    )

                data = await response.json()

                # Extract automations array from response
                automations = data.get("automations", [])
                logger.info(
                    "Fetched %d automations from bridge on instance %s",
                    len(automations),
                    self.instance.instance_id,
                )
                return automations

        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(
                f"Failed to fetch automations from bridge: {e}"
            ) from e

    async def get_scenes(self) -> list[dict[str, Any]]:
        """Fetch scene configurations from bridge.

        Returns:
            List of scene configs with entity lists

        Raises:
            HomeAssistantConnectionError: If bridge is unavailable or request fails
        """
        if not await self.is_available():
            raise HomeAssistantConnectionError(
                f"Bridge not available on instance {self.instance.instance_id}"
            )

        url = f"{self.instance.url}{self.SCENES_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self.instance.token}"}

        try:
            async with self.session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HomeAssistantConnectionError(
                        f"Bridge scenes request failed: {response.status} - {error_text}"
                    )

                data = await response.json()

                scenes = data.get("scenes", [])
                logger.info(
                    "Fetched %d scenes from bridge on instance %s",
                    len(scenes),
                    self.instance.instance_id,
                )
                return scenes

        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to fetch scenes from bridge: {e}") from e

    async def get_scripts(self) -> list[dict[str, Any]]:
        """Fetch script configurations from bridge.

        Returns:
            List of script configs with sequences

        Raises:
            HomeAssistantConnectionError: If bridge is unavailable or request fails
        """
        if not await self.is_available():
            raise HomeAssistantConnectionError(
                f"Bridge not available on instance {self.instance.instance_id}"
            )

        url = f"{self.instance.url}{self.SCRIPTS_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self.instance.token}"}

        try:
            async with self.session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HomeAssistantConnectionError(
                        f"Bridge scripts request failed: {response.status} - {error_text}"
                    )

                data = await response.json()

                scripts = data.get("scripts", [])
                logger.info(
                    "Fetched %d scripts from bridge on instance %s",
                    len(scripts),
                    self.instance.instance_id,
                )
                return scripts

        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to fetch scripts from bridge: {e}") from e

    def reset_availability_cache(self) -> None:
        """Reset the availability cache to force re-check on next call."""
        self._is_available = None
        logger.debug("Bridge availability cache reset for instance %s", self.instance.instance_id)
