"""Tests for out-of-scope entity audit."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.core.config import (
    Config,
    HomeAssistantConfig,
    MonitoringConfig,
    NotificationsConfig,
    OutOfScopeAuditConfig,
)
from ha_boss.core.database import OutOfScopeAuditStatus
from ha_boss.monitoring.out_of_scope_audit import OutOfScopeAuditor
from ha_boss.notifications.manager import NotificationChannel
from ha_boss.notifications.templates import NotificationSeverity, NotificationType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(
    *,
    enabled: bool = True,
    interval_seconds: int = 86400,
    chronic_threshold_seconds: int = 259200,
    include_stale: bool = False,
    group_by_integration: bool = True,
) -> Config:
    """Build a minimal Config with the given out_of_scope_audit settings."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://homeassistant.local:8123",
            token="test_token",
        ),
        monitoring=MonitoringConfig(
            out_of_scope_audit=OutOfScopeAuditConfig(
                enabled=enabled,
                interval_seconds=interval_seconds,
                chronic_threshold_seconds=chronic_threshold_seconds,
                include_stale=include_stale,
                group_by_integration=group_by_integration,
            ),
        ),
        notifications=NotificationsConfig(on_healing_failure=False),
        mode="production",
    )


def _make_state(entity_id: str, state: str, last_updated: str | None = None) -> dict:
    """Create a minimal HA state dict."""
    return {
        "entity_id": entity_id,
        "state": state,
        "last_updated": last_updated or datetime.now(UTC).isoformat(),
        "attributes": {},
    }


def _make_baseline_row(
    entity_id: str,
    instance_id: str = "default",
    first_unavailable_at: datetime | None = None,
    last_state: str = "unavailable",
) -> OutOfScopeAuditStatus:
    """Create a mock OutOfScopeAuditStatus row."""
    row = MagicMock(spec=OutOfScopeAuditStatus)
    row.entity_id = entity_id
    row.instance_id = instance_id
    row.first_unavailable_at = first_unavailable_at or datetime.now(UTC)
    row.last_state = last_state
    row.last_seen_at = datetime.now(UTC)
    return row


@pytest.fixture
def mock_ha_client() -> AsyncMock:
    client = AsyncMock()
    client.get_states = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_entity_discovery() -> MagicMock:
    svc = MagicMock()
    svc.get_monitored_entities = MagicMock(return_value=set())
    return svc


@pytest.fixture
def mock_integration_discovery() -> MagicMock:
    disc = MagicMock()
    disc.get_integration_for_entity = MagicMock(return_value=None)
    disc.get_domain = MagicMock(return_value=None)
    return disc


@pytest.fixture
def mock_notification_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.notify = AsyncMock()
    mgr.dismiss = AsyncMock()
    return mgr


def _make_auditor(
    ha_client: AsyncMock,
    entity_discovery: MagicMock,
    integration_discovery: MagicMock,
    notification_manager: AsyncMock,
    config: Config | None = None,
    instance_id: str = "default",
) -> OutOfScopeAuditor:
    """Create an OutOfScopeAuditor with a mocked database."""
    cfg = config or _make_config()
    db = MagicMock()

    # Build an async context manager for sessions that returns an empty baseline
    async_session_cm = AsyncMock()
    async_session_cm.__aenter__ = AsyncMock()
    async_session_cm.__aexit__ = AsyncMock(return_value=False)

    # Patch DB session to yield a session that returns empty results
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session_mock.execute = AsyncMock(return_value=result_mock)
    session_mock.commit = AsyncMock()

    async_session_cm.__aenter__.return_value = session_mock
    db.async_session = MagicMock(return_value=async_session_cm)

    return OutOfScopeAuditor(
        ha_client=ha_client,
        entity_discovery=entity_discovery,
        integration_discovery=integration_discovery,
        database=db,
        notification_manager=notification_manager,
        config=cfg,
        instance_id=instance_id,
    )


# ---------------------------------------------------------------------------
# Tests: out-of-scope computation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_minus_monitored_gives_out_of_scope(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """Entities not in the monitored set are treated as out-of-scope."""
    monitored = {"sensor.monitored_a", "light.monitored_b"}
    mock_entity_discovery.get_monitored_entities.return_value = monitored

    all_states = [
        _make_state("sensor.monitored_a", "ok"),
        _make_state("light.monitored_b", "on"),
        _make_state("sensor.oos_c", "unavailable"),
        _make_state("sensor.oos_d", "ok"),
    ]
    mock_ha_client.get_states.return_value = all_states

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
    )

    stats = await auditor.run_audit()

    # sensor.oos_c and sensor.oos_d are out-of-scope; only sensor.oos_c is bad
    assert stats["total_out_of_scope"] == 2
    assert stats["bad_count"] == 1
    assert stats["new_count"] == 1


@pytest.mark.asyncio
async def test_no_notification_when_nothing_new(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """No notification is sent when there are zero new failures."""
    mock_entity_discovery.get_monitored_entities.return_value = {"sensor.monitored"}
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.monitored", "ok"),
        _make_state("sensor.oos_fine", "ok"),
    ]

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
    )
    stats = await auditor.run_audit()

    assert stats["new_count"] == 0
    assert stats["notified"] is False
    mock_notification_manager.notify.assert_not_called()


@pytest.mark.asyncio
async def test_net_new_only_triggers_digest(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """Only entities absent from the baseline trigger a new notification line."""
    monitored: set[str] = set()
    mock_entity_discovery.get_monitored_entities.return_value = monitored

    mock_ha_client.get_states.return_value = [
        _make_state("sensor.already_known", "unavailable"),
        _make_state("sensor.brand_new", "unavailable"),
    ]

    # Seed the baseline with sensor.already_known
    existing_row = _make_baseline_row("sensor.already_known")
    # fresh — not chronic
    existing_row.first_unavailable_at = datetime.now(UTC)

    cfg = _make_config()
    db = MagicMock()
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [existing_row]
    session_mock.execute = AsyncMock(return_value=result_mock)
    session_mock.commit = AsyncMock()

    async_session_cm = AsyncMock()
    async_session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    async_session_cm.__aexit__ = AsyncMock(return_value=False)
    db.async_session = MagicMock(return_value=async_session_cm)

    auditor = OutOfScopeAuditor(
        ha_client=mock_ha_client,
        entity_discovery=mock_entity_discovery,
        integration_discovery=mock_integration_discovery,
        database=db,
        notification_manager=mock_notification_manager,
        config=cfg,
        instance_id="default",
    )
    stats = await auditor.run_audit()

    # Only sensor.brand_new is new
    assert stats["new_count"] == 1
    assert stats["notified"] is True
    mock_notification_manager.notify.assert_called_once()

    # The call context should contain brand_new but not already_known
    call_args = mock_notification_manager.notify.call_args
    context = call_args[0][0]
    assert context.notification_type == NotificationType.OUT_OF_SCOPE_AUDIT
    assert context.severity == NotificationSeverity.INFO
    new_failures = context.stats["new_failures"]
    entity_ids = [f["entity_id"] for f in new_failures]
    assert "sensor.brand_new" in entity_ids
    assert "sensor.already_known" not in entity_ids


@pytest.mark.asyncio
async def test_chronic_entities_suppressed_from_per_entity_lines(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """Entities bad longer than chronic_threshold are counted but not listed."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.old_failure", "unavailable"),  # chronic
        _make_state("sensor.new_failure", "unavailable"),  # new
    ]

    chronic_threshold_seconds = 259200  # 3 days
    # old_failure has been unavailable for 4 days → chronic
    old_row = _make_baseline_row(
        "sensor.old_failure",
        first_unavailable_at=datetime.now(UTC) - timedelta(days=4),
    )

    cfg = _make_config(chronic_threshold_seconds=chronic_threshold_seconds)
    db = MagicMock()
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [old_row]
    session_mock.execute = AsyncMock(return_value=result_mock)
    session_mock.commit = AsyncMock()

    async_session_cm = AsyncMock()
    async_session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    async_session_cm.__aexit__ = AsyncMock(return_value=False)
    db.async_session = MagicMock(return_value=async_session_cm)

    auditor = OutOfScopeAuditor(
        ha_client=mock_ha_client,
        entity_discovery=mock_entity_discovery,
        integration_discovery=mock_integration_discovery,
        database=db,
        notification_manager=mock_notification_manager,
        config=cfg,
        instance_id="default",
    )
    stats = await auditor.run_audit()

    assert stats["chronic_count"] == 1
    assert stats["new_count"] == 1  # only sensor.new_failure
    assert stats["notified"] is True

    # The digest context should report chronic count but NOT list old_failure
    context = mock_notification_manager.notify.call_args[0][0]
    assert context.stats["chronic_count"] == 1
    new_failure_ids = [f["entity_id"] for f in context.stats["new_failures"]]
    assert "sensor.old_failure" not in new_failure_ids
    assert "sensor.new_failure" in new_failure_ids


@pytest.mark.asyncio
async def test_notify_called_with_cli_and_ha_not_mobile(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """Digest must be sent with CLI + HOME_ASSISTANT channels, MOBILE excluded."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.new_bad", "unavailable"),
    ]

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
    )
    await auditor.run_audit()

    mock_notification_manager.notify.assert_called_once()
    call_args = mock_notification_manager.notify.call_args
    # channels is the second positional arg or keyword arg
    channels = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("channels")
    assert NotificationChannel.CLI in channels
    assert NotificationChannel.HOME_ASSISTANT in channels
    assert NotificationChannel.MOBILE not in channels


@pytest.mark.asyncio
async def test_grouping_by_domain_fallback(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """When integration discovery returns None, group falls back to entity domain."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    mock_ha_client.get_states.return_value = [
        _make_state("light.bedroom", "unavailable"),
        _make_state("sensor.temp", "unavailable"),
    ]
    # Integration discovery returns nothing
    mock_integration_discovery.get_integration_for_entity.return_value = None

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
    )
    await auditor.run_audit()

    context = mock_notification_manager.notify.call_args[0][0]
    groups = {f["group"] for f in context.stats["new_failures"]}
    assert "light" in groups
    assert "sensor" in groups


@pytest.mark.asyncio
async def test_grouping_by_integration_domain(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """When integration discovery returns a domain, use it for grouping."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    mock_ha_client.get_states.return_value = [
        _make_state("light.bedroom", "unavailable"),
    ]
    mock_integration_discovery.get_integration_for_entity.return_value = "abc123"
    mock_integration_discovery.get_domain.return_value = "hue"

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
    )
    await auditor.run_audit()

    context = mock_notification_manager.notify.call_args[0][0]
    groups = {f["group"] for f in context.stats["new_failures"]}
    assert "hue" in groups


@pytest.mark.asyncio
async def test_recovered_entities_removed_from_baseline(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """Entities that recovered are removed from the baseline."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    # sensor.recovered is now "ok" — it was previously bad
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.recovered", "ok"),
    ]

    recovered_row = _make_baseline_row("sensor.recovered")

    cfg = _make_config()
    db = MagicMock()
    session_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [recovered_row]
    session_mock.execute = AsyncMock(return_value=result_mock)
    session_mock.commit = AsyncMock()

    async_session_cm = AsyncMock()
    async_session_cm.__aenter__ = AsyncMock(return_value=session_mock)
    async_session_cm.__aexit__ = AsyncMock(return_value=False)
    db.async_session = MagicMock(return_value=async_session_cm)

    auditor = OutOfScopeAuditor(
        ha_client=mock_ha_client,
        entity_discovery=mock_entity_discovery,
        integration_discovery=mock_integration_discovery,
        database=db,
        notification_manager=mock_notification_manager,
        config=cfg,
        instance_id="default",
    )
    stats = await auditor.run_audit()

    assert stats["recovered_count"] == 1
    # A delete should have been executed for the recovered entity
    session_mock.execute.assert_called()


@pytest.mark.asyncio
async def test_include_stale_flagged_entities(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """When include_stale=True, stale entities are included in bad set."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    stale_last_updated = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.stale_oos", "on", last_updated=stale_last_updated),
    ]

    cfg = _make_config(
        include_stale=True,
        # stale threshold 1 hour → 3-hour-old entity is stale
    )
    # Patch stale threshold to 3600 (default)
    cfg.monitoring.stale_threshold_seconds = 3600

    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
        config=cfg,
    )
    stats = await auditor.run_audit()
    assert stats["bad_count"] >= 1


@pytest.mark.asyncio
async def test_no_stale_when_include_stale_false(
    mock_ha_client: AsyncMock,
    mock_entity_discovery: MagicMock,
    mock_integration_discovery: MagicMock,
    mock_notification_manager: AsyncMock,
) -> None:
    """When include_stale=False (default), stale entities with ok state are ignored."""
    mock_entity_discovery.get_monitored_entities.return_value = set()
    stale_last_updated = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    mock_ha_client.get_states.return_value = [
        _make_state("sensor.stale_oos", "on", last_updated=stale_last_updated),
    ]

    cfg = _make_config(include_stale=False)
    auditor = _make_auditor(
        mock_ha_client,
        mock_entity_discovery,
        mock_integration_discovery,
        mock_notification_manager,
        config=cfg,
    )
    stats = await auditor.run_audit()
    # "on" state is not unavailable/unknown; not stale in the check because include_stale=False
    assert stats["bad_count"] == 0


# ---------------------------------------------------------------------------
# Tests: config defaults
# ---------------------------------------------------------------------------


def test_out_of_scope_audit_config_defaults() -> None:
    """OutOfScopeAuditConfig defaults: disabled, daily interval, 3-day chronic."""
    from ha_boss.core.config import OutOfScopeAuditConfig

    cfg = OutOfScopeAuditConfig()
    assert cfg.enabled is False
    assert cfg.interval_seconds == 86400
    assert cfg.chronic_threshold_seconds == 259200
    assert cfg.include_stale is False
    assert cfg.group_by_integration is True


def test_monitoring_config_has_out_of_scope_audit_field() -> None:
    """MonitoringConfig exposes out_of_scope_audit as a nested config."""
    from ha_boss.core.config import MonitoringConfig, OutOfScopeAuditConfig

    mc = MonitoringConfig()
    assert isinstance(mc.out_of_scope_audit, OutOfScopeAuditConfig)
    assert mc.out_of_scope_audit.enabled is False
