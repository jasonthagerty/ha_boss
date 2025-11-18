"""Tests for LLMRouter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity


@pytest.fixture
def mock_ollama():
    """Create mock OllamaClient."""
    from ha_boss.intelligence.ollama_client import OllamaClient

    mock = MagicMock(spec=OllamaClient)
    mock.generate = AsyncMock(return_value="Ollama response")
    mock.is_available = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_claude():
    """Create mock ClaudeClient."""
    from ha_boss.intelligence.claude_client import ClaudeClient

    mock = MagicMock(spec=ClaudeClient)
    mock.generate = AsyncMock(return_value="Claude response")
    mock.is_available = AsyncMock(return_value=True)
    return mock


@pytest.mark.asyncio
async def test_simple_task_routes_to_ollama(mock_ollama, mock_claude):
    """Test SIMPLE tasks route to Ollama only."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Explain why sensor failed",
        complexity=TaskComplexity.SIMPLE,
    )

    assert result == "Ollama response"
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_not_called()


@pytest.mark.asyncio
async def test_moderate_task_routes_to_ollama_first(mock_ollama, mock_claude):
    """Test MODERATE tasks route to Ollama first, Claude as fallback."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Analyze pattern",
        complexity=TaskComplexity.MODERATE,
    )

    assert result == "Ollama response"
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_not_called()


@pytest.mark.asyncio
async def test_moderate_task_falls_back_to_claude(mock_ollama, mock_claude):
    """Test MODERATE tasks fall back to Claude when Ollama fails."""
    mock_ollama.generate = AsyncMock(return_value=None)  # Ollama fails

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Analyze pattern",
        complexity=TaskComplexity.MODERATE,
    )

    assert result == "Claude response"
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_called_once()


@pytest.mark.asyncio
async def test_complex_task_routes_to_claude_first(mock_ollama, mock_claude):
    """Test COMPLEX tasks route to Claude first."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Generate complex automation",
        complexity=TaskComplexity.COMPLEX,
    )

    assert result == "Claude response"
    mock_claude.generate.assert_called_once()
    mock_ollama.generate.assert_not_called()


@pytest.mark.asyncio
async def test_complex_task_falls_back_to_ollama(mock_ollama, mock_claude):
    """Test COMPLEX tasks fall back to Ollama when Claude fails."""
    mock_claude.generate = AsyncMock(return_value=None)  # Claude fails

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Generate automation",
        complexity=TaskComplexity.COMPLEX,
    )

    assert result == "Ollama response"
    mock_claude.generate.assert_called_once()
    mock_ollama.generate.assert_called_once()


@pytest.mark.asyncio
async def test_local_only_mode_never_uses_claude(mock_ollama, mock_claude):
    """Test local-only mode never uses Claude API."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=True,  # Local-only mode
    )

    # Even for COMPLEX tasks
    result = await router.generate(
        prompt="Generate automation",
        complexity=TaskComplexity.COMPLEX,
    )

    assert result == "Ollama response"
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_not_called()


@pytest.mark.asyncio
async def test_local_only_mode_no_fallback_to_claude(mock_ollama, mock_claude):
    """Test local-only mode doesn't fall back to Claude even when Ollama fails."""
    mock_ollama.generate = AsyncMock(return_value=None)  # Ollama fails

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=True,
    )

    result = await router.generate(
        prompt="Test prompt",
        complexity=TaskComplexity.MODERATE,
    )

    assert result is None
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_not_called()


@pytest.mark.asyncio
async def test_both_llms_unavailable(mock_ollama, mock_claude):
    """Test handling when both LLMs fail."""
    mock_ollama.generate = AsyncMock(return_value=None)
    mock_claude.generate = AsyncMock(return_value=None)

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    result = await router.generate(
        prompt="Test prompt",
        complexity=TaskComplexity.MODERATE,
    )

    assert result is None
    mock_ollama.generate.assert_called_once()
    mock_claude.generate.assert_called_once()


@pytest.mark.asyncio
async def test_no_llms_configured():
    """Test router with no LLMs configured."""
    router = LLMRouter(
        ollama_client=None,
        claude_client=None,
        local_only=False,
    )

    result = await router.generate(
        prompt="Test prompt",
        complexity=TaskComplexity.SIMPLE,
    )

    assert result is None


@pytest.mark.asyncio
async def test_only_ollama_configured(mock_ollama):
    """Test router with only Ollama configured."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    # Even COMPLEX tasks use Ollama
    result = await router.generate(
        prompt="Complex task",
        complexity=TaskComplexity.COMPLEX,
    )

    assert result == "Ollama response"
    mock_ollama.generate.assert_called_once()


@pytest.mark.asyncio
async def test_only_claude_configured(mock_claude):
    """Test router with only Claude configured."""
    router = LLMRouter(
        ollama_client=None,
        claude_client=mock_claude,
        local_only=False,
    )

    # Even SIMPLE tasks use Claude
    result = await router.generate(
        prompt="Simple task",
        complexity=TaskComplexity.SIMPLE,
    )

    assert result == "Claude response"
    mock_claude.generate.assert_called_once()


@pytest.mark.asyncio
async def test_generate_with_max_tokens(mock_ollama):
    """Test passing max_tokens parameter."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    await router.generate(
        prompt="Test",
        complexity=TaskComplexity.SIMPLE,
        max_tokens=500,
    )

    # Verify max_tokens was passed
    call_kwargs = mock_ollama.generate.call_args[1]
    assert call_kwargs["max_tokens"] == 500


@pytest.mark.asyncio
async def test_generate_with_system_prompt(mock_ollama):
    """Test passing system_prompt parameter."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    await router.generate(
        prompt="Test",
        complexity=TaskComplexity.SIMPLE,
        system_prompt="You are an expert.",
    )

    # Verify system_prompt was passed
    call_kwargs = mock_ollama.generate.call_args[1]
    assert call_kwargs["system_prompt"] == "You are an expert."


@pytest.mark.asyncio
async def test_temperature_adjustment_for_claude(mock_claude):
    """Test temperature is adjusted to Claude's 0.0-1.0 range."""
    router = LLMRouter(
        ollama_client=None,
        claude_client=mock_claude,
        local_only=False,
    )

    # Pass temperature > 1.0 (valid for Ollama but not Claude)
    await router.generate(
        prompt="Test",
        complexity=TaskComplexity.COMPLEX,
        temperature=1.5,
    )

    # Verify temperature was capped at 1.0 for Claude
    call_kwargs = mock_claude.generate.call_args[1]
    assert call_kwargs["temperature"] == 1.0


@pytest.mark.asyncio
async def test_temperature_passed_through_for_ollama(mock_ollama):
    """Test temperature is passed through to Ollama (supports 0.0-2.0)."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    await router.generate(
        prompt="Test",
        complexity=TaskComplexity.SIMPLE,
        temperature=1.5,
    )

    # Verify temperature was passed as-is
    call_kwargs = mock_ollama.generate.call_args[1]
    assert call_kwargs["temperature"] == 1.5


@pytest.mark.asyncio
async def test_get_available_llms_both_available(mock_ollama, mock_claude):
    """Test get_available_llms when both are available."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    available = await router.get_available_llms()

    assert "Ollama" in available
    assert "Claude" in available
    assert len(available) == 2


@pytest.mark.asyncio
async def test_get_available_llms_only_ollama(mock_ollama, mock_claude):
    """Test get_available_llms when only Ollama is available."""
    mock_claude.is_available = AsyncMock(return_value=False)

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    available = await router.get_available_llms()

    assert available == ["Ollama"]


@pytest.mark.asyncio
async def test_get_available_llms_local_only_mode(mock_ollama, mock_claude):
    """Test get_available_llms in local-only mode (Claude excluded)."""
    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=True,
    )

    available = await router.get_available_llms()

    assert available == ["Ollama"]


@pytest.mark.asyncio
async def test_get_available_llms_none_available(mock_ollama, mock_claude):
    """Test get_available_llms when no LLMs are available."""
    mock_ollama.is_available = AsyncMock(return_value=False)
    mock_claude.is_available = AsyncMock(return_value=False)

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=mock_claude,
        local_only=False,
    )

    available = await router.get_available_llms()

    assert available == []


@pytest.mark.asyncio
async def test_get_available_llms_check_error(mock_ollama):
    """Test get_available_llms handles errors gracefully."""
    mock_ollama.is_available = AsyncMock(side_effect=Exception("Connection error"))

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    available = await router.get_available_llms()

    assert available == []


@pytest.mark.asyncio
async def test_generate_handles_client_exception(mock_ollama):
    """Test that generate handles exceptions from client gracefully."""
    mock_ollama.generate = AsyncMock(side_effect=Exception("Unexpected error"))

    router = LLMRouter(
        ollama_client=mock_ollama,
        claude_client=None,
        local_only=False,
    )

    result = await router.generate(
        prompt="Test",
        complexity=TaskComplexity.SIMPLE,
    )

    assert result is None
