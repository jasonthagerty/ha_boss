"""Tests for EntityDiscoveryService config fetching and relationship persistence.

Regression tests for the scenes-only discovery bug: automation and script entity
references must come from the REST config API (state attributes never carry
triggers/conditions/actions/sequence), and the junction tables must actually get
rows when automations/scripts reference entities.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from ha_boss.core.config import Config
from ha_boss.core.database import AutomationEntity, ScriptEntity, init_database
from ha_boss.discovery.entity_discovery import EntityDiscoveryService


@pytest.fixture
def config() -> Config:
    """Minimal config for discovery tests."""
    return Config(home_assistant={"url": "http://localhost:8123", "token": "test_token"})


@pytest.fixture
def ha_client() -> MagicMock:
    """Mock HA client with async API methods."""
    client = MagicMock()
    client.instance_id = "default"
    client.get_states = AsyncMock(return_value=[])
    client.get_automation_config = AsyncMock()
    client.get_script_config = AsyncMock()
    client.get_entity_registry = AsyncMock(return_value=[])
    return client


AUTOMATION_STATE = {
    "entity_id": "automation.family_room_display_control",
    "state": "on",
    "attributes": {
        "id": "1747334278571",
        "friendly_name": "Family Room - Display Control",
        "mode": "restart",
    },
}

MODERN_AUTOMATION_CONFIG = {
    "id": "1747334278571",
    "alias": "Family Room - Display Control",
    "mode": "restart",
    "triggers": [
        {"trigger": "state", "entity_id": "media_player.family_room_appletv", "to": "playing"},
    ],
    "conditions": [
        {"condition": "state", "entity_id": "sensor.sync_box_hdmi4_status", "state": "linked"},
    ],
    "actions": [
        {"action": "light.turn_off", "target": {"entity_id": "light.family_room"}},
    ],
}


@pytest.mark.asyncio
async def test_process_automation_fetches_config_and_persists_relationships(
    tmp_path, config, ha_client
) -> None:
    """Automation entity refs come from the fetched config, not state attributes."""
    db = await init_database(tmp_path / "test.db")
    try:
        ha_client.get_states = AsyncMock(return_value=[AUTOMATION_STATE])
        ha_client.get_automation_config = AsyncMock(return_value=MODERN_AUTOMATION_CONFIG)

        service = EntityDiscoveryService(ha_client, db, config)
        count = await service._fetch_and_process_automations()

        assert count == 1
        ha_client.get_automation_config.assert_awaited_once_with("1747334278571")

        async with db.async_session() as session:
            result = await session.execute(select(AutomationEntity.entity_id).distinct())
            entity_ids = {row[0] for row in result.all()}

        assert entity_ids == {
            "media_player.family_room_appletv",
            "sensor.sync_box_hdmi4_status",
            "light.family_room",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_automation_without_config_id_persists_nothing(
    tmp_path, config, ha_client
) -> None:
    """An automation without an 'id' attribute cannot be config-fetched."""
    db = await init_database(tmp_path / "test.db")
    try:
        state = {
            "entity_id": "automation.yaml_no_id",
            "state": "on",
            "attributes": {"friendly_name": "YAML automation"},
        }
        ha_client.get_states = AsyncMock(return_value=[state])

        service = EntityDiscoveryService(ha_client, db, config)
        count = await service._fetch_and_process_automations()

        assert count == 1
        ha_client.get_automation_config.assert_not_awaited()

        async with db.async_session() as session:
            result = await session.execute(select(AutomationEntity))
            assert result.scalars().all() == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_automation_survives_config_fetch_error(tmp_path, config, ha_client) -> None:
    """A failed config fetch degrades to no relationships without aborting the refresh."""
    db = await init_database(tmp_path / "test.db")
    try:
        ha_client.get_states = AsyncMock(return_value=[AUTOMATION_STATE])
        ha_client.get_automation_config = AsyncMock(side_effect=RuntimeError("boom"))

        service = EntityDiscoveryService(ha_client, db, config)
        count = await service._fetch_and_process_automations()

        assert count == 1
        async with db.async_session() as session:
            result = await session.execute(select(AutomationEntity))
            assert result.scalars().all() == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_script_fetches_config_and_persists_relationships(
    tmp_path, config, ha_client
) -> None:
    """Script entity refs come from the fetched config's sequence."""
    db = await init_database(tmp_path / "test.db")
    try:
        state = {
            "entity_id": "script.family_room_tv_on",
            "state": "off",
            "attributes": {"friendly_name": "Family Room - TV On", "mode": "single"},
        }
        script_config = {
            "alias": "Family Room - TV On",
            "mode": "single",
            "sequence": [
                {
                    "if": [
                        {
                            "condition": "state",
                            "entity_id": "media_player.lg_webos_tv_oled65c8pua",
                            "state": ["off", "unavailable"],
                        }
                    ],
                    "then": [{"action": "wake_on_lan.send_magic_packet", "data": {"mac": "x"}}],
                }
            ],
        }
        ha_client.get_states = AsyncMock(return_value=[state])
        ha_client.get_script_config = AsyncMock(return_value=script_config)

        service = EntityDiscoveryService(ha_client, db, config)
        count = await service._fetch_and_process_scripts()

        assert count == 1
        ha_client.get_script_config.assert_awaited_once_with("family_room_tv_on")

        async with db.async_session() as session:
            result = await session.execute(select(ScriptEntity.entity_id).distinct())
            entity_ids = {row[0] for row in result.all()}

        assert entity_ids == {"media_player.lg_webos_tv_oled65c8pua"}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_script_uses_registry_unique_id_for_renamed_script(
    tmp_path, config, ha_client
) -> None:
    """A renamed script's config lives under its registry unique_id, not its entity_id."""
    db = await init_database(tmp_path / "test.db")
    try:
        state = {
            "entity_id": "script.run_the_vacuum",
            "state": "off",
            "attributes": {"friendly_name": "Cleaning - Run All Vacuums"},
        }
        ha_client.get_states = AsyncMock(return_value=[state])
        ha_client.get_entity_registry = AsyncMock(
            return_value=[
                {"entity_id": "script.run_the_vacuum", "unique_id": "run_the_vacume"},
                {"entity_id": "light.unrelated", "unique_id": "xyz"},
            ]
        )
        ha_client.get_script_config = AsyncMock(
            return_value={
                "sequence": [{"action": "vacuum.start", "target": {"entity_id": "vacuum.roo"}}]
            }
        )

        service = EntityDiscoveryService(ha_client, db, config)
        count = await service._fetch_and_process_scripts()

        assert count == 1
        ha_client.get_script_config.assert_awaited_once_with("run_the_vacume")

        async with db.async_session() as session:
            result = await session.execute(select(ScriptEntity.entity_id).distinct())
            entity_ids = {row[0] for row in result.all()}

        assert entity_ids == {"vacuum.roo"}
    finally:
        await db.close()
