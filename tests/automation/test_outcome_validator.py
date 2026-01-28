"""Tests for outcome validation service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.outcome_validator import (
    EntityValidationResult,
    OutcomeValidator,
    ValidationResult,
)
from ha_boss.core.database import (
    AutomationDesiredState,
    AutomationExecution,
    AutomationOutcomePattern,
    AutomationOutcomeValidation,
)


@pytest.fixture
def mock_database():
    """Create mock database."""
    db = MagicMock()
    db.async_session = MagicMock()
    return db


@pytest.fixture
def mock_ha_client():
    """Create mock HA client."""
    client = AsyncMock()
    client.get_history = AsyncMock()
    return client


@pytest.fixture
def validator(mock_database, mock_ha_client):
    """Create OutcomeValidator with mocks."""
    return OutcomeValidator(
        database=mock_database,
        ha_client=mock_ha_client,
        instance_id="test_instance",
    )


@pytest.fixture
def mock_execution():
    """Create mock AutomationExecution."""
    execution = MagicMock(spec=AutomationExecution)
    execution.id = 123
    execution.automation_id = "automation.test"
    execution.executed_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    return execution


@pytest.fixture
def mock_desired_states():
    """Create mock desired states."""
    state1 = MagicMock(spec=AutomationDesiredState)
    state1.entity_id = "light.bedroom"
    state1.desired_state = "on"
    state1.desired_attributes = {"brightness": 128}

    state2 = MagicMock(spec=AutomationDesiredState)
    state2.entity_id = "switch.fan"
    state2.desired_state = "off"
    state2.desired_attributes = None

    return [state1, state2]


class TestOutcomeValidator:
    """Test OutcomeValidator service."""

    @pytest.mark.asyncio
    async def test_validate_execution_success(
        self, validator, mock_database, mock_ha_client, mock_execution, mock_desired_states
    ):
        """Test successful validation where all entities reach desired state."""
        # Mock database queries
        mock_session = AsyncMock()

        # Mock execution query
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        # Mock desired states query
        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = mock_desired_states

        mock_session.execute.side_effect = [
            mock_exec_result,  # Get execution
            mock_desired_result,  # Get desired states
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Mock HA history responses (both entities reached desired state)
        light_history = [
            [
                {
                    "state": "on",
                    "attributes": {"brightness": 128},
                    "last_changed": "2024-01-01T12:00:01Z",
                }
            ]
        ]

        switch_history = [
            [
                {
                    "state": "off",
                    "attributes": {},
                    "last_changed": "2024-01-01T12:00:02Z",
                }
            ]
        ]

        mock_ha_client.get_history.side_effect = [light_history, switch_history]

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Verify result
        assert result.overall_success is True
        assert len(result.entity_results) == 2
        assert result.entity_results["light.bedroom"].achieved is True
        assert result.entity_results["switch.fan"].achieved is True

        # Verify time_to_achievement was calculated
        assert result.entity_results["light.bedroom"].time_to_achievement_ms == 1000
        assert result.entity_results["switch.fan"].time_to_achievement_ms == 2000

    @pytest.mark.asyncio
    async def test_validate_execution_partial_failure(
        self, validator, mock_database, mock_ha_client, mock_execution, mock_desired_states
    ):
        """Test partial failure where some entities don't reach desired state."""
        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = mock_desired_states

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Light succeeded, switch failed (wrong state)
        light_history = [
            [
                {
                    "state": "on",
                    "attributes": {"brightness": 128},
                    "last_changed": "2024-01-01T12:00:01Z",
                }
            ]
        ]

        switch_history = [
            [
                {
                    "state": "on",  # Still on instead of off
                    "attributes": {},
                    "last_changed": "2024-01-01T12:00:02Z",
                }
            ]
        ]

        mock_ha_client.get_history.side_effect = [light_history, switch_history]

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Verify result
        assert result.overall_success is False
        assert result.entity_results["light.bedroom"].achieved is True
        assert result.entity_results["switch.fan"].achieved is False
        assert result.entity_results["switch.fan"].actual_state == "on"

    @pytest.mark.asyncio
    async def test_validate_execution_complete_failure(
        self, validator, mock_database, mock_ha_client, mock_execution, mock_desired_states
    ):
        """Test complete failure where no entities reach desired state."""
        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = mock_desired_states

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Both entities failed to reach desired state
        light_history = [
            [
                {
                    "state": "off",  # Still off
                    "attributes": {"brightness": 0},
                    "last_changed": "2024-01-01T12:00:01Z",
                }
            ]
        ]

        switch_history = [
            [
                {
                    "state": "on",  # Still on
                    "attributes": {},
                    "last_changed": "2024-01-01T12:00:02Z",
                }
            ]
        ]

        mock_ha_client.get_history.side_effect = [light_history, switch_history]

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Verify result
        assert result.overall_success is False
        assert result.entity_results["light.bedroom"].achieved is False
        assert result.entity_results["switch.fan"].achieved is False

    @pytest.mark.asyncio
    async def test_validate_execution_no_history(
        self, validator, mock_database, mock_ha_client, mock_execution, mock_desired_states
    ):
        """Test handling when no history is available."""
        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = mock_desired_states

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # No history returned
        mock_ha_client.get_history.return_value = []

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Verify result
        assert result.overall_success is False
        assert result.entity_results["light.bedroom"].achieved is False
        assert result.entity_results["light.bedroom"].actual_state is None

    @pytest.mark.asyncio
    async def test_validate_execution_not_found(self, validator, mock_database, mock_ha_client):
        """Test error handling when execution ID not found."""
        # Mock database query returning None
        mock_session = AsyncMock()
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = None

        mock_session.execute.return_value = mock_exec_result
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Should raise ValueError
        with pytest.raises(ValueError, match="Execution ID 999 not found"):
            await validator.validate_execution(execution_id=999)

    @pytest.mark.asyncio
    async def test_validate_execution_no_desired_states(
        self, validator, mock_database, mock_ha_client, mock_execution
    ):
        """Test handling when no desired states exist."""
        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        # No desired states found
        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Should return failure with no entity results
        assert result.overall_success is False
        assert len(result.entity_results) == 0

    @pytest.mark.asyncio
    async def test_time_to_achievement_calculation(
        self, validator, mock_database, mock_ha_client, mock_execution
    ):
        """Test calculation of time_to_achievement_ms."""
        # Create desired state
        desired_state = MagicMock(spec=AutomationDesiredState)
        desired_state.entity_id = "light.test"
        desired_state.desired_state = "on"
        desired_state.desired_attributes = {"brightness": 100}

        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = [desired_state]

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # History shows state change after 2.5 seconds
        history = [
            [
                {
                    "state": "off",
                    "attributes": {"brightness": 0},
                    "last_changed": "2024-01-01T12:00:00Z",  # At execution time
                },
                {
                    "state": "on",
                    "attributes": {"brightness": 100},
                    "last_changed": "2024-01-01T12:00:02.500Z",  # 2.5s later
                },
            ]
        ]

        mock_ha_client.get_history.return_value = history

        # Run validation
        result = await validator.validate_execution(execution_id=123)

        # Verify time calculation
        assert result.entity_results["light.test"].achieved is True
        assert result.entity_results["light.test"].time_to_achievement_ms == 2500

    def test_compare_states(self, validator):
        """Test state comparison logic."""
        # Case-insensitive matching
        assert validator._compare_states("on", "on") is True
        assert validator._compare_states("on", "ON") is True
        assert validator._compare_states("OFF", "off") is True

        # Mismatch
        assert validator._compare_states("on", "off") is False

        # None handling
        assert validator._compare_states("on", None) is False

    def test_compare_attributes_exact_match(self, validator):
        """Test exact attribute comparison."""
        desired = {"color": "red", "effect": "none"}
        actual = {"color": "red", "effect": "none"}

        assert validator._compare_attributes(desired, actual) is True

    def test_compare_attributes_numeric_tolerance(self, validator):
        """Test numeric attribute comparison with tolerance."""
        # Within 5% tolerance (brightness 100 ± 5)
        desired = {"brightness": 100}
        actual = {"brightness": 103}  # 3% difference
        assert validator._compare_attributes(desired, actual) is True

        # Outside tolerance
        actual = {"brightness": 110}  # 10% difference
        assert validator._compare_attributes(desired, actual) is False

    def test_compare_attributes_zero_value_tolerance(self, validator):
        """Test numeric attribute comparison with zero desired value."""
        # Zero value should use minimum absolute tolerance (1.0)
        desired = {"brightness": 0}
        actual = {"brightness": 0}  # Exact match
        assert validator._compare_attributes(desired, actual) is True

        # Within minimum tolerance (1.0)
        actual = {"brightness": 1}
        assert validator._compare_attributes(desired, actual) is True

        # Outside minimum tolerance
        actual = {"brightness": 2}
        assert validator._compare_attributes(desired, actual) is False

    def test_compare_attributes_missing_key(self, validator):
        """Test attribute comparison when key is missing."""
        desired = {"brightness": 100, "color_temp": 300}
        actual = {"brightness": 100}  # Missing color_temp

        assert validator._compare_attributes(desired, actual) is False

    def test_compare_attributes_no_desired(self, validator):
        """Test attribute comparison when no desired attributes."""
        # If no desired attributes, always pass
        assert validator._compare_attributes(None, {"any": "value"}) is True
        assert validator._compare_attributes(None, None) is True

    def test_compare_attributes_no_actual(self, validator):
        """Test attribute comparison when no actual attributes."""
        desired = {"brightness": 100}
        assert validator._compare_attributes(desired, None) is False

    @pytest.mark.asyncio
    async def test_store_validation_results(self, validator, mock_database, mock_execution):
        """Test storing validation results in database."""
        # Create validation result
        entity_result = EntityValidationResult(
            entity_id="light.test",
            desired_state="on",
            desired_attributes={"brightness": 128},
            actual_state="on",
            actual_attributes={"brightness": 130},
            achieved=True,
            time_to_achievement_ms=1500,
        )

        result = ValidationResult(
            execution_id=123,
            automation_id="automation.test",
            instance_id="test_instance",
            overall_success=True,
            entity_results={"light.test": entity_result},
        )

        # Mock session
        mock_session = AsyncMock()
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Store results
        await validator._store_validation_results(result)

        # Verify record was added
        assert mock_session.add.call_count == 1
        assert mock_session.commit.call_count == 1

        # Verify record details
        added_record = mock_session.add.call_args[0][0]
        assert isinstance(added_record, AutomationOutcomeValidation)
        assert added_record.entity_id == "light.test"
        assert added_record.achieved is True
        assert added_record.time_to_achievement_ms == 1500

    @pytest.mark.asyncio
    async def test_learn_patterns_new_pattern(self, validator, mock_database):
        """Test learning a new pattern from successful validation."""
        # Create successful entity result
        entity_result = EntityValidationResult(
            entity_id="light.test",
            desired_state="on",
            desired_attributes={"brightness": 128},
            actual_state="on",
            actual_attributes={"brightness": 128},
            achieved=True,
        )

        entity_results = {"light.test": entity_result}

        # Mock session
        mock_session = AsyncMock()

        # Mock pattern query (no existing pattern)
        mock_pattern_result = MagicMock()
        mock_pattern_result.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [
            mock_pattern_result,  # Pattern query
            MagicMock(),  # Update confidence
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Learn patterns
        await validator._learn_patterns("automation.test", entity_results)

        # Verify new pattern was added
        assert mock_session.add.call_count == 1
        added_pattern = mock_session.add.call_args[0][0]
        assert isinstance(added_pattern, AutomationOutcomePattern)
        assert added_pattern.entity_id == "light.test"
        assert added_pattern.occurrence_count == 1

    @pytest.mark.asyncio
    async def test_learn_patterns_existing_pattern(self, validator, mock_database):
        """Test incrementing existing pattern occurrence count."""
        # Create successful entity result
        entity_result = EntityValidationResult(
            entity_id="light.test",
            desired_state="on",
            desired_attributes={"brightness": 128},
            actual_state="on",
            actual_attributes={"brightness": 128},
            achieved=True,
        )

        entity_results = {"light.test": entity_result}

        # Mock existing pattern
        mock_pattern = MagicMock(spec=AutomationOutcomePattern)
        mock_pattern.occurrence_count = 5

        # Mock session
        mock_session = AsyncMock()

        mock_pattern_result = MagicMock()
        mock_pattern_result.scalar_one_or_none.return_value = mock_pattern

        mock_session.execute.side_effect = [
            mock_pattern_result,  # Pattern query
            MagicMock(),  # Update confidence
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Learn patterns
        await validator._learn_patterns("automation.test", entity_results)

        # Verify count was incremented
        assert mock_pattern.occurrence_count == 6

    @pytest.mark.asyncio
    async def test_learn_patterns_skip_failures(self, validator, mock_database):
        """Test that pattern learning skips failed validations."""
        # Create failed entity result
        entity_result = EntityValidationResult(
            entity_id="light.test",
            desired_state="on",
            desired_attributes={"brightness": 128},
            actual_state="off",
            actual_attributes=None,
            achieved=False,
        )

        entity_results = {"light.test": entity_result}

        # Mock session
        mock_session = AsyncMock()
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Learn patterns
        await validator._learn_patterns("automation.test", entity_results)

        # Should not add any patterns or update anything
        assert mock_session.add.call_count == 0
        assert mock_session.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_confidence_update_from_patterns(self, validator, mock_database):
        """Test that confidence scores increase with pattern occurrences."""
        # Create successful entity result
        entity_result = EntityValidationResult(
            entity_id="light.test",
            desired_state="on",
            desired_attributes={},
            actual_state="on",
            actual_attributes={},
            achieved=True,
        )

        entity_results = {"light.test": entity_result}

        # Mock pattern with 3 occurrences
        mock_pattern = MagicMock(spec=AutomationOutcomePattern)
        mock_pattern.occurrence_count = 3

        # Mock session
        mock_session = AsyncMock()

        mock_pattern_result = MagicMock()
        mock_pattern_result.scalar_one_or_none.return_value = mock_pattern

        mock_session.execute.side_effect = [
            mock_pattern_result,
            MagicMock(),  # Update statement
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Learn patterns
        await validator._learn_patterns("automation.test", entity_results)

        # After increment, occurrence_count = 4
        # new_confidence = min(1.0, 0.5 + (4 * 0.1)) = 0.9
        assert mock_pattern.occurrence_count == 4

        # Verify execute was called (confidence update)
        assert mock_session.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_validation_window_configuration(
        self, validator, mock_database, mock_ha_client, mock_execution, mock_desired_states
    ):
        """Test that validation window is configurable."""
        # Mock database queries
        mock_session = AsyncMock()

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_execution

        mock_desired_result = MagicMock()
        mock_desired_result.scalars.return_value.all.return_value = mock_desired_states

        mock_session.execute.side_effect = [
            mock_exec_result,
            mock_desired_result,
        ]

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Mock history
        mock_ha_client.get_history.return_value = [[{"state": "on", "attributes": {}}]]

        # Run validation with custom window
        await validator.validate_execution(execution_id=123, validation_window_seconds=10.0)

        # Verify history was called with correct time window
        call_kwargs = mock_ha_client.get_history.call_args.kwargs
        assert "start_time" in call_kwargs
        assert "end_time" in call_kwargs

        # End time should be start + 10 seconds
        start_time = call_kwargs["start_time"]
        end_time = call_kwargs["end_time"]
        assert (end_time - start_time).total_seconds() == 10.0
