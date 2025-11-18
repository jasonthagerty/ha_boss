"""Tests for ClaudeClient using Anthropic SDK."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
from anthropic.types import TextBlock

from ha_boss.intelligence.claude_client import ClaudeClient


@pytest.fixture
def claude_client():
    """Create ClaudeClient instance for testing."""
    return ClaudeClient(
        api_key="test-api-key-12345",
        model="claude-3-5-sonnet-20241022",
        timeout=60.0,
    )


@pytest.mark.asyncio
async def test_generate_success(claude_client: ClaudeClient):
    """Test successful text generation."""
    # Mock Anthropic SDK response
    mock_text_block = MagicMock(spec=TextBlock)
    mock_text_block.text = "Here's an automation for your lights."
    mock_text_block.type = "text"

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    # Mock Anthropic client
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        # Test generation
        result = await claude_client.generate("Generate an automation")

        assert result == "Here's an automation for your lights."
        mock_client.messages.create.assert_called_once()

        # Verify request parameters
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-3-5-sonnet-20241022"
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "Generate an automation"
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_with_options(claude_client: ClaudeClient):
    """Test generation with custom options."""
    mock_text_block = MagicMock(spec=TextBlock)
    mock_text_block.text = "Test response"

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await claude_client.generate(
            prompt="Test prompt",
            max_tokens=2048,
            temperature=0.5,
            system_prompt="You are an automation expert.",
        )

        assert result == "Test response"

        # Verify options
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 2048
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["system"] == "You are an automation expert."


@pytest.mark.asyncio
async def test_generate_connection_error(claude_client: ClaudeClient):
    """Test handling of connection errors."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_timeout(claude_client: ClaudeClient):
    """Test handling of request timeout."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=MagicMock())
        )
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_auth_error(claude_client: ClaudeClient):
    """Test handling of authentication errors (401)."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                message="Invalid API key",
                response=MagicMock(),
                body=None,
            )
        )
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_rate_limit_error(claude_client: ClaudeClient):
    """Test handling of rate limit errors (429)."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="Rate limit exceeded",
                response=MagicMock(),
                body=None,
            )
        )
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_api_status_error(claude_client: ClaudeClient):
    """Test handling of API status errors."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="Server error",
                response=MagicMock(),
                body=None,
            )
        )
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_invalid_temperature():
    """Test temperature validation."""
    client = ClaudeClient(api_key="test", model="claude-3-5-sonnet-20241022")

    with pytest.raises(ValueError, match="temperature must be between 0.0 and 1.0"):
        await client.generate("Test", temperature=1.5)

    with pytest.raises(ValueError, match="temperature must be between 0.0 and 1.0"):
        await client.generate("Test", temperature=-0.1)


@pytest.mark.asyncio
async def test_is_available_success(claude_client: ClaudeClient):
    """Test availability check when API is available."""
    mock_text_block = MagicMock(spec=TextBlock)
    mock_text_block.text = "OK"

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        available = await claude_client.is_available()

        assert available is True


@pytest.mark.asyncio
async def test_is_available_failure(claude_client: ClaudeClient):
    """Test availability check when API is unavailable."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )
        mock_get_client.return_value = mock_client

        available = await claude_client.is_available()

        assert available is False


@pytest.mark.asyncio
async def test_context_manager():
    """Test async context manager."""
    client = ClaudeClient(api_key="test", model="claude-3-5-sonnet-20241022")

    async with client as c:
        assert c._client is not None
        assert isinstance(c._client, anthropic.AsyncAnthropic)

    # Client should be closed after context exit
    assert client._client is None


@pytest.mark.asyncio
async def test_close():
    """Test manual close."""
    client = ClaudeClient(api_key="test", model="claude-3-5-sonnet-20241022")

    # Create client
    await client._get_client()
    assert client._client is not None

    # Close
    await client.close()
    assert client._client is None


@pytest.mark.asyncio
async def test_generate_empty_response(claude_client: ClaudeClient):
    """Test handling of empty response content."""
    mock_response = MagicMock()
    mock_response.content = []

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result == ""
