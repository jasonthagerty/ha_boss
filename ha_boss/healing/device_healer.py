"""Device-level healing strategies for automation failures.

This module implements Level 2 healing in the goal-oriented healing cascade.
Device-level healing attempts to fix device-wide failures by:
1. Reconnecting the device (if supported by integration)
2. Rebooting the device (if supported by integration)
3. Rediscovering the device through integration discovery
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ha_boss.core.database import Database, DeviceHealingAction
from ha_boss.core.ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class DeviceHealingResult:
    """Result of device-level healing attempt."""

    devices_attempted: list[str]  # device_ids
    success: bool  # True if ANY device healed successfully
    devices_healed: list[str]  # device_ids that succeeded
    actions_attempted: list[str]  # e.g., ["reconnect", "reboot"]
    final_action: str | None  # Which action succeeded (if any)
    error_message: str | None
    total_duration_seconds: float


class DeviceHealer:
    """Device-level healer - Level 2 in healing cascade.

    Attempts to heal device-wide failures by reconnecting, rebooting,
    or rediscovering devices through their integrations.
    """

    def __init__(
        self,
        database: Database,
        ha_client: HomeAssistantClient,
        instance_id: str = "default",
        reboot_timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize device healer.

        Args:
            database: Database manager for recording actions
            ha_client: Home Assistant API client for device operations
            instance_id: Instance identifier for multi-instance setups
            reboot_timeout_seconds: Timeout for device reboot operations
        """
        self.database = database
        self.ha_client = ha_client
        self.instance_id = instance_id
        self.reboot_timeout_seconds = reboot_timeout_seconds

    async def heal(
        self,
        entity_ids: list[str],
        triggered_by: str = "automation_failure",
        automation_id: str | None = None,
        execution_id: int | None = None,
    ) -> DeviceHealingResult:
        """Attempt device-level healing.

        Flow:
        1. Map entity_ids to device_ids via HA device registry
        2. For each device, try healing strategies:
           - Reconnect (if integration supports it)
           - Reboot (if integration supports it)
           - Rediscover (if integration supports it)

        Args:
            entity_ids: List of entity IDs that failed
            triggered_by: What triggered healing (automation_failure, manual, pattern)
            automation_id: Optional automation ID context
            execution_id: Optional execution ID for linking

        Returns:
            DeviceHealingResult with success status and actions taken
        """
        start_time = datetime.now(UTC)
        actions_attempted: list[str] = []
        devices_healed: list[str] = []
        error_message: str | None = None

        logger.info(
            f"Starting device-level healing for {len(entity_ids)} entities (triggered_by={triggered_by})"
        )

        # Validate inputs
        if not entity_ids:
            return DeviceHealingResult(
                devices_attempted=[],
                success=False,
                devices_healed=[],
                actions_attempted=[],
                final_action=None,
                error_message="No entity IDs provided",
                total_duration_seconds=0.0,
            )

        try:
            # Map entities to devices
            device_map = await self._get_devices_for_entities(entity_ids)

            if not device_map:
                error_message = "No devices found for provided entities"
                logger.warning(f"Device healing failed: {error_message}")
                return DeviceHealingResult(
                    devices_attempted=[],
                    success=False,
                    devices_healed=[],
                    actions_attempted=[],
                    final_action=None,
                    error_message=error_message,
                    total_duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                )

            devices_attempted = list(device_map.keys())
            logger.info(f"Found {len(devices_attempted)} unique devices to heal")

            # Attempt healing for each device
            final_action: str | None = None
            for device_id in devices_attempted:
                device_entities = device_map[device_id]
                logger.info(
                    f"Attempting healing for device {device_id} "
                    f"(affects {len(device_entities)} entities)"
                )

                # Check which healing features are supported
                features = await self._check_integration_features(device_id)

                # Try healing strategies in order
                healing_strategies = [
                    ("reconnect", self._reconnect_device, features["reconnect"]),
                    ("reboot", self._reboot_device, features["reboot"]),
                    ("rediscover", self._rediscover_device, features["rediscover"]),
                ]

                for action_type, strategy_func, supported in healing_strategies:
                    if not supported:
                        logger.debug(
                            f"Skipping {action_type} for device {device_id} (not supported)"
                        )
                        continue

                    if action_type not in actions_attempted:
                        actions_attempted.append(action_type)

                    logger.info(f"Trying {action_type} for device {device_id}")
                    action_start = datetime.now(UTC)
                    success = False
                    action_error: str | None = None

                    try:
                        success = await strategy_func(device_id)
                    except Exception as e:
                        action_error = f"Strategy exception: {str(e)}"
                        logger.error(
                            f"Device healing strategy {action_type} failed for {device_id}: {e}",
                            exc_info=True,
                        )

                    # Record this healing attempt
                    duration = (datetime.now(UTC) - action_start).total_seconds()
                    await self._record_action(
                        device_id=device_id,
                        action_type=action_type,
                        triggered_by=triggered_by,
                        automation_id=automation_id,
                        execution_id=execution_id,
                        success=success,
                        error_message=action_error,
                        duration_seconds=duration,
                    )

                    if success:
                        final_action = action_type
                        devices_healed.append(device_id)
                        logger.info(f"Device {device_id} healed successfully via {action_type}")
                        break  # Move to next device

            # Overall success if any device was healed
            overall_success = len(devices_healed) > 0

            if overall_success:
                logger.info(
                    f"Device-level healing succeeded: {len(devices_healed)}/{len(devices_attempted)} devices healed"
                )
            else:
                error_message = "All device healing strategies failed"
                logger.info(
                    f"Device-level healing failed: all {len(devices_attempted)} devices failed to heal"
                )

            return DeviceHealingResult(
                devices_attempted=devices_attempted,
                success=overall_success,
                devices_healed=devices_healed,
                actions_attempted=actions_attempted,
                final_action=final_action,
                error_message=error_message,
                total_duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            )

        except Exception as e:
            error_message = f"Device healing exception: {str(e)}"
            logger.error(f"Device healing failed with exception: {e}", exc_info=True)
            return DeviceHealingResult(
                devices_attempted=[],
                success=False,
                devices_healed=[],
                actions_attempted=actions_attempted,
                final_action=None,
                error_message=error_message,
                total_duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
            )

    async def _get_devices_for_entities(
        self,
        entity_ids: list[str],
    ) -> dict[str, list[str]]:
        """Map entity IDs to device IDs via HA device registry.

        Uses HA API: GET /api/config/entity_registry/list

        Args:
            entity_ids: List of entity IDs to map

        Returns:
            Dict mapping device_id -> [entity_id, entity_id, ...]
        """
        try:
            # Get entity registry
            entity_registry = await self.ha_client._request(
                "GET", "/api/config/entity_registry/list"
            )

            if not isinstance(entity_registry, list):
                logger.warning(f"Entity registry returned unexpected type: {type(entity_registry)}")
                return {}

            # Build mapping
            device_map: dict[str, list[str]] = {}
            entity_ids_set = set(entity_ids)

            for entity_entry in entity_registry:
                entity_id = entity_entry.get("entity_id")
                device_id = entity_entry.get("device_id")

                # Skip entities not in our list
                if entity_id not in entity_ids_set:
                    continue

                # Skip entities without device_id (some entities don't have devices)
                if not device_id:
                    logger.debug(f"Entity {entity_id} has no device_id, skipping")
                    continue

                # Add to device map
                if device_id not in device_map:
                    device_map[device_id] = []
                device_map[device_id].append(entity_id)

            logger.debug(f"Mapped {len(entity_ids)} entities to {len(device_map)} devices")
            return device_map

        except Exception as e:
            logger.error(f"Failed to get device mapping: {e}", exc_info=True)
            return {}

    async def _reconnect_device(
        self,
        device_id: str,
    ) -> bool:
        """Attempt device reconnection.

        Strategy:
        - Call integration-specific reconnect service if available
        - For Zigbee/Z-Wave: Use network-level reconnect
        - For Wi-Fi devices: Often not supported

        Args:
            device_id: Device ID to reconnect

        Returns:
            True on success, False otherwise
        """
        try:
            # Get device info to determine integration
            device_info = await self._get_device_info(device_id)
            if not device_info:
                logger.warning(f"Cannot reconnect: device {device_id} not found")
                return False

            integration = self._get_device_integration(device_info)
            logger.debug(f"Device {device_id} uses integration: {integration}")

            # Try integration-specific reconnect strategies
            if integration in ("zha", "zigbee2mqtt", "deconz"):
                # Zigbee networks - try reconfigure
                logger.info(f"Attempting Zigbee reconfigure for device {device_id}")
                try:
                    await self.ha_client.call_service(
                        domain=integration,
                        service="reconfigure_device",
                        service_data={"device_id": device_id},
                    )
                    await asyncio.sleep(2.0)  # Wait for reconfigure to complete
                    return True
                except Exception as e:
                    logger.debug(f"Zigbee reconfigure failed: {e}")
                    return False

            elif integration in ("zwave_js", "ozw"):
                # Z-Wave networks - try ping/heal
                logger.info(f"Attempting Z-Wave heal for device {device_id}")
                try:
                    await self.ha_client.call_service(
                        domain=integration,
                        service="ping",
                        service_data={"device_id": device_id},
                    )
                    await asyncio.sleep(2.0)
                    return True
                except Exception as e:
                    logger.debug(f"Z-Wave ping failed: {e}")
                    return False

            else:
                # Generic reconnect not supported for most integrations
                logger.debug(f"Reconnect not supported for integration: {integration}")
                return False

        except Exception as e:
            logger.error(f"Reconnect failed for device {device_id}: {e}", exc_info=True)
            return False

    async def _reboot_device(
        self,
        device_id: str,
    ) -> bool:
        """Attempt device reboot/power cycle.

        Strategy:
        - Call integration-specific reboot service if available
        - Use timeout (default: 30s) to wait for device to come back online
        - Check device availability after reboot

        Args:
            device_id: Device ID to reboot

        Returns:
            True on success, False otherwise
        """
        try:
            # Get device info
            device_info = await self._get_device_info(device_id)
            if not device_info:
                logger.warning(f"Cannot reboot: device {device_id} not found")
                return False

            integration = self._get_device_integration(device_info)

            # Try integration-specific reboot
            if integration in ("tuya", "tp_link", "shelly", "esphome"):
                logger.info(f"Attempting reboot for device {device_id} via {integration}")
                try:
                    # Different integrations use different service names
                    service_name = "reboot" if integration == "esphome" else "restart"

                    await asyncio.wait_for(
                        self.ha_client.call_service(
                            domain=integration,
                            service=service_name,
                            service_data={"device_id": device_id},
                        ),
                        timeout=10.0,
                    )

                    # Wait for device to come back online
                    logger.debug(f"Waiting {self.reboot_timeout_seconds}s for device to reboot")
                    await asyncio.sleep(self.reboot_timeout_seconds)

                    # Check if device is back online by getting its info
                    updated_info = await self._get_device_info(device_id)
                    return updated_info is not None

                except TimeoutError:
                    logger.warning(f"Reboot command timed out for device {device_id}")
                    return False
                except Exception as e:
                    logger.debug(f"Reboot failed: {e}")
                    return False

            else:
                logger.debug(f"Reboot not supported for integration: {integration}")
                return False

        except Exception as e:
            logger.error(f"Reboot failed for device {device_id}: {e}", exc_info=True)
            return False

    async def _rediscover_device(
        self,
        device_id: str,
    ) -> bool:
        """Attempt device re-discovery.

        Strategy:
        - Trigger integration discovery scan
        - Wait for device to be rediscovered

        Args:
            device_id: Device ID to rediscover

        Returns:
            True on success, False otherwise
        """
        try:
            # Get device info
            device_info = await self._get_device_info(device_id)
            if not device_info:
                logger.warning(f"Cannot rediscover: device {device_id} not found")
                return False

            integration = self._get_device_integration(device_info)
            config_entries = device_info.get("config_entries", [])

            if not config_entries:
                logger.warning(f"Device {device_id} has no config entries for rediscovery")
                return False

            # Reload the integration's config entry
            logger.info(f"Attempting rediscovery for device {device_id} via {integration}")
            for entry_id in config_entries:
                try:
                    await asyncio.wait_for(
                        self.ha_client.reload_integration(entry_id),
                        timeout=30.0,
                    )
                    # Wait for discovery to complete
                    await asyncio.sleep(5.0)

                    # Check if device still exists
                    updated_info = await self._get_device_info(device_id)
                    if updated_info:
                        logger.info(f"Device {device_id} rediscovered successfully")
                        return True

                except TimeoutError:
                    logger.warning(f"Rediscovery timed out for device {device_id}")
                except Exception as e:
                    logger.debug(f"Rediscovery failed for entry {entry_id}: {e}")

            return False

        except Exception as e:
            logger.error(f"Rediscovery failed for device {device_id}: {e}", exc_info=True)
            return False

    async def _record_action(
        self,
        device_id: str,
        action_type: str,
        triggered_by: str,
        automation_id: str | None,
        execution_id: int | None,
        success: bool,
        error_message: str | None,
        duration_seconds: float,
    ) -> None:
        """Record device healing action to database.

        Args:
            device_id: Device being healed
            action_type: Type of action ("reconnect", "reboot", "rediscover")
            triggered_by: What triggered healing
            automation_id: Optional automation ID
            execution_id: Optional execution ID
            success: Whether action succeeded
            error_message: Optional error message
            duration_seconds: Duration of action
        """
        async with self.database.async_session() as session:
            action = DeviceHealingAction(
                instance_id=self.instance_id,
                device_id=device_id,
                action_type=action_type,
                triggered_by=triggered_by,
                automation_id=automation_id,
                execution_id=execution_id,
                success=success,
                error_message=error_message,
                duration_seconds=duration_seconds,
                created_at=datetime.now(UTC),
            )
            session.add(action)
            await session.commit()

    async def _check_integration_features(
        self,
        device_id: str,
    ) -> dict[str, bool]:
        """Check which healing features are supported by device's integration.

        Returns dict with feature availability:
        {
            "reconnect": bool,
            "reboot": bool,
            "rediscover": bool,
        }

        Note: For MVP, we use heuristics based on integration domain.
        Future: Query actual integration capabilities.

        Args:
            device_id: Device to check

        Returns:
            Dictionary of supported features
        """
        try:
            device_info = await self._get_device_info(device_id)
            if not device_info:
                # Default: only rediscover supported (generic fallback)
                return {"reconnect": False, "reboot": False, "rediscover": True}

            integration = self._get_device_integration(device_info)

            # Integration-specific feature support
            if integration in ("zha", "zigbee2mqtt", "deconz"):
                # Zigbee
                return {"reconnect": True, "reboot": False, "rediscover": True}

            elif integration in ("zwave_js", "ozw"):
                # Z-Wave
                return {"reconnect": True, "reboot": False, "rediscover": True}

            elif integration in ("tuya", "tp_link", "wemo", "shelly", "esphome"):
                # Wi-Fi/Smart Plugs
                return {"reconnect": True, "reboot": True, "rediscover": True}

            else:
                # Unknown integration - only generic rediscover
                return {"reconnect": False, "reboot": False, "rediscover": True}

        except Exception as e:
            logger.debug(f"Failed to check features for device {device_id}: {e}")
            return {"reconnect": False, "reboot": False, "rediscover": True}

    async def _get_device_info(self, device_id: str) -> dict[str, Any] | None:
        """Get device information from HA device registry.

        Args:
            device_id: Device ID to look up

        Returns:
            Device info dictionary or None if not found
        """
        try:
            device_registry = await self.ha_client._request(
                "GET", "/api/config/device_registry/list"
            )

            if not isinstance(device_registry, list):
                return None

            for device in device_registry:
                if isinstance(device, dict) and device.get("id") == device_id:
                    return device

            return None

        except Exception as e:
            logger.debug(f"Failed to get device info for {device_id}: {e}")
            return None

    def _get_device_integration(self, device_info: dict[str, Any]) -> str:
        """Extract integration domain from device info.

        Args:
            device_info: Device information dictionary

        Returns:
            Integration domain (e.g., "zha", "zigbee2mqtt", "tuya")
        """
        # Try to get integration from config_entries
        config_entries = device_info.get("config_entries", [])
        if config_entries:
            # For now, just use "unknown" - we'd need to query config entries
            # to get the actual integration domain
            pass

        # Try manufacturer-based heuristics
        manufacturer = device_info.get("manufacturer", "").lower()
        if "philips" in manufacturer or "signify" in manufacturer:
            return "hue"
        elif "tuya" in manufacturer or "smart life" in manufacturer:
            return "tuya"
        elif "tp-link" in manufacturer or "kasa" in manufacturer:
            return "tp_link"
        elif "shelly" in manufacturer:
            return "shelly"
        elif "esphome" in manufacturer:
            return "esphome"

        # Default to unknown
        return "unknown"
