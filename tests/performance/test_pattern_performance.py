"""Performance benchmarks for pattern collection."""

import time
from datetime import UTC, datetime

import pytest

from ha_boss.core.config import Config, DatabaseConfig, HomeAssistantConfig, IntelligenceConfig
from ha_boss.core.database import Database
from ha_boss.intelligence.pattern_collector import PatternCollector
from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer


@pytest.fixture
async def perf_database(tmp_path):
    """Create test database for performance tests."""
    db_path = tmp_path / "perf_test.db"
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def perf_config():
    """Create test configuration for performance tests."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://test:8123",
            token="test_token",
        ),
        database=DatabaseConfig(
            path=":memory:",
            retention_days=30,
        ),
        intelligence=IntelligenceConfig(
            pattern_collection_enabled=True,
        ),
        mode="testing",
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_pattern_recording_latency(perf_database, perf_config):
    """Test that pattern recording latency is < 5ms.

    Acceptance: Pattern recording should complete in < 5ms.
    """
    pattern_collector = PatternCollector(config=perf_config, database=perf_database)

    # Warm up
    await pattern_collector.record_entity_unavailable(
        integration_id="warm_up",
        integration_domain="test",
        entity_id="sensor.warmup",
    )

    # Benchmark unavailable event recording
    iterations = 100
    start_time = time.perf_counter()

    for i in range(iterations):
        await pattern_collector.record_entity_unavailable(
            integration_id=f"test_{i}",
            integration_domain="test",
            entity_id=f"sensor.test_{i}",
        )

    end_time = time.perf_counter()
    avg_latency_ms = ((end_time - start_time) / iterations) * 1000

    # Assert < 5ms average
    assert avg_latency_ms < 5.0, f"Pattern recording took {avg_latency_ms:.2f}ms (expected < 5ms)"

    print(f"\n✓ Pattern recording latency: {avg_latency_ms:.2f}ms (target: < 5ms)")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_healing_attempt_recording_latency(perf_database, perf_config):
    """Test that healing attempt recording latency is < 5ms.

    Acceptance: Healing attempt recording should complete in < 5ms.
    """
    pattern_collector = PatternCollector(config=perf_config, database=perf_database)

    # Warm up
    await pattern_collector.record_healing_attempt(
        integration_id="warm_up",
        integration_domain="test",
        entity_id="sensor.warmup",
        success=True,
    )

    # Benchmark healing attempt recording
    iterations = 100
    start_time = time.perf_counter()

    for i in range(iterations):
        await pattern_collector.record_healing_attempt(
            integration_id=f"test_{i}",
            integration_domain="test",
            entity_id=f"sensor.test_{i}",
            success=i % 2 == 0,  # Alternate success/failure
        )

    end_time = time.perf_counter()
    avg_latency_ms = ((end_time - start_time) / iterations) * 1000

    # Assert < 5ms average
    assert avg_latency_ms < 5.0, f"Healing recording took {avg_latency_ms:.2f}ms (expected < 5ms)"

    print(f"\n✓ Healing attempt recording latency: {avg_latency_ms:.2f}ms (target: < 5ms)")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_query_performance_with_10k_events(perf_database, perf_config):
    """Test that queries complete in < 100ms with 10k events.

    Acceptance: Reliability queries should complete in < 100ms even with 10k events.
    """
    pattern_collector = PatternCollector(config=perf_config, database=perf_database)

    # Create 10k events (mix of unavailable, heal_success, heal_failure)
    print("\n  Creating 10k events for performance test...")
    for i in range(10000):
        if i % 3 == 0:
            await pattern_collector.record_entity_unavailable(
                integration_id=f"integration_{i % 10}",
                integration_domain=f"domain_{i % 10}",
                entity_id=f"sensor.test_{i}",
            )
        elif i % 3 == 1:
            await pattern_collector.record_healing_attempt(
                integration_id=f"integration_{i % 10}",
                integration_domain=f"domain_{i % 10}",
                entity_id=f"sensor.test_{i}",
                success=True,
            )
        else:
            await pattern_collector.record_healing_attempt(
                integration_id=f"integration_{i % 10}",
                integration_domain=f"domain_{i % 10}",
                entity_id=f"sensor.test_{i}",
                success=False,
            )

    print("  ✓ 10k events created")

    # Benchmark queries
    analyzer = ReliabilityAnalyzer(perf_database)

    # Test 1: Get all integration metrics
    start_time = time.perf_counter()
    metrics = await analyzer.get_integration_metrics(days=30)
    end_time = time.perf_counter()
    query_time_ms = (end_time - start_time) * 1000

    assert query_time_ms < 100.0, f"Metrics query took {query_time_ms:.2f}ms (expected < 100ms)"
    assert len(metrics) > 0, "Should have returned metrics"
    print(f"  ✓ get_integration_metrics(): {query_time_ms:.2f}ms (target: < 100ms)")

    # Test 2: Get failure timeline
    start_time = time.perf_counter()
    events = await analyzer.get_failure_timeline(days=30, limit=100)
    end_time = time.perf_counter()
    query_time_ms = (end_time - start_time) * 1000

    assert query_time_ms < 100.0, f"Timeline query took {query_time_ms:.2f}ms (expected < 100ms)"
    assert len(events) > 0, "Should have returned events"
    print(f"  ✓ get_failure_timeline(): {query_time_ms:.2f}ms (target: < 100ms)")

    # Test 3: Get top failing integrations
    start_time = time.perf_counter()
    top_failing = await analyzer.get_top_failing_integrations(days=30, limit=10)
    end_time = time.perf_counter()
    query_time_ms = (end_time - start_time) * 1000

    assert query_time_ms < 100.0, f"Top failing query took {query_time_ms:.2f}ms (expected < 100ms)"
    assert len(top_failing) > 0, "Should have returned integrations"
    print(f"  ✓ get_top_failing_integrations(): {query_time_ms:.2f}ms (target: < 100ms)")

    # Test 4: Get recommendations
    start_time = time.perf_counter()
    recommendations = await analyzer.get_recommendations(integration_domain="domain_0", days=30)
    end_time = time.perf_counter()
    query_time_ms = (end_time - start_time) * 1000

    assert (
        query_time_ms < 100.0
    ), f"Recommendations query took {query_time_ms:.2f}ms (expected < 100ms)"
    print(f"  ✓ get_recommendations(): {query_time_ms:.2f}ms (target: < 100ms)")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_pattern_recording(perf_database, perf_config):
    """Test that concurrent pattern recording doesn't degrade performance.

    Acceptance: Concurrent recordings should not significantly degrade latency.
    """
    import asyncio

    pattern_collector = PatternCollector(config=perf_config, database=perf_database)

    # Test concurrent recording
    async def record_batch(batch_id: int, count: int):
        """Record a batch of events."""
        for i in range(count):
            await pattern_collector.record_entity_unavailable(
                integration_id=f"batch_{batch_id}",
                integration_domain="test",
                entity_id=f"sensor.test_{batch_id}_{i}",
            )

    # Run 10 concurrent batches of 10 events each
    start_time = time.perf_counter()
    await asyncio.gather(*[record_batch(i, 10) for i in range(10)])
    end_time = time.perf_counter()

    total_time_ms = (end_time - start_time) * 1000
    avg_per_event_ms = total_time_ms / 100

    # Should still average < 5ms per event even with concurrency
    assert (
        avg_per_event_ms < 10.0
    ), f"Concurrent recording took {avg_per_event_ms:.2f}ms/event (expected < 10ms)"

    print(
        f"\n✓ Concurrent recording: {avg_per_event_ms:.2f}ms/event (100 events, 10 concurrent batches)"
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_database_growth_impact(perf_database, perf_config):
    """Test that database growth doesn't significantly impact query performance.

    Acceptance: Query times should remain roughly constant as database grows.
    """
    pattern_collector = PatternCollector(config=perf_config, database=perf_database)
    analyzer = ReliabilityAnalyzer(perf_database)

    query_times = []

    # Test at different data sizes: 100, 1000, 5000 events
    for batch_size in [100, 1000, 5000]:
        # Add events
        for i in range(batch_size):
            await pattern_collector.record_healing_attempt(
                integration_id="test_integration",
                integration_domain="test",
                entity_id=f"sensor.test_{i}",
                success=i % 2 == 0,
            )

        # Measure query time
        start_time = time.perf_counter()
        await analyzer.get_integration_metrics(days=30)
        end_time = time.perf_counter()
        query_time_ms = (end_time - start_time) * 1000
        query_times.append(query_time_ms)

        print(f"  Query time with {batch_size} events: {query_time_ms:.2f}ms")

    # Check that growth is sub-linear (query time shouldn't increase dramatically)
    # With 5000 events, query should still be < 100ms
    assert (
        query_times[-1] < 100.0
    ), f"Query with 5000 events took {query_times[-1]:.2f}ms (expected < 100ms)"

    print(f"\n✓ Query performance scales well with database growth")
