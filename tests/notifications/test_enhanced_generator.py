"""Tests for enhanced notification generator."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity
from ha_boss.notifications.enhanced_generator import EnhancedNotificationGenerator


@pytest.fixture
def mock_llm_router():
    """Create mock LLM router."""
    router = MagicMock(spec=LLMRouter)
    router.generate = AsyncMock()
    return router


@pytest.fixture
def generator(mock_llm_router):
    """Create enhanced notification generator."""
    return EnhancedNotificationGenerator(mock_llm_router)


@pytest.mark.asyncio
async def test_generate_failure_analysis_success(generator, mock_llm_router):
    """Test successful AI analysis generation."""
    # Mock LLM response with proper format
    mock_llm_router.generate.return_value = """ANALYSIS:
The Met.no integration is failing due to API rate limiting. This commonly occurs
when the integration makes too many requests in a short period.

SUGGESTIONS:
1. Check Home Assistant logs for rate limit errors
2. Reduce polling frequency in the met configuration
3. Consider using a weather integration as backup"""

    result = await generator.generate_failure_analysis(
        entity_id="sensor.outdoor_temp",
        issue_type="unavailable",
        error="Integration reload failed: timeout",
        attempts=3,
        healing_stats={"success_rate": 45.0, "total_attempts": 20},
        integration_info={"domain": "met", "title": "Met.no"},
    )

    assert result is not None
    assert "analysis" in result
    assert "suggestions" in result
    assert "rate limiting" in result["analysis"]
    assert "polling frequency" in result["suggestions"]

    # Verify LLM was called with correct parameters
    mock_llm_router.generate.assert_called_once()
    call_kwargs = mock_llm_router.generate.call_args[1]
    assert call_kwargs["complexity"] == TaskComplexity.SIMPLE
    assert call_kwargs["max_tokens"] == 256
    assert call_kwargs["temperature"] == 0.3
    assert "sensor.outdoor_temp" in call_kwargs["prompt"]


@pytest.mark.asyncio
async def test_generate_failure_analysis_with_minimal_context(generator, mock_llm_router):
    """Test AI analysis with minimal context."""
    mock_llm_router.generate.return_value = """ANALYSIS:
Entity is unavailable.

SUGGESTIONS:
1. Check the integration
2. Restart Home Assistant"""

    result = await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Connection refused",
        attempts=1,
    )

    assert result is not None
    assert "analysis" in result
    assert "suggestions" in result


@pytest.mark.asyncio
async def test_generate_failure_analysis_llm_returns_none(generator, mock_llm_router):
    """Test handling when LLM returns None."""
    mock_llm_router.generate.return_value = None

    result = await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=1,
    )

    assert result is None


@pytest.mark.asyncio
async def test_generate_failure_analysis_llm_exception(generator, mock_llm_router):
    """Test handling when LLM throws exception."""
    mock_llm_router.generate.side_effect = Exception("LLM connection error")

    result = await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=1,
    )

    assert result is None


@pytest.mark.asyncio
async def test_generate_failure_analysis_unstructured_response(generator, mock_llm_router):
    """Test parsing of unstructured LLM response."""
    # LLM returns response without clear sections
    mock_llm_router.generate.return_value = (
        "The sensor is failing because the integration cannot connect. "
        "Try restarting the integration."
    )

    result = await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=1,
    )

    assert result is not None
    # Full response should be in analysis
    assert "sensor is failing" in result["analysis"]
    # No separate suggestions section
    assert result["suggestions"] == ""


@pytest.mark.asyncio
async def test_generate_circuit_breaker_analysis_success(generator, mock_llm_router):
    """Test successful circuit breaker analysis generation."""
    mock_llm_router.generate.return_value = """ANALYSIS:
The Philips Hue integration has repeatedly failed, triggering the circuit breaker.
This indicates a persistent issue with the integration or its connection.

SUGGESTIONS:
1. Check the Hue bridge connectivity
2. Verify API credentials are still valid
3. Look for firmware update issues on the bridge"""

    reset_time = datetime.now() + timedelta(hours=1)

    result = await generator.generate_circuit_breaker_analysis(
        integration_name="Philips Hue",
        failure_count=10,
        reset_time=reset_time,
        healing_stats={"success_rate": 20.0, "total_attempts": 50},
    )

    assert result is not None
    assert "analysis" in result
    assert "suggestions" in result
    assert "circuit breaker" in result["analysis"]

    # Verify LLM was called
    mock_llm_router.generate.assert_called_once()


@pytest.mark.asyncio
async def test_generate_circuit_breaker_analysis_llm_fails(generator, mock_llm_router):
    """Test circuit breaker analysis when LLM fails."""
    mock_llm_router.generate.return_value = None

    reset_time = datetime.now() + timedelta(hours=1)

    result = await generator.generate_circuit_breaker_analysis(
        integration_name="Test Integration",
        failure_count=5,
        reset_time=reset_time,
    )

    assert result is None


@pytest.mark.asyncio
async def test_prompt_includes_historical_stats(generator, mock_llm_router):
    """Test that historical stats are included in prompt."""
    mock_llm_router.generate.return_value = "ANALYSIS:\nTest\n\nSUGGESTIONS:\n1. Test"

    await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=3,
        healing_stats={"success_rate": 30.0, "total_attempts": 100},
    )

    # Check prompt contains historical data
    call_kwargs = mock_llm_router.generate.call_args[1]
    prompt = call_kwargs["prompt"]
    assert "30%" in prompt or "Historical success rate" in prompt
    assert "100" in prompt


@pytest.mark.asyncio
async def test_prompt_includes_integration_info(generator, mock_llm_router):
    """Test that integration info is included in prompt."""
    mock_llm_router.generate.return_value = "ANALYSIS:\nTest\n\nSUGGESTIONS:\n1. Test"

    await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=1,
        integration_info={"domain": "hue", "title": "Philips Hue"},
    )

    # Check prompt contains integration info
    call_kwargs = mock_llm_router.generate.call_args[1]
    prompt = call_kwargs["prompt"]
    assert "Philips Hue" in prompt
    assert "hue" in prompt


@pytest.mark.asyncio
async def test_parse_response_with_reversed_sections(generator, mock_llm_router):
    """Test parsing when sections are in unexpected order."""
    # This should still work even though order is weird
    mock_llm_router.generate.return_value = """SUGGESTIONS:
1. Do this first

ANALYSIS:
This is the analysis after suggestions."""

    result = await generator.generate_failure_analysis(
        entity_id="sensor.test",
        issue_type="unavailable",
        error="Test error",
        attempts=1,
    )

    assert result is not None
    # With reversed order, full response goes to analysis
    assert result["analysis"] != ""
