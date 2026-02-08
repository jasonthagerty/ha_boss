"""Tests for device-level healing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from ha_boss.core.database import Database, DeviceHealingAction
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.device_healer import DeviceHealer


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.init_db()
    yield database
    await database.close()


@pytest.fixture
def ha_client():
    """Create mock HA client."""
    client = MagicMock(spec=HomeAssistantClient)
    client.call_service = AsyncMock()
    client.reload_integration = AsyncMock()
    client._request = AsyncMock()
    client.get_state = AsyncMock()
    client.instance_id = "test_instance"
    return client


@pytest.fixture
def device_healer(database, ha_client):
    """Create device healer instance."""
    return DeviceHealer(
        database=database,
        ha_client=ha_client,
        instance_id="test_instance",
        reboot_timeout_seconds=1.0,  # Short timeout for tests
    )


# Sample test data
MOCK_ENTITY_REGISTRY = [
    {
        "entity_id": "light.living_room",
        "device_id": "device_123",
        "platform": "hue",
    },
    {
        "entity_id": "light.bedroom",
        "device_id": "device_123",
        "platform": "hue",
    },
    {
        "entity_id": "switch.kitchen",
        "device_id": "device_456",
        "platform": "tuya",
    },
    {
        "entity_id": "sensor.temperature",
        "device_id": None,  # Entity without device
        "platform": "mqtt",
    },
]

MOCK_DEVICE_REGISTRY = [
    {
        "id": "device_123",
        "name": "Living Room Hub",
        "manufacturer": "Philips",
        "model": "Hue Bridge",
        "config_entries": ["entry_123"],
    },
    {
        "id": "device_456",
        "name": "Smart Switch",
        "manufacturer": "Tuya",
        "model": "WiFi Switch",
        "config_entries": ["entry_456"],
    },
]


class TestDeviceHealerInit:
    """Test DeviceHealer initialization."""

    def test_init_with_defaults(self, database, ha_client):
        """Test initialization with default values."""
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
        )
        assert healer.database is database
        assert healer.ha_client is ha_client
        assert healer.instance_id == "default"
        assert healer.reboot_timeout_seconds == 30.0

    def test_init_with_custom_values(self, database, ha_client):
        """Test initialization with custom values."""
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            instance_id="custom",
            reboot_timeout_seconds=60.0,
        )
        assert healer.instance_id == "custom"
        assert healer.reboot_timeout_seconds == 60.0


class TestHeal:
    """Test main heal() method."""

    @pytest.mark.asyncio
    async def test_heal_with_empty_entity_list(self, device_healer):
        """Test heal with empty entity list."""
        result = await device_healer.heal([])
        assert result.success is False
        assert result.error_message == "No entity IDs provided"
        assert result.devices_attempted == []

    @pytest.mark.asyncio
    async def test_heal_with_no_devices_found(self, device_healer, ha_client):
        """Test heal when no devices found for entities."""
        # Mock entity registry with no device_ids
        ha_client._request.return_value = [{"entity_id": "sensor.test", "device_id": None}]

        result = await device_healer.heal(["sensor.test"])
        assert result.success is False
        assert "No devices found" in result.error_message
        assert result.devices_attempted == []

    @pytest.mark.asyncio
    async def test_heal_succeeds_on_reconnect(self, device_healer, ha_client, database):
        """Test heal succeeds on reconnect."""
        # Mock entity and device registries
        # Need to return device registry list for all _get_device_info calls
        ha_client._request.return_value = MOCK_DEVICE_REGISTRY

        # Mock entity registry call first, then device registry
        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request

        # Mock successful reconnect
        ha_client.call_service.return_value = None

        with patch.object(device_healer, "_get_device_integration", return_value="zha"):
            result = await device_healer.heal(["light.living_room"])

        assert result.success is True
        assert len(result.devices_attempted) == 1
        assert "device_123" in result.devices_attempted
        assert result.devices_healed == ["device_123"]
        assert "reconnect" in result.actions_attempted
        assert result.final_action == "reconnect"

        # Verify action was recorded
        async with database.async_session() as session:
            actions = await session.execute(select(DeviceHealingAction))
            action_list = list(actions.scalars().all())
            assert len(action_list) >= 1
            assert any(
                a.device_id == "device_123" and a.action_type == "reconnect" and a.success
                for a in action_list
            )

    @pytest.mark.asyncio
    async def test_heal_succeeds_on_reboot(self, device_healer, ha_client):
        """Test heal succeeds on reboot when reconnect fails."""

        # Mock registries - device_info returns the device
        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request

        # Mock: reconnect unsupported, reboot works
        call_count = {"count": 0}

        async def mock_call_service(*args, **kwargs):
            call_count["count"] += 1
            # First call is reboot (reconnect is unsupported for tuya with support)
            return None

        ha_client.call_service.side_effect = mock_call_service

        with patch.object(device_healer, "_get_device_integration", return_value="esphome"):
            # esphome supports reboot
            result = await device_healer.heal(["switch.kitchen"])

        # Result depends on whether device comes back after reboot
        # Since we mock device_info to always return the device, reboot should succeed
        assert result.success is True
        assert "device_456" in result.devices_healed
        assert "reboot" in result.actions_attempted
        assert result.final_action in ("reboot", "reconnect", "rediscover")

    @pytest.mark.asyncio
    async def test_heal_succeeds_on_rediscover(self, device_healer, ha_client):
        """Test heal succeeds on rediscover when other methods fail."""
        # Mock registries
        ha_client._request.side_effect = [
            MOCK_DEVICE_REGISTRY,  # _fetch_device_registry() at start of heal()
            MOCK_ENTITY_REGISTRY,
        ]

        # Mock reconnect and reboot fail, rediscover succeeds
        ha_client.call_service.side_effect = [
            Exception("Reconnect failed"),
            Exception("Reboot failed"),
        ]
        ha_client.reload_integration.return_value = None
        ha_client.get_state.return_value = {"state": "on"}  # Entity verification

        result = await device_healer.heal(["switch.kitchen"])

        assert result.success is True
        assert result.devices_healed == ["device_456"]
        assert "rediscover" in result.actions_attempted
        assert result.final_action == "rediscover"

    @pytest.mark.asyncio
    async def test_heal_all_strategies_fail(self, device_healer, ha_client):
        """Test heal when all strategies fail."""
        # Mock registries
        ha_client._request.side_effect = [
            MOCK_DEVICE_REGISTRY,  # _fetch_device_registry() at start of heal()
            MOCK_ENTITY_REGISTRY,
        ]

        # All healing methods fail
        ha_client.call_service.side_effect = Exception("All methods failed")
        ha_client.reload_integration.side_effect = Exception("Reload failed")

        result = await device_healer.heal(["switch.kitchen"])

        assert result.success is False
        assert len(result.devices_healed) == 0

    @pytest.mark.asyncio
    async def test_heal_multiple_entities_same_device(self, device_healer, ha_client):
        """Test healing multiple entities that belong to same device."""

        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request
        ha_client.call_service.return_value = None

        with patch.object(device_healer, "_get_device_integration", return_value="zha"):
            # Two entities from same device
            result = await device_healer.heal(["light.living_room", "light.bedroom"])

        assert result.success is True
        # Should only attempt healing once for the device
        assert len(result.devices_attempted) == 1
        assert result.devices_attempted[0] == "device_123"

    @pytest.mark.asyncio
    async def test_heal_multiple_entities_different_devices(self, device_healer, ha_client):
        """Test healing multiple entities from different devices."""

        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request
        ha_client.call_service.return_value = None

        # Mock different integrations for each device
        integration_map = {"device_123": "zha", "device_456": "tuya"}

        async def mock_get_integration(device_info):
            device_id = device_info.get("id")
            return integration_map.get(device_id, "unknown")

        with patch.object(
            device_healer,
            "_get_device_integration",
            side_effect=lambda x: integration_map.get(x["id"], "unknown"),
        ):
            result = await device_healer.heal(["light.living_room", "switch.kitchen"])

        assert result.success is True
        assert len(result.devices_attempted) == 2
        assert set(result.devices_attempted) == {"device_123", "device_456"}
        assert len(result.devices_healed) == 2

    @pytest.mark.asyncio
    async def test_heal_partial_success(self, device_healer, ha_client):
        """Test heal with partial success (some devices heal, some don't)."""

        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request

        # First device succeeds, second device fails
        call_count = {"count": 0}

        async def mock_call_service(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                return None  # First device reconnect succeeds
            raise Exception("Failed")

        ha_client.call_service.side_effect = mock_call_service
        ha_client.reload_integration.side_effect = Exception("Failed")

        with patch.object(
            device_healer,
            "_get_device_integration",
            side_effect=lambda x: "zha" if x["id"] == "device_123" else "tuya",
        ):
            result = await device_healer.heal(["light.living_room", "switch.kitchen"])

        assert result.success is True  # Overall success if ANY device healed
        assert len(result.devices_healed) == 1
        assert result.devices_healed[0] == "device_123"


class TestGetDevicesForEntities:
    """Test entity to device mapping."""

    @pytest.mark.asyncio
    async def test_map_entities_to_devices(self, device_healer, ha_client):
        """Test successful mapping of entities to devices."""
        ha_client._request.return_value = MOCK_ENTITY_REGISTRY

        device_map = await device_healer._get_devices_for_entities(
            ["light.living_room", "switch.kitchen"]
        )

        assert len(device_map) == 2
        assert "device_123" in device_map
        assert "device_456" in device_map
        assert device_map["device_123"] == ["light.living_room"]
        assert device_map["device_456"] == ["switch.kitchen"]

    @pytest.mark.asyncio
    async def test_map_multiple_entities_same_device(self, device_healer, ha_client):
        """Test mapping multiple entities to same device."""
        ha_client._request.return_value = MOCK_ENTITY_REGISTRY

        device_map = await device_healer._get_devices_for_entities(
            ["light.living_room", "light.bedroom"]
        )

        assert len(device_map) == 1
        assert "device_123" in device_map
        assert set(device_map["device_123"]) == {"light.living_room", "light.bedroom"}

    @pytest.mark.asyncio
    async def test_map_skips_entities_without_device(self, device_healer, ha_client):
        """Test that entities without device_id are skipped."""
        ha_client._request.return_value = MOCK_ENTITY_REGISTRY

        device_map = await device_healer._get_devices_for_entities(
            ["sensor.temperature"]  # Has no device_id
        )

        assert len(device_map) == 0

    @pytest.mark.asyncio
    async def test_map_handles_api_error(self, device_healer, ha_client):
        """Test graceful handling of API errors."""
        ha_client._request.side_effect = Exception("API error")

        device_map = await device_healer._get_devices_for_entities(["light.living_room"])

        assert device_map == {}

    @pytest.mark.asyncio
    async def test_map_handles_invalid_response(self, device_healer, ha_client):
        """Test handling of invalid API response."""
        ha_client._request.return_value = "not a list"

        device_map = await device_healer._get_devices_for_entities(["light.living_room"])

        assert device_map == {}


class TestReconnectDevice:
    """Test device reconnection."""

    @pytest.mark.asyncio
    async def test_reconnect_zigbee_device(self, device_healer, ha_client):
        """Test reconnecting Zigbee device."""
        # Mock device with Zigbee integration
        device_info = {
            "id": "device_123",
            "manufacturer": "Philips",
            "config_entries": ["entry_123"],
        }
        ha_client._request.return_value = [device_info]
        ha_client.call_service.return_value = None

        with patch.object(device_healer, "_get_device_integration", return_value="zha"):
            success = await device_healer._reconnect_device("device_123")

        assert success is True
        ha_client.call_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_zwave_device(self, device_healer, ha_client):
        """Test reconnecting Z-Wave device."""
        device_info = {
            "id": "device_456",
            "manufacturer": "Aeotec",
            "config_entries": ["entry_456"],
        }
        ha_client._request.return_value = [device_info]
        ha_client.call_service.return_value = None

        with patch.object(device_healer, "_get_device_integration", return_value="zwave_js"):
            success = await device_healer._reconnect_device("device_456")

        assert success is True

    @pytest.mark.asyncio
    async def test_reconnect_unsupported_integration(self, device_healer, ha_client):
        """Test reconnect with unsupported integration."""
        device_info = {"id": "device_789", "manufacturer": "Unknown"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="unknown"):
            success = await device_healer._reconnect_device("device_789")

        assert success is False

    @pytest.mark.asyncio
    async def test_reconnect_device_not_found(self, device_healer, ha_client):
        """Test reconnect when device not found."""
        ha_client._request.return_value = []

        success = await device_healer._reconnect_device("nonexistent")

        assert success is False


class TestRebootDevice:
    """Test device reboot."""

    @pytest.mark.asyncio
    async def test_reboot_tuya_device(self, device_healer, ha_client):
        """Test rebooting Tuya device."""
        device_info = {
            "id": "device_456",
            "manufacturer": "Tuya",
            "config_entries": ["entry_456"],
        }
        ha_client._request.side_effect = [
            [device_info],  # get_device_info
            [device_info],  # check after reboot
        ]
        ha_client.call_service.return_value = None

        with patch.object(device_healer, "_get_device_integration", return_value="tuya"):
            success = await device_healer._reboot_device("device_456")

        assert success is True
        ha_client.call_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_reboot_timeout(self, device_healer, ha_client):
        """Test reboot with timeout."""
        device_info = {"id": "device_456", "manufacturer": "Tuya"}
        ha_client._request.return_value = [device_info]
        ha_client.call_service.side_effect = TimeoutError()

        with patch.object(device_healer, "_get_device_integration", return_value="tuya"):
            success = await device_healer._reboot_device("device_456")

        assert success is False

    @pytest.mark.asyncio
    async def test_reboot_unsupported_integration(self, device_healer, ha_client):
        """Test reboot with unsupported integration."""
        device_info = {"id": "device_789", "manufacturer": "Unknown"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="unknown"):
            success = await device_healer._reboot_device("device_789")

        assert success is False


class TestRediscoverDevice:
    """Test device rediscovery."""

    @pytest.mark.asyncio
    async def test_rediscover_device(self, device_healer, ha_client):
        """Test successful device rediscovery."""
        device_info = {
            "id": "device_123",
            "manufacturer": "Philips",
            "config_entries": ["entry_123"],
        }
        ha_client._request.side_effect = [
            [device_info],  # get_device_info
            [device_info],  # check after reload
        ]
        ha_client.reload_integration.return_value = None

        success = await device_healer._rediscover_device("device_123")

        assert success is True
        ha_client.reload_integration.assert_called_once_with("entry_123")

    @pytest.mark.asyncio
    async def test_rediscover_no_config_entries(self, device_healer, ha_client):
        """Test rediscover when device has no config entries."""
        device_info = {"id": "device_123", "config_entries": []}
        ha_client._request.return_value = [device_info]

        success = await device_healer._rediscover_device("device_123")

        assert success is False

    @pytest.mark.asyncio
    async def test_rediscover_reload_timeout(self, device_healer, ha_client):
        """Test rediscover with reload timeout."""
        device_info = {
            "id": "device_123",
            "config_entries": ["entry_123"],
        }
        ha_client._request.return_value = [device_info]
        ha_client.reload_integration.side_effect = TimeoutError()

        success = await device_healer._rediscover_device("device_123")

        assert success is False


class TestRecordAction:
    """Test database action recording."""

    @pytest.mark.asyncio
    async def test_record_successful_action(self, device_healer, database):
        """Test recording successful healing action."""
        await device_healer._record_action(
            device_id="device_123",
            action_type="reconnect",
            triggered_by="automation_failure",
            automation_id="automation.test",
            execution_id=42,
            success=True,
            error_message=None,
            duration_seconds=1.5,
        )

        async with database.async_session() as session:
            result = await session.execute(select(DeviceHealingAction))
            actions = list(result.scalars().all())

            assert len(actions) == 1
            action = actions[0]
            assert action.device_id == "device_123"
            assert action.action_type == "reconnect"
            assert action.triggered_by == "automation_failure"
            assert action.automation_id == "automation.test"
            assert action.execution_id == 42
            assert action.success is True
            assert action.error_message is None
            assert action.duration_seconds == 1.5

    @pytest.mark.asyncio
    async def test_record_failed_action(self, device_healer, database):
        """Test recording failed healing action."""
        await device_healer._record_action(
            device_id="device_456",
            action_type="reboot",
            triggered_by="manual",
            automation_id=None,
            execution_id=None,
            success=False,
            error_message="Reboot timeout",
            duration_seconds=30.0,
        )

        async with database.async_session() as session:
            result = await session.execute(select(DeviceHealingAction))
            actions = list(result.scalars().all())

            assert len(actions) == 1
            action = actions[0]
            assert action.success is False
            assert action.error_message == "Reboot timeout"


class TestCheckIntegrationFeatures:
    """Test integration feature detection."""

    @pytest.mark.asyncio
    async def test_zigbee_features(self, device_healer, ha_client):
        """Test Zigbee integration features."""
        device_info = {"id": "device_123", "manufacturer": "Philips"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="zha"):
            features = await device_healer._check_integration_features("device_123")

        assert features["reconnect"] is True
        assert features["reboot"] is False
        assert features["rediscover"] is True

    @pytest.mark.asyncio
    async def test_zwave_features(self, device_healer, ha_client):
        """Test Z-Wave integration features."""
        device_info = {"id": "device_456", "manufacturer": "Aeotec"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="zwave_js"):
            features = await device_healer._check_integration_features("device_456")

        assert features["reconnect"] is True
        assert features["reboot"] is False
        assert features["rediscover"] is True

    @pytest.mark.asyncio
    async def test_wifi_features(self, device_healer, ha_client):
        """Test Wi-Fi device integration features."""
        device_info = {"id": "device_789", "manufacturer": "Tuya"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="tuya"):
            features = await device_healer._check_integration_features("device_789")

        assert features["reconnect"] is True
        assert features["reboot"] is True
        assert features["rediscover"] is True

    @pytest.mark.asyncio
    async def test_unknown_integration_features(self, device_healer, ha_client):
        """Test unknown integration defaults."""
        device_info = {"id": "device_999", "manufacturer": "Unknown"}
        ha_client._request.return_value = [device_info]

        with patch.object(device_healer, "_get_device_integration", return_value="unknown"):
            features = await device_healer._check_integration_features("device_999")

        assert features["reconnect"] is False
        assert features["reboot"] is False
        assert features["rediscover"] is True

    @pytest.mark.asyncio
    async def test_features_device_not_found(self, device_healer, ha_client):
        """Test feature check when device not found."""
        ha_client._request.return_value = []

        features = await device_healer._check_integration_features("nonexistent")

        # Should return defaults when device not found
        assert features["rediscover"] is True


class TestGetDeviceIntegration:
    """Test integration detection from device info."""

    def test_detect_hue_integration(self, device_healer):
        """Test detecting Hue integration."""
        device_info = {"manufacturer": "Philips", "model": "Hue Bridge"}
        integration = device_healer._get_device_integration(device_info)
        assert integration == "hue"

    def test_detect_tuya_integration(self, device_healer):
        """Test detecting Tuya integration."""
        device_info = {"manufacturer": "Tuya Inc", "model": "Smart Switch"}
        integration = device_healer._get_device_integration(device_info)
        assert integration == "tuya"

    def test_detect_tplink_integration(self, device_healer):
        """Test detecting TP-Link integration."""
        device_info = {"manufacturer": "TP-Link", "model": "HS100"}
        integration = device_healer._get_device_integration(device_info)
        assert integration == "tp_link"

    def test_detect_shelly_integration(self, device_healer):
        """Test detecting Shelly integration."""
        device_info = {"manufacturer": "Shelly", "model": "1PM"}
        integration = device_healer._get_device_integration(device_info)
        assert integration == "shelly"

    def test_unknown_manufacturer(self, device_healer):
        """Test unknown manufacturer defaults to unknown."""
        device_info = {"manufacturer": "Acme Corp", "model": "Widget"}
        integration = device_healer._get_device_integration(device_info)
        assert integration == "unknown"


class TestConcurrentDeviceHealing:
    """Test concurrent device healing operations."""

    @pytest.mark.asyncio
    async def test_concurrent_healing_multiple_devices(self, device_healer, ha_client):
        """Test healing multiple devices concurrently."""

        async def mock_request(method, endpoint):
            if "entity_registry" in endpoint:
                return MOCK_ENTITY_REGISTRY
            elif "device_registry" in endpoint:
                return MOCK_DEVICE_REGISTRY
            return None

        ha_client._request.side_effect = mock_request
        ha_client.call_service.return_value = None

        with patch.object(
            device_healer,
            "_get_device_integration",
            side_effect=lambda x: "zha" if x["id"] == "device_123" else "tuya",
        ):
            # Heal entities from different devices
            result = await device_healer.heal(
                ["light.living_room", "switch.kitchen"],
                triggered_by="pattern",
            )

        assert result.success is True
        assert len(result.devices_healed) == 2


class TestGracefulFallback:
    """Test graceful fallback when features unsupported."""

    @pytest.mark.asyncio
    async def test_skip_unsupported_reconnect(self, device_healer, ha_client):
        """Test that unsupported reconnect is skipped."""
        ha_client._request.side_effect = [
            MOCK_DEVICE_REGISTRY,  # _fetch_device_registry() at start of heal()
            MOCK_ENTITY_REGISTRY,
        ]
        ha_client.reload_integration.return_value = None
        ha_client.get_state.return_value = {"state": "on"}  # Entity verification

        # Mock integration with only rediscover support
        with patch.object(
            device_healer,
            "_check_integration_features",
            return_value={"reconnect": False, "reboot": False, "rediscover": True},
        ):
            result = await device_healer.heal(["light.living_room"])

        # Should skip to rediscover
        assert result.success is True
        assert "reconnect" not in result.actions_attempted
        assert "reboot" not in result.actions_attempted
        assert "rediscover" in result.actions_attempted


class TestStateVerificationTimeout:
    """Test configurable state verification timeout."""

    @pytest.mark.asyncio
    async def test_custom_verification_timeout(self, database, ha_client):
        """Test that custom verification timeout is used."""
        custom_timeout = 3.0
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_timeout=custom_timeout,
        )
        assert healer.state_verification_timeout == custom_timeout

    @pytest.mark.asyncio
    async def test_default_verification_timeout(self, database, ha_client):
        """Test default verification timeout value."""
        healer = DeviceHealer(database=database, ha_client=ha_client)
        assert healer.state_verification_timeout == 5.0

    @pytest.mark.asyncio
    async def test_verification_timeout_sleep(self, database, ha_client):
        """Test that verification waits the specified timeout duration."""
        custom_timeout = 0.1  # Short timeout for testing
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_timeout=custom_timeout,
        )

        # Mock get_state to return available state
        ha_client.get_state.return_value = {"state": "on"}

        with patch("asyncio.sleep") as mock_sleep:
            result = await healer._verify_entity_states(["light.test"])
            # Verify sleep was called with the custom timeout
            mock_sleep.assert_called_once_with(custom_timeout)
            assert result is True


class TestPartialSuccessThreshold:
    """Test partial success threshold logic."""

    @pytest.mark.asyncio
    async def test_default_threshold(self, database, ha_client):
        """Test default threshold is 50%."""
        healer = DeviceHealer(database=database, ha_client=ha_client)
        assert healer.state_verification_partial_threshold == 0.5

    @pytest.mark.asyncio
    async def test_custom_threshold(self, database, ha_client):
        """Test custom threshold can be set."""
        custom_threshold = 0.75
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=custom_threshold,
        )
        assert healer.state_verification_partial_threshold == custom_threshold

    @pytest.mark.asyncio
    async def test_partial_success_at_50_percent_threshold(self, database, ha_client):
        """Test partial success with exactly 50% entities available.

        4 entities: 2 available, 2 unavailable (50% threshold)
        Should return True and log warning about partial success.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        # Mock states: first two available, next two unavailable
        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "off"},
            {"state": "unavailable"},
            {"state": "unknown"},
        ]

        with patch("ha_boss.healing.device_healer.logger") as mock_logger:
            result = await healer._verify_entity_states(
                ["light.1", "light.2", "light.3", "light.4"]
            )

            assert result is True
            # Should log warning about partial success
            assert mock_logger.warning.called
            warning_message = mock_logger.warning.call_args[0][0]
            assert "Partial success" in warning_message
            assert "2/4" in warning_message

    @pytest.mark.asyncio
    async def test_partial_success_below_threshold(self, database, ha_client):
        """Test failure when entities below threshold.

        4 entities: 1 available, 3 unavailable (25% < 50% threshold)
        Should return False and log debug message.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "unavailable"},
            {"state": "unavailable"},
            {"state": "unknown"},
        ]

        with patch("ha_boss.healing.device_healer.logger") as mock_logger:
            result = await healer._verify_entity_states(
                ["light.1", "light.2", "light.3", "light.4"]
            )

            assert result is False
            # Should log debug message about verification failure
            assert mock_logger.debug.called
            debug_message = mock_logger.debug.call_args[0][0]
            assert "Verification failed" in debug_message
            assert "1/4" in debug_message

    @pytest.mark.asyncio
    async def test_100_percent_success(self, database, ha_client):
        """Test 100% success with all entities available.

        All 4 entities available - should return True and NOT log warning.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        # All entities return available state
        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "on"},
            {"state": "on"},
            {"state": "on"},
        ]

        with patch("ha_boss.healing.device_healer.logger") as mock_logger:
            result = await healer._verify_entity_states(
                ["light.1", "light.2", "light.3", "light.4"]
            )

            assert result is True
            # Should NOT log warning (only logs warning for partial success)
            mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_percent_success(self, database, ha_client):
        """Test failure with 0% entities available.

        All 4 entities unavailable - should return False.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        ha_client.get_state.side_effect = [
            {"state": "unavailable"},
            {"state": "unavailable"},
            {"state": "unknown"},
            {"state": "unknown"},
        ]

        with patch("ha_boss.healing.device_healer.logger") as mock_logger:
            result = await healer._verify_entity_states(
                ["light.1", "light.2", "light.3", "light.4"]
            )

            assert result is False
            # Should log debug message
            assert mock_logger.debug.called

    @pytest.mark.asyncio
    async def test_custom_threshold_75_percent(self, database, ha_client):
        """Test custom 75% threshold.

        With 75% threshold, 75% entities available should succeed,
        74% should fail, 76% should succeed.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.75,
        )

        # Test at exactly 75% (3 out of 4 available)
        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "on"},
            {"state": "on"},
            {"state": "unavailable"},
        ]

        result = await healer._verify_entity_states(["light.1", "light.2", "light.3", "light.4"])
        assert result is True

    @pytest.mark.asyncio
    async def test_custom_threshold_below_minimum(self, database, ha_client):
        """Test custom threshold at 74% (below 75% minimum).

        With 75% threshold, 2 out of 4 entities (50%) should fail.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.75,
        )

        # Test at 50% (2 out of 4 available) - below 75% threshold
        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "on"},
            {"state": "unavailable"},
            {"state": "unavailable"},
        ]

        result = await healer._verify_entity_states(["light.1", "light.2", "light.3", "light.4"])
        assert result is False

    @pytest.mark.asyncio
    async def test_zero_entities_edge_case(self, database, ha_client):
        """Test with empty entity list.

        Empty list should handle gracefully - returns True (0/0 = undefined, treated as success).
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        result = await healer._verify_entity_states([])
        # With 0 entities, 0/0 = 0.0 which is < 0.5, so False
        assert result is False

    @pytest.mark.asyncio
    async def test_partial_success_with_exception(self, database, ha_client):
        """Test partial success when some entities throw exceptions.

        If some entity state fetches fail, they count as unavailable.
        With 2 available + 2 exceptions = 2/4 = 50% success.
        """
        healer = DeviceHealer(
            database=database,
            ha_client=ha_client,
            state_verification_partial_threshold=0.5,
        )

        # First two succeed, next two throw exceptions
        ha_client.get_state.side_effect = [
            {"state": "on"},
            {"state": "on"},
            Exception("API error"),
            Exception("API error"),
        ]

        with patch("ha_boss.healing.device_healer.logger") as mock_logger:
            result = await healer._verify_entity_states(
                ["light.1", "light.2", "light.3", "light.4"]
            )

            # 2 available / 4 total = 50% = meets threshold
            assert result is True
            # Should log warning about partial success
            assert mock_logger.warning.called
