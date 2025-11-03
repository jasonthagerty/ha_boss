"""Tests for state_tracker module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_boss.core.database import Database
from ha_boss.core.exceptions import DatabaseError
from ha_boss.monitoring.state_tracker import (
    EntityState,
    StateTracker,
    create_state_tracker,
)


@pytest.fixture
async def mock_database() -> Database:
    """Create a mock database."""
    db = MagicMock(spec=Database)
    db.async_session = MagicMock()
    return db


@pytest.fixture
async def state_tracker(mock_database: Database) -> StateTracker:
    """Create a state tracker instance."""
    return StateTracker(mock_database)


@pytest.fixture
def sample_states() -> list[dict]:
    """Sample entity states for testing."""
    return [
        {
            "entity_id": "sensor.temperature",
            "state": "23.5",
            "last_updated": "2024-01-01T12:00:00Z",
            "attributes": {"friendly_name": "Living Room Temperature", "unit": "°C"},
        },
        {
            "entity_id": "binary_sensor.door",
            "state": "off",
            "last_updated": "2024-01-01T12:05:00Z",
            "attributes": {"friendly_name": "Front Door", "device_class": "door"},
        },
        {
            "entity_id": "light.bedroom",
            "state": "on",
            "last_updated": "2024-01-01T12:10:00Z",
            "attributes": {"friendly_name": "Bedroom Light", "brightness": 200},
        },
    ]


class TestEntityState:
    """Tests for EntityState class."""

    def test_entity_state_initialization(self) -> None:
        """Test EntityState initialization."""
        now = datetime.utcnow()
        state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=now,
            attributes={"key": "value"},
        )

        assert state.entity_id == "sensor.test"
        assert state.state == "active"
        assert state.last_updated == now
        assert state.attributes == {"key": "value"}

    def test_entity_state_repr(self) -> None:
        """Test EntityState string representation."""
        now = datetime.utcnow()
        state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=now,
        )

        repr_str = repr(state)
        assert "sensor.test" in repr_str
        assert "active" in repr_str


class TestStateTrackerInitialization:
    """Tests for StateTracker initialization."""

    @pytest.mark.asyncio
    async def test_initialize_empty(self, state_tracker: StateTracker) -> None:
        """Test initialization with empty state list."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize([])
            states = await state_tracker.get_all_states()
            assert len(states) == 0

    @pytest.mark.asyncio
    async def test_initialize_with_states(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test initialization with sample states."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

            states = await state_tracker.get_all_states()
            assert len(states) == 3

            # Check specific entity
            temp_state = await state_tracker.get_state("sensor.temperature")
            assert temp_state is not None
            assert temp_state.state == "23.5"
            assert temp_state.attributes["friendly_name"] == "Living Room Temperature"

    @pytest.mark.asyncio
    async def test_initialize_invalid_timestamp(self, state_tracker: StateTracker) -> None:
        """Test initialization handles invalid timestamps gracefully."""
        states = [
            {
                "entity_id": "sensor.test",
                "state": "active",
                "last_updated": "invalid-timestamp",
                "attributes": {},
            }
        ]

        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(states)

            test_state = await state_tracker.get_state("sensor.test")
            assert test_state is not None
            assert test_state.state == "active"
            # Should use current time as fallback
            assert isinstance(test_state.last_updated, datetime)


class TestStateTrackerUpdates:
    """Tests for state update functionality."""

    @pytest.mark.asyncio
    async def test_update_state_new_entity(self, state_tracker: StateTracker) -> None:
        """Test updating state for a new entity."""
        state_data = {
            "entity_id": "sensor.new",
            "new_state": {
                "state": "10",
                "last_updated": "2024-01-01T13:00:00Z",
                "attributes": {"unit": "kWh"},
            },
        }

        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            with patch.object(state_tracker, "_record_state_history", new_callable=AsyncMock):
                await state_tracker.update_state(state_data)

        new_state = await state_tracker.get_state("sensor.new")
        assert new_state is not None
        assert new_state.state == "10"
        assert new_state.attributes["unit"] == "kWh"

    @pytest.mark.asyncio
    async def test_update_state_existing_entity(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test updating state for existing entity."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        # Update temperature sensor
        update_data = {
            "entity_id": "sensor.temperature",
            "new_state": {
                "state": "24.5",
                "last_updated": "2024-01-01T13:00:00Z",
                "attributes": {"friendly_name": "Living Room Temperature", "unit": "°C"},
            },
        }

        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            with patch.object(
                state_tracker, "_record_state_history", new_callable=AsyncMock
            ) as mock_history:
                await state_tracker.update_state(update_data)

                # Should record history since state changed
                mock_history.assert_called_once()

        updated_state = await state_tracker.get_state("sensor.temperature")
        assert updated_state is not None
        assert updated_state.state == "24.5"

    @pytest.mark.asyncio
    async def test_update_state_no_change(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test updating state when state value doesn't change."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        # Update with same state value
        update_data = {
            "entity_id": "sensor.temperature",
            "new_state": {
                "state": "23.5",  # Same as initial
                "last_updated": "2024-01-01T13:00:00Z",
                "attributes": {"friendly_name": "Living Room Temperature", "unit": "°C"},
            },
        }

        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            with patch.object(
                state_tracker, "_record_state_history", new_callable=AsyncMock
            ) as mock_history:
                await state_tracker.update_state(update_data)

                # Should NOT record history since state didn't change
                mock_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_state_with_callback(self, state_tracker: StateTracker) -> None:
        """Test state update triggers callback."""
        callback = AsyncMock()
        state_tracker.on_state_updated = callback

        state_data = {
            "entity_id": "sensor.test",
            "new_state": {
                "state": "active",
                "last_updated": "2024-01-01T13:00:00Z",
                "attributes": {},
            },
        }

        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.update_state(state_data)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0].entity_id == "sensor.test"
        assert args[1] is None  # No old state

    @pytest.mark.asyncio
    async def test_update_state_entity_removed(self, state_tracker: StateTracker) -> None:
        """Test updating state when entity is removed."""
        # Initialize with entity
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(
                [
                    {
                        "entity_id": "sensor.removed",
                        "state": "active",
                        "last_updated": "2024-01-01T12:00:00Z",
                        "attributes": {},
                    }
                ]
            )

        # Send removal event (no new_state)
        removal_data = {
            "entity_id": "sensor.removed",
            "new_state": None,
        }

        await state_tracker.update_state(removal_data)

        # Entity should be removed from cache
        removed_state = await state_tracker.get_state("sensor.removed")
        assert removed_state is None

    @pytest.mark.asyncio
    async def test_update_state_missing_entity_id(self, state_tracker: StateTracker) -> None:
        """Test update_state handles missing entity_id."""
        state_data = {
            "new_state": {
                "state": "active",
                "last_updated": "2024-01-01T13:00:00Z",
            },
        }

        # Should not raise, just log warning
        await state_tracker.update_state(state_data)


class TestStateTrackerQueries:
    """Tests for state query methods."""

    @pytest.mark.asyncio
    async def test_get_state_existing(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test getting state for existing entity."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        state = await state_tracker.get_state("sensor.temperature")
        assert state is not None
        assert state.entity_id == "sensor.temperature"

    @pytest.mark.asyncio
    async def test_get_state_nonexistent(self, state_tracker: StateTracker) -> None:
        """Test getting state for non-existent entity."""
        state = await state_tracker.get_state("sensor.nonexistent")
        assert state is None

    @pytest.mark.asyncio
    async def test_get_all_states(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test getting all states."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        all_states = await state_tracker.get_all_states()
        assert len(all_states) == 3
        assert "sensor.temperature" in all_states
        assert "binary_sensor.door" in all_states
        assert "light.bedroom" in all_states

    @pytest.mark.asyncio
    async def test_get_entities_by_domain(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test getting entities by domain."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        sensors = await state_tracker.get_entities_by_domain("sensor")
        assert len(sensors) == 1
        assert sensors[0].entity_id == "sensor.temperature"

        binary_sensors = await state_tracker.get_entities_by_domain("binary_sensor")
        assert len(binary_sensors) == 1
        assert binary_sensors[0].entity_id == "binary_sensor.door"

        lights = await state_tracker.get_entities_by_domain("light")
        assert len(lights) == 1
        assert lights[0].entity_id == "light.bedroom"

    @pytest.mark.asyncio
    async def test_is_entity_monitored(
        self, state_tracker: StateTracker, sample_states: list[dict]
    ) -> None:
        """Test checking if entity is monitored."""
        with patch.object(state_tracker, "_persist_entity", new_callable=AsyncMock):
            await state_tracker.initialize(sample_states)

        assert await state_tracker.is_entity_monitored("sensor.temperature") is True
        assert await state_tracker.is_entity_monitored("sensor.nonexistent") is False


class TestStateTrackerPersistence:
    """Tests for database persistence."""

    @pytest.mark.asyncio
    async def test_persist_entity_new(self, mock_database: Database) -> None:
        """Test persisting a new entity to database."""
        tracker = StateTracker(mock_database)

        # Mock session and query
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Entity doesn't exist
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
            attributes={"friendly_name": "Test Sensor"},
        )

        await tracker._persist_entity(entity_state)

        # Should add new entity
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_entity_database_error(self, mock_database: Database) -> None:
        """Test handling database error during persist."""
        tracker = StateTracker(mock_database)

        # Mock session to raise error
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Database error"))
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        entity_state = EntityState(
            entity_id="sensor.test",
            state="active",
            last_updated=datetime.utcnow(),
        )

        with pytest.raises(DatabaseError):
            await tracker._persist_entity(entity_state)


class TestCreateStateTracker:
    """Tests for create_state_tracker factory function."""

    @pytest.mark.asyncio
    async def test_create_state_tracker(
        self, mock_database: Database, sample_states: list[dict]
    ) -> None:
        """Test creating and initializing state tracker."""
        with patch.object(StateTracker, "_persist_entity", new_callable=AsyncMock):
            tracker = await create_state_tracker(mock_database, sample_states)

            assert isinstance(tracker, StateTracker)
            states = await tracker.get_all_states()
            assert len(states) == 3

    @pytest.mark.asyncio
    async def test_create_state_tracker_with_callback(self, mock_database: Database) -> None:
        """Test creating state tracker with callback."""
        callback = AsyncMock()

        with patch.object(StateTracker, "_persist_entity", new_callable=AsyncMock):
            tracker = await create_state_tracker(mock_database, [], on_state_updated=callback)

            assert tracker.on_state_updated == callback
