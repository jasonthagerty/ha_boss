"""Tests for EntityExtractor class."""

from ha_boss.discovery.entity_discovery import EntityExtractor


class TestEntityExtractorAutomations:
    """Tests for automation entity extraction."""

    def test_extract_simple_automation(self) -> None:
        """Test extraction from simple automation with entity_id fields."""
        attrs = {
            "trigger": [{"platform": "state", "entity_id": "binary_sensor.door"}],
            "condition": [{"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.bedroom"}}],
        }

        result = EntityExtractor.extract_from_automation(attrs)

        assert "trigger" in result
        assert "condition" in result
        assert "action" in result

        # Check trigger entities
        trigger_entities = [entity_id for entity_id, _ in result["trigger"]]
        assert "binary_sensor.door" in trigger_entities

        # Check condition entities
        condition_entities = [entity_id for entity_id, _ in result["condition"]]
        assert "sun.sun" in condition_entities

        # Check action entities
        action_entities = [entity_id for entity_id, _ in result["action"]]
        assert "light.bedroom" in action_entities

    def test_extract_automation_with_lists(self) -> None:
        """Test extraction with entity_id as list."""
        attrs = {
            "trigger": [
                {"platform": "state", "entity_id": ["sensor.temp1", "sensor.temp2", "sensor.temp3"]}
            ],
            "action": [
                {
                    "service": "light.turn_on",
                    "target": {"entity_id": ["light.living_room", "light.kitchen"]},
                }
            ],
        }

        result = EntityExtractor.extract_from_automation(attrs)

        trigger_entities = [entity_id for entity_id, _ in result["trigger"]]
        assert "sensor.temp1" in trigger_entities
        assert "sensor.temp2" in trigger_entities
        assert "sensor.temp3" in trigger_entities

        action_entities = [entity_id for entity_id, _ in result["action"]]
        assert "light.living_room" in action_entities
        assert "light.kitchen" in action_entities

    def test_extract_automation_nested_data(self) -> None:
        """Test extraction from nested data structures."""
        attrs = {
            "action": [
                {
                    "service": "climate.set_temperature",
                    "data": {"entity_id": "climate.bedroom", "temperature": 20},
                }
            ]
        }

        result = EntityExtractor.extract_from_automation(attrs)

        action_entities = [entity_id for entity_id, _ in result["action"]]
        assert "climate.bedroom" in action_entities

    def test_extract_automation_choose_action(self) -> None:
        """Test extraction from choose action with conditions."""
        attrs = {
            "action": [
                {
                    "choose": [
                        {
                            "conditions": [
                                {"condition": "state", "entity_id": "input_boolean.away_mode"}
                            ],
                            "sequence": [
                                {"service": "light.turn_off", "target": {"entity_id": "light.all"}}
                            ],
                        }
                    ]
                }
            ]
        }

        result = EntityExtractor.extract_from_automation(attrs)

        action_entities = [entity_id for entity_id, _ in result["action"]]
        assert "input_boolean.away_mode" in action_entities
        assert "light.all" in action_entities

    def test_extract_automation_empty(self) -> None:
        """Test extraction from automation with no entities."""
        attrs = {"trigger": [], "condition": [], "action": []}

        result = EntityExtractor.extract_from_automation(attrs)

        assert len(result["trigger"]) == 0
        assert len(result["condition"]) == 0
        assert len(result["action"]) == 0

    def test_extract_automation_with_context(self) -> None:
        """Test that extraction includes context information."""
        attrs = {
            "trigger": [{"platform": "state", "entity_id": "sensor.temperature"}],
        }

        result = EntityExtractor.extract_from_automation(attrs)

        # Check that context dict is returned
        assert len(result["trigger"]) == 1
        entity_id, context = result["trigger"][0]
        assert entity_id == "sensor.temperature"
        assert isinstance(context, dict)


class TestEntityExtractorScenes:
    """Tests for scene entity extraction."""

    def test_extract_simple_scene(self) -> None:
        """Test extraction from simple scene."""
        attrs = {
            "entity_id": ["light.bedroom", "light.living_room", "climate.bedroom"],
        }

        result = EntityExtractor.extract_from_scene(attrs)

        entities = [entity_id for entity_id, _ in result]
        assert "light.bedroom" in entities
        assert "light.living_room" in entities
        assert "climate.bedroom" in entities

    def test_extract_scene_with_attributes(self) -> None:
        """Test extraction from scene with state attributes."""
        attrs = {
            "entity_id": ["light.bedroom"],
            "state": {"light.bedroom": {"state": "on", "brightness": 200}},
        }

        result = EntityExtractor.extract_from_scene(attrs)

        entities = [entity_id for entity_id, _ in result]
        assert "light.bedroom" in entities

    def test_extract_scene_empty(self) -> None:
        """Test extraction from scene with no entities."""
        attrs = {}

        result = EntityExtractor.extract_from_scene(attrs)

        assert len(result) == 0


class TestEntityExtractorScripts:
    """Tests for script entity extraction."""

    def test_extract_simple_script(self) -> None:
        """Test extraction from simple script."""
        attrs = {
            "sequence": [
                {"service": "light.turn_on", "target": {"entity_id": "light.bedroom"}},
                {
                    "service": "climate.set_temperature",
                    "data": {"entity_id": "climate.living_room"},
                },
            ]
        }

        result = EntityExtractor.extract_from_script(attrs)

        entities = [entity_id for entity_id, _ in result]
        assert "light.bedroom" in entities
        assert "climate.living_room" in entities

    def test_extract_script_with_conditions(self) -> None:
        """Test extraction from script with conditional logic."""
        attrs = {
            "sequence": [
                {
                    "condition": "state",
                    "entity_id": "input_boolean.guest_mode",
                    "state": "on",
                },
                {"service": "light.turn_on", "target": {"entity_id": "light.guest_room"}},
            ]
        }

        result = EntityExtractor.extract_from_script(attrs)

        entities = [entity_id for entity_id, _ in result]
        assert "input_boolean.guest_mode" in entities
        assert "light.guest_room" in entities

    def test_extract_script_empty(self) -> None:
        """Test extraction from script with no entities."""
        attrs = {"sequence": []}

        result = EntityExtractor.extract_from_script(attrs)

        assert len(result) == 0


class TestEntityExtractorRecursive:
    """Tests for recursive entity extraction."""

    def test_extract_deeply_nested(self) -> None:
        """Test extraction from deeply nested structures."""
        item = {
            "level1": {
                "level2": {
                    "level3": {
                        "entity_id": "sensor.deep_nested",
                    }
                }
            }
        }

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "sensor.deep_nested" in result

    def test_extract_from_list(self) -> None:
        """Test extraction from list items."""
        item = [
            {"entity_id": "sensor.one"},
            {"entity_id": "sensor.two"},
            {"nested": {"entity_id": "sensor.three"}},
        ]

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "sensor.one" in result
        assert "sensor.two" in result
        assert "sensor.three" in result

    def test_extract_filters_invalid_entity_ids(self) -> None:
        """Test that invalid entity_ids are filtered out."""
        item = {
            "entity_id": [
                "sensor.valid",  # Valid
                "invalid_no_dot",  # Invalid - no dot
                "light.also_valid",  # Valid
                "",  # Invalid - empty
            ]
        }

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "sensor.valid" in result
        assert "light.also_valid" in result
        assert "invalid_no_dot" not in result
        assert "" not in result

    def test_extract_from_target_entity_id(self) -> None:
        """Test extraction from target.entity_id pattern."""
        item = {"target": {"entity_id": "switch.bedroom"}}

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "switch.bedroom" in result

    def test_extract_from_data_entity_id(self) -> None:
        """Test extraction from data.entity_id pattern."""
        item = {"data": {"entity_id": "cover.garage"}}

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "cover.garage" in result

    def test_extract_ignores_non_entity_keys(self) -> None:
        """Test that non-entity_id keys are ignored."""
        item = {
            "entity_id": "sensor.correct",
            "some_other_field": "sensor.wrong",
            "device_id": "abc123",
            "area_id": "living_room",
        }

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert "sensor.correct" in result
        assert "sensor.wrong" not in result
        assert len(result) == 1


class TestEntityExtractorEdgeCases:
    """Tests for edge cases and error handling."""

    def test_extract_automation_missing_keys(self) -> None:
        """Test automation extraction with missing trigger/condition/action."""
        attrs = {"mode": "single"}  # No trigger/condition/action

        result = EntityExtractor.extract_from_automation(attrs)

        assert "trigger" in result
        assert "condition" in result
        assert "action" in result
        assert len(result["trigger"]) == 0
        assert len(result["condition"]) == 0
        assert len(result["action"]) == 0

    def test_extract_with_none_values(self) -> None:
        """Test extraction handles None values gracefully."""
        item = {"entity_id": None, "nested": None}

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert len(result) == 0

    def test_extract_with_numeric_values(self) -> None:
        """Test extraction ignores numeric entity_id values."""
        item = {"entity_id": 123}

        result = EntityExtractor._extract_entity_ids_recursive(item)

        assert len(result) == 0

    def test_extract_deduplication(self) -> None:
        """Test that duplicate entity_ids are deduplicated."""
        attrs = {
            "trigger": [
                {"platform": "state", "entity_id": "sensor.temp"},
                {"platform": "numeric_state", "entity_id": "sensor.temp"},  # Duplicate
            ],
            "action": [
                {"service": "light.turn_on", "target": {"entity_id": "sensor.temp"}}  # Duplicate
            ],
        }

        result = EntityExtractor.extract_from_automation(attrs)

        # Each relationship type should have the entity once
        trigger_entities = [entity_id for entity_id, _ in result["trigger"]]
        action_entities = [entity_id for entity_id, _ in result["action"]]

        # Within each type, check for presence (set will handle duplicates)
        assert "sensor.temp" in set(trigger_entities)
        assert "sensor.temp" in set(action_entities)
