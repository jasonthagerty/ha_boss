# Issue #31: Comprehensive Testing for Pattern Collection

## 📋 Overview

Add comprehensive test coverage for all Phase 2 pattern collection features.

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P1
**Effort**: 2 hours

## 🎯 Objective

Ensure pattern collection features are thoroughly tested:
- ≥80% code coverage for new code
- Unit tests for all components
- Integration tests for end-to-end flows
- Performance benchmarks
- No regressions in existing MVP tests

## 🧪 Test Coverage Plan

### 1. Database Models Tests

**File**: `tests/core/test_database_patterns.py`

```python
"""Tests for pattern collection database models."""

import pytest
from datetime import UTC, datetime

from ha_boss.core.database import (
    Database,
    IntegrationReliability,
    IntegrationMetrics,
    PatternInsight
)


@pytest.mark.asyncio
async def test_integration_reliability_creation():
    """Test creating IntegrationReliability record."""
    # Create database in memory
    # Create IntegrationReliability instance
    # Save to database
    # Query back
    # Verify all fields match


@pytest.mark.asyncio
async def test_integration_reliability_indexes():
    """Test that indexes exist for performance."""
    # Create database
    # Verify indexes on:
    #   - integration_id
    #   - integration_domain, timestamp
    #   - event_type
    #   - timestamp


@pytest.mark.asyncio
async def test_integration_metrics_unique_constraint():
    """Test unique constraint on (integration_id, period_start)."""
    # Create two metrics with same integration + period
    # Second should fail or update (depending on implementation)


@pytest.mark.asyncio
async def test_pattern_insight_json_storage():
    """Test JSON data storage in PatternInsight."""
    # Create insight with complex JSON data
    # Save and query back
    # Verify JSON deserialized correctly
```

### 2. PatternCollector Tests

**File**: `tests/intelligence/test_pattern_collector.py`

```python
"""Tests for PatternCollector service."""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from ha_boss.core.config import Config
from ha_boss.core.database import Database
from ha_boss.intelligence.pattern_collector import PatternCollector


@pytest.fixture
async def collector(tmp_path):
    """Create PatternCollector with test database."""
    db_path = tmp_path / "test.db"
    config = Config(
        database={"path": str(db_path)},
        intelligence={"pattern_collection_enabled": True}
    )
    db = Database(str(db_path))
    await db.init_db()

    collector = PatternCollector(db, config)
    yield collector
    await db.close()


@pytest.mark.asyncio
async def test_record_healing_success(collector):
    """Test recording successful healing attempt."""
    await collector.record_healing_attempt(
        entity_id="sensor.test",
        integration_id="abc123",
        integration_domain="test",
        success=True,
        details={"test": "data"}
    )

    # Query database
    # Verify event stored with event_type='heal_success'


@pytest.mark.asyncio
async def test_record_healing_failure(collector):
    """Test recording failed healing attempt."""
    # Similar to above with success=False
    # Verify event_type='heal_failure'


@pytest.mark.asyncio
async def test_record_entity_unavailable(collector):
    """Test recording entity unavailable event."""
    await collector.record_entity_unavailable(
        entity_id="sensor.test",
        integration_id="abc123",
        integration_domain="test",
        details={"reason": "timeout"}
    )

    # Verify event_type='unavailable'


@pytest.mark.asyncio
async def test_disabled_collection(tmp_path):
    """Test that collection respects enabled flag."""
    db_path = tmp_path / "test.db"
    config = Config(
        database={"path": str(db_path)},
        intelligence={"pattern_collection_enabled": False}
    )
    db = Database(str(db_path))
    await db.init_db()
    collector = PatternCollector(db, config)

    await collector.record_healing_attempt(
        entity_id="sensor.test",
        integration_id="abc123",
        integration_domain="test",
        success=True
    )

    # Verify nothing stored in database
    count = await collector.get_event_count()
    assert count == 0


@pytest.mark.asyncio
async def test_error_handling(collector):
    """Test graceful error handling."""
    # Mock database to raise exception
    collector.database.session = AsyncMock(side_effect=Exception("DB Error"))

    # Should not raise, just log
    await collector.record_healing_attempt(
        entity_id="sensor.test",
        integration_id="abc123",
        integration_domain="test",
        success=True
    )


@pytest.mark.asyncio
async def test_missing_integration_info(collector):
    """Test handling when integration info is None."""
    # Call with integration_id=None
    await collector.record_healing_attempt(
        entity_id="sensor.test",
        integration_id=None,
        integration_domain=None,
        success=True
    )

    # Should skip gracefully, not crash
    count = await collector.get_event_count()
    assert count == 0
```

### 3. ReliabilityAnalyzer Tests

**File**: `tests/intelligence/test_reliability_analyzer.py`

```python
"""Tests for ReliabilityAnalyzer."""

import pytest
from datetime import UTC, datetime, timedelta

from ha_boss.intelligence.reliability_analyzer import (
    ReliabilityAnalyzer,
    ReliabilityMetric
)


@pytest.mark.asyncio
async def test_get_integration_metrics(test_db_with_events):
    """Test getting reliability metrics."""
    analyzer = ReliabilityAnalyzer(test_db_with_events)
    metrics = await analyzer.get_integration_metrics(days=7)

    assert len(metrics) > 0
    assert all(isinstance(m, ReliabilityMetric) for m in metrics)


@pytest.mark.asyncio
async def test_success_rate_calculation():
    """Test success rate calculation."""
    # Add 8 successes, 2 failures
    # Success rate should be 80%


@pytest.mark.asyncio
async def test_reliability_score_labels():
    """Test reliability score labels."""
    metric = ReliabilityMetric(
        integration_id="test",
        integration_domain="test",
        total_events=10,
        heal_successes=10,
        heal_failures=0,
        unavailable_events=0,
        success_rate=1.0,
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
    )
    assert metric.reliability_score == "Excellent"


@pytest.mark.asyncio
async def test_failure_timeline():
    """Test getting failure timeline."""
    # Add failures at different times
    # Verify returned in chronological order


@pytest.mark.asyncio
async def test_top_failing_integrations():
    """Test getting top N failing integrations."""
    # Add events for 5 integrations with varying success rates
    # Get top 3
    # Verify worst 3 returned


@pytest.mark.asyncio
async def test_no_data_handling():
    """Test handling when no data exists."""
    # Empty database
    # Should return empty list, not crash


@pytest.mark.asyncio
async def test_filter_by_domain():
    """Test filtering metrics by integration domain."""
    # Add events for multiple integrations
    # Query for specific domain
    # Verify only that domain returned


@pytest.mark.asyncio
async def test_recommendations():
    """Test generating recommendations."""
    # Test different scenarios:
    # - Poor reliability → critical warning
    # - Medium reliability → suggestions
    # - Good reliability → positive message
```

### 4. CLI Tests

**File**: `tests/cli/test_patterns_commands.py`

```python
"""Tests for pattern CLI commands."""

import pytest
from typer.testing import CliRunner

from ha_boss.cli.commands import app


def test_reliability_command(test_db_with_patterns):
    """Test patterns reliability command."""
    runner = CliRunner()
    result = runner.invoke(app, ["patterns", "reliability"])

    assert result.exit_code == 0
    assert "Integration Reliability" in result.stdout


def test_reliability_no_data():
    """Test reliability with no data."""
    # Empty database
    # Should show friendly message


def test_failures_timeline():
    """Test patterns failures command."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["patterns", "failures", "--integration", "test"]
    )

    assert result.exit_code == 0


def test_missing_integration_parameter():
    """Test error when integration parameter missing."""
    runner = CliRunner()
    result = runner.invoke(app, ["patterns", "failures"])

    assert result.exit_code == 1
    assert "required" in result.stdout.lower()
```

### 5. Service Integration Tests

**File**: `tests/test_integration_patterns.py`

```python
"""Integration tests for pattern collection."""

import pytest
from unittest.mock import patch, AsyncMock

from ha_boss.service.main import HABossService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pattern_collection_end_to_end(integration_config):
    """Test full pattern collection flow."""
    # Enable pattern collection
    integration_config.intelligence.pattern_collection_enabled = True

    # Start service (with mocks)
    service = HABossService(integration_config)

    with patch(...):  # Mock external dependencies
        await service.start()

        # Simulate health issue
        # Trigger healing
        # Verify pattern recorded

        await service.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pattern_collection_disabled():
    """Test service works with pattern collection disabled."""
    # Set pattern_collection_enabled=False
    # Start service
    # Trigger healing
    # Verify no patterns recorded
    # Service should still work normally


@pytest.mark.asyncio
async def test_pattern_collection_performance():
    """Verify pattern collection has minimal performance impact."""
    import time

    # Measure healing time without pattern collection
    start = time.perf_counter()
    # ... perform healing ...
    time_without = time.perf_counter() - start

    # Measure with pattern collection
    start = time.perf_counter()
    # ... perform healing with pattern collection ...
    time_with = time.perf_counter() - start

    # Verify overhead < 5ms
    overhead = (time_with - time_without) * 1000  # Convert to ms
    assert overhead < 5.0, f"Pattern collection overhead too high: {overhead}ms"
```

### 6. Performance Benchmarks

**File**: `tests/performance/test_pattern_performance.py`

```python
"""Performance tests for pattern collection."""

import pytest
import time


@pytest.mark.performance
@pytest.mark.asyncio
async def test_pattern_recording_latency():
    """Test pattern recording is fast."""
    # Record 100 patterns
    # Measure average latency
    # Assert < 5ms per event


@pytest.mark.performance
@pytest.mark.asyncio
async def test_query_performance():
    """Test query performance with large dataset."""
    # Insert 10,000 events
    # Query reliability metrics
    # Assert query completes in < 100ms
```

## ✅ Acceptance Criteria

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Code coverage ≥ 80% for new code
- [ ] Performance benchmarks met:
  - Pattern recording < 5ms
  - Queries < 100ms for 10k events
- [ ] No regressions in existing MVP tests (232 tests still passing)
- [ ] Tests run in CI successfully
- [ ] Edge cases covered (no data, errors, disabled)

## 📊 Coverage Goals

### Target Coverage by Module

- `intelligence/pattern_collector.py`: ≥90%
- `intelligence/reliability_analyzer.py`: ≥85%
- `core/database.py` (new models): ≥80%
- CLI pattern commands: ≥75%
- Service integration: ≥80%

### Overall Phase 2 Coverage

- Minimum: 80% (required)
- Target: 85% (goal)
- Stretch: 90% (excellent)

## 🔧 Test Utilities

Create shared test fixtures:

**File**: `tests/fixtures/pattern_fixtures.py`

```python
"""Shared fixtures for pattern testing."""

import pytest
from datetime import UTC, datetime, timedelta

from ha_boss.core.database import Database, IntegrationReliability


@pytest.fixture
async def test_db_with_events(tmp_path):
    """Create test database with sample events."""
    db_path = tmp_path / "test_patterns.db"
    db = Database(str(db_path))
    await db.init_db()

    # Add sample events
    async with db.session() as session:
        # Add various events for testing
        events = [
            IntegrationReliability(
                integration_id="test_123",
                integration_domain="test",
                timestamp=datetime.now(UTC) - timedelta(days=i),
                event_type="heal_success" if i % 2 == 0 else "heal_failure",
                entity_id=f"sensor.test_{i}",
            )
            for i in range(10)
        ]
        session.add_all(events)
        await session.commit()

    yield db
    await db.close()
```

## 📝 Implementation Notes

1. **Test Isolation**: Each test gets fresh database (tmp_path)

2. **Async Tests**: Use `@pytest.mark.asyncio` for all async tests

3. **Fixtures**: Create reusable fixtures for common test data

4. **Performance Tests**: Mark with `@pytest.mark.performance` for optional running

5. **Integration Tests**: Mark with `@pytest.mark.integration`

6. **CI Integration**: All tests must pass in GitHub Actions

## 🔗 Dependencies

- **Requires**: #26, #27, #28, #29, #30 (all other issues complete)
- **Blocks**: None (this is quality assurance)

---

**Labels**: `phase-2`, `testing`, `quality`, `P1`
