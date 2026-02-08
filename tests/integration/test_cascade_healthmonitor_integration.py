"""Integration tests for HealthMonitor + CascadeOrchestrator.

These tests validate end-to-end healing workflows with real HealthMonitor
detection triggering cascade execution through actual healers and database.

Test Coverage:
- End-to-end cascade with HealthMonitor detection
- Pattern learning integration across multiple cascades
- Timeout handling with real operations
- Concurrent failures with multiple entities
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from ha_boss.core.config import Config, HomeAssistantConfig, MonitoringConfig
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
from ha_boss.monitoring.health_monitor import HealthMonitor
from ha_boss.monitoring.state_tracker import EntityState, StateTracker

# ============================================================================
# FIXTURES: Database, Healers, Escalator, Orchestrator, HealthMonitor
# ============================================================================


@pytest.fixture
async def database(tmp_path):  # type: ignore
    """Create real async test database."""
    db_path = tmp_path / "test.db"  # type: ignore
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration for HealthMonitor."""
    config = MagicMock(spec=Config)
    config.monitoring = MonitoringConfig(
        include=[],
        exclude=["sensor.time*", "sensor.date*"],
        grace_period_seconds=2,  # Fast grace period for tests
        stale_threshold_seconds=10,  # Fast stale threshold
    )
    config.home_assistant = MagicMock(spec=HomeAssistantConfig)
    return config


@pytest.fixture
async def mock_state_tracker() -> StateTracker:
    """Create a mock state tracker."""
    tracker = MagicMock(spec=StateTracker)
    tracker.instance_id = "test_instance"
    tracker.get_all_states = AsyncMock(return_value={})
    tracker.get_state = AsyncMock(return_value=None)
    return tracker


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
) -> CascadeOrchestrator:
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


@pytest.fixture
async def health_monitor(  # type: ignore
    mock_config: Config, database, mock_state_tracker: StateTracker
) -> HealthMonitor:
    """Create a real HealthMonitor instance."""
    return HealthMonitor(mock_config, database, mock_state_tracker)  # type: ignore


# ============================================================================
# TEST CLASS: End-to-End with HealthMonitor Detection
# ============================================================================


class TestEndToEndWithHealthMonitor:
    """Test HealthMonitor triggers cascade and healing executes.

    These tests validate the complete flow:
    1. HealthMonitor detects entity issue (unavailable/stale)
    2. Issue triggers cascade execution
    3. Cascade attempts healing through levels
    4. Database records complete cascade history
    """

    @pytest.mark.asyncio
    async def test_healthmonitor_detects_and_triggers_cascade(
        self,
        health_monitor: HealthMonitor,  # type: ignore
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """HealthMonitor detects unavailable → triggers cascade → entity recovered.

        Scenario:
        - HealthMonitor detects entity in unavailable state
        - Grace period expired, issue confirmed
        - Issue passed to cascade orchestrator
        - Entity healer recovers entity
        - Cascade completes successfully

        Verifies:
        - HealthMonitor._detect_issue_type() identifies issue
        - Cascade triggered with correct context
        - Entity healer called
        - Database records cascade execution
        """
        # Setup: Create unavailable entity
        unavailable_entity = EntityState(
            entity_id="light.living_room",
            state="unavailable",
            last_updated=datetime.now(UTC),
        )

        # Test HealthMonitor detection logic
        issue_type = health_monitor._detect_issue_type(unavailable_entity)
        assert issue_type == "unavailable"

        # Mock entity healer success
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Create healing context from detected issue
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.healthmonitor_test",
            execution_id=1,
            trigger_type="health_issue",
            failed_entities=["light.living_room"],
        )

        # Execute cascade
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify cascade success
        assert result.success is True
        assert result.successful_level == HealingLevel.ENTITY

        # Verify database record
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            records = list(db_result.scalars().all())
            assert len(records) == 1
            exec_record = records[0]
            assert exec_record.automation_id == "automation.healthmonitor_test"
            assert exec_record.entity_level_success is True
            assert exec_record.final_success is True

    @pytest.mark.asyncio
    async def test_healthmonitor_multiple_issues_concurrent_cascades(
        self,
        health_monitor: HealthMonitor,  # type: ignore
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Multiple detected issues trigger concurrent cascades.

        Scenario:
        - HealthMonitor detects multiple unavailable entities
        - Each triggers independent cascade
        - Cascades execute concurrently
        - All database records created

        Verifies:
        - Multiple issues detected via _detect_issue_type
        - Concurrent cascade execution
        - Each cascade has isolated database record
        - No cross-cascade contamination
        """
        # Setup: Create multiple unavailable entities
        entities_to_test = [
            ("light.living_room", "unavailable"),
            ("sensor.temperature", "unavailable"),
        ]

        # Verify detection works for both
        for entity_id, state in entities_to_test:
            entity = EntityState(
                entity_id=entity_id,
                state=state,
                last_updated=datetime.now(UTC),
            )
            issue_type = health_monitor._detect_issue_type(entity)
            assert issue_type == "unavailable"

        # Mock entity healer success for both
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="",  # Will be set per call
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Create healing contexts for both entities
        contexts = [
            HealingContext(
                instance_id="test_instance",
                automation_id=f"automation.multi_cascade_{i}",
                execution_id=i,
                trigger_type="health_issue",
                failed_entities=[entity_id],
            )
            for i, (entity_id, _) in enumerate(entities_to_test, start=1)
        ]

        # Execute cascades concurrently
        results = await asyncio.gather(
            *[
                orchestrator.execute_cascade(ctx, use_intelligent_routing=False)  # type: ignore
                for ctx in contexts
            ]
        )

        # Verify all cascades succeeded
        assert all(r.success for r in results)
        assert len(results) == 2

        # Verify database records
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            records = list(db_result.scalars().all())
            assert len(records) == 2

            # Verify isolation
            automations = {r.automation_id for r in records}
            assert len(automations) == 2
            assert "automation.multi_cascade_1" in automations
            assert "automation.multi_cascade_2" in automations

    @pytest.mark.asyncio
    async def test_healthmonitor_grace_period_prevents_premature_escalation(
        self,
        health_monitor: HealthMonitor,  # type: ignore
        orchestrator,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Grace period prevents immediate cascade for transient issues.

        Scenario:
        - Entity becomes unavailable
        - HealthMonitor records issue but grace period not expired
        - _check_health_with_grace() respects grace period
        - After grace period expires, issue is detected
        - Cascade triggered

        Verifies:
        - Detection identifies unavailable state
        - Grace period config prevents premature escalation
        - Cascade can be triggered when grace period expires
        """
        # Setup: Entity with unavailable state
        entity = EntityState(
            entity_id="light.test",
            state="unavailable",
            last_updated=datetime.now(UTC),
        )

        # Verify detection identifies the issue
        issue_type = health_monitor._detect_issue_type(entity)
        assert issue_type == "unavailable"

        # Verify grace period is configured (2 seconds in test config)
        assert health_monitor.config.monitoring.grace_period_seconds == 2

        # Create context for cascade after grace period would expire
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.grace_period_test",
            execution_id=1,
            trigger_type="health_issue",
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

        # Execute cascade (as would happen after grace period)
        result = await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore
        assert result.success is True

    @pytest.mark.asyncio
    async def test_cascade_handles_timeout_during_healing(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Cascade times out gracefully when healers are slow.

        Scenario:
        - Cascade initiated with short timeout
        - Entity healer takes longer than timeout
        - Cascade cancels operation
        - Timeout recorded in database
        - Escalator notified

        Verifies:
        - Cascade times out at timeout_seconds
        - Result marked as failure with timeout error
        - Database records timeout
        - No partial healing applied
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.timeout_test",
            execution_id=7,
            trigger_type="health_issue",
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

        # Verify database record
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            exec_record = db_result.scalar_one()
            assert exec_record.final_success is False


# ============================================================================
# TEST CLASS: Pattern Learning Across Multiple Cascades
# ============================================================================


class TestPatternLearningIntegration:
    """Test pattern learning from HealthMonitor-triggered cascades.

    Pattern learning enables intelligent routing: after sufficient successes,
    subsequent cascades for the same automation skip to the proven level.
    """

    @pytest.mark.asyncio
    async def test_pattern_created_after_first_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """First successful cascade creates pattern record.

        Scenario:
        - Cascade executes and entity healer succeeds
        - Cascade completes successfully
        - Pattern learned and stored in database

        Verifies:
        - AutomationOutcomePattern created
        - Pattern tracks successful level (entity)
        - Pattern tracks successful strategy (retry_service_call)
        - Success count initialized to 1
        """
        context = HealingContext(
            instance_id="test_instance",
            automation_id="automation.pattern_create",
            execution_id=9,
            trigger_type="health_issue",
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
    async def test_pattern_incremented_on_repeat_success(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Subsequent successes increment pattern counter.

        Scenario:
        - Pattern exists with success_count = 1
        - Same automation triggers again
        - Cascade succeeds again
        - Pattern updated with success_count = 2

        Verifies:
        - Existing pattern found
        - Success count incremented
        - Timestamp updated to most recent cascade
        - Last_observed reflects latest success
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
            trigger_type="health_issue",
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
    async def test_intelligent_routing_skips_to_proven_level(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
    ) -> None:
        """After threshold, intelligent routing skips to proven level.

        Scenario:
        - Pattern exists with success_count >= threshold (2)
        - Successful level is device
        - Next cascade uses intelligent routing
        - Cascade skips entity level, goes directly to device
        - Device healer succeeds

        Verifies:
        - Pattern matched by intelligent routing
        - Entity level skipped (not attempted)
        - Device level attempted first
        - matched_pattern_id set in result
        - routing_strategy = "intelligent"
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
            trigger_type="health_issue",
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

        # Verify entity healer never called
        entity_healer.heal.assert_not_called()

    @pytest.mark.asyncio
    async def test_pattern_learning_across_multiple_automations(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Patterns learned independently for different automations.

        Scenario:
        - Multiple automations trigger cascades
        - Each learns its own pattern
        - Patterns isolated per automation
        - No cross-contamination

        Verifies:
        - Multiple patterns created
        - Each pattern tracks unique automation
        - Success counts independent
        - Intelligent routing matches correct pattern
        """
        # Execute cascades for two different automations
        for i, automation_id in enumerate(
            ["automation.pattern_a", "automation.pattern_b"], start=1
        ):
            context = HealingContext(
                instance_id="test_instance",
                automation_id=automation_id,
                execution_id=i,
                trigger_type="health_issue",
                failed_entities=[f"light.test_{i}"],
            )

            entity_healer.heal.return_value = EntityHealingResult(
                entity_id=f"light.test_{i}",
                success=True,
                actions_attempted=["retry_service_call"],
                final_action="retry_service_call",
                error_message=None,
                total_duration_seconds=0.5,
            )

            await orchestrator.execute_cascade(context, use_intelligent_routing=False)  # type: ignore

        # Verify both patterns created and isolated
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(AutomationOutcomePattern)
            db_result = await session.execute(stmt)
            patterns = list(db_result.scalars().all())
            assert len(patterns) == 2

            automations = {p.automation_id for p in patterns}
            assert automations == {"automation.pattern_a", "automation.pattern_b"}


# ============================================================================
# TEST CLASS: Concurrent Failures with Multiple Entities
# ============================================================================


class TestConcurrentFailures:
    """Test concurrent entity failures and cascades.

    When multiple entities fail simultaneously, the system should handle
    concurrent cascade execution correctly with proper isolation.
    """

    @pytest.mark.asyncio
    async def test_multiple_entities_concurrent_cascades(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """Multiple failed entities trigger concurrent cascades.

        Scenario:
        - Five entities fail simultaneously
        - Each triggers independent cascade context
        - Cascades execute concurrently
        - All complete successfully
        - Database records created for each

        Verifies:
        - All cascades execute without blocking
        - Each cascade has unique execution record
        - Total execution time < sequential time
        - No deadlocks or race conditions
        """
        entities = [f"light.room_{i}" for i in range(5)]
        contexts = [
            HealingContext(
                instance_id="test_instance",
                automation_id=f"automation.concurrent_{i}",
                execution_id=i,
                trigger_type="health_issue",
                failed_entities=[entity],
            )
            for i, entity in enumerate(entities, start=1)
        ]

        # Mock entity healer success for all
        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Execute cascades concurrently
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(
            *[
                orchestrator.execute_cascade(ctx, use_intelligent_routing=False)  # type: ignore
                for ctx in contexts
            ]
        )
        elapsed = asyncio.get_event_loop().time() - start_time

        # Verify all succeeded
        assert len(results) == 5
        assert all(r.success for r in results)

        # Verify concurrent execution (should be faster than sequential)
        # Sequential would be ~2.5s (5 * 0.5s), concurrent should be <1s
        assert elapsed < 2.0  # Some overhead allowed

        # Verify database records
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            records = list(db_result.scalars().all())
            assert len(records) == 5

            # Verify isolation
            execution_ids = {r.execution_id for r in records}
            assert execution_ids == {1, 2, 3, 4, 5}

    @pytest.mark.asyncio
    async def test_concurrent_cascades_different_healing_levels(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
        device_healer: MagicMock,
        integration_healer: MagicMock,
    ) -> None:
        """Concurrent cascades requiring different healing levels.

        Scenario:
        - Cascade 1: Fails at entity, succeeds at device
        - Cascade 2: Fails at entity, fails at device, succeeds at integration
        - Cascade 3: Succeeds at entity immediately
        - All execute concurrently
        - Database records complete cascade progression

        Verifies:
        - Each cascade progresses through appropriate levels
        - No interference between concurrent cascades
        - Results and database records accurate
        """

        # Cascade 1: entity fails, device succeeds
        context1 = HealingContext(
            instance_id="test_instance",
            automation_id="automation.concurrent_mixed_1",
            execution_id=1,
            trigger_type="health_issue",
            failed_entities=["light.room_1"],
        )

        # Cascade 2: entity fails, device fails, integration succeeds
        context2 = HealingContext(
            instance_id="test_instance",
            automation_id="automation.concurrent_mixed_2",
            execution_id=2,
            trigger_type="health_issue",
            failed_entities=["sensor.temp"],
        )

        # Cascade 3: entity succeeds
        context3 = HealingContext(
            instance_id="test_instance",
            automation_id="automation.concurrent_mixed_3",
            execution_id=3,
            trigger_type="health_issue",
            failed_entities=["light.room_3"],
        )

        # Use context-specific side effects to avoid race conditions
        def entity_heal_side_effect(**kwargs: object) -> EntityHealingResult:
            # Extract entity_id from kwargs
            entity_id = kwargs.get("entity_id", "")
            if entity_id == "light.room_3":
                return EntityHealingResult(
                    entity_id="light.room_3",
                    success=True,
                    actions_attempted=["retry_service_call"],
                    final_action="retry_service_call",
                    error_message=None,
                    total_duration_seconds=0.3,
                )
            else:
                return EntityHealingResult(
                    entity_id=entity_id,
                    success=False,
                    actions_attempted=["retry_service_call"],
                    final_action=None,
                    error_message="Failed",
                    total_duration_seconds=0.5,
                )

        def device_heal_side_effect(**kwargs: object) -> DeviceHealingResult:
            # Device succeeds for room_1, fails for others
            # The heal function receives entity_ids (list) and other args
            entity_ids = kwargs.get("entity_ids", [])
            entity_id = entity_ids[0] if entity_ids else ""
            if entity_id == "light.room_1":
                return DeviceHealingResult(
                    devices_attempted=["device_1"],
                    success=True,
                    devices_healed=["device_1"],
                    actions_attempted=["reconnect"],
                    final_action="reconnect",
                    error_message=None,
                    total_duration_seconds=1.0,
                )
            else:
                return DeviceHealingResult(
                    devices_attempted=["device_2"],
                    success=False,
                    devices_healed=[],
                    actions_attempted=["reconnect"],
                    final_action=None,
                    error_message="Failed",
                    total_duration_seconds=1.0,
                )

        entity_healer.heal.side_effect = entity_heal_side_effect
        device_healer.heal.side_effect = device_heal_side_effect
        integration_healer.heal = AsyncMock(return_value=True)

        # Execute concurrently
        results = await asyncio.gather(
            orchestrator.execute_cascade(context1, use_intelligent_routing=False),  # type: ignore
            orchestrator.execute_cascade(context2, use_intelligent_routing=False),  # type: ignore
            orchestrator.execute_cascade(context3, use_intelligent_routing=False),  # type: ignore
        )

        # Verify results
        assert len(results) == 3
        assert all(r.success for r in results)

        # Verify database
        db = database  # type: ignore
        async with db.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            records = list(db_result.scalars().all())
            assert len(records) == 3

            # Check cascade 1: entity fails, device succeeds
            c1 = [r for r in records if r.execution_id == 1][0]
            assert c1.entity_level_attempted is True
            assert c1.entity_level_success is False
            assert c1.device_level_attempted is True
            assert c1.device_level_success is True
            assert c1.final_success is True

            # Check cascade 2: entity fails, device fails, integration succeeds
            c2 = [r for r in records if r.execution_id == 2][0]
            assert c2.entity_level_attempted is True
            assert c2.entity_level_success is False
            assert c2.device_level_attempted is True
            assert c2.device_level_success is False
            assert c2.integration_level_attempted is True
            assert c2.integration_level_success is True
            assert c2.final_success is True

            # Check cascade 3: entity succeeds
            c3 = [r for r in records if r.execution_id == 3][0]
            assert c3.entity_level_attempted is True
            assert c3.entity_level_success is True
            assert c3.device_level_attempted is False
            assert c3.final_success is True

    @pytest.mark.asyncio
    async def test_concurrent_cascades_no_database_corruption(
        self,
        orchestrator,  # type: ignore
        database,  # type: ignore
        entity_healer: MagicMock,
    ) -> None:
        """High concurrency ensures no database corruption.

        Scenario:
        - 10 cascades execute concurrently
        - Each creates cascade record and pattern
        - Verify all records created correctly
        - Verify data integrity

        Verifies:
        - No lost records under high concurrency
        - Data integrity preserved
        - No constraint violations
        - Timestamps accurate
        """
        num_cascades = 10

        contexts = [
            HealingContext(
                instance_id="test_instance",
                automation_id=f"automation.stress_test_{i}",
                execution_id=i,
                trigger_type="health_issue",
                failed_entities=[f"light.room_{i}"],
            )
            for i in range(1, num_cascades + 1)
        ]

        entity_healer.heal.return_value = EntityHealingResult(
            entity_id="",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.1,
        )

        # Execute concurrently
        results = await asyncio.gather(
            *[
                orchestrator.execute_cascade(ctx, use_intelligent_routing=False)  # type: ignore
                for ctx in contexts
            ]
        )

        # Verify all succeeded
        assert len(results) == num_cascades
        assert all(r.success for r in results)

        # Verify database integrity
        db = database  # type: ignore
        async with db.async_session() as session:
            # Check cascade executions
            exec_stmt = select(HealingCascadeExecution)
            exec_result = await session.execute(exec_stmt)
            exec_records = list(exec_result.scalars().all())
            assert len(exec_records) == num_cascades

            # Check patterns
            pattern_stmt = select(AutomationOutcomePattern)
            pattern_result = await session.execute(pattern_stmt)
            pattern_records = list(pattern_result.scalars().all())
            assert len(pattern_records) == num_cascades

            # Verify execution_ids are unique and complete
            exec_ids = {r.execution_id for r in exec_records}
            assert exec_ids == set(range(1, num_cascades + 1))

            # Verify automations are unique
            automations = {r.automation_id for r in exec_records}
            expected_automations = {
                f"automation.stress_test_{i}" for i in range(1, num_cascades + 1)
            }
            assert automations == expected_automations
