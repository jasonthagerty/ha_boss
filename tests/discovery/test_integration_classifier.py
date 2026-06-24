"""Tests for the IntegrationClassifier (cloud vs local entity detection)."""

from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, HomeAssistantConfig
from ha_boss.discovery.integration_classifier import IntegrationClassifier


def _config(**cloud_kwargs) -> Config:
    cfg = Config(
        home_assistant=HomeAssistantConfig(url="http://homeassistant.local:8123", token="t"),
        mode="production",
    )
    for k, v in cloud_kwargs.items():
        setattr(cfg.monitoring.cloud_handling, k, v)
    return cfg


def _make_classifier(*, manifests, registry, config=None) -> IntegrationClassifier:
    ha_client = AsyncMock()
    ha_client.get_integration_manifests = AsyncMock(return_value=manifests)
    ha_client.get_entity_registry = AsyncMock(return_value=registry)
    return IntegrationClassifier(
        ha_client=ha_client,
        config=config or _config(),
        database=None,
        instance_id="default",
    )


_MANIFESTS = [
    {"domain": "playstation_network", "iot_class": "cloud_polling"},
    {"domain": "plex", "iot_class": "cloud_polling"},
    {"domain": "hue", "iot_class": "local_push"},
    {"domain": "zwave_js", "iot_class": "local_push"},
    {"domain": "no_class"},  # missing iot_class -> ignored
]

_REGISTRY = [
    {"entity_id": "sensor.jasonthagerty_online_id", "platform": "playstation_network"},
    {"entity_id": "media_player.plex_tv", "platform": "plex"},
    {"entity_id": "light.kitchen", "platform": "hue"},
    {"entity_id": "lock.front", "platform": "zwave_js"},
    {"entity_id": "sensor.orphan", "platform": "no_class"},  # no iot_class
    {"entity_id": "sensor.no_platform"},  # missing platform -> skipped
]


@pytest.mark.asyncio
async def test_refresh_builds_entity_iot_class_map() -> None:
    classifier = _make_classifier(manifests=_MANIFESTS, registry=_REGISTRY)
    count = await classifier.refresh()

    # 4 entities resolve to a known iot_class (orphan + no_platform excluded)
    assert count == 4
    assert classifier.iot_class_for("sensor.jasonthagerty_online_id") == "cloud_polling"
    assert classifier.iot_class_for("light.kitchen") == "local_push"
    assert classifier.iot_class_for("sensor.orphan") is None
    assert classifier.iot_class_for("sensor.no_platform") is None


@pytest.mark.asyncio
async def test_is_cloud_classification() -> None:
    classifier = _make_classifier(manifests=_MANIFESTS, registry=_REGISTRY)
    await classifier.refresh()

    assert classifier.is_cloud("sensor.jasonthagerty_online_id") is True
    assert classifier.is_cloud("media_player.plex_tv") is True
    assert classifier.is_cloud("light.kitchen") is False  # local_push
    assert classifier.is_cloud("lock.front") is False
    assert classifier.is_cloud("sensor.unknown_entity") is False  # not classified


@pytest.mark.asyncio
async def test_is_cloud_false_when_disabled() -> None:
    classifier = _make_classifier(
        manifests=_MANIFESTS, registry=_REGISTRY, config=_config(enabled=False)
    )
    await classifier.refresh()
    assert classifier.is_cloud("sensor.jasonthagerty_online_id") is False


@pytest.mark.asyncio
async def test_custom_iot_classes_respected() -> None:
    # Treat local_push as "cloud" via config override; cloud_polling no longer counts.
    classifier = _make_classifier(
        manifests=_MANIFESTS, registry=_REGISTRY, config=_config(iot_classes=["local_push"])
    )
    await classifier.refresh()
    assert classifier.is_cloud("light.kitchen") is True
    assert classifier.is_cloud("sensor.jasonthagerty_online_id") is False


@pytest.mark.asyncio
async def test_is_cloud_before_refresh_is_false() -> None:
    classifier = _make_classifier(manifests=_MANIFESTS, registry=_REGISTRY)
    # No refresh() called yet -> nothing classified
    assert classifier.is_cloud("sensor.jasonthagerty_online_id") is False
