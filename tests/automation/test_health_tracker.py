"""Tests for automation health tracker."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.health_tracker import AutomationHealthTracker
from ha_boss.core.database import AutomationHealthStatus, Database


@pytest.fixture
def mock_database():
    """Create mock database."""
    db = MagicMock(spec=Database)
    db.async_session = MagicMock()
    return db


@pytest.fixture
def health_tracker(mock_database):
    """Create AutomationHealthTracker with default threshold."""
    return AutomationHealthTracker(
        database=mock_database,
        consecutive_success_threshold=3,
    )


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    return session


class TestHealthTrackerInit:
    """Test AutomationHealthTracker initialization."""

    def test_init_default_threshold(self, mock_database):
        """Test initialization with default threshold."""
        tracker = AutomationHealthTracker(database=mock_database)
        assert tracker.database == mock_database
        assert tracker.consecutive_success_threshold == 3

    def test_init_custom_threshold(self, mock_database):
        """Test initialization with custom threshold."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=5,
        )
        assert tracker.consecutive_success_threshold == 5

    def test_init_threshold_boundary_min(self, mock_database):
        """Test initialization with threshold = 1."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=1,
        )
        assert tracker.consecutive_success_threshold == 1

    def test_init_threshold_boundary_max(self, mock_database):
        """Test initialization with threshold = 100."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=100,
        )
        assert tracker.consecutive_success_threshold == 100

    def test_init_invalid_threshold_zero(self, mock_database):
        """Test initialization fails with threshold = 0."""
        with pytest.raises(ValueError, match="consecutive_success_threshold must be >= 1"):
            AutomationHealthTracker(
                database=mock_database,
                consecutive_success_threshold=0,
            )

    def test_init_invalid_threshold_negative(self, mock_database):
        """Test initialization fails with negative threshold."""
        with pytest.raises(ValueError, match="consecutive_success_threshold must be >= 1"):
            AutomationHealthTracker(
                database=mock_database,
                consecutive_success_threshold=-1,
            )


class TestRecordExecutionResult:
    """Test record_execution_result method."""

    @pytest.mark.asyncio
    async def test_record_first_success(self, health_tracker, mock_database, mock_session):
        """Test recording first successful execution."""
        # Setup mock
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Mock no existing status
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Record success
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        # Verify status
        assert status.instance_id == "test_instance"
        assert status.automation_id == "automation.test"
        assert status.consecutive_successes == 1
        assert status.consecutive_failures == 0
        assert status.total_successes == 1
        assert status.total_failures == 0
        assert status.total_executions == 1
        assert status.is_validated_healthy is False  # Need 3 consecutive
        assert status.last_validation_at is None

        # Verify session interactions
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_success_reaches_threshold(
        self, health_tracker, mock_database, mock_session
    ):
        """Test recording success that reaches validation threshold."""
        # Setup existing status with 2 consecutive successes
        existing_status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=2,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=2,
            total_successes=2,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_status
        mock_session.execute.return_value = mock_result

        # Record third success
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        # Verify validation threshold met
        assert status.consecutive_successes == 3
        assert status.is_validated_healthy is True
        assert status.last_validation_at is not None
        assert status.total_successes == 3
        assert status.total_executions == 3

    @pytest.mark.asyncio
    async def test_record_success_above_threshold(
        self, health_tracker, mock_database, mock_session
    ):
        """Test recording success when already above threshold."""
        # Setup existing validated status
        existing_status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=5,
            consecutive_failures=0,
            is_validated_healthy=True,
            last_validation_at=datetime.now(UTC),
            total_executions=5,
            total_successes=5,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_status
        mock_session.execute.return_value = mock_result

        # Record another success
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        # Verify counters incremented, still validated
        assert status.consecutive_successes == 6
        assert status.is_validated_healthy is True
        assert status.total_successes == 6
        assert status.total_executions == 6

    @pytest.mark.asyncio
    async def test_record_first_failure(self, health_tracker, mock_database, mock_session):
        """Test recording first failed execution."""
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Mock no existing status
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Record failure
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=False,
        )

        # Verify status
        assert status.consecutive_successes == 0
        assert status.consecutive_failures == 1
        assert status.total_successes == 0
        assert status.total_failures == 1
        assert status.total_executions == 1
        assert status.is_validated_healthy is False

    @pytest.mark.asyncio
    async def test_failure_resets_consecutive_successes(
        self, health_tracker, mock_database, mock_session
    ):
        """Test failure resets consecutive success counter."""
        # Setup existing status with 2 consecutive successes (not yet validated)
        existing_status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=2,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=2,
            total_successes=2,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_status
        mock_session.execute.return_value = mock_result

        # Record failure
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=False,
        )

        # Verify reset
        assert status.consecutive_successes == 0
        assert status.consecutive_failures == 1
        assert status.total_failures == 1
        assert status.total_executions == 3

    @pytest.mark.asyncio
    async def test_failure_removes_validation(self, health_tracker, mock_database, mock_session):
        """Test failure removes validated status."""
        # Setup existing validated status
        existing_status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=5,
            consecutive_failures=0,
            is_validated_healthy=True,
            last_validation_at=datetime.now(UTC),
            total_executions=5,
            total_successes=5,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_status
        mock_session.execute.return_value = mock_result

        # Record failure
        status = await health_tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=False,
        )

        # Verify validation removed
        assert status.consecutive_successes == 0
        assert status.consecutive_failures == 1
        assert status.is_validated_healthy is False
        assert status.total_failures == 1
        assert status.total_executions == 6

    @pytest.mark.asyncio
    async def test_record_empty_instance_id(self, health_tracker):
        """Test record fails with empty instance_id."""
        with pytest.raises(ValueError, match="instance_id cannot be empty"):
            await health_tracker.record_execution_result(
                instance_id="",
                automation_id="automation.test",
                success=True,
            )

    @pytest.mark.asyncio
    async def test_record_empty_automation_id(self, health_tracker):
        """Test record fails with empty automation_id."""
        with pytest.raises(ValueError, match="automation_id cannot be empty"):
            await health_tracker.record_execution_result(
                instance_id="test_instance",
                automation_id="",
                success=True,
            )

    @pytest.mark.asyncio
    async def test_record_whitespace_instance_id(self, health_tracker):
        """Test record fails with whitespace-only instance_id."""
        with pytest.raises(ValueError, match="instance_id cannot be empty"):
            await health_tracker.record_execution_result(
                instance_id="   ",
                automation_id="automation.test",
                success=True,
            )


class TestGetReliabilityScore:
    """Test get_reliability_score method."""

    @pytest.mark.asyncio
    async def test_score_no_status(self, health_tracker, mock_database, mock_session):
        """Test score returns 0.0 when no status exists."""
        mock_database.async_session.return_value.__aenter__.return_value = mock_session

        # Mock no existing status
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        score = await health_tracker.get_reliability_score(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_no_executions(self, health_tracker, mock_database, mock_session):
        """Test score returns 0.0 when no executions."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=0,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=0,
            total_successes=0,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        score = await health_tracker.get_reliability_score(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_perfect_reliability(self, health_tracker, mock_database, mock_session):
        """Test score calculation with 100% success rate."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=10,
            consecutive_failures=0,
            is_validated_healthy=True,
            last_validation_at=datetime.now(UTC),
            total_executions=10,
            total_successes=10,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        score = await health_tracker.get_reliability_score(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert score == 1.0

    @pytest.mark.asyncio
    async def test_score_fifty_percent_reliability(
        self, health_tracker, mock_database, mock_session
    ):
        """Test score calculation with 50% success rate."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=0,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=10,
            total_successes=5,
            total_failures=5,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        score = await health_tracker.get_reliability_score(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert score == 0.5

    @pytest.mark.asyncio
    async def test_score_zero_reliability(self, health_tracker, mock_database, mock_session):
        """Test score calculation with 0% success rate."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=0,
            consecutive_failures=5,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=5,
            total_successes=0,
            total_failures=5,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        score = await health_tracker.get_reliability_score(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_empty_instance_id(self, health_tracker):
        """Test score fails with empty instance_id."""
        with pytest.raises(ValueError, match="instance_id cannot be empty"):
            await health_tracker.get_reliability_score(
                instance_id="",
                automation_id="automation.test",
            )


class TestGetHealthStatus:
    """Test get_health_status method."""

    @pytest.mark.asyncio
    async def test_get_status_exists(self, health_tracker, mock_database, mock_session):
        """Test getting existing health status."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=3,
            consecutive_failures=0,
            is_validated_healthy=True,
            last_validation_at=datetime.now(UTC),
            total_executions=5,
            total_successes=5,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        result = await health_tracker.get_health_status(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert result == status
        assert result.consecutive_successes == 3
        assert result.is_validated_healthy is True

    @pytest.mark.asyncio
    async def test_get_status_not_exists(self, health_tracker, mock_database, mock_session):
        """Test getting non-existent health status."""
        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await health_tracker.get_health_status(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_status_empty_automation_id(self, health_tracker):
        """Test get status fails with empty automation_id."""
        with pytest.raises(ValueError, match="automation_id cannot be empty"):
            await health_tracker.get_health_status(
                instance_id="test_instance",
                automation_id="",
            )


class TestResetValidation:
    """Test reset_validation method."""

    @pytest.mark.asyncio
    async def test_reset_validated_status(self, health_tracker, mock_database, mock_session):
        """Test resetting validated automation status."""
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=5,
            consecutive_failures=0,
            is_validated_healthy=True,
            last_validation_at=datetime.now(UTC),
            total_executions=10,
            total_successes=8,
            total_failures=2,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        await health_tracker.reset_validation(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        # Verify reset
        assert status.consecutive_successes == 0
        assert status.consecutive_failures == 0
        assert status.is_validated_healthy is False
        assert status.last_validation_at is None
        # Totals preserved
        assert status.total_executions == 10
        assert status.total_successes == 8
        assert status.total_failures == 2

        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_non_existent_status(self, health_tracker, mock_database, mock_session):
        """Test resetting non-existent status (no-op)."""
        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Should not raise error
        await health_tracker.reset_validation(
            instance_id="test_instance",
            automation_id="automation.test",
        )

        # Should not commit if no status found
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_empty_instance_id(self, health_tracker):
        """Test reset fails with empty instance_id."""
        with pytest.raises(ValueError, match="instance_id cannot be empty"):
            await health_tracker.reset_validation(
                instance_id="",
                automation_id="automation.test",
            )


class TestConcurrentUpdates:
    """Test concurrent execution safety."""

    @pytest.mark.asyncio
    async def test_concurrent_record_execution(self, health_tracker, mock_database, mock_session):
        """Test concurrent execution records don't corrupt data."""
        # Use a shared counter to track session creation order
        call_count = {"count": 0}
        created_statuses = []

        def create_session():
            """Create a mock session for each concurrent call."""
            session = AsyncMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock()
            session.add = MagicMock(side_effect=lambda obj: created_statuses.append(obj))

            # First call: no existing status, second+ calls: return created status
            call_index = call_count["count"]
            call_count["count"] += 1

            if call_index == 0:
                # First call - no existing status
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
            else:
                # Subsequent calls - return the first created status
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = (
                    created_statuses[0] if created_statuses else None
                )

            session.execute = AsyncMock(return_value=mock_result)
            return session

        # Mock session factory to create new session for each call
        def mock_session_factory():
            """Async context manager for sessions."""

            class SessionContext:
                def __init__(self, session):
                    self.session = session

                async def __aenter__(self):
                    return self.session

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            return SessionContext(create_session())

        mock_database.async_session = mock_session_factory

        # Execute concurrent updates
        results = await asyncio.gather(
            health_tracker.record_execution_result(
                instance_id="test_instance",
                automation_id="automation.test",
                success=True,
            ),
            health_tracker.record_execution_result(
                instance_id="test_instance",
                automation_id="automation.test",
                success=True,
            ),
            health_tracker.record_execution_result(
                instance_id="test_instance",
                automation_id="automation.test",
                success=True,
            ),
        )

        # All should complete successfully
        assert len(results) == 3
        assert all(isinstance(r, AutomationHealthStatus) for r in results)


class TestThresholdBoundaries:
    """Test threshold boundary conditions."""

    @pytest.mark.asyncio
    async def test_threshold_one_success(self, mock_database, mock_session):
        """Test threshold=1 validates immediately on first success."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=1,
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        status = await tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        # Should validate immediately
        assert status.consecutive_successes == 1
        assert status.is_validated_healthy is True
        assert status.last_validation_at is not None

    @pytest.mark.asyncio
    async def test_threshold_exactly_at_threshold(self, mock_database, mock_session):
        """Test validation occurs exactly at threshold."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=3,
        )

        # Setup status with 2 successes
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=2,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=2,
            total_successes=2,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        # Third success should trigger validation
        result = await tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        assert result.consecutive_successes == 3
        assert result.is_validated_healthy is True

    @pytest.mark.asyncio
    async def test_threshold_one_below_threshold(self, mock_database, mock_session):
        """Test one below threshold does not validate."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=3,
        )

        # Setup status with 1 success
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=1,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=1,
            total_successes=1,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        # Second success should not validate (need 3)
        result = await tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        assert result.consecutive_successes == 2
        assert result.is_validated_healthy is False

    @pytest.mark.asyncio
    async def test_threshold_high_value(self, mock_database, mock_session):
        """Test high threshold value (100) requires many successes."""
        tracker = AutomationHealthTracker(
            database=mock_database,
            consecutive_success_threshold=100,
        )

        # Setup status with 99 successes
        status = AutomationHealthStatus(
            instance_id="test_instance",
            automation_id="automation.test",
            consecutive_successes=99,
            consecutive_failures=0,
            is_validated_healthy=False,
            last_validation_at=None,
            total_executions=99,
            total_successes=99,
            total_failures=0,
            updated_at=datetime.now(UTC),
        )

        mock_database.async_session.return_value.__aenter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status
        mock_session.execute.return_value = mock_result

        # Should not validate yet
        result = await tracker.record_execution_result(
            instance_id="test_instance",
            automation_id="automation.test",
            success=True,
        )

        # Now at 100 - should validate
        assert result.consecutive_successes == 100
        assert result.is_validated_healthy is True
