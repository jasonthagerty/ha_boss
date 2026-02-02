"""Tests for entity-level healing."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from ha_boss.core.database import AutomationServiceCall, Database, EntityHealingAction
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.healing.entity_healer import EntityHealer


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.init_db()
    yield database
    await database.close()


@pytest.fixture
def ha_client():
    """Create mock HA client."""
    client = MagicMock(spec=HomeAssistantClient)
    client.call_service = AsyncMock()
    client.instance_id = "test_instance"
    return client


@pytest.fixture
def entity_healer(database, ha_client):
    """Create entity healer instance."""
    return EntityHealer(
        database=database,
        ha_client=ha_client,
        instance_id="test_instance",
        max_retry_attempts=3,
        retry_base_delay=0.1,  # Short delay for tests
    )


class TestEntityHealerInit:
    """Test EntityHealer initialization."""

    def test_init_with_defaults(self, database, ha_client):
        """Test initialization with default values."""
        healer = EntityHealer(
            database=database,
            ha_client=ha_client,
        )
        assert healer.database is database
        assert healer.ha_client is ha_client
        assert healer.instance_id == "default"
        assert healer.max_retry_attempts == 3
        assert healer.retry_base_delay == 1.0

    def test_init_with_custom_values(self, database, ha_client):
        """Test initialization with custom values."""
        healer = EntityHealer(
            database=database,
            ha_client=ha_client,
            instance_id="custom",
            max_retry_attempts=5,
            retry_base_delay=2.0,
        )
        assert healer.instance_id == "custom"
        assert healer.max_retry_attempts == 5
        assert healer.retry_base_delay == 2.0


class TestHeal:
    """Test main heal() method."""

    @pytest.mark.asyncio
    async def test_heal_with_empty_entity_id(self, entity_healer):
        """Test heal with empty entity_id."""
        result = await entity_healer.heal("")
        assert result.success is False
        assert result.error_message == "Invalid entity_id: cannot be empty"
        assert result.actions_attempted == []

    @pytest.mark.asyncio
    async def test_heal_with_no_service_call_history(self, entity_healer):
        """Test heal when no service call history exists."""
        result = await entity_healer.heal("light.living_room")
        assert result.success is False
        assert "No previous service call found" in result.error_message
        assert result.entity_id == "light.living_room"

    @pytest.mark.asyncio
    async def test_heal_succeeds_on_retry(self, entity_healer, database, ha_client):
        """Test heal succeeds on first retry."""
        # Insert service call history
        async with database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_on",
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add(service_call)
            await session.commit()

        # Mock successful service call
        ha_client.call_service.return_value = None

        result = await entity_healer.heal("light.living_room")

        assert result.success is True
        assert result.final_action == "retry_service_call"
        assert "retry_service_call" in result.actions_attempted
        assert result.error_message is None
        assert ha_client.call_service.called

    @pytest.mark.asyncio
    async def test_heal_succeeds_on_alternative_params(self, entity_healer, database, ha_client):
        """Test heal succeeds with alternative parameters after retry fails."""
        # Insert service call history
        async with database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_on",
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add(service_call)
            await session.commit()

        # Mock: first 3 retries fail, then alternative succeeds
        call_count = 0

        async def mock_call_service(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:  # First 3 retries fail
                raise Exception("Service call failed")
            # Alternative succeeds
            return None

        ha_client.call_service.side_effect = mock_call_service

        result = await entity_healer.heal("light.living_room")

        assert result.success is True
        assert result.final_action == "alternative_params"
        assert "retry_service_call" in result.actions_attempted
        assert "alternative_params" in result.actions_attempted
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_heal_all_strategies_fail(self, entity_healer, database, ha_client):
        """Test heal when all strategies fail."""
        # Insert service call history
        async with database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_on",
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add(service_call)
            await session.commit()

        # Mock: all calls fail
        ha_client.call_service.side_effect = Exception("Service unavailable")

        result = await entity_healer.heal("light.living_room")

        assert result.success is False
        assert result.final_action is None
        assert "retry_service_call" in result.actions_attempted
        assert "alternative_params" in result.actions_attempted
        assert "All healing strategies failed" in result.error_message


class TestRetryServiceCall:
    """Test _retry_service_call method."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self, entity_healer, ha_client):
        """Test retry succeeds immediately."""
        ha_client.call_service.return_value = None

        success = await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )

        assert success is True
        assert ha_client.call_service.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, entity_healer, ha_client):
        """Test retry succeeds on second attempt."""
        call_count = 0

        async def mock_call_service(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First attempt fails")
            return None

        ha_client.call_service.side_effect = mock_call_service

        success = await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )

        assert success is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_fails_all_attempts(self, entity_healer, ha_client):
        """Test retry fails after max attempts."""
        ha_client.call_service.side_effect = Exception("Service unavailable")

        success = await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )

        assert success is False
        assert ha_client.call_service.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff(self, entity_healer, ha_client):
        """Test exponential backoff timing."""
        ha_client.call_service.side_effect = Exception("Service unavailable")

        start_time = asyncio.get_event_loop().time()
        await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )
        elapsed = asyncio.get_event_loop().time() - start_time

        # Expected delays: 0 (first), 0.1 (second), 0.2 (third) = 0.3s total
        # Allow generous margin for test execution time and asyncio overhead
        assert elapsed >= 0.3
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_retry_records_actions_to_database(self, entity_healer, ha_client, database):
        """Test that retry attempts are recorded to database."""
        ha_client.call_service.side_effect = Exception("Service unavailable")

        await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )

        # Check database for recorded actions
        async with database.async_session() as session:
            result = await session.execute(
                select(EntityHealingAction).where(
                    EntityHealingAction.entity_id == "light.living_room"
                )
            )
            actions = result.scalars().all()

        assert len(actions) == 3  # 3 retry attempts
        assert all(a.action_type == "retry_service_call" for a in actions)
        assert all(a.success is False for a in actions)

    @pytest.mark.asyncio
    async def test_retry_handles_timeout(self, entity_healer, ha_client):
        """Test retry handles service call timeouts."""

        async def slow_service(*args, **kwargs):
            await asyncio.sleep(20)  # Exceeds 10s timeout

        ha_client.call_service.side_effect = slow_service

        success = await entity_healer._retry_service_call(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
        )

        assert success is False


class TestAlternativeParams:
    """Test _try_alternative_params method."""

    @pytest.mark.asyncio
    async def test_alternative_params_for_light(self, entity_healer, ha_client):
        """Test alternative parameters for light entities."""
        call_count = 0

        async def mock_call_service(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # First alternative fails
                raise Exception("Failed")
            return None  # Second succeeds

        ha_client.call_service.side_effect = mock_call_service

        success = await entity_healer._try_alternative_params(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            original_params={"entity_id": "light.living_room", "brightness": 200},
        )

        assert success is True
        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_alternative_params_for_climate(self, entity_healer, ha_client):
        """Test alternative parameters for climate entities."""
        ha_client.call_service.return_value = None

        await entity_healer._try_alternative_params(
            entity_id="climate.living_room",
            service_domain="climate",
            service_name="set_temperature",
            original_params={"entity_id": "climate.living_room", "temperature": 20},
        )

        # Should try temperature +/- 1
        assert ha_client.call_service.called

    @pytest.mark.asyncio
    async def test_alternative_params_no_alternatives_available(self, entity_healer, ha_client):
        """Test when no alternatives are available."""
        success = await entity_healer._try_alternative_params(
            entity_id="switch.kitchen",
            service_domain="switch",
            service_name="turn_on",
            original_params={"entity_id": "switch.kitchen"},
        )

        assert success is False
        assert not ha_client.call_service.called

    @pytest.mark.asyncio
    async def test_alternative_params_all_fail(self, entity_healer, ha_client):
        """Test when all alternative parameters fail."""
        ha_client.call_service.side_effect = Exception("Service unavailable")

        success = await entity_healer._try_alternative_params(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            original_params={"entity_id": "light.living_room", "brightness": 200},
        )

        assert success is False

    @pytest.mark.asyncio
    async def test_alternative_params_cover_entity(self, entity_healer, ha_client):
        """Test alternative parameters for cover entities."""
        ha_client.call_service.return_value = None

        await entity_healer._try_alternative_params(
            entity_id="cover.garage",
            service_domain="cover",
            service_name="set_cover_position",
            original_params={"entity_id": "cover.garage", "position": 45},
        )

        # Should try positions 0, 50, 100
        assert ha_client.call_service.called


class TestGetAlternativeParams:
    """Test _get_alternative_params method."""

    def test_light_entity_with_brightness(self, entity_healer):
        """Test alternatives for light with brightness."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            original_params={"brightness": 200},
        )

        assert len(alternatives) == 3
        assert all("brightness_pct" in alt for alt in alternatives)
        assert any(alt["brightness_pct"] == 50 for alt in alternatives)
        assert any(alt["brightness_pct"] == 75 for alt in alternatives)
        assert any(alt["brightness_pct"] == 100 for alt in alternatives)

    def test_light_entity_without_brightness(self, entity_healer):
        """Test alternatives for light without brightness."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="light.living_room",
            service_domain="light",
            service_name="turn_on",
            original_params={},
        )

        assert len(alternatives) == 1
        assert alternatives[0]["brightness_pct"] == 100

    def test_climate_entity(self, entity_healer):
        """Test alternatives for climate entity."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="climate.living_room",
            service_domain="climate",
            service_name="set_temperature",
            original_params={"temperature": 20},
        )

        assert len(alternatives) == 2
        assert any(alt["temperature"] == 21 for alt in alternatives)
        assert any(alt["temperature"] == 19 for alt in alternatives)

    def test_cover_entity_with_position(self, entity_healer):
        """Test alternatives for cover with position."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="cover.garage",
            service_domain="cover",
            service_name="set_cover_position",
            original_params={"position": 45},
        )

        assert len(alternatives) == 3
        assert any(alt["position"] == 0 for alt in alternatives)
        assert any(alt["position"] == 50 for alt in alternatives)
        assert any(alt["position"] == 100 for alt in alternatives)

    def test_cover_entity_open_close(self, entity_healer):
        """Test alternatives for cover open/close."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="cover.garage",
            service_domain="cover",
            service_name="open_cover",
            original_params={},
        )

        assert len(alternatives) == 1
        assert alternatives[0]["service"] == "stop_cover"

    def test_switch_entity_no_alternatives(self, entity_healer):
        """Test that switch entities have no alternatives."""
        alternatives = entity_healer._get_alternative_params(
            entity_id="switch.kitchen",
            service_domain="switch",
            service_name="turn_on",
            original_params={},
        )

        assert len(alternatives) == 0


class TestRecordAction:
    """Test _record_action method."""

    @pytest.mark.asyncio
    async def test_record_successful_action(self, entity_healer, database):
        """Test recording a successful healing action."""
        await entity_healer._record_action(
            entity_id="light.living_room",
            action_type="retry_service_call",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room"},
            triggered_by="automation_failure",
            automation_id="test_automation",
            execution_id=123,
            success=True,
            error_message=None,
            duration_seconds=1.5,
        )

        async with database.async_session() as session:
            result = await session.execute(
                select(EntityHealingAction).where(
                    EntityHealingAction.entity_id == "light.living_room"
                )
            )
            action = result.scalar_one()

        assert action.action_type == "retry_service_call"
        assert action.service_domain == "light"
        assert action.service_name == "turn_on"
        assert action.triggered_by == "automation_failure"
        assert action.automation_id == "test_automation"
        assert action.execution_id == 123
        assert action.success is True
        assert action.error_message is None
        assert action.duration_seconds == 1.5

    @pytest.mark.asyncio
    async def test_record_failed_action(self, entity_healer, database):
        """Test recording a failed healing action."""
        await entity_healer._record_action(
            entity_id="light.living_room",
            action_type="alternative_params",
            service_domain="light",
            service_name="turn_on",
            service_data={"entity_id": "light.living_room", "brightness_pct": 50},
            triggered_by="manual",
            automation_id=None,
            execution_id=None,
            success=False,
            error_message="Service call timeout",
            duration_seconds=10.0,
        )

        async with database.async_session() as session:
            result = await session.execute(
                select(EntityHealingAction).where(
                    EntityHealingAction.entity_id == "light.living_room"
                )
            )
            action = result.scalar_one()

        assert action.success is False
        assert action.error_message == "Service call timeout"
        assert action.automation_id is None
        assert action.execution_id is None


class TestGetLastServiceCall:
    """Test _get_last_service_call method."""

    @pytest.mark.asyncio
    async def test_get_last_service_call_found(self, entity_healer, database):
        """Test retrieving last service call when it exists."""
        # Insert service call
        async with database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_on",
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add(service_call)
            await session.commit()

        result = await entity_healer._get_last_service_call("light.living_room")

        assert result is not None
        service_domain, service_name, service_data = result
        assert service_domain == "light"
        assert service_name == "turn_on"
        assert service_data["entity_id"] == "light.living_room"

    @pytest.mark.asyncio
    async def test_get_last_service_call_not_found(self, entity_healer):
        """Test when no service call exists."""
        result = await entity_healer._get_last_service_call("light.nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_service_call_returns_most_recent(self, entity_healer, database):
        """Test that most recent service call is returned."""
        # Insert multiple service calls
        async with database.async_session() as session:
            old_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_off",
                entity_id="light.living_room",
                called_at=datetime.now(UTC) - timedelta(hours=1),
                success=True,
            )
            new_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="light.turn_on",
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add_all([old_call, new_call])
            await session.commit()

        result = await entity_healer._get_last_service_call("light.living_room")

        assert result is not None
        service_domain, service_name, service_data = result
        assert service_name == "turn_on"  # Most recent

    @pytest.mark.asyncio
    async def test_get_last_service_call_invalid_format(self, entity_healer, database):
        """Test handling of invalid service_name format."""
        # Insert service call with invalid format
        async with database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id="test_instance",
                automation_id="test_automation",
                service_name="invalid_format",  # Missing dot separator
                entity_id="light.living_room",
                called_at=datetime.now(UTC),
                success=False,
            )
            session.add(service_call)
            await session.commit()

        result = await entity_healer._get_last_service_call("light.living_room")
        assert result is None


class TestConcurrentHealing:
    """Test concurrent healing operations."""

    @pytest.mark.asyncio
    async def test_concurrent_healing_different_entities(self, entity_healer, database, ha_client):
        """Test healing multiple entities concurrently."""
        # Insert service call history for multiple entities
        async with database.async_session() as session:
            entities = ["light.living_room", "light.bedroom", "light.kitchen"]
            for entity_id in entities:
                service_call = AutomationServiceCall(
                    instance_id="test_instance",
                    automation_id="test_automation",
                    service_name="light.turn_on",
                    entity_id=entity_id,
                    called_at=datetime.now(UTC),
                    success=False,
                )
                session.add(service_call)
            await session.commit()

        ha_client.call_service.return_value = None

        # Heal all entities concurrently
        results = await asyncio.gather(
            entity_healer.heal("light.living_room"),
            entity_healer.heal("light.bedroom"),
            entity_healer.heal("light.kitchen"),
        )

        assert all(r.success for r in results)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_database_records_from_concurrent_operations(
        self, entity_healer, database, ha_client
    ):
        """Test that database correctly records concurrent healing operations."""
        # Insert service call history
        async with database.async_session() as session:
            entities = ["light.room1", "light.room2"]
            for entity_id in entities:
                service_call = AutomationServiceCall(
                    instance_id="test_instance",
                    automation_id="test_automation",
                    service_name="light.turn_on",
                    entity_id=entity_id,
                    called_at=datetime.now(UTC),
                    success=False,
                )
                session.add(service_call)
            await session.commit()

        ha_client.call_service.return_value = None

        # Execute concurrent healing
        await asyncio.gather(
            entity_healer.heal("light.room1"),
            entity_healer.heal("light.room2"),
        )

        # Verify database records
        async with database.async_session() as session:
            result = await session.execute(select(EntityHealingAction))
            actions = result.scalars().all()

        assert len(actions) >= 2  # At least one per entity
