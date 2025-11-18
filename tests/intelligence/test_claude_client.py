"""Tests for ClaudeClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

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
    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "msg_123",
        "type": "message",
        "content": [{"type": "text", "text": "Here's an automation for your lights."}],
        "stop_reason": "end_turn",
    }
    mock_response.raise_for_status = MagicMock()

    # Mock httpx client
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        # Test generation
        result = await claude_client.generate("Generate an automation")

        assert result == "Here's an automation for your lights."
        mock_client.post.assert_called_once()

        # Verify request payload
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.anthropic.com/v1/messages"
        payload = call_args[1]["json"]
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "Generate an automation"
        assert payload["max_tokens"] == 1024
        assert payload["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_with_options(claude_client: ClaudeClient):
    """Test generation with custom options."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "Test response"}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await claude_client.generate(
            prompt="Test prompt",
            max_tokens=2048,
            temperature=0.5,
            system_prompt="You are an automation expert.",
        )

        assert result == "Test response"

        # Verify options
        payload = mock_client.post.call_args[1]["json"]
        assert payload["max_tokens"] == 2048
        assert payload["temperature"] == 0.5
        assert payload["system"] == "You are an automation expert."


@pytest.mark.asyncio
async def test_generate_connection_error(claude_client: ClaudeClient):
    """Test handling of connection errors."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_timeout(claude_client: ClaudeClient):
    """Test handling of request timeout."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_auth_error(claude_client: ClaudeClient):
    """Test handling of authentication errors (401)."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=mock_response
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
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "429 Too Many Requests", request=MagicMock(), response=mock_response
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
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "OK"}],
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        available = await claude_client.is_available()

        assert available is True


@pytest.mark.asyncio
async def test_is_available_failure(claude_client: ClaudeClient):
    """Test availability check when API is unavailable."""
    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_get_client.return_value = mock_client

        available = await claude_client.is_available()

        assert available is False


@pytest.mark.asyncio
async def test_context_manager():
    """Test async context manager."""
    client = ClaudeClient(api_key="test", model="claude-3-5-sonnet-20241022")

    async with client as c:
        assert c._client is not None
        assert isinstance(c._client, httpx.AsyncClient)

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
    mock_response.json.return_value = {"content": []}
    mock_response.raise_for_status = MagicMock()

    with patch.object(claude_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await claude_client.generate("Test prompt")

        assert result == ""
