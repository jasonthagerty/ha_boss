"""Tests for integration discovery and management."""

import json
from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig
from ha_boss.core.database import Integration, init_database
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.integration_manager import IntegrationDiscovery


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
async def database(tmp_path):
    """Create test database."""
    db = await init_database(tmp_path / "test.db")
    yield db
    await db.close()


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    return AsyncMock(spec=HomeAssistantClient)


@pytest.fixture
def integration_discovery(mock_ha_client, database, mock_config):
    """Create IntegrationDiscovery instance."""
    return IntegrationDiscovery(mock_ha_client, database, mock_config)


@pytest.fixture
def mock_storage_files(tmp_path):
    """Create mock HA storage files."""
    storage_dir = tmp_path / ".storage"
    storage_dir.mkdir()

    # Mock core.config_entries
    config_entries = {
        "version": 1,
        "minor_version": 1,
        "key": "core.config_entries",
        "data": {
            "entries": [
                {
                    "entry_id": "abc123",
                    "version": 1,
                    "domain": "hue",
                    "title": "Philips Hue",
                    "data": {},
                    "options": {},
                    "system_options": {},
                    "source": "user",
                    "unique_id": None,
                    "disabled_by": None,
                },
                {
                    "entry_id": "def456",
                    "version": 1,
                    "domain": "zwave_js",
                    "title": "Z-Wave JS",
                    "data": {},
                    "options": {},
                    "system_options": {},
                    "source": "user",
                    "unique_id": None,
                    "disabled_by": None,
                },
            ]
        },
    }

    # Mock core.entity_registry
    entity_registry = {
        "version": 1,
        "minor_version": 1,
        "key": "core.entity_registry",
        "data": {
            "entities": [
                {
                    "entity_id": "light.living_room",
                    "config_entry_id": "abc123",
                    "device_id": "device1",
                    "area_id": None,
                    "unique_id": "hue_light_1",
                    "platform": "hue",
                    "name": None,
                    "icon": None,
                    "disabled_by": None,
                },
                {
                    "entity_id": "light.bedroom",
                    "config_entry_id": "abc123",
                    "device_id": "device2",
                    "area_id": None,
                    "unique_id": "hue_light_2",
                    "platform": "hue",
                    "name": None,
                    "icon": None,
                    "disabled_by": None,
                },
                {
                    "entity_id": "sensor.temperature",
                    "config_entry_id": "def456",
                    "device_id": "device3",
                    "area_id": None,
                    "unique_id": "zwave_sensor_1",
                    "platform": "zwave_js",
                    "name": None,
                    "icon": None,
                    "disabled_by": None,
                },
            ]
        },
    }

    (storage_dir / "core.config_entries").write_text(json.dumps(config_entries))
    (storage_dir / "core.entity_registry").write_text(json.dumps(entity_registry))

    return storage_dir


@pytest.mark.asyncio
async def test_discover_from_storage(integration_discovery, mock_storage_files):
    """Test discovering integrations from storage files."""
    await integration_discovery._discover_from_storage(mock_storage_files)

    # Should have discovered 2 integrations
    assert len(integration_discovery._integrations) == 2
    assert "abc123" in integration_discovery._integrations
    assert "def456" in integration_discovery._integrations

    # Check integration details
    hue_integration = integration_discovery._integrations["abc123"]
    assert hue_integration["domain"] == "hue"
    assert hue_integration["title"] == "Philips Hue"

    # Should have mapped 3 entities
    assert len(integration_discovery._entity_to_integration) == 3
    assert integration_discovery._entity_to_integration["light.living_room"] == "abc123"
    assert integration_discovery._entity_to_integration["light.bedroom"] == "abc123"
    assert integration_discovery._entity_to_integration["sensor.temperature"] == "def456"


@pytest.mark.asyncio
async def test_discover_from_storage_missing_files(integration_discovery, tmp_path):
    """Test handling of missing storage files."""
    with pytest.raises(FileNotFoundError):
        await integration_discovery._discover_from_storage(tmp_path)


@pytest.mark.asyncio
async def test_discover_from_api(integration_discovery, mock_ha_client):
    """Test discovering integrations from API."""
    # Mock get_states response
    mock_ha_client.get_states.return_value = [
        {"entity_id": "light.living_room", "state": "on"},
        {"entity_id": "sensor.temperature", "state": "20.5"},
        {"entity_id": "switch.outlet", "state": "off"},
    ]

    # Mock get_config response
    mock_ha_client.get_config.return_value = {"version": "2024.1.0"}

    await integration_discovery._discover_from_api()

    # Should have created domain-based pseudo-integrations
    assert len(integration_discovery._integrations) == 3
    assert "domain_light" in integration_discovery._integrations
    assert "domain_sensor" in integration_discovery._integrations
    assert "domain_switch" in integration_discovery._integrations

    # Should have mapped all 3 entities
    assert len(integration_discovery._entity_to_integration) == 3
    assert integration_discovery._entity_to_integration["light.living_room"] == "domain_light"
    assert integration_discovery._entity_to_integration["sensor.temperature"] == "domain_sensor"


@pytest.mark.asyncio
async def test_discover_all_with_storage(integration_discovery, mock_storage_files, mock_ha_client):
    """Test complete discovery with storage files."""
    mock_ha_client.get_config.return_value = {"version": "2024.1.0"}

    mappings = await integration_discovery.discover_all(storage_path=mock_storage_files)

    # Should have discovered from storage
    assert len(mappings) == 3
    assert "light.living_room" in mappings
    assert "sensor.temperature" in mappings


@pytest.mark.asyncio
async def test_discover_all_api_fallback(integration_discovery, mock_ha_client):
    """Test API fallback when storage unavailable."""
    mock_ha_client.get_states.return_value = [
        {"entity_id": "light.living_room", "state": "on"},
    ]
    mock_ha_client.get_config.return_value = {"version": "2024.1.0"}

    # No storage path provided, should fall back to API
    mappings = await integration_discovery.discover_all()

    assert len(mappings) == 1
    assert "light.living_room" in mappings


@pytest.mark.asyncio
async def test_discover_all_failure(integration_discovery, mock_ha_client):
    """Test handling when all discovery methods fail."""
    # Make API discovery fail
    mock_ha_client.get_states.side_effect = Exception("API error")

    with pytest.raises(Exception, match="Failed to discover any integrations"):
        await integration_discovery.discover_all()


@pytest.mark.asyncio
async def test_save_and_load_from_database(integration_discovery, mock_storage_files, database):
    """Test persisting and loading from database."""
    # Discover from storage
    await integration_discovery._discover_from_storage(mock_storage_files)

    # Save to database
    await integration_discovery._save_to_database()

    # Create new instance and load from database
    new_discovery = IntegrationDiscovery(
        AsyncMock(spec=HomeAssistantClient),
        database,
        Config(home_assistant=HomeAssistantConfig(url="http://test", token="test")),
    )

    await new_discovery._load_from_database()

    # Should have loaded integrations and mappings
    assert len(new_discovery._integrations) == 2
    assert len(new_discovery._entity_to_integration) == 3


@pytest.mark.asyncio
async def test_get_integration_for_entity(integration_discovery, mock_storage_files):
    """Test looking up integration for entity."""
    await integration_discovery._discover_from_storage(mock_storage_files)

    entry_id = integration_discovery.get_integration_for_entity("light.living_room")
    assert entry_id == "abc123"

    # Unknown entity returns None
    assert integration_discovery.get_integration_for_entity("light.unknown") is None


@pytest.mark.asyncio
async def test_get_integration_details(integration_discovery, mock_storage_files):
    """Test getting integration details."""
    await integration_discovery._discover_from_storage(mock_storage_files)

    details = integration_discovery.get_integration_details("abc123")
    assert details is not None
    assert details["domain"] == "hue"
    assert details["title"] == "Philips Hue"

    # Unknown integration returns None
    assert integration_discovery.get_integration_details("unknown") is None


@pytest.mark.asyncio
async def test_get_all_integrations(integration_discovery, mock_storage_files):
    """Test getting all integrations."""
    await integration_discovery._discover_from_storage(mock_storage_files)

    all_integrations = integration_discovery.get_all_integrations()
    assert len(all_integrations) == 2
    assert "abc123" in all_integrations
    assert "def456" in all_integrations


@pytest.mark.asyncio
async def test_get_entity_count(integration_discovery, mock_storage_files):
    """Test getting entity count."""
    await integration_discovery._discover_from_storage(mock_storage_files)

    count = integration_discovery.get_entity_count()
    assert count == 3


@pytest.mark.asyncio
async def test_add_manual_mapping(integration_discovery):
    """Test adding manual entity→integration mapping."""
    await integration_discovery.add_manual_mapping(
        entity_id="sensor.custom",
        entry_id="manual123",
        domain="custom",
        title="Custom Integration",
    )

    # Should be in cache
    assert integration_discovery.get_integration_for_entity("sensor.custom") == "manual123"

    details = integration_discovery.get_integration_details("manual123")
    assert details is not None
    assert details["domain"] == "custom"
    assert details["title"] == "Custom Integration"
    assert details["source"] == "manual"


@pytest.mark.asyncio
async def test_discover_all_persists_to_database(
    integration_discovery, mock_storage_files, mock_ha_client, database
):
    """Test that discover_all persists results to database."""
    mock_ha_client.get_config.return_value = {"version": "2024.1.0"}

    await integration_discovery.discover_all(storage_path=mock_storage_files)

    # Verify data was saved to database
    async with database.async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(Integration))
        integrations = result.scalars().all()

        assert len(integrations) == 2
        entry_ids = {i.entry_id for i in integrations}
        assert "abc123" in entry_ids
        assert "def456" in entry_ids
