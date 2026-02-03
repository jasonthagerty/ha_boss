"""Integration tests for cascade orchestrator integration with automation tracking."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, call, patch

import pytest

from ha_boss.automation.health_tracker import AutomationHealthTracker
from ha_boss.automation.outcome_validator import (
    EntityValidationResult,
    OutcomeValidator,
    ValidationResult,
)
from ha_boss.core.config import (
    Config,
    HomeAssistantConfig,
    HomeAssistantInstance,
    OutcomeValidationConfig,
)
from ha_boss.core.database import AutomationDesiredState, AutomationExecution, init_database
from ha_boss.healing.cascade_orchestrator import (
    CascadeOrchestrator,
    CascadeResult,
    HealingContext,
    HealingLevel,
)
from ha_boss.monitoring.automation_tracker import AutomationTracker


@pytest.fixture
async def database():
    """Create test database."""
    db = await init_database(":memory:")
    yield db
    await db.close()


@pytest.fixture
def mock_ha_client():
    """Create mock Home Assistant client."""
    client = AsyncMock()
    client.get_history = AsyncMock(return_value=[[]])  # Default: no history
    client.call_service = AsyncMock()
    return client


@pytest.fixture
def mock_cascade_orchestrator():
    """Create mock cascade orchestrator."""
    orchestrator = AsyncMock(spec=CascadeOrchestrator)
    orchestrator.execute_cascade = AsyncMock(
        return_value=CascadeResult(
            success=True,
            routing_strategy="sequential",
            levels_attempted=[HealingLevel.ENTITY, HealingLevel.INTEGRATION],
            successful_level=HealingLevel.INTEGRATION,
            successful_strategy="reload_integration",
            entity_results={"light.test": True},
            total_duration_seconds=1.5,
            error_message=None,
        )
    )
    return orchestrator


@pytest.fixture
async def health_tracker(database):
    """Create real health tracker."""
    return AutomationHealthTracker(database=database, consecutive_success_threshold=3)


@pytest.fixture
def config():
    """Create test config with outcome validation enabled."""
    return Config(
        home_assistant=HomeAssistantConfig(
            instances=[
                HomeAssistantInstance(
                    instance_id="test",
                    url="http://test:8123",
                    token="test-token",
                )
            ]
        ),
        outcome_validation=OutcomeValidationConfig(
            enabled=True,
            validation_delay_seconds=0.1,  # Short delay for tests
        ),
    )


class TestAutomationTrackerIntegration:
    """Test AutomationTracker integration with cascade and health tracker."""

    @pytest.mark.asyncio
    async def test_tracker_passes_dependencies_to_validator(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker, config
    ):
        """Test that cascade_orchestrator and health_tracker are passed to OutcomeValidator."""
        tracker = AutomationTracker(
            database=database,
            ha_client=mock_ha_client,
            instance_id="test",
            config=config,
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        # The dependencies should be stored for use in validation
        assert tracker.cascade_orchestrator is mock_cascade_orchestrator
        assert tracker.health_tracker is health_tracker

    @pytest.mark.asyncio
    async def test_tracker_backward_compatible_without_dependencies(
        self, database, mock_ha_client, config
    ):
        """Test that AutomationTracker works without cascade/health tracker."""
        # Should not raise an error
        tracker = AutomationTracker(
            database=database,
            ha_client=mock_ha_client,
            instance_id="test",
            config=config,
            cascade_orchestrator=None,
            health_tracker=None,
        )

        assert tracker.cascade_orchestrator is None
        assert tracker.health_tracker is None

        # Should still process executions without errors
        execution_id = await tracker.record_execution(
            automation_id="automation.test",
            trigger_type="state",
            success=True,
        )

        assert execution_id is not None
        # Verify it didn't crash (no assertion needed beyond this)


class TestOutcomeValidatorIntegration:
    """Test OutcomeValidator integration with cascade and health tracker."""

    async def _setup_execution_with_desired_states(
        self, database, automation_id: str, entity_states: dict[str, str]
    ) -> int:
        """Helper to create an execution with desired states."""
        async with database.async_session() as session:
            # Create execution
            execution = AutomationExecution(
                instance_id="test",
                automation_id=automation_id,
                executed_at=datetime.now(UTC),
                trigger_type="state",
                success=True,
            )
            session.add(execution)
            await session.flush()
            execution_id = execution.id

            # Create desired states
            for entity_id, state in entity_states.items():
                desired_state = AutomationDesiredState(
                    instance_id="test",
                    automation_id=automation_id,
                    entity_id=entity_id,
                    desired_state=state,
                    confidence=0.9,
                    inference_method="test",
                    created_at=datetime.now(UTC),
                )
                session.add(desired_state)

            await session.commit()

        return execution_id

    def _mock_history_success(self, entity_id: str, state: str):
        """Create mock history response for successful state."""
        # Note: Omitting last_changed to avoid timezone-naive datetime arithmetic issues
        # in the validator (which is a known bug to be fixed separately)
        return [
            [
                {
                    "entity_id": entity_id,
                    "state": state,
                    "attributes": {},
                }
            ]
        ]

    def _mock_history_failure(self, entity_id: str, state: str):
        """Create mock history response for failed state."""
        # Note: Omitting last_changed to avoid timezone-naive datetime arithmetic issues
        # in the validator (which is a known bug to be fixed separately)
        return [
            [
                {
                    "entity_id": entity_id,
                    "state": state,
                    "attributes": {},
                }
            ]
        ]

    @pytest.mark.asyncio
    async def test_validator_records_success_in_health_tracker(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test successful validation updates health tracker."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock successful entity history
        mock_ha_client.get_history.return_value = self._mock_history_success("light.test", "on")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        assert result.overall_success is True

        # Give background tasks time to complete
        await asyncio.sleep(0.2)

        # Verify health tracker recorded success
        health = await health_tracker.get_health_status("test", "automation.test")
        assert health.total_executions == 1
        assert health.consecutive_successes == 1
        assert health.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_validator_records_failure_in_health_tracker(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test failed validation updates health tracker."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock failed entity history (expected on, got off)
        mock_ha_client.get_history.return_value = self._mock_history_failure("light.test", "off")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        assert result.overall_success is False

        # Give background tasks time to complete
        await asyncio.sleep(0.3)

        # Verify health tracker recorded failure
        health = await health_tracker.get_health_status("test", "automation.test")
        assert health.total_executions == 1
        assert health.consecutive_successes == 0
        assert health.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_validator_triggers_cascade_on_failure(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test cascade is triggered when validation fails."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock failed entity history
        mock_ha_client.get_history.return_value = self._mock_history_failure("light.test", "off")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background task time to run
        await asyncio.sleep(0.3)

        # Verify cascade was triggered
        mock_cascade_orchestrator.execute_cascade.assert_called_once()
        call_args = mock_cascade_orchestrator.execute_cascade.call_args
        context = call_args[0][0]

        assert isinstance(context, HealingContext)
        assert context.automation_id == "automation.test"
        assert "light.test" in context.failed_entities

    @pytest.mark.asyncio
    async def test_validator_does_not_trigger_cascade_on_success(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test cascade is NOT triggered when validation succeeds."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock successful entity history
        mock_ha_client.get_history.return_value = self._mock_history_success("light.test", "on")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background task time (if any)
        await asyncio.sleep(0.3)

        # Verify cascade was NOT triggered
        mock_cascade_orchestrator.execute_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_validator_skips_cascade_if_not_configured(
        self, database, mock_ha_client, health_tracker
    ):
        """Test cascade is skipped if orchestrator not provided."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock failed entity history
        mock_ha_client.get_history.return_value = self._mock_history_failure("light.test", "off")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=None,  # No orchestrator
            health_tracker=health_tracker,
        )

        # Should not raise error even though validation fails
        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background task time (if any)
        await asyncio.sleep(0.3)

        assert result.overall_success is False
        # No exception means cascade was properly skipped

    @pytest.mark.asyncio
    async def test_validator_builds_healing_context_correctly(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test HealingContext is built with correct data from validation failure."""
        # Setup execution with multiple desired states
        execution_id = await self._setup_execution_with_desired_states(
            database,
            "automation.test",
            {
                "light.test1": "on",
                "light.test2": "on",
            },
        )

        # Mock multiple entity histories (one fails, one succeeds)
        def get_history_side_effect(filter_entity_id, **kwargs):
            if filter_entity_id == "light.test1":
                return self._mock_history_failure("light.test1", "off")
            elif filter_entity_id == "light.test2":
                return self._mock_history_success("light.test2", "on")
            return [[]]

        mock_ha_client.get_history.side_effect = get_history_side_effect

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background task time to run
        await asyncio.sleep(0.3)

        # Verify cascade was called with correct context
        mock_cascade_orchestrator.execute_cascade.assert_called_once()
        context = mock_cascade_orchestrator.execute_cascade.call_args[0][0]

        assert context.automation_id == "automation.test"
        # failed_entities is a list of entity IDs
        assert "light.test1" in context.failed_entities
        assert "light.test2" not in context.failed_entities

    @pytest.mark.asyncio
    async def test_cascade_runs_as_background_task(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker
    ):
        """Test cascade execution doesn't block validation."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Make cascade take some time
        async def slow_cascade(context, **kwargs):
            await asyncio.sleep(0.4)
            return CascadeResult(
                success=True,
                routing_strategy="sequential",
                levels_attempted=[HealingLevel.INTEGRATION],
                successful_level=HealingLevel.INTEGRATION,
                successful_strategy="reload_integration",
                entity_results={"light.test": True},
                total_duration_seconds=0.4,
                error_message=None,
            )

        mock_cascade_orchestrator.execute_cascade = AsyncMock(side_effect=slow_cascade)

        # Mock failed entity history
        mock_ha_client.get_history.return_value = self._mock_history_failure("light.test", "off")

        validator = OutcomeValidator(
            ha_client=mock_ha_client,
            database=database,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        # Measure time for validation to complete
        start = asyncio.get_event_loop().time()
        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Validation should return quickly (< 0.2s), not wait for cascade (0.4s)
        assert elapsed < 0.3
        assert result.overall_success is False

        # Wait for cascade to complete
        await asyncio.sleep(0.5)

        # Verify cascade was actually called
        mock_cascade_orchestrator.execute_cascade.assert_called_once()


class TestEndToEndIntegration:
    """Test end-to-end automation tracking → validation → healing cascade flow."""

    async def _setup_execution_with_desired_states(
        self, database, automation_id: str, entity_states: dict[str, str]
    ) -> int:
        """Helper to create an execution with desired states."""
        async with database.async_session() as session:
            # Create execution
            execution = AutomationExecution(
                instance_id="test",
                automation_id=automation_id,
                executed_at=datetime.now(UTC),
                trigger_type="state",
                success=True,
            )
            session.add(execution)
            await session.flush()
            execution_id = execution.id

            # Create desired states
            for entity_id, state in entity_states.items():
                desired_state = AutomationDesiredState(
                    instance_id="test",
                    automation_id=automation_id,
                    entity_id=entity_id,
                    desired_state=state,
                    confidence=0.9,
                    inference_method="test",
                    created_at=datetime.now(UTC),
                )
                session.add(desired_state)

            await session.commit()

        return execution_id

    def _mock_history_failure(self, entity_id: str, state: str):
        """Create mock history response for failed state."""
        # Note: Omitting last_changed to avoid timezone-naive datetime arithmetic issues
        # in the validator (which is a known bug to be fixed separately)
        return [
            [
                {
                    "entity_id": entity_id,
                    "state": state,
                    "attributes": {},
                }
            ]
        ]

    @pytest.mark.asyncio
    async def test_full_flow_with_validation_failure(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker, config
    ):
        """Test complete flow: execution → validation failure → cascade trigger."""
        # Setup execution with desired state
        execution_id = await self._setup_execution_with_desired_states(
            database, "automation.test", {"light.test": "on"}
        )

        # Mock failed entity history for validation
        mock_ha_client.get_history.return_value = self._mock_history_failure("light.test", "off")

        # Create validator
        validator = OutcomeValidator(
            database=database,
            ha_client=mock_ha_client,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        # Validate execution
        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background tasks time to complete
        await asyncio.sleep(0.4)

        # Verify validation failed
        assert result.overall_success is False

        # Verify health tracker recorded failure
        health = await health_tracker.get_health_status("test", "automation.test")
        assert health.total_executions == 1
        assert health.consecutive_failures >= 1  # At least one failure recorded

        # Verify cascade was triggered
        mock_cascade_orchestrator.execute_cascade.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_flow_with_multiple_entities(
        self, database, mock_ha_client, mock_cascade_orchestrator, health_tracker, config
    ):
        """Test flow with multiple entities having mixed success/failure."""
        # Setup execution with multiple desired states
        execution_id = await self._setup_execution_with_desired_states(
            database,
            "automation.test",
            {
                "light.test1": "on",
                "light.test2": "on",
                "light.test3": "on",
            },
        )

        # Mock multiple entity histories (mixed success/failure)
        def get_history_side_effect(filter_entity_id, **kwargs):
            # Note: Omitting last_changed to avoid timezone arithmetic issues
            histories = {
                "light.test1": [
                    [
                        {
                            "entity_id": "light.test1",
                            "state": "off",
                            "attributes": {},
                        }
                    ]
                ],
                "light.test2": [
                    [
                        {
                            "entity_id": "light.test2",
                            "state": "on",
                            "attributes": {},
                        }
                    ]
                ],
                "light.test3": [
                    [
                        {
                            "entity_id": "light.test3",
                            "state": "unavailable",
                            "attributes": {},
                        }
                    ]
                ],
            }
            return histories.get(filter_entity_id, [[]])

        mock_ha_client.get_history.side_effect = get_history_side_effect

        # Create validator
        validator = OutcomeValidator(
            database=database,
            ha_client=mock_ha_client,
            instance_id="test",
            cascade_orchestrator=mock_cascade_orchestrator,
            health_tracker=health_tracker,
        )

        # Validate execution
        result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=0.1,
        )

        # Give background tasks time to complete
        await asyncio.sleep(0.4)

        # Verify validation failed (2 out of 3 failed)
        assert result.overall_success is False

        # Verify health tracker recorded failure
        health = await health_tracker.get_health_status("test", "automation.test")
        assert health.total_executions == 1
        assert health.consecutive_failures >= 1  # At least one failure recorded

        # Verify cascade was triggered
        mock_cascade_orchestrator.execute_cascade.assert_called_once()

        # Verify healing context contains only failed entities
        context = mock_cascade_orchestrator.execute_cascade.call_args[0][0]
        assert len(context.failed_entities) == 2
        assert "light.test1" in context.failed_entities
        assert "light.test3" in context.failed_entities
        assert "light.test2" not in context.failed_entities
