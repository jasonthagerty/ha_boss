"""Tests for config merge logic in entity discovery."""

import fnmatch

from ha_boss.core.config import AutoDiscoveryConfig, Config, MonitoringConfig


class TestConfigMergeFormula:
    """Tests for (auto_discovered ∪ config.include) - config.exclude formula."""

    def test_auto_discovered_only(self) -> None:
        """Test with only auto-discovered entities (no config overrides)."""
        auto_discovered = {"sensor.temp", "light.bedroom", "binary_sensor.door"}
        include_patterns = []
        exclude_patterns = []
        all_entities = []  # No additional entities

        # Apply formula: (auto_discovered ∪ include) - exclude
        monitored = auto_discovered.copy()

        # Apply include patterns
        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        # Apply exclude patterns
        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        assert monitored == {"sensor.temp", "light.bedroom", "binary_sensor.door"}

    def test_include_adds_to_discovered(self) -> None:
        """Test that config.include adds to auto-discovered entities."""
        auto_discovered = {"sensor.temp", "light.bedroom"}
        include_patterns = ["sensor.manual", "switch.*"]
        exclude_patterns = []
        all_entities = [
            "sensor.temp",
            "light.bedroom",
            "sensor.manual",
            "switch.kitchen",
            "switch.bedroom",
            "cover.garage",
        ]

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        # Should have auto-discovered + matched includes
        assert "sensor.temp" in monitored
        assert "light.bedroom" in monitored
        assert "sensor.manual" in monitored
        assert "switch.kitchen" in monitored
        assert "switch.bedroom" in monitored
        assert "cover.garage" not in monitored

    def test_exclude_removes_from_set(self) -> None:
        """Test that config.exclude removes from final set."""
        auto_discovered = {
            "sensor.temperature",
            "sensor.time",
            "sensor.time_utc",
            "sun.sun",
            "light.bedroom",
        }
        include_patterns = []
        exclude_patterns = ["sensor.time*", "sun.sun"]
        all_entities = []

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        # Should exclude matching patterns
        assert "sensor.temperature" in monitored
        assert "light.bedroom" in monitored
        assert "sensor.time" not in monitored
        assert "sensor.time_utc" not in monitored
        assert "sun.sun" not in monitored

    def test_full_formula(self) -> None:
        """Test complete formula: (auto_discovered ∪ include) - exclude."""
        auto_discovered = {"sensor.temperature", "sensor.time", "light.bedroom"}
        include_patterns = ["input_boolean.*"]
        exclude_patterns = ["sensor.time*"]
        all_entities = [
            "sensor.temperature",
            "sensor.time",
            "light.bedroom",
            "input_boolean.guest_mode",
            "input_boolean.away_mode",
        ]

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        # Auto-discovered (minus excluded)
        assert "sensor.temperature" in monitored
        assert "light.bedroom" in monitored
        assert "sensor.time" not in monitored

        # Included
        assert "input_boolean.guest_mode" in monitored
        assert "input_boolean.away_mode" in monitored

    def test_exclude_overrides_include(self) -> None:
        """Test that exclude takes precedence over include."""
        auto_discovered = set()
        include_patterns = ["sensor.*"]
        exclude_patterns = ["sensor.time*"]
        all_entities = ["sensor.temperature", "sensor.time", "sensor.time_utc"]

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        # Should include sensor.temperature but exclude time sensors
        assert "sensor.temperature" in monitored
        assert "sensor.time" not in monitored
        assert "sensor.time_utc" not in monitored

    def test_pattern_matching_wildcard(self) -> None:
        """Test wildcard pattern matching."""
        auto_discovered = set()
        include_patterns = ["light.bedroom_*"]
        exclude_patterns = []
        all_entities = [
            "light.bedroom_main",
            "light.bedroom_accent",
            "light.living_room",
        ]

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        assert "light.bedroom_main" in monitored
        assert "light.bedroom_accent" in monitored
        assert "light.living_room" not in monitored

    def test_empty_config_lists(self) -> None:
        """Test with empty include/exclude lists."""
        auto_discovered = {"sensor.temp", "light.bedroom"}
        include_patterns = []
        exclude_patterns = []
        all_entities = []

        # Apply formula
        monitored = auto_discovered.copy()

        for pattern in include_patterns:
            for entity_id in all_entities:
                if fnmatch.fnmatch(entity_id, pattern):
                    monitored.add(entity_id)

        to_exclude = set()
        for pattern in exclude_patterns:
            for entity_id in monitored:
                if fnmatch.fnmatch(entity_id, pattern):
                    to_exclude.add(entity_id)
        monitored -= to_exclude

        assert monitored == {"sensor.temp", "light.bedroom"}


class TestEntityGracePeriod:
    """Tests for per-entity grace period overrides."""

    def test_entity_override_grace_period(self) -> None:
        """Test that entity override returns custom grace period."""
        config = Config(
            home_assistant={"url": "http://localhost:8123", "token": "test_token"},
            monitoring=MonitoringConfig(
                grace_period_seconds=300,
                entity_overrides={
                    "sensor.critical_temp": {"grace_period_seconds": 60},
                },
                auto_discovery=AutoDiscoveryConfig(enabled=True),
            ),
        )

        # Check override works
        grace_period = config.monitoring.get_entity_grace_period("sensor.critical_temp")
        assert grace_period == 60

    def test_entity_default_grace_period(self) -> None:
        """Test that entity without override returns default grace period."""
        config = Config(
            home_assistant={"url": "http://localhost:8123", "token": "test_token"},
            monitoring=MonitoringConfig(
                grace_period_seconds=300,
                entity_overrides={},
                auto_discovery=AutoDiscoveryConfig(enabled=True),
            ),
        )

        grace_period = config.monitoring.get_entity_grace_period("sensor.temp")
        assert grace_period == 300

    def test_entity_override_none_uses_default(self) -> None:
        """Test that override with None value uses default."""
        config = Config(
            home_assistant={"url": "http://localhost:8123", "token": "test_token"},
            monitoring=MonitoringConfig(
                grace_period_seconds=300,
                entity_overrides={
                    "sensor.temp": {"grace_period_seconds": None},
                },
                auto_discovery=AutoDiscoveryConfig(enabled=True),
            ),
        )

        grace_period = config.monitoring.get_entity_grace_period("sensor.temp")
        assert grace_period == 300


class TestAutoDiscoveryConfig:
    """Tests for AutoDiscoveryConfig validation and defaults."""

    def test_default_values(self) -> None:
        """Test auto-discovery config defaults."""
        config = AutoDiscoveryConfig()

        assert config.enabled is True
        assert config.skip_disabled_automations is True
        assert config.include_scenes is True
        assert config.include_scripts is True
        assert config.refresh_interval_seconds == 3600
        assert config.refresh_on_automation_reload is True
        assert config.refresh_on_scene_reload is True
        assert config.refresh_on_script_reload is True

    def test_custom_values(self) -> None:
        """Test auto-discovery config with custom values."""
        config = AutoDiscoveryConfig(
            enabled=False,
            skip_disabled_automations=False,
            include_scenes=False,
            include_scripts=False,
            refresh_interval_seconds=7200,
            refresh_on_automation_reload=False,
            refresh_on_scene_reload=False,
            refresh_on_script_reload=False,
        )

        assert config.enabled is False
        assert config.skip_disabled_automations is False
        assert config.include_scenes is False
        assert config.include_scripts is False
        assert config.refresh_interval_seconds == 7200
        assert config.refresh_on_automation_reload is False
        assert config.refresh_on_scene_reload is False
        assert config.refresh_on_script_reload is False

    def test_disable_periodic_refresh(self) -> None:
        """Test disabling periodic refresh with interval = 0."""
        config = AutoDiscoveryConfig(refresh_interval_seconds=0)

        assert config.refresh_interval_seconds == 0
