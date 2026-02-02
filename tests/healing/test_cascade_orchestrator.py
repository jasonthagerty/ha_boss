"""Tests for healing cascade orchestrator."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from ha_boss.core.database import (
    AutomationOutcomePattern,
    Database,
    HealingCascadeExecution,
)
from ha_boss.healing.cascade_orchestrator import (
    CascadeOrchestrator,
    HealingContext,
    HealingLevel,
)
from ha_boss.healing.device_healer import DeviceHealer, DeviceHealingResult
from ha_boss.healing.entity_healer import EntityHealer, EntityHealingResult
from ha_boss.healing.escalation import NotificationEscalator
from ha_boss.healing.heal_strategies import HealingManager


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    await database.init_db()
    yield database
    await database.close()


@pytest.fixture
def entity_healer():
    """Create mock entity healer."""
    healer = MagicMock(spec=EntityHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def device_healer():
    """Create mock device healer."""
    healer = MagicMock(spec=DeviceHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def integration_healer():
    """Create mock integration healer."""
    healer = MagicMock(spec=HealingManager)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def escalator():
    """Create mock escalator."""
    esc = MagicMock(spec=NotificationEscalator)
    esc.notify_healing_failure = AsyncMock()
    return esc


@pytest.fixture
def orchestrator(database, entity_healer, device_healer, integration_healer, escalator):
    """Create cascade orchestrator instance."""
    return CascadeOrchestrator(
        database=database,
        entity_healer=entity_healer,
        device_healer=device_healer,
        integration_healer=integration_healer,
        escalator=escalator,
        instance_id="test_instance",
        pattern_match_threshold=2,
    )


class TestCascadeOrchestratorInit:
    """Test CascadeOrchestrator initialization."""

    def test_init_with_defaults(
        self, database, entity_healer, device_healer, integration_healer, escalator
    ):
        """Test initialization with default values."""
        orchestrator = CascadeOrchestrator(
            database=database,
            entity_healer=entity_healer,
            device_healer=device_healer,
            integration_healer=integration_healer,
            escalator=escalator,
        )
        assert orchestrator.database is database
        assert orchestrator.entity_healer is entity_healer
        assert orchestrator.device_healer is device_healer
        assert orchestrator.integration_healer is integration_healer
        assert orchestrator.escalator is escalator
        assert orchestrator.instance_id == "default"
        assert orchestrator.pattern_match_threshold == 2

    def test_init_with_custom_values(
        self, database, entity_healer, device_healer, integration_healer, escalator
    ):
        """Test initialization with custom values."""
        orchestrator = CascadeOrchestrator(
            database=database,
            entity_healer=entity_healer,
            device_healer=device_healer,
            integration_healer=integration_healer,
            escalator=escalator,
            instance_id="custom",
            pattern_match_threshold=5,
        )
        assert orchestrator.instance_id == "custom"
        assert orchestrator.pattern_match_threshold == 5


class TestSequentialCascade:
    """Test sequential cascade execution."""

    @pytest.mark.asyncio
    async def test_cascade_with_no_failed_entities(self, orchestrator):
        """Test cascade with empty failed entities list."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=[],  # Empty list
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        # Should complete but report no success
        assert result.entity_results == {}

    @pytest.mark.asyncio
    async def test_cascade_succeeds_at_entity_level(self, orchestrator, entity_healer):
        """Test cascade succeeds at Level 1 (entity)."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.successful_level == HealingLevel.ENTITY
        assert result.successful_strategy == "retry_service_call"
        assert HealingLevel.ENTITY in result.levels_attempted
        assert HealingLevel.DEVICE not in result.levels_attempted
        assert result.entity_results["light.living_room"] is True

    @pytest.mark.asyncio
    async def test_cascade_succeeds_at_device_level(
        self, orchestrator, entity_healer, device_healer
    ):
        """Test cascade succeeds at Level 2 (device) after Level 1 fails."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer failure
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Retry failed",
            total_duration_seconds=1.0,
        )

        # Mock device healer success
        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=True,
            devices_healed=["device_123"],
            actions_attempted=["reconnect"],
            final_action="reconnect",
            error_message=None,
            total_duration_seconds=2.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.successful_level == HealingLevel.DEVICE
        assert result.successful_strategy == "reconnect"
        assert HealingLevel.ENTITY in result.levels_attempted
        assert HealingLevel.DEVICE in result.levels_attempted
        assert HealingLevel.INTEGRATION not in result.levels_attempted
        assert result.entity_results["light.living_room"] is True

    @pytest.mark.asyncio
    async def test_cascade_succeeds_at_integration_level(
        self, orchestrator, entity_healer, device_healer, integration_healer
    ):
        """Test cascade succeeds at Level 3 (integration) after Level 1 and 2 fail."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer failure
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Retry failed",
            total_duration_seconds=1.0,
        )

        # Mock device healer failure
        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=False,
            devices_healed=[],
            actions_attempted=["reconnect", "reboot"],
            final_action=None,
            error_message="All strategies failed",
            total_duration_seconds=2.0,
        )

        # Mock integration healer success
        integration_healer.heal.return_value = True

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.successful_level == HealingLevel.INTEGRATION
        assert result.successful_strategy == "reload_integration"
        assert len(result.levels_attempted) == 3
        assert result.entity_results["light.living_room"] is True

    @pytest.mark.asyncio
    async def test_cascade_all_levels_fail(
        self, orchestrator, entity_healer, device_healer, integration_healer
    ):
        """Test cascade when all levels fail."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock all healers failing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Retry failed",
            total_duration_seconds=1.0,
        )

        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=False,
            devices_healed=[],
            actions_attempted=["reconnect", "reboot"],
            final_action=None,
            error_message="All strategies failed",
            total_duration_seconds=2.0,
        )

        integration_healer.heal.return_value = False

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is False
        assert result.routing_strategy == "sequential"
        assert result.successful_level is None
        assert result.successful_strategy is None
        assert len(result.levels_attempted) == 3
        assert result.error_message == "All healing levels failed"

    @pytest.mark.asyncio
    async def test_cascade_multiple_entities(self, orchestrator, entity_healer):
        """Test cascade with multiple entities."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room", "light.bedroom"],
        )

        # Mock entity healer partial success
        call_count = {"count": 0}

        async def mock_heal(**kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                # First entity succeeds
                return EntityHealingResult(
                    entity_id="light.living_room",
                    success=True,
                    actions_attempted=["retry_service_call"],
                    final_action="retry_service_call",
                    error_message=None,
                    total_duration_seconds=1.0,
                )
            else:
                # Second entity fails
                return EntityHealingResult(
                    entity_id="light.bedroom",
                    success=False,
                    actions_attempted=["retry_service_call"],
                    final_action=None,
                    error_message="Retry failed",
                    total_duration_seconds=1.0,
                )

        entity_healer.heal.side_effect = mock_heal

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        # Cascade succeeds if ANY entity heals
        assert result.success is True
        assert result.entity_results["light.living_room"] is True
        assert result.entity_results["light.bedroom"] is False


class TestIntelligentRouting:
    """Test intelligent routing with pattern matching."""

    @pytest.mark.asyncio
    async def test_intelligent_routing_with_pattern(self, orchestrator, database, device_healer):
        """Test intelligent routing jumps to proven level."""
        # Create pattern showing device-level healing works
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.test",
                entity_id="light.living_room",
                observed_state="on",
                successful_healing_level="device",
                successful_healing_strategy="reconnect",
                healing_success_count=5,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock device healer success
        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=True,
            devices_healed=["device_123"],
            actions_attempted=["reconnect"],
            final_action="reconnect",
            error_message=None,
            total_duration_seconds=2.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)

        assert result.success is True
        assert result.routing_strategy == "intelligent"
        assert result.successful_level == HealingLevel.DEVICE
        # Should jump directly to device level, skipping entity level
        assert result.levels_attempted == [HealingLevel.DEVICE]
        assert result.matched_pattern_id is not None

    @pytest.mark.asyncio
    async def test_intelligent_routing_fallback_to_sequential(
        self, orchestrator, database, device_healer, entity_healer
    ):
        """Test intelligent routing falls back to sequential when pattern fails."""
        # Create pattern showing device-level healing works
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.test",
                entity_id="light.living_room",
                observed_state="on",
                successful_healing_level="device",
                successful_healing_strategy="reconnect",
                healing_success_count=5,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock device healer failure (pattern doesn't work this time)
        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=False,
            devices_healed=[],
            actions_attempted=["reconnect"],
            final_action=None,
            error_message="Reconnect failed",
            total_duration_seconds=2.0,
        )

        # Mock entity healer success (fallback succeeds)
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)

        # Falls back to sequential, which succeeds at entity level
        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.successful_level == HealingLevel.ENTITY

    @pytest.mark.asyncio
    async def test_no_pattern_match(self, orchestrator, entity_healer):
        """Test behavior when no pattern matches."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)

        # No pattern, falls back to sequential
        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.matched_pattern_id is None


class TestPatternLearning:
    """Test pattern learning from successful healing."""

    @pytest.mark.asyncio
    async def test_record_new_pattern(self, orchestrator, database, entity_healer):
        """Test recording new successful healing pattern."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is True

        # Check pattern was recorded
        async with database.async_session() as session:
            stmt = select(AutomationOutcomePattern).where(
                AutomationOutcomePattern.automation_id == "automation.test"
            )
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())

            assert len(patterns) == 1
            pattern = patterns[0]
            assert pattern.successful_healing_level == "entity"
            assert pattern.successful_healing_strategy == "retry_service_call"
            assert pattern.healing_success_count == 1

    @pytest.mark.asyncio
    async def test_update_existing_pattern(self, orchestrator, database, entity_healer):
        """Test updating existing pattern on subsequent success."""
        # Create existing pattern
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.test",
                entity_id="light.living_room",
                observed_state="on",
                successful_healing_level="entity",
                successful_healing_strategy="retry_service_call",
                healing_success_count=1,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is True

        # Check pattern was updated
        async with database.async_session() as session:
            stmt = select(AutomationOutcomePattern).where(
                AutomationOutcomePattern.automation_id == "automation.test"
            )
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())

            assert len(patterns) == 1
            pattern = patterns[0]
            assert pattern.healing_success_count == 2  # Incremented


class TestDatabaseRecording:
    """Test cascade execution recording to database."""

    @pytest.mark.asyncio
    async def test_cascade_execution_recorded(self, orchestrator, database, entity_healer):
        """Test cascade execution is recorded to database."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room", "light.bedroom"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        # Check cascade execution was recorded
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            executions = list(db_result.scalars().all())

            assert len(executions) == 1
            execution = executions[0]
            assert execution.instance_id == "test_instance"
            assert execution.automation_id == "automation.test"
            assert execution.execution_id == 1
            assert execution.trigger_type == "outcome_failure"
            assert execution.failed_entities == ["light.living_room", "light.bedroom"]
            assert execution.routing_strategy == "sequential"
            assert execution.entity_level_attempted is True
            assert execution.entity_level_success is True
            assert execution.device_level_attempted is False
            assert execution.final_success is True
            assert execution.total_duration_seconds > 0

    @pytest.mark.asyncio
    async def test_cascade_levels_recorded(
        self, orchestrator, database, entity_healer, device_healer
    ):
        """Test all attempted levels are recorded."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer failure
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Failed",
            total_duration_seconds=1.0,
        )

        # Mock device healer success
        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=True,
            devices_healed=["device_123"],
            actions_attempted=["reconnect"],
            final_action="reconnect",
            error_message=None,
            total_duration_seconds=2.0,
        )

        await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        # Check levels recorded
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            execution = db_result.scalar_one()

            assert execution.entity_level_attempted is True
            assert execution.entity_level_success is False
            assert execution.device_level_attempted is True
            assert execution.device_level_success is True
            assert execution.integration_level_attempted is False


class TestTimeout:
    """Test cascade timeout handling."""

    @pytest.mark.asyncio
    async def test_cascade_timeout(self, orchestrator, entity_healer):
        """Test cascade times out correctly."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
            timeout_seconds=0.1,  # Very short timeout
        )

        # Mock entity healer to take too long
        async def slow_heal(**kwargs):
            await asyncio.sleep(1.0)
            return EntityHealingResult(
                entity_id="light.living_room",
                success=True,
                actions_attempted=["retry_service_call"],
                final_action="retry_service_call",
                error_message=None,
                total_duration_seconds=1.0,
            )

        entity_healer.heal.side_effect = slow_heal

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is False
        assert "timed out" in result.error_message.lower()


class TestErrorHandling:
    """Test error handling in cascade execution."""

    @pytest.mark.asyncio
    async def test_cascade_handles_healer_exception(self, orchestrator, entity_healer):
        """Test cascade handles exceptions from healers."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer raising exception
        entity_healer.heal.side_effect = Exception("Healer crashed")

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is False
        assert "exception" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_intelligent_routing_entity_level(self, orchestrator, database, entity_healer):
        """Test intelligent routing to entity level."""
        # Create pattern showing entity-level healing works
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.test",
                entity_id="light.living_room",
                observed_state="on",
                successful_healing_level="entity",
                successful_healing_strategy="retry_service_call",
                healing_success_count=5,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)

        assert result.success is True
        assert result.routing_strategy == "intelligent"
        assert result.successful_level == HealingLevel.ENTITY
        assert result.levels_attempted == [HealingLevel.ENTITY]

    @pytest.mark.asyncio
    async def test_pattern_with_no_healing_level(self, orchestrator, database, entity_healer):
        """Test pattern without successful healing level falls back to sequential."""
        # Create pattern WITHOUT successful healing level
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.test",
                entity_id="light.living_room",
                observed_state="on",
                successful_healing_level=None,  # No healing level
                healing_success_count=5,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)

        # Falls back to sequential
        assert result.success is True
        assert result.routing_strategy == "sequential"

    @pytest.mark.asyncio
    async def test_integration_healer_exception(
        self, orchestrator, entity_healer, device_healer, integration_healer
    ):
        """Test integration healer exception handling."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity and device healers failing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Failed",
            total_duration_seconds=1.0,
        )

        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_123"],
            success=False,
            devices_healed=[],
            actions_attempted=["reconnect"],
            final_action=None,
            error_message="Failed",
            total_duration_seconds=2.0,
        )

        # Mock integration healer raising exception
        integration_healer.heal.side_effect = Exception("Integration failed")

        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)

        assert result.success is False
        assert result.entity_results["light.living_room"] is False
