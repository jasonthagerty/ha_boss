"""Tests for the deep end-to-end self-test."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.config import Config
from ha_boss.core.database import (
    AutomationEntity,
    DiscoveryRefresh,
    SceneEntity,
    init_database,
)
from ha_boss.monitoring.deep_selftest import DeepSelfTest


@pytest.fixture
def config() -> Config:
    """Config with the self-test enabled."""
    return Config(
        home_assistant={"url": "http://localhost:8123", "token": "test_token"},
        self_test={"enabled": True},
    )


@pytest.fixture
def ha_client() -> MagicMock:
    """Mock REST client."""
    client = MagicMock()
    client.get_config = AsyncMock(return_value={"version": "2026.7.2"})
    client.call_service = AsyncMock()
    return client


@pytest.fixture
def notification_manager() -> MagicMock:
    """Mock notification manager."""
    manager = MagicMock()
    manager.notify = AsyncMock()
    manager.dismiss = AsyncMock()
    manager.notification_id_for = MagicMock(return_value="haboss_self_check_selftest")
    return manager


@pytest.fixture
def ws_client() -> MagicMock:
    """Mock WebSocket client reporting connected."""
    client = MagicMock()
    client.is_connected = MagicMock(return_value=True)
    return client


async def _seed_discovery(
    db, automations_found: int, automation_refs: int, scene_refs: int
) -> None:
    """Seed a successful refresh row plus junction rows."""
    async with db.async_session() as session:
        session.add(
            DiscoveryRefresh(
                instance_id="default",
                trigger_type="periodic",
                trigger_source="test",
                automations_found=automations_found,
                scenes_found=1,
                scripts_found=0,
                entities_discovered=automation_refs + scene_refs,
                duration_seconds=0.1,
                timestamp=datetime.now(UTC),
                success=True,
            )
        )
        for i in range(automation_refs):
            session.add(
                AutomationEntity(
                    instance_id="default",
                    automation_id=f"automation.test_{i}",
                    entity_id=f"light.test_{i}",
                    relationship_type="action",
                    discovered_at=datetime.now(UTC),
                )
            )
        for i in range(scene_refs):
            session.add(
                SceneEntity(
                    instance_id="default",
                    scene_id="scene.test",
                    entity_id=f"switch.test_{i}",
                    discovered_at=datetime.now(UTC),
                )
            )
        await session.commit()


def _make_selftest(config, ha_client, db, notification_manager, ws_client) -> DeepSelfTest:
    return DeepSelfTest(
        config=config,
        ha_client=ha_client,
        database=db,
        notification_manager=notification_manager,
        websocket_client=ws_client,
        instance_id="default",
    )


@pytest.mark.asyncio
async def test_all_checks_pass(tmp_path, config, ha_client, notification_manager, ws_client):
    """Healthy system → PASS verdict written, prior warning dismissed."""
    db = await init_database(tmp_path / "test.db")
    try:
        await _seed_discovery(db, automations_found=5, automation_refs=3, scene_refs=2)
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)

        with patch("ha_boss.monitoring.deep_selftest.run_self_check", AsyncMock(return_value=[])):
            problems = await selftest.run(trigger="startup")

        assert problems == []
        verdicts = [
            c.args for c in ha_client.call_service.await_args_list if c.args[0] == "input_text"
        ]
        assert len(verdicts) == 1
        assert verdicts[0][2]["value"].startswith("PASS ha=2026.7.2")
        notification_manager.dismiss.assert_awaited_once()
        notification_manager.notify.assert_not_awaited()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_detects_broken_automation_extraction(
    tmp_path, config, ha_client, notification_manager, ws_client
):
    """Objects found but zero junction rows → FAIL (the scenes-only regression)."""
    db = await init_database(tmp_path / "test.db")
    try:
        await _seed_discovery(db, automations_found=53, automation_refs=0, scene_refs=39)
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)

        with patch("ha_boss.monitoring.deep_selftest.run_self_check", AsyncMock(return_value=[])):
            problems = await selftest.run(trigger="startup")

        assert any("automations" in p and "extraction is broken" in p for p in problems)
        verdicts = [
            c.args for c in ha_client.call_service.await_args_list if c.args[0] == "input_text"
        ]
        assert verdicts[0][2]["value"].startswith("FAIL(")
        notification_manager.notify.assert_awaited_once()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ws_disconnected_is_a_problem(
    tmp_path, config, ha_client, notification_manager, ws_client
):
    """A disconnected WebSocket fails the test."""
    db = await init_database(tmp_path / "test.db")
    try:
        await _seed_discovery(db, automations_found=5, automation_refs=3, scene_refs=2)
        ws_client.is_connected = MagicMock(return_value=False)
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)

        with patch("ha_boss.monitoring.deep_selftest.run_self_check", AsyncMock(return_value=[])):
            problems = await selftest.run(trigger="startup")

        assert any("WebSocket" in p for p in problems)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_switch_trigger_resets_request_helper(
    tmp_path, config, ha_client, notification_manager, ws_client
):
    """An on-demand run turns the request input_boolean back off."""
    db = await init_database(tmp_path / "test.db")
    try:
        await _seed_discovery(db, automations_found=5, automation_refs=3, scene_refs=2)
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)

        with patch("ha_boss.monitoring.deep_selftest.run_self_check", AsyncMock(return_value=[])):
            await selftest.run(trigger="switch")

        resets = [
            c.args for c in ha_client.call_service.await_args_list if c.args[0] == "input_boolean"
        ]
        assert resets == [
            ("input_boolean", "turn_off", {"entity_id": config.self_test.request_entity_id})
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_version_change_triggers_run(
    tmp_path, config, ha_client, notification_manager, ws_client
):
    """First sighting stores quietly; a changed version runs the self-test."""
    db = await init_database(tmp_path / "test.db")
    try:
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)
        selftest.run = AsyncMock(return_value=[])  # type: ignore[method-assign]

        assert await selftest.check_version_change("2026.7.2") is False
        selftest.run.assert_not_awaited()

        assert await selftest.check_version_change("2026.7.2") is False
        selftest.run.assert_not_awaited()

        assert await selftest.check_version_change("2026.8.0") is True
        selftest.run.assert_awaited_once_with(trigger="version_change")

        # The new version is persisted — seeing it again does not re-run
        selftest.run.reset_mock()
        assert await selftest.check_version_change("2026.8.0") is False
        selftest.run.assert_not_awaited()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unknown_version_is_ignored(
    tmp_path, config, ha_client, notification_manager, ws_client
):
    """A missing version in the handshake never triggers a run."""
    db = await init_database(tmp_path / "test.db")
    try:
        selftest = _make_selftest(config, ha_client, db, notification_manager, ws_client)
        selftest.run = AsyncMock(return_value=[])  # type: ignore[method-assign]

        assert await selftest.check_version_change(None) is False
        selftest.run.assert_not_awaited()
    finally:
        await db.close()
