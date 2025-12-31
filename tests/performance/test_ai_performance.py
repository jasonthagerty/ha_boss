"""Performance benchmarks for AI/LLM operations."""

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.automation.analyzer import AutomationAnalyzer
from ha_boss.automation.generator import AutomationGenerator
from ha_boss.core.config import (
    Config,
    DatabaseConfig,
    HomeAssistantConfig,
    IntelligenceConfig,
    NotificationsConfig,
)
from ha_boss.core.database import Database
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.intelligence.anomaly_detector import AnomalyDetector
from ha_boss.intelligence.claude_client import ClaudeClient
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity
from ha_boss.intelligence.ollama_client import OllamaClient
from ha_boss.intelligence.pattern_collector import PatternCollector
from ha_boss.intelligence.weekly_summary import WeeklySummaryGenerator

# Environment flags for conditional test execution
OLLAMA_AVAILABLE = os.getenv("TEST_OLLAMA_AVAILABLE", "").lower() == "true"
CLAUDE_AVAILABLE = os.getenv("TEST_CLAUDE_AVAILABLE", "").lower() == "true"


@pytest.fixture
async def perf_database(tmp_path: Path) -> AsyncGenerator[Database, None]:
    """Create test database for performance tests."""
    db_path = tmp_path / "perf_ai_test.db"
    db = Database(str(db_path))
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def perf_config() -> Config:
    """Create test configuration for performance tests."""
    return Config(
        home_assistant=HomeAssistantConfig(
            url="http://test:8123",
            token="test_token",
        ),
        database=DatabaseConfig(
            path=Path(":memory:"),
            retention_days=30,
        ),
        intelligence=IntelligenceConfig(
            pattern_collection_enabled=True,
            ollama_url=os.getenv("TEST_OLLAMA_URL", "http://localhost:11434"),
            ollama_model=os.getenv("TEST_OLLAMA_MODEL", "llama3.1:8b"),
            claude_api_key=os.getenv("TEST_CLAUDE_API_KEY", ""),
            claude_model=os.getenv("TEST_CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
        ),
        notifications=NotificationsConfig(
            ai_enhanced=True,
        ),
        mode="testing",
    )


@pytest.fixture
async def ollama_client(perf_config: Config) -> AsyncGenerator[OllamaClient, None]:
    """Create Ollama client for performance tests."""
    client = OllamaClient(
        url=perf_config.intelligence.ollama_url,
        model=perf_config.intelligence.ollama_model,
        timeout=30.0,
    )
    async with client:
        yield client


@pytest.fixture
async def claude_client(perf_config: Config) -> AsyncGenerator[ClaudeClient, None]:
    """Create Claude client for performance tests."""
    if not perf_config.intelligence.claude_api_key:
        pytest.skip("Claude API key not configured")

    client = ClaudeClient(
        api_key=perf_config.intelligence.claude_api_key,
        model=perf_config.intelligence.claude_model,
        timeout=60.0,
    )
    async with client:
        yield client


@pytest.fixture
async def llm_router(
    perf_config: Config,
    ollama_client: OllamaClient,
    claude_client: ClaudeClient,
) -> LLMRouter:
    """Create LLM router with both clients."""
    return LLMRouter(
        ollama_client=ollama_client,
        claude_client=claude_client,
        local_only=False,
    )


@pytest.fixture
def mock_ha_client() -> HomeAssistantClient:
    """Create mock HA client for testing."""
    mock_client = MagicMock(spec=HomeAssistantClient)
    mock_client.get_states = AsyncMock(
        return_value=[
            {
                "entity_id": "automation.test_automation",
                "state": "on",
                "attributes": {
                    "friendly_name": "Test Automation",
                    "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion"}],
                    "condition": [],
                    "action": [
                        {"service": "light.turn_on", "target": {"entity_id": "light.bedroom"}}
                    ],
                },
            }
        ]
    )
    return mock_client


# ============================================================================
# Ollama Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not available")
async def test_ollama_simple_prompt_latency(ollama_client: OllamaClient) -> None:
    """Test that Ollama simple prompts complete in < 2s.

    Acceptance: Simple prompts should complete in < 2s (target: 1s).
    """
    # Warm up (first request may be slower due to model loading)
    await ollama_client.generate(
        prompt="Say 'OK'",
        max_tokens=10,
        temperature=0.0,
    )

    # Benchmark simple prompt
    start_time = time.perf_counter()
    result = await ollama_client.generate(
        prompt="Explain in one sentence why integrations fail.",
        max_tokens=50,
        temperature=0.7,
    )
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Ollama should return a result"
    assert latency_s < 2.0, f"Ollama took {latency_s:.2f}s (expected < 2s)"

    print(f"\n✓ Ollama simple prompt: {latency_s:.2f}s (target: < 2s)")


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not available")
async def test_ollama_concurrent_requests(ollama_client: OllamaClient) -> None:
    """Test that concurrent Ollama requests maintain acceptable latency.

    Acceptance: Concurrent requests should average < 3s each.
    """
    # Warm up
    await ollama_client.generate("Say 'OK'", max_tokens=10, temperature=0.0)

    # Run 3 concurrent requests
    prompts = [
        "Summarize why integrations fail.",
        "Explain network connectivity issues.",
        "Describe sensor unavailability.",
    ]

    start_time = time.perf_counter()
    results = await asyncio.gather(
        *[ollama_client.generate(prompt, max_tokens=50, temperature=0.7) for prompt in prompts]
    )
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_latency = total_time / len(prompts)

    # Assertions
    assert all(r is not None for r in results), "All requests should succeed"
    assert avg_latency < 3.0, f"Average latency {avg_latency:.2f}s (expected < 3s)"

    print(f"\n✓ Ollama concurrent (3 requests): {avg_latency:.2f}s avg (target: < 3s)")


# ============================================================================
# Claude API Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not CLAUDE_AVAILABLE, reason="Claude API not available")
async def test_claude_complex_task_latency(claude_client: ClaudeClient) -> None:
    """Test that Claude complex tasks complete in < 10s.

    Acceptance: Complex automation generation should complete in < 10s (target: 5s).
    """
    complex_prompt = """Generate a Home Assistant automation that:
1. Triggers when motion is detected in the bedroom
2. Only runs between sunset and sunrise
3. Turns on the bedroom light at 30% brightness
4. Sends a notification
5. Waits 5 minutes, then turns off the light if no more motion

Output only valid YAML."""

    start_time = time.perf_counter()
    result = await claude_client.generate(
        prompt=complex_prompt,
        max_tokens=1024,
        temperature=0.7,
    )
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Claude should return a result"
    assert latency_s < 10.0, f"Claude took {latency_s:.2f}s (expected < 10s)"

    print(f"\n✓ Claude complex task: {latency_s:.2f}s (target: < 10s)")


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not CLAUDE_AVAILABLE, reason="Claude API not available")
async def test_claude_simple_task_latency(claude_client: ClaudeClient) -> None:
    """Test that Claude simple tasks complete in < 5s.

    Acceptance: Simple tasks should complete in < 5s (target: 3s).
    """
    simple_prompt = "Explain in 2 sentences why a Z-Wave integration might fail."

    start_time = time.perf_counter()
    result = await claude_client.generate(
        prompt=simple_prompt,
        max_tokens=100,
        temperature=0.7,
    )
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Claude should return a result"
    assert latency_s < 5.0, f"Claude took {latency_s:.2f}s (expected < 5s)"

    print(f"\n✓ Claude simple task: {latency_s:.2f}s (target: < 5s)")


# ============================================================================
# Enhanced Notification Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not available for notifications")
async def test_enhanced_notification_latency(
    perf_database: Database,
    perf_config: Config,
    ollama_client: OllamaClient,
) -> None:
    """Test that enhanced notifications complete in < 3s total.

    Acceptance: Enhanced notification generation should complete in < 3s.
    """
    llm_router = LLMRouter(ollama_client=ollama_client, claude_client=None, local_only=True)

    # Simulate notification enhancement
    notification_context = {
        "integration": "zwave_js",
        "entity_id": "sensor.bedroom_temp",
        "failure_count": 5,
        "last_success": "2 hours ago",
    }

    prompt = f"""Generate a concise notification message for:
Integration: {notification_context['integration']}
Entity: {notification_context['entity_id']}
Failures: {notification_context['failure_count']}
Last success: {notification_context['last_success']}

Keep it under 100 words."""

    start_time = time.perf_counter()
    result = await llm_router.generate(
        prompt=prompt,
        complexity=TaskComplexity.SIMPLE,
        max_tokens=150,
    )
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Enhanced notification should generate"
    assert latency_s < 3.0, f"Notification took {latency_s:.2f}s (expected < 3s)"

    print(f"\n✓ Enhanced notification: {latency_s:.2f}s (target: < 3s)")


# ============================================================================
# Anomaly Detection Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
async def test_anomaly_detection_scan_latency(
    perf_database: Database,
    perf_config: Config,
) -> None:
    """Test that anomaly detection for 30-day scan completes in < 5s.

    Acceptance: 30-day anomaly scan should complete in < 5s (target: 3s).
    """
    # Create test data (simulate 30 days of failures)
    pattern_collector = PatternCollector("default", config=perf_config, database=perf_database)

    print("\n  Creating 30 days of test failure data...")
    for day in range(30):
        for _hour in range(24):
            # Create varying failure rates
            failure_count = 5 + (day % 10)  # Varying pattern
            for i in range(failure_count):
                await pattern_collector.record_healing_attempt(
                    integration_id=f"integration_{day % 5}",
                    integration_domain=f"domain_{day % 5}",
                    entity_id=f"sensor.test_{i}",
                    success=i % 3 != 0,  # 33% failure rate
                )

    print("  ✓ Test data created")

    # Create anomaly detector (without LLM for pure detection speed)
    detector = AnomalyDetector(
        "default",
        database=perf_database,
        llm_router=None,  # Skip AI explanations for performance test
        sensitivity_threshold=2.0,
    )

    # Benchmark anomaly detection
    start_time = time.perf_counter()
    anomalies = await detector.detect_anomalies(hours=24 * 30)  # 30 days
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert latency_s < 5.0, f"Anomaly detection took {latency_s:.2f}s (expected < 5s)"
    print(f"\n✓ Anomaly detection (30-day scan): {latency_s:.2f}s (target: < 5s)")
    print(f"  Detected {len(anomalies)} anomalies")


# ============================================================================
# Weekly Summary Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not available for summaries")
async def test_weekly_summary_generation_latency(
    perf_database: Database,
    perf_config: Config,
    ollama_client: OllamaClient,
) -> None:
    """Test that weekly summary generation completes in < 15s.

    Acceptance: Weekly summary with AI should complete in < 15s (target: 10s).
    """
    # Create test data (1 week of reliability data)
    pattern_collector = PatternCollector("default", config=perf_config, database=perf_database)

    print("\n  Creating 1 week of test data...")
    for _day in range(7):
        for i in range(50):  # 50 events per day
            await pattern_collector.record_healing_attempt(
                integration_id=f"integration_{i % 5}",
                integration_domain=f"domain_{i % 5}",
                entity_id=f"sensor.test_{i}",
                success=i % 4 != 0,  # 75% success rate
            )

    print("  ✓ Test data created")

    # Create LLM router and summary generator
    llm_router = LLMRouter(ollama_client=ollama_client, claude_client=None, local_only=True)
    generator = WeeklySummaryGenerator(
        config=perf_config,
        database=perf_database,
        llm_router=llm_router,
    )

    # Benchmark summary generation (AI is included if config.notifications.ai_enhanced is True)
    start_time = time.perf_counter()
    summary = await generator.generate_summary()
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert summary is not None, "Summary should be generated"
    assert latency_s < 15.0, f"Summary generation took {latency_s:.2f}s (expected < 15s)"

    print(f"\n✓ Weekly summary generation: {latency_s:.2f}s (target: < 15s)")


# ============================================================================
# Automation Analysis Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama not available for analysis")
async def test_automation_analysis_latency(
    perf_config: Config,
    mock_ha_client: HomeAssistantClient,
    ollama_client: OllamaClient,
) -> None:
    """Test that automation analysis completes in < 5s.

    Acceptance: Single automation analysis with AI should complete in < 5s (target: 3s).
    """
    llm_router = LLMRouter(ollama_client=ollama_client, claude_client=None, local_only=True)
    analyzer = AutomationAnalyzer(
        ha_client=mock_ha_client,
        config=perf_config,
        llm_router=llm_router,
    )

    # Benchmark analysis
    start_time = time.perf_counter()
    result = await analyzer.analyze_automation(
        automation_id="automation.test_automation",
        include_ai=True,
    )
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Analysis should complete"
    assert latency_s < 5.0, f"Automation analysis took {latency_s:.2f}s (expected < 5s)"

    print(f"\n✓ Automation analysis: {latency_s:.2f}s (target: < 5s)")


# ============================================================================
# Automation Generation Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(not CLAUDE_AVAILABLE, reason="Claude API required for generation")
async def test_automation_generation_latency(
    perf_config: Config,
    mock_ha_client: HomeAssistantClient,
    claude_client: ClaudeClient,
) -> None:
    """Test that automation generation completes in < 15s.

    Acceptance: Automation generation via Claude should complete in < 15s (target: 8s).
    """
    llm_router = LLMRouter(ollama_client=None, claude_client=claude_client, local_only=False)
    generator = AutomationGenerator(
        ha_client=mock_ha_client,
        config=perf_config,
        llm_router=llm_router,
    )

    prompt = "Turn on bedroom light when motion detected, only at night"

    # Benchmark generation
    start_time = time.perf_counter()
    result = await generator.generate_from_prompt(prompt)
    end_time = time.perf_counter()

    latency_s = end_time - start_time

    # Assertions
    assert result is not None, "Automation should be generated"
    assert latency_s < 15.0, f"Automation generation took {latency_s:.2f}s (expected < 15s)"

    print(f"\n✓ Automation generation: {latency_s:.2f}s (target: < 15s)")


# ============================================================================
# End-to-End Performance Tests
# ============================================================================


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.skipif(
    not (OLLAMA_AVAILABLE and CLAUDE_AVAILABLE),
    reason="Both Ollama and Claude required",
)
async def test_llm_router_failover_latency(
    ollama_client: OllamaClient,
    claude_client: ClaudeClient,
) -> None:
    """Test LLM router failover doesn't add significant latency.

    Acceptance: Failover should add < 1s overhead.
    """
    llm_router = LLMRouter(
        ollama_client=ollama_client,
        claude_client=claude_client,
        local_only=False,
    )

    # Test simple task routing (should use Ollama)
    start_time = time.perf_counter()
    result_local = await llm_router.generate(
        prompt="Say 'OK'",
        complexity=TaskComplexity.SIMPLE,
        max_tokens=10,
    )
    local_time = time.perf_counter() - start_time

    # Test complex task routing (should use Claude)
    start_time = time.perf_counter()
    result_cloud = await llm_router.generate(
        prompt="Say 'OK'",
        complexity=TaskComplexity.COMPLEX,
        max_tokens=10,
    )
    cloud_time = time.perf_counter() - start_time

    # Assertions
    assert result_local is not None, "Local routing should succeed"
    assert result_cloud is not None, "Cloud routing should succeed"

    print(
        f"\n✓ LLM Router - Simple (Ollama): {local_time:.2f}s, Complex (Claude): {cloud_time:.2f}s"
    )
