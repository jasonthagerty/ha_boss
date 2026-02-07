"""Integration tests for multi-instance healing scenarios.

These tests verify that the healing system correctly handles multiple Home Assistant
instances with proper isolation of patterns, cascades, health tracking, and database
queries.

Test Coverage:
- Instance-specific configuration and orchestrator initialization
- Database query isolation (filtering by instance_id)
- Pattern learning per instance (one instance's patterns don't affect another)
- Cascade execution isolation per instance
- Health tracking per instance
- Concurrent cascades on different instances
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
async def database(tmp_path):
    """Create real async test database with temporary file."""
    db_path = tmp_path / "test_multi_instance.db"
    database = Database(str(db_path))
    await database.init_db()
    yield database
    await database.close()


@pytest.fixture
def entity_healer_ha1():
    """Create mock entity healer for HA instance 1."""
    healer = MagicMock(spec=EntityHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def device_healer_ha1():
    """Create mock device healer for HA instance 1."""
    healer = MagicMock(spec=DeviceHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def integration_healer_ha1():
    """Create mock integration healer for HA instance 1."""
    healer = MagicMock(spec=HealingManager)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def escalator_ha1():
    """Create mock escalator for HA instance 1."""
    esc = MagicMock(spec=NotificationEscalator)
    esc.notify_healing_failure = AsyncMock()
    return esc


@pytest.fixture
def entity_healer_ha2():
    """Create mock entity healer for HA instance 2."""
    healer = MagicMock(spec=EntityHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def device_healer_ha2():
    """Create mock device healer for HA instance 2."""
    healer = MagicMock(spec=DeviceHealer)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def integration_healer_ha2():
    """Create mock integration healer for HA instance 2."""
    healer = MagicMock(spec=HealingManager)
    healer.heal = AsyncMock()
    return healer


@pytest.fixture
def escalator_ha2():
    """Create mock escalator for HA instance 2."""
    esc = MagicMock(spec=NotificationEscalator)
    esc.notify_healing_failure = AsyncMock()
    return esc


@pytest.fixture
def orchestrator_ha1(
    database, entity_healer_ha1, device_healer_ha1, integration_healer_ha1, escalator_ha1
):
    """Create cascade orchestrator for HA instance 1 (home)."""
    return CascadeOrchestrator(
        database=database,
        entity_healer=entity_healer_ha1,
        device_healer=device_healer_ha1,
        integration_healer=integration_healer_ha1,
        escalator=escalator_ha1,
        instance_id="home",
        pattern_match_threshold=2,
    )


@pytest.fixture
def orchestrator_ha2(
    database, entity_healer_ha2, device_healer_ha2, integration_healer_ha2, escalator_ha2
):
    """Create cascade orchestrator for HA instance 2 (office)."""
    return CascadeOrchestrator(
        database=database,
        entity_healer=entity_healer_ha2,
        device_healer=device_healer_ha2,
        integration_healer=integration_healer_ha2,
        escalator=escalator_ha2,
        instance_id="office",
        pattern_match_threshold=2,
    )


class TestMultiInstanceInitialization:
    """Test proper initialization of orchestrators with different instance_ids."""

    def test_orchestrator_ha1_has_correct_instance_id(self, orchestrator_ha1):
        """Test orchestrator for 'home' instance has correct instance_id."""
        assert orchestrator_ha1.instance_id == "home"

    def test_orchestrator_ha2_has_correct_instance_id(self, orchestrator_ha2):
        """Test orchestrator for 'office' instance has correct instance_id."""
        assert orchestrator_ha2.instance_id == "office"

    def test_orchestrators_are_independent(self, orchestrator_ha1, orchestrator_ha2):
        """Test that two orchestrators are separate instances."""
        assert orchestrator_ha1.instance_id != orchestrator_ha2.instance_id
        assert orchestrator_ha1 is not orchestrator_ha2
        assert orchestrator_ha1.database is orchestrator_ha2.database  # Shared database
        assert orchestrator_ha1.entity_healer is not orchestrator_ha2.entity_healer

    def test_orchestrators_share_database(self, orchestrator_ha1, orchestrator_ha2, database):
        """Test that both orchestrators use the same database instance."""
        assert orchestrator_ha1.database is database
        assert orchestrator_ha2.database is database


class TestInstanceIsolationInDatabase:
    """Test that database queries properly filter by instance_id."""

    @pytest.mark.asyncio
    async def test_cascade_executions_isolated_by_instance(
        self, orchestrator_ha1, orchestrator_ha2, database, entity_healer_ha1, entity_healer_ha2
    ):
        """Test that cascade executions are isolated per instance in database."""
        # Configure healers for success
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        # Execute cascade on instance 1
        context_ha1 = HealingContext(
            instance_id="home",
            automation_id="automation.home_lighting",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )
        await orchestrator_ha1.execute_cascade(context_ha1, use_intelligent_routing=False)

        # Execute cascade on instance 2
        context_ha2 = HealingContext(
            instance_id="office",
            automation_id="automation.office_lighting",
            execution_id=2,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )
        await orchestrator_ha2.execute_cascade(context_ha2, use_intelligent_routing=False)

        # Query all cascades
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution)
            db_result = await session.execute(stmt)
            all_executions = list(db_result.scalars().all())

        # Verify we have 2 cascades
        assert len(all_executions) == 2

        # Verify each cascade has correct instance_id
        home_cascades = [e for e in all_executions if e.instance_id == "home"]
        office_cascades = [e for e in all_executions if e.instance_id == "office"]

        assert len(home_cascades) == 1
        assert len(office_cascades) == 1
        assert home_cascades[0].automation_id == "automation.home_lighting"
        assert office_cascades[0].automation_id == "automation.office_lighting"

    @pytest.mark.asyncio
    async def test_patterns_isolated_by_instance(
        self, orchestrator_ha1, orchestrator_ha2, database, entity_healer_ha1, entity_healer_ha2
    ):
        """Test that learned patterns are isolated per instance."""
        # Configure healers for success to trigger pattern learning
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        # Execute on instance 1
        context_ha1 = HealingContext(
            instance_id="home",
            automation_id="automation.test",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )
        await orchestrator_ha1.execute_cascade(context_ha1, use_intelligent_routing=False)

        # Execute on instance 2 with different entity
        context_ha2 = HealingContext(
            instance_id="office",
            automation_id="automation.test",
            execution_id=2,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )
        await orchestrator_ha2.execute_cascade(context_ha2, use_intelligent_routing=False)

        # Query patterns
        async with database.async_session() as session:
            stmt = select(AutomationOutcomePattern)
            db_result = await session.execute(stmt)
            all_patterns = list(db_result.scalars().all())

        # Should have 2 patterns (one per instance)
        assert len(all_patterns) == 2

        # Verify instance isolation
        home_patterns = [p for p in all_patterns if p.instance_id == "home"]
        office_patterns = [p for p in all_patterns if p.instance_id == "office"]

        assert len(home_patterns) == 1
        assert len(office_patterns) == 1
        assert home_patterns[0].entity_id == "light.living_room"
        assert office_patterns[0].entity_id == "light.office"


class TestPatternIsolationBetweenInstances:
    """Test that patterns learned on one instance don't affect another."""

    @pytest.mark.asyncio
    async def test_instance1_pattern_doesnt_affect_instance2(
        self,
        orchestrator_ha1,
        orchestrator_ha2,
        database,
        entity_healer_ha1,
        entity_healer_ha2,
        device_healer_ha2,
    ):
        """Test that successful pattern in instance 1 doesn't influence instance 2 routing."""
        # Learn a pattern on instance 1 (entity level succeeds)
        async with database.async_session() as session:
            pattern = AutomationOutcomePattern(
                instance_id="home",
                automation_id="automation.light_control",
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

        # Configure instance 2 where device level succeeds (different healing path)
        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Retry failed",
            total_duration_seconds=1.0,
        )

        device_healer_ha2.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_office"],
            success=True,
            devices_healed=["device_office"],
            actions_attempted=["reconnect"],
            final_action="reconnect",
            error_message=None,
            total_duration_seconds=2.0,
        )

        # Execute on instance 2 with intelligent routing
        context_ha2 = HealingContext(
            instance_id="office",
            automation_id="automation.light_control",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )

        result = await orchestrator_ha2.execute_cascade(context_ha2, use_intelligent_routing=True)

        # Should fall back to sequential (no matching pattern for office instance)
        # and succeed at device level, not entity level
        assert result.success is True
        assert result.routing_strategy == "sequential"
        assert result.successful_level == HealingLevel.DEVICE
        assert result.entity_results["light.office"] is True


class TestConcurrentCascadesOnDifferentInstances:
    """Test that concurrent cascades on different instances execute properly."""

    @pytest.mark.asyncio
    async def test_concurrent_cascades_home_and_office(
        self,
        orchestrator_ha1,
        orchestrator_ha2,
        entity_healer_ha1,
        entity_healer_ha2,
    ):
        """Test concurrent cascade execution on two different instances."""
        # Configure healers
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Create contexts for both instances
        context_ha1 = HealingContext(
            instance_id="home",
            automation_id="automation.home_lights",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room", "light.bedroom"],
        )

        context_ha2 = HealingContext(
            instance_id="office",
            automation_id="automation.office_lights",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )

        # Execute cascades concurrently
        results = await asyncio.gather(
            orchestrator_ha1.execute_cascade(context_ha1, use_intelligent_routing=False),
            orchestrator_ha2.execute_cascade(context_ha2, use_intelligent_routing=False),
        )

        # Verify both succeeded
        assert results[0].success is True
        assert results[1].success is True
        assert results[0].routing_strategy == "sequential"
        assert results[1].routing_strategy == "sequential"

    @pytest.mark.asyncio
    async def test_concurrent_cascades_with_different_outcomes(
        self,
        orchestrator_ha1,
        orchestrator_ha2,
        entity_healer_ha1,
        entity_healer_ha2,
        device_healer_ha2,
    ):
        """Test concurrent cascades with instance 1 succeeding at entity level, instance 2 at device level."""
        # Instance 1: Entity level succeeds
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=0.5,
        )

        # Instance 2: Entity fails, device succeeds
        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=False,
            actions_attempted=["retry_service_call"],
            final_action=None,
            error_message="Retry failed",
            total_duration_seconds=0.5,
        )

        device_healer_ha2.heal.return_value = DeviceHealingResult(
            devices_attempted=["device_office"],
            success=True,
            devices_healed=["device_office"],
            actions_attempted=["reconnect"],
            final_action="reconnect",
            error_message=None,
            total_duration_seconds=1.5,
        )

        # Create contexts
        context_ha1 = HealingContext(
            instance_id="home",
            automation_id="automation.home_lights",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.living_room"],
        )

        context_ha2 = HealingContext(
            instance_id="office",
            automation_id="automation.office_lights",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )

        # Execute concurrently
        results = await asyncio.gather(
            orchestrator_ha1.execute_cascade(context_ha1, use_intelligent_routing=False),
            orchestrator_ha2.execute_cascade(context_ha2, use_intelligent_routing=False),
        )

        # Verify different outcomes
        assert results[0].success is True
        assert results[0].successful_level == HealingLevel.ENTITY

        assert results[1].success is True
        assert results[1].successful_level == HealingLevel.DEVICE

        # Verify entity results are correct per instance
        assert results[0].entity_results["light.living_room"] is True
        assert results[1].entity_results["light.office"] is True


class TestInstanceConfigurationIsolation:
    """Test that configuration is isolated per instance."""

    def test_orchestrators_have_independent_thresholds(
        self,
        database,
        entity_healer_ha1,
        entity_healer_ha2,
        device_healer_ha1,
        device_healer_ha2,
        integration_healer_ha1,
        integration_healer_ha2,
        escalator_ha1,
        escalator_ha2,
    ):
        """Test that orchestrators can have different pattern_match_thresholds."""
        orch1 = CascadeOrchestrator(
            database=database,
            entity_healer=entity_healer_ha1,
            device_healer=device_healer_ha1,
            integration_healer=integration_healer_ha1,
            escalator=escalator_ha1,
            instance_id="home",
            pattern_match_threshold=2,
        )

        orch2 = CascadeOrchestrator(
            database=database,
            entity_healer=entity_healer_ha2,
            device_healer=device_healer_ha2,
            integration_healer=integration_healer_ha2,
            escalator=escalator_ha2,
            instance_id="office",
            pattern_match_threshold=5,
        )

        assert orch1.pattern_match_threshold == 2
        assert orch2.pattern_match_threshold == 5
        assert orch1.instance_id == "home"
        assert orch2.instance_id == "office"


class TestHealthTrackingPerInstance:
    """Test that health tracking is properly isolated per instance."""

    @pytest.mark.asyncio
    async def test_multiple_cascades_same_instance_accumulate(
        self, orchestrator_ha1, database, entity_healer_ha1
    ):
        """Test that multiple cascades on same instance all appear in database with correct instance_id."""
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.living_room",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        # Execute 3 cascades on instance 1
        for i in range(3):
            context = HealingContext(
                instance_id="home",
                automation_id=f"automation.test_{i}",
                execution_id=i + 1,
                trigger_type="outcome_failure",
                failed_entities=["light.living_room"],
            )
            await orchestrator_ha1.execute_cascade(context, use_intelligent_routing=False)

        # Query cascades
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.instance_id == "home"
            )
            db_result = await session.execute(stmt)
            home_executions = list(db_result.scalars().all())

        # Should have 3 cascades for home instance
        assert len(home_executions) == 3
        assert all(e.instance_id == "home" for e in home_executions)
        automation_ids = {e.automation_id for e in home_executions}
        assert automation_ids == {"automation.test_0", "automation.test_1", "automation.test_2"}

    @pytest.mark.asyncio
    async def test_instance_specific_cascade_queries(
        self, orchestrator_ha1, orchestrator_ha2, database, entity_healer_ha1, entity_healer_ha2
    ):
        """Test that querying cascades by instance_id returns only that instance's data."""
        # Configure healers
        entity_healer_ha1.heal.return_value = EntityHealingResult(
            entity_id="light.home",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        entity_healer_ha2.heal.return_value = EntityHealingResult(
            entity_id="light.office",
            success=True,
            actions_attempted=["retry_service_call"],
            final_action="retry_service_call",
            error_message=None,
            total_duration_seconds=1.0,
        )

        # Execute 2 cascades on instance 1
        for i in range(2):
            context = HealingContext(
                instance_id="home",
                automation_id=f"automation.home_{i}",
                execution_id=i + 1,
                trigger_type="outcome_failure",
                failed_entities=["light.home"],
            )
            await orchestrator_ha1.execute_cascade(context, use_intelligent_routing=False)

        # Execute 1 cascade on instance 2
        context = HealingContext(
            instance_id="office",
            automation_id="automation.office_0",
            execution_id=1,
            trigger_type="outcome_failure",
            failed_entities=["light.office"],
        )
        await orchestrator_ha2.execute_cascade(context, use_intelligent_routing=False)

        # Query for home instance only
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.instance_id == "home"
            )
            db_result = await session.execute(stmt)
            home_executions = list(db_result.scalars().all())

        # Should get only home's cascades
        assert len(home_executions) == 2
        assert all(e.instance_id == "home" for e in home_executions)

        # Query for office instance
        async with database.async_session() as session:
            stmt = select(HealingCascadeExecution).where(
                HealingCascadeExecution.instance_id == "office"
            )
            db_result = await session.execute(stmt)
            office_executions = list(db_result.scalars().all())

        # Should get only office's cascades
        assert len(office_executions) == 1
        assert office_executions[0].instance_id == "office"
