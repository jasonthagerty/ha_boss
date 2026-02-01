"""Tests for trigger failure detector."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.trigger_detector import (
    TriggerFailureContext,
    TriggerFailureDetector,
)
from ha_boss.core.database import AutomationDesiredState, Database
from ha_boss.core.ha_client import HomeAssistantClient


@pytest.fixture
def mock_database() -> MagicMock:
    """Create mock database."""
    db = MagicMock(spec=Database)
    db.async_session = MagicMock()
    return db


@pytest.fixture
def mock_ha_client() -> MagicMock:
    """Create mock Home Assistant client."""
    return MagicMock(spec=HomeAssistantClient)


@pytest.fixture
def detector(mock_database: MagicMock, mock_ha_client: MagicMock) -> TriggerFailureDetector:
    """Create trigger failure detector."""
    return TriggerFailureDetector(mock_database, mock_ha_client, "default")


class TestTriggerFailureContext:
    """Test TriggerFailureContext dataclass."""

    def test_create_context(self) -> None:
        """Test creating a trigger failure context."""
        context = TriggerFailureContext(
            automation_id="automation.test",
            instance_id="default",
            expected_trigger={"entity_id": "sensor.temp"},
            actual_state={"state": "on"},
            timestamp=datetime.now(UTC),
        )

        assert context.automation_id == "automation.test"
        assert context.instance_id == "default"
        assert context.detection_method == "state_change_monitoring"

    def test_context_default_detection_method(self) -> None:
        """Test default detection method."""
        context = TriggerFailureContext(
            automation_id="automation.test",
            instance_id="default",
            expected_trigger={},
            actual_state={},
            timestamp=datetime.now(UTC),
        )

        assert context.detection_method == "state_change_monitoring"

    def test_context_custom_detection_method(self) -> None:
        """Test custom detection method."""
        context = TriggerFailureContext(
            automation_id="automation.test",
            instance_id="default",
            expected_trigger={},
            actual_state={},
            timestamp=datetime.now(UTC),
            detection_method="custom_method",
        )

        assert context.detection_method == "custom_method"


class TestTriggerDetectorInit:
    """Test TriggerFailureDetector initialization."""

    def test_init_with_defaults(self, mock_database: MagicMock, mock_ha_client: MagicMock) -> None:
        """Test initialization with default instance_id."""
        detector = TriggerFailureDetector(mock_database, mock_ha_client)

        assert detector.database is mock_database
        assert detector.ha_client is mock_ha_client
        assert detector.instance_id == "default"

    def test_init_with_custom_instance_id(
        self, mock_database: MagicMock, mock_ha_client: MagicMock
    ) -> None:
        """Test initialization with custom instance_id."""
        detector = TriggerFailureDetector(
            mock_database, mock_ha_client, instance_id="home_assistant"
        )

        assert detector.instance_id == "home_assistant"


class TestMonitorStateChanges:
    """Test monitor_state_changes method."""

    @pytest.mark.asyncio
    async def test_monitor_successful_validation(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test successful trigger validation."""
        # Mock state retrieval
        mock_ha_client.get_state = AsyncMock(
            return_value={"state": "20", "entity_id": "sensor.temp"}
        )

        # Mock validation to return False (trigger did not fail)
        detector.validate_trigger_fired = AsyncMock(return_value=False)

        result = await detector.monitor_state_changes(
            automation_id="automation.test",
            expected_trigger={"entity_id": "sensor.temp"},
            validation_window=0.1,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_monitor_detects_trigger_failure(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test detection of trigger failure."""
        # Mock state retrieval
        mock_ha_client.get_state = AsyncMock(
            return_value={"state": "25", "entity_id": "sensor.temp"}
        )

        # Mock validation to return True (trigger failed)
        detector.validate_trigger_fired = AsyncMock(return_value=True)

        result = await detector.monitor_state_changes(
            automation_id="automation.test",
            expected_trigger={"entity_id": "sensor.temp", "above": 25},
            validation_window=0.1,
        )

        assert result is not None
        assert result.automation_id == "automation.test"
        assert result.instance_id == "default"
        assert result.detection_method == "state_change_monitoring"

    @pytest.mark.asyncio
    async def test_monitor_invalid_automation_id(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid automation ID."""
        with pytest.raises(ValueError, match="Invalid automation_id"):
            await detector.monitor_state_changes(
                automation_id="",
                expected_trigger={"entity_id": "sensor.temp"},
            )

    @pytest.mark.asyncio
    async def test_monitor_invalid_trigger(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid trigger."""
        with pytest.raises(ValueError, match="Invalid expected_trigger"):
            await detector.monitor_state_changes(
                automation_id="automation.test",
                expected_trigger={},  # Empty trigger
            )

    @pytest.mark.asyncio
    async def test_monitor_invalid_window(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid validation window."""
        with pytest.raises(ValueError, match="validation_window must be positive"):
            await detector.monitor_state_changes(
                automation_id="automation.test",
                expected_trigger={"entity_id": "sensor.temp"},
                validation_window=-1,
            )

    @pytest.mark.asyncio
    async def test_monitor_get_states_returns_none(self, detector: TriggerFailureDetector) -> None:
        """Test when unable to get initial states."""
        detector._get_trigger_entity_states = AsyncMock(return_value=None)

        result = await detector.monitor_state_changes(
            automation_id="automation.test",
            expected_trigger={"entity_id": "sensor.temp"},
            validation_window=0.1,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_monitor_rapid_state_changes(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test handling of rapid successive state changes."""
        # Mock rapid state changes
        states = [
            {"state": "20"},
            {"state": "25"},
            {"state": "30"},
        ]
        mock_ha_client.get_state = AsyncMock(side_effect=states)

        detector.validate_trigger_fired = AsyncMock(return_value=False)

        result = await detector.monitor_state_changes(
            automation_id="automation.test",
            expected_trigger={"entity_id": "sensor.temp"},
            validation_window=0.05,
        )

        assert result is None


class TestValidateTriggerFired:
    """Test validate_trigger_fired method."""

    @pytest.mark.asyncio
    async def test_trigger_should_fire_on_state_transition_to(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test trigger should fire when state transitions to target value."""
        # Mock automation config - creates trigger with 'to' condition
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "sensor.temp"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # State changes from 'off' to 'on', matching the trigger condition
        state_change = {
            "initial": {"sensor.temp": {"state": "off"}},
            "final": {"sensor.temp": {"state": "on"}},
        }

        result = await detector.validate_trigger_fired(
            automation_id="automation.test",
            state_change=state_change,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_trigger_should_not_fire_when_to_condition_not_met(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test trigger should not fire when 'to' condition not met."""
        # Mock automation config - trigger requires transition TO 'on'
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "sensor.temp"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # State stays 'off', does not transition to 'on'
        state_change = {
            "initial": {"sensor.temp": {"state": "off"}},
            "final": {"sensor.temp": {"state": "off"}},
        }

        result = await detector.validate_trigger_fired(
            automation_id="automation.test",
            state_change=state_change,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_trigger_case_insensitive_comparison(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test case-insensitive state comparison."""
        # Mock automation config with different case
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "sensor.mode"
        desired_state.desired_state = "ON"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        state_change = {
            "initial": {"sensor.mode": {"state": "off"}},
            "final": {"sensor.mode": {"state": "on"}},  # lowercase
        }

        result = await detector.validate_trigger_fired(
            automation_id="automation.test",
            state_change=state_change,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_trigger_invalid_automation_id(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid automation ID."""
        with pytest.raises(ValueError, match="Invalid automation_id"):
            await detector.validate_trigger_fired(
                automation_id="",
                state_change={"initial": {}, "final": {}},
            )

    @pytest.mark.asyncio
    async def test_trigger_invalid_state_change(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid state change."""
        with pytest.raises(ValueError, match="Invalid state_change"):
            await detector.validate_trigger_fired(
                automation_id="automation.test",
                state_change={},  # Empty state change
            )

    @pytest.mark.asyncio
    async def test_trigger_no_matching_entities(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test when no automation config matches state change."""
        # Mock automation config with different entity
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "sensor.other"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        state_change = {
            "initial": {"sensor.temp": {"state": "off"}},
            "final": {"sensor.temp": {"state": "on"}},
        }

        result = await detector.validate_trigger_fired(
            automation_id="automation.test",
            state_change=state_change,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_trigger_none_values(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test handling of None values in state."""
        # Mock automation config
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "sensor.temp"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        state_change = {
            "initial": {"sensor.temp": {"state": None}},
            "final": {"sensor.temp": {"state": None}},
        }

        result = await detector.validate_trigger_fired(
            automation_id="automation.test",
            state_change=state_change,
        )

        assert result is False


class TestGetTriggerEntityStates:
    """Test _get_trigger_entity_states method."""

    @pytest.mark.asyncio
    async def test_get_states_with_single_entity(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test getting states for single entity."""
        mock_ha_client.get_state = AsyncMock(
            return_value={"state": "25", "entity_id": "sensor.temp"}
        )

        states = await detector._get_trigger_entity_states({"entity_id": "sensor.temp"})

        assert states is not None
        assert "sensor.temp" in states
        assert states["sensor.temp"]["state"] == "25"

    @pytest.mark.asyncio
    async def test_get_states_with_multiple_entities(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test getting states for multiple entities."""

        def mock_get_state(entity_id: str) -> dict[str, Any]:
            return {"state": "25" if "temp" in entity_id else "100"}

        mock_ha_client.get_state = AsyncMock(side_effect=mock_get_state)

        states = await detector._get_trigger_entity_states(
            {"entity_id": ["sensor.temp", "sensor.humidity"]}
        )

        assert states is not None
        assert len(states) == 2
        assert "sensor.temp" in states
        assert "sensor.humidity" in states

    @pytest.mark.asyncio
    async def test_get_states_handles_failures(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test graceful handling of state query failures."""
        mock_ha_client.get_state = AsyncMock(side_effect=Exception("Connection failed"))

        states = await detector._get_trigger_entity_states({"entity_id": "sensor.temp"})

        assert states is None

    @pytest.mark.asyncio
    async def test_get_states_with_nested_trigger(
        self, detector: TriggerFailureDetector, mock_ha_client: MagicMock
    ) -> None:
        """Test getting states from nested trigger structure."""
        mock_ha_client.get_state = AsyncMock(return_value={"state": "on"})

        states = await detector._get_trigger_entity_states(
            {
                "platform": "state",
                "entity_id": "sensor.temp",
                "to": "25",
            }
        )

        assert states is not None
        assert "sensor.temp" in states

    @pytest.mark.asyncio
    async def test_get_states_invalid_trigger(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid trigger."""
        with pytest.raises(ValueError, match="Invalid trigger"):
            await detector._get_trigger_entity_states(None)

    @pytest.mark.asyncio
    async def test_get_states_empty_trigger(self, detector: TriggerFailureDetector) -> None:
        """Test with trigger containing no entity IDs."""
        states = await detector._get_trigger_entity_states({})

        assert states is None


class TestGetAutomationConfig:
    """Test _get_automation_config method."""

    @pytest.mark.asyncio
    async def test_get_config_success(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test successful config retrieval."""
        # Mock database query
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.automation_id = "automation.test"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        config = await detector._get_automation_config("automation.test")

        assert len(config) == 1
        assert config[0] is desired_state

    @pytest.mark.asyncio
    async def test_get_config_not_found(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test when config not found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        config = await detector._get_automation_config("automation.nonexistent")

        assert config == []

    @pytest.mark.asyncio
    async def test_get_config_invalid_id(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid automation ID."""
        with pytest.raises(ValueError, match="Invalid automation_id"):
            await detector._get_automation_config("")

    @pytest.mark.asyncio
    async def test_get_config_database_error(
        self, detector: TriggerFailureDetector, mock_database: MagicMock
    ) -> None:
        """Test that database errors propagate correctly."""
        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("Database error")
        )

        # Should propagate exception instead of returning empty list
        with pytest.raises(Exception, match="Database error"):
            await detector._get_automation_config("automation.test")


class TestExtractEntityIdsFromTrigger:
    """Test _extract_entity_ids_from_trigger method."""

    def test_extract_single_entity_id(self, detector: TriggerFailureDetector) -> None:
        """Test extracting single entity ID."""
        entity_ids = detector._extract_entity_ids_from_trigger({"entity_id": "sensor.temp"})

        assert entity_ids == {"sensor.temp"}

    def test_extract_multiple_entity_ids(self, detector: TriggerFailureDetector) -> None:
        """Test extracting multiple entity IDs from list."""
        entity_ids = detector._extract_entity_ids_from_trigger(
            {"entity_id": ["sensor.temp", "sensor.humidity"]}
        )

        assert entity_ids == {"sensor.temp", "sensor.humidity"}

    def test_extract_nested_entity_ids(self, detector: TriggerFailureDetector) -> None:
        """Test extracting nested entity IDs."""
        entity_ids = detector._extract_entity_ids_from_trigger(
            {
                "platform": "state",
                "entity_id": "sensor.temp",
                "condition": {
                    "condition": "state",
                    "entity_id": "sensor.humidity",
                },
            }
        )

        assert entity_ids == {"sensor.temp", "sensor.humidity"}

    def test_extract_from_list_of_dicts(self, detector: TriggerFailureDetector) -> None:
        """Test extracting from list of dictionaries."""
        entity_ids = detector._extract_entity_ids_from_trigger(
            {
                "trigger": [
                    {"entity_id": "sensor.temp"},
                    {"entity_id": "sensor.humidity"},
                ]
            }
        )

        assert entity_ids == {"sensor.temp", "sensor.humidity"}

    def test_extract_empty_trigger(self, detector: TriggerFailureDetector) -> None:
        """Test with empty trigger."""
        entity_ids = detector._extract_entity_ids_from_trigger({})

        assert entity_ids == set()

    def test_extract_invalid_trigger(self, detector: TriggerFailureDetector) -> None:
        """Test with invalid trigger type."""
        entity_ids = detector._extract_entity_ids_from_trigger(None)

        assert entity_ids == set()

    def test_extract_mixed_types(self, detector: TriggerFailureDetector) -> None:
        """Test extracting with mixed data types."""
        entity_ids = detector._extract_entity_ids_from_trigger(
            {
                "entity_id": "sensor.main",
                "conditions": {
                    "entity_id": "sensor.condition",
                },
                "triggers": [
                    {"entity_id": "sensor.trigger1"},
                    {"entity_id": ["sensor.trigger2", "sensor.trigger3"]},
                ],
            }
        )

        assert entity_ids == {
            "sensor.main",
            "sensor.condition",
            "sensor.trigger1",
            "sensor.trigger2",
            "sensor.trigger3",
        }


class TestCheckStateTrigger:
    """Test _check_state_trigger method."""

    def test_state_trigger_to_condition_match(self, detector: TriggerFailureDetector) -> None:
        """Test state trigger with 'to' condition matching."""
        trigger = {"entity_id": "light.living_room", "to": "on"}
        initial = {"light.living_room": {"state": "off"}}
        final = {"light.living_room": {"state": "on"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is True

    def test_state_trigger_to_condition_no_match(self, detector: TriggerFailureDetector) -> None:
        """Test state trigger with 'to' condition not matching."""
        trigger = {"entity_id": "light.living_room", "to": "on"}
        initial = {"light.living_room": {"state": "off"}}
        final = {"light.living_room": {"state": "off"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is False

    def test_state_trigger_from_to_condition_match(self, detector: TriggerFailureDetector) -> None:
        """Test state trigger with both 'from' and 'to' conditions matching."""
        trigger = {"entity_id": "light.living_room", "from": "off", "to": "on"}
        initial = {"light.living_room": {"state": "off"}}
        final = {"light.living_room": {"state": "on"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is True

    def test_state_trigger_from_condition_no_match(self, detector: TriggerFailureDetector) -> None:
        """Test state trigger with 'from' condition not matching."""
        trigger = {"entity_id": "light.living_room", "from": "off", "to": "on"}
        initial = {"light.living_room": {"state": "unknown"}}
        final = {"light.living_room": {"state": "on"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is False

    def test_state_trigger_no_entity_id(self, detector: TriggerFailureDetector) -> None:
        """Test state trigger without entity_id."""
        trigger = {"to": "on"}
        initial = {}
        final = {}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is False

    def test_state_trigger_no_conditions_state_changed(
        self, detector: TriggerFailureDetector
    ) -> None:
        """Test state trigger with no from/to conditions when state changes."""
        trigger = {"entity_id": "light.living_room"}
        initial = {"light.living_room": {"state": "off"}}
        final = {"light.living_room": {"state": "on"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is True

    def test_state_trigger_no_conditions_state_unchanged(
        self, detector: TriggerFailureDetector
    ) -> None:
        """Test state trigger with no from/to conditions when state doesn't change."""
        trigger = {"entity_id": "light.living_room"}
        initial = {"light.living_room": {"state": "on"}}
        final = {"light.living_room": {"state": "on"}}

        result = detector._check_state_trigger(trigger, initial, final)
        assert result is False


class TestCheckNumericTrigger:
    """Test _check_numeric_trigger method."""

    def test_numeric_trigger_above_condition_match(self, detector: TriggerFailureDetector) -> None:
        """Test numeric trigger with 'above' condition matching."""
        trigger = {"entity_id": "sensor.temp", "above": 25}
        initial = {"sensor.temp": {"state": "20"}}
        final = {"sensor.temp": {"state": "30"}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is True

    def test_numeric_trigger_above_condition_no_match(
        self, detector: TriggerFailureDetector
    ) -> None:
        """Test numeric trigger with 'above' condition not matching."""
        trigger = {"entity_id": "sensor.temp", "above": 25}
        initial = {"sensor.temp": {"state": "20"}}
        final = {"sensor.temp": {"state": "24"}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is False

    def test_numeric_trigger_below_condition_match(self, detector: TriggerFailureDetector) -> None:
        """Test numeric trigger with 'below' condition matching."""
        trigger = {"entity_id": "sensor.temp", "below": 15}
        initial = {"sensor.temp": {"state": "20"}}
        final = {"sensor.temp": {"state": "10"}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is True

    def test_numeric_trigger_below_condition_no_match(
        self, detector: TriggerFailureDetector
    ) -> None:
        """Test numeric trigger with 'below' condition not matching."""
        trigger = {"entity_id": "sensor.temp", "below": 15}
        initial = {"sensor.temp": {"state": "20"}}
        final = {"sensor.temp": {"state": "16"}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is False

    def test_numeric_trigger_invalid_state(self, detector: TriggerFailureDetector) -> None:
        """Test numeric trigger with non-numeric state."""
        trigger = {"entity_id": "sensor.temp", "above": 25}
        initial = {"sensor.temp": {"state": "unknown"}}
        final = {"sensor.temp": {"state": "unavailable"}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is False

    def test_numeric_trigger_none_state(self, detector: TriggerFailureDetector) -> None:
        """Test numeric trigger with None state."""
        trigger = {"entity_id": "sensor.temp", "above": 25}
        initial = {"sensor.temp": {"state": None}}
        final = {"sensor.temp": {"state": None}}

        result = detector._check_numeric_trigger(trigger, initial, final)
        assert result is False


class TestCompareStates:
    """Test _compare_states method."""

    def test_compare_exact_match(self, detector: TriggerFailureDetector) -> None:
        """Test exact state match."""
        result = detector._compare_states("on", "on")
        assert result is True

    def test_compare_case_insensitive(self, detector: TriggerFailureDetector) -> None:
        """Test case-insensitive comparison."""
        result = detector._compare_states("ON", "on")
        assert result is True

    def test_compare_no_match(self, detector: TriggerFailureDetector) -> None:
        """Test state mismatch."""
        result = detector._compare_states("on", "off")
        assert result is False

    def test_compare_none_actual(self, detector: TriggerFailureDetector) -> None:
        """Test with None actual state."""
        result = detector._compare_states("on", None)
        assert result is False

    def test_compare_none_desired(self, detector: TriggerFailureDetector) -> None:
        """Test with None desired state."""
        result = detector._compare_states(None, "on")
        assert result is False

    def test_compare_both_none(self, detector: TriggerFailureDetector) -> None:
        """Test with both states None."""
        result = detector._compare_states(None, None)
        assert result is False

    def test_compare_numeric_strings(self, detector: TriggerFailureDetector) -> None:
        """Test comparing numeric string states."""
        result = detector._compare_states("25", "25")
        assert result is True

    def test_compare_empty_strings(self, detector: TriggerFailureDetector) -> None:
        """Test comparing empty strings."""
        result = detector._compare_states("", "")
        assert result is True


class TestIntegration:
    """Integration tests for trigger failure detector."""

    @pytest.mark.asyncio
    async def test_full_workflow_trigger_failure(
        self,
        detector: TriggerFailureDetector,
        mock_database: MagicMock,
        mock_ha_client: MagicMock,
    ) -> None:
        """Test full workflow detecting trigger failure."""
        # Mock state queries
        mock_ha_client.get_state = AsyncMock(
            return_value={"state": "on", "entity_id": "light.living_room"}
        )

        # Mock automation config
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "light.living_room"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # Monitor and expect failure detection
        result = await detector.monitor_state_changes(
            automation_id="automation.lights_on",
            expected_trigger={"entity_id": "light.living_room", "to": "on"},
            validation_window=0.05,
        )

        assert result is not None
        assert isinstance(result, TriggerFailureContext)
        assert result.automation_id == "automation.lights_on"

    @pytest.mark.asyncio
    async def test_full_workflow_no_trigger_failure(
        self,
        detector: TriggerFailureDetector,
        mock_database: MagicMock,
        mock_ha_client: MagicMock,
    ) -> None:
        """Test full workflow with no trigger failure."""
        # Mock state queries
        mock_ha_client.get_state = AsyncMock(
            return_value={"state": "off", "entity_id": "light.living_room"}
        )

        # Mock automation config (entity not in desired state)
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "light.living_room"
        desired_state.desired_state = "on"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [desired_state]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_database.async_session.return_value = AsyncMock()
        mock_database.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_database.async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # Monitor and expect no failure
        result = await detector.monitor_state_changes(
            automation_id="automation.lights_on",
            expected_trigger={"entity_id": "light.living_room"},
            validation_window=0.05,
        )

        assert result is None
