"""End-to-end integration tests for the healing cascade system.

Tests the complete healing cascade flow from automation failure detection
through cascade execution, pattern learning, and database consistency.
"""

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
async def database(tmp_path):  # type: ignore
    """Create real async test database."""
    db_path = tmp_path / "test.db"  # type: ignore
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def entity_healer() -> MagicMock:
    """Create mock entity healer."""
    healer = MagicMock(spec=EntityHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def device_healer() -> MagicMock:
    """Create mock device healer."""
    healer = MagicMock(spec=DeviceHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def integration_healer() -> MagicMock:
    """Create mock integration healer."""
    healer = MagicMock(spec=HealingManager)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def escalator() -> MagicMock:
    """Create mock escalator."""
    esc = MagicMock(spec=NotificationEscalator)
    esc.notify_healing_failure = AsyncMock()
    return esc


@pytest.fixture
async def orchestrator(  # type: ignore
    database,  # type: ignore
    entity_healer: MagicMock,
    device_healer: MagicMock,
    integration_healer: MagicMock,
    escalator: MagicMock,
) -> object:
    """Create real cascade orchestrator with mocked healers."""
    return CascadeOrchestrator(
        database=database,  # type: ignore
        entity_healer=entity_healer,
        device_healer=device_healer,
        integration_healer=integration_healer,
        escalator=escalator,
        instance_id="test_instance",
        pattern_match_threshold=2,
    )


class TestEndToEndCascadeFlow:
    """Test complete end-to-end cascade flows."""

    @pytest.mark.asyncio
    async def test_full_cascade_entity_level_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test complete cascade flow: trigger detection → entity healing → success.

        Verifies:
        - Cascade execution recorded in database
        - Entity result tracked
        - Pattern learning triggers
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.test_flow",
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
            total_duration_seconds=0.5,
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify result
        assert result.success is True
        assert result.successful_level == HealingLevel.ENTITY
        assert result.entity_results["light.living_room"] is True

        # Verify database record created
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            executions = list(db_result.scalars().all())
            assert len(executions) == 1
            exec_record = executions[0]
            assert exec_record.automation_id == "automation.test_flow"
            assert exec_record.final_success is True
            assert exec_record.entity_level_attempted is True
            assert exec_record.entity_level_success is True
            assert exec_record.device_level_attempted is False

        # Verify pattern recorded
        async with db.async_session() as session:
            stmt = select(AutomationOutcomePattern).where(
                AutomationOutcomePattern.automation_id == "automation.test_flow"
            )
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())
            assert len(patterns) == 1
            pattern = patterns[0]
            assert pattern.successful_healing_level == "entity"
            assert pattern.successful_healing_strategy == "retry_service_call"

    @pytest.mark.asyncio
    async def test_full_cascade_device_level_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
    ) -> None:
        """Test complete cascade: entity fails → device heals → success.

        Verifies:
        - L1 fails but doesn't stop cascade
        - L2 succeeds
        - Results recorded correctly
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.device_cascade",
            execution_id=2,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        # Mock entity healer failure
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Service call timeout",
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

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify result
        assert result.success is True
        assert result.successful_level == HealingLevel.DEVICE
        assert HealingLevel.ENTITY in result.levels_attempted
        assert HealingLevel.DEVICE in result.levels_attempted
        assert HealingLevel.INTEGRATION not in result.levels_attempted

        # Verify database consistency
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()
            assert exec_record.entity_level_attempted is True
            assert exec_record.entity_level_success is False
            assert exec_record.device_level_attempted is True
            assert exec_record.device_level_success is True
            assert exec_record.final_success is True

    @pytest.mark.asyncio
    async def test_full_cascade_integration_level_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
        integration_healer: MagicMock,
    ) -> None:
        """Test complete cascade: L1 and L2 fail → L3 succeeds.

        Verifies:
        - Sequential progression through all levels
        - Integration healing succeeds
        - All database records updated correctly
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.integration_cascade",
            execution_id=3,
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

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify result
        assert result.success is True
        assert result.successful_level == HealingLevel.INTEGRATION
        assert result.successful_strategy == "reload_integration"
        assert len(result.levels_attempted) == 3

        # Verify all levels recorded
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()
            assert exec_record.entity_level_attempted is True
            assert exec_record.entity_level_success is False
            assert exec_record.device_level_attempted is True
            assert exec_record.device_level_success is False
            assert exec_record.integration_level_attempted is True
            assert exec_record.integration_level_success is True

    @pytest.mark.asyncio
    async def test_cascade_escalation_on_complete_failure(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
        integration_healer: MagicMock,
        escalator: MagicMock,
    ) -> None:
        """Test cascade escalation when all levels fail.

        Verifies:
        - Cascade fails after L3
        - Escalator notified
        - Database records failure
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.escalation_test",
            execution_id=4,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
        )

        # Mock all healers failing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Failed",
            total_duration_seconds=1.0,
        )

        device_healer.heal.return_value = DeviceHealingResult(
            devices_attempted=[],
            success=False,
            devices_healed=[],
            actions_attempted=["reconnect"],
            final_action=None,
            error_message="Failed",
            total_duration_seconds=2.0,
        )

        integration_healer.heal.return_value = False

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify result
        assert result.success is False
        assert result.error_message == "All healing levels failed"

        # Verify escalator was called
        escalator.notify_healing_failure.assert_called_once()

        # Verify database records failure
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()
            assert exec_record.final_success is False


class TestSequentialCascadeProgression:
    """Test sequential cascade L1→L2→L3 progression logic."""

    @pytest.mark.asyncio
    async def test_cascade_stops_at_first_success(
        self,
        orchestrator,  # type: ignore
        device_healer: MagicMock,
        entity_healer: MagicMock,
    ) -> None:
        """Verify cascade stops at first successful level.

        If L1 succeeds, L2 and L3 should not be attempted.
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.stop_test",
            execution_id=5,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
        )

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify only L1 attempted
        assert result.success is True
        assert result.levels_attempted == [HealingLevel.ENTITY]

        # Verify L2 healer never called
        device_healer.heal.assert_not_called()

    @pytest.mark.asyncio
    async def test_cascade_progression_through_levels(
        self,
        orchestrator,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
        integration_healer: MagicMock,
    ) -> None:
        """Verify cascade progresses through all levels sequentially.

        Tests the L1→L2→L3 progression when each level fails.
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.progression",
            execution_id=6,
            trigger_type="outcome_failure",
            failed_entities=["sensor.test"],
        )

        # Track call order
        call_sequence: list[str] = []

        async def mock_entity_heal(**kwargs: object) -> EntityHealingResult:
            call_sequence.append("entity")
            return EntityHealingResult(
                entity_id="sensor.test",
                success=False,
                actions_attempted=["retry_service_call"],
                final_action=None,
                error_message="Failed",
                total_duration_seconds=1.0,
            )

        async def mock_device_heal(**kwargs: object) -> DeviceHealingResult:
            call_sequence.append("device")
            return DeviceHealingResult(
                devices_attempted=[],
                success=False,
                devices_healed=[],
                actions_attempted=["reconnect"],
                final_action=None,
                error_message="Failed",
                total_duration_seconds=2.0,
            )

        def mock_integration_heal(health_issue: object) -> bool:
            call_sequence.append("integration")
            return False

        entity_healer.heal.side_effect = mock_entity_heal
        device_healer.heal.side_effect = mock_device_heal
        integration_healer.heal = AsyncMock(side_effect=mock_integration_heal)

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify all levels attempted in order
        assert call_sequence == ["entity", "device", "integration"]
        assert result.levels_attempted == [
            HealingLevel.ENTITY,
            HealingLevel.DEVICE,
            HealingLevel.INTEGRATION,
        ]


class TestCascadeTimeout:
    """Test cascade timeout and timeout escalation."""

    @pytest.mark.asyncio
    async def test_cascade_timeout_interrupts_healing(
        self,
        orchestrator,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test cascade timeout interrupts slow healing.

        Verifies:
        - Cascade times out at timeout_seconds
        - Result marked as failure
        - Error message indicates timeout
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.timeout_test",
            execution_id=7,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
            timeout_seconds=0.1,  # Very short timeout
        )

        # Mock slow entity healer
        async def slow_heal(**kwargs: object) -> EntityHealingResult:
            await asyncio.sleep(1.0)  # Takes longer than timeout
            return EntityHealingResult(
                entity_id="light.test",
                success=True,
                actions_attempted=["retry_service_call"],
                final_action="retry_service_call",
                error_message=None,
                total_duration_seconds=1.0,
            )

        entity_healer.heal.side_effect = slow_heal

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify timeout
        assert result.success is False
        assert "timed out" in result.error_message.lower()  # type: ignore

    @pytest.mark.asyncio
    async def test_cascade_timeout_recorded_in_database(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test timeout is recorded in cascade execution record."""
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.timeout_db_test",
            execution_id=8,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
            timeout_seconds=0.05,
        )

        # Mock slow healer
        async def slow_heal(**kwargs: object) -> EntityHealingResult:
            await asyncio.sleep(0.5)
            return EntityHealingResult(
                entity_id="light.test",
                success=True,
                actions_attempted=[],
                final_action=None,
                error_message=None,
                total_duration_seconds=0.5,
            )

        entity_healer.heal.side_effect = slow_heal

        # Execute cascade
        await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify database record
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()
            assert exec_record.final_success is False
            assert exec_record.completed_at is not None


class TestPatternLearning:
    """Test pattern learning from successful cascades."""

    @pytest.mark.asyncio
    async def test_pattern_created_on_first_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test pattern created when cascade succeeds.

        Verifies:
        - AutomationOutcomePattern record created
        - Pattern tracks successful level and strategy
        - Success count initialized to 1
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.pattern_create",
            execution_id=9,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
        )

        # Mock successful entity healing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Execute cascade
        await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify pattern created
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(AutomationOutcomePattern).where(
                AutomationOutcomePattern.automation_id == "automation.pattern_create"
            )
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())
            assert len(patterns) == 1
            pattern = patterns[0]
            assert pattern.successful_healing_level == "entity"
            assert pattern.successful_healing_strategy == "retry_service_call"
            assert pattern.healing_success_count == 1
            assert pattern.entity_id == "light.test"

    @pytest.mark.asyncio
    async def test_pattern_incremented_on_subsequent_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test pattern success count incremented on subsequent success.

        Verifies:
        - Existing pattern found and updated
        - Success count incremented
        - Timestamp updated
        """
        # Create initial pattern
        db = database  # type: ignore
        async with db.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.pattern_increment",
                entity_id="light.test",
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
            automation_id="automation.pattern_increment",
            execution_id=10,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
        )

        # Mock successful healing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Execute cascade
        await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify pattern updated
        async with db.async_session() as session:
            stmt = select(AutomationOutcomePattern).where(
                AutomationOutcomePattern.automation_id == "automation.pattern_increment"
            )
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())
            assert len(patterns) == 1
            pattern = patterns[0]
            assert pattern.healing_success_count == 2

    @pytest.mark.asyncio
    async def test_pattern_reaches_threshold_enables_intelligent_routing(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        device_healer: MagicMock,
    ) -> None:
        """Test pattern reaching threshold enables intelligent routing.

        Verifies:
        - Pattern with success_count >= threshold can be matched
        - Intelligent routing uses pattern
        - Direct jump to device level (skipping entity)
        """
        # Create pattern with success count = 2 (matches threshold)
        db = database  # type: ignore
        async with db.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="test_instance",
                automation_id="automation.pattern_threshold",
                entity_id="light.test",
                observed_state="on",
                successful_healing_level="device",
                successful_healing_strategy="reconnect",
                healing_success_count=2,
                first_observed=datetime.now(UTC),
                last_observed=datetime.now(UTC),
            )
            session.add(pattern)
            await session.commit()

        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.pattern_threshold",
            execution_id=11,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
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

        # Execute with intelligent routing
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=True)  # type: ignore

        # Verify intelligent routing used
        assert result.success is True
        assert result.routing_strategy == "intelligent"
        assert result.levels_attempted == [HealingLevel.DEVICE]
        assert result.matched_pattern_id is not None


class TestDatabaseConsistency:
    """Test database consistency throughout cascade execution."""

    @pytest.mark.asyncio
    async def test_cascade_execution_record_complete(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test cascade execution record contains all required fields.

        Verifies:
        - Record created before cascade
        - All metadata recorded
        - Timing information accurate
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.db_consistency",
            execution_id=12,
            trigger_type="outcome_failure",
            failed_entities=["light.test1", "light.test2"],
        )

        # Mock successful healing
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test1",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify database record complete
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()

            # Verify all fields
            assert exec_record.instance_id == "test_instance"
            assert exec_record.automation_id == "automation.db_consistency"
            assert exec_record.execution_id == 12
            assert exec_record.trigger_type == "outcome_failure"
            assert exec_record.failed_entities == ["light.test1", "light.test2"]
            assert exec_record.routing_strategy in ["sequential", "intelligent"]
            assert exec_record.created_at is not None
            assert exec_record.completed_at is not None
            assert exec_record.final_success == result.success
            # Timing may differ slightly due to database operations
            assert abs(exec_record.total_duration_seconds - result.total_duration_seconds) < 0.05

    @pytest.mark.asyncio
    async def test_multiple_cascade_records_isolated(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Test multiple cascades produce independent records.

        Verifies:
        - No cross-cascade contamination
        - Each cascade has isolated record
        - Entity results tracked separately
        """
        # First cascade
        context1 = HealingContext(
            instance_id="test_instance",
            automation_id="automation.cascade1",
            execution_id=13,
            trigger_type="outcome_failure",
            failed_entities=["light.test"],
        )

        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.test",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        await orchestrator.execute_cascade(context1, use_intelligent_routing=False)  # type: ignore

        # Second cascade
        context2 = HealingContext(
            instance_id="test_instance",
            automation_id="automation.cascade2",
            execution_id=14,
            trigger_type="outcome_failure",
            failed_entities=["sensor.test"],
        )

        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="sensor.test",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        await orchestrator.execute_cascade(context2, use_intelligent_routing=False)  # type: ignore

        # Verify both records exist and isolated
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            records = list(db_result.scalars().all())
            assert len(records) == 2

            # Verify isolation
            record1 = [r for r in records if r.automation_id == "automation.cascade1"][0]
            record2 = [r for r in records if r.automation_id == "automation.cascade2"][0]

            assert record1.automation_id != record2.automation_id
            assert record1.execution_id != record2.execution_id
            assert record1.failed_entities != record2.failed_entities
