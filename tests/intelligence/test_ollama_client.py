"""Tests for OllamaClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ha_boss.intelligence.ollama_client import OllamaClient


@pytest.fixture
def ollama_client():
    """Create OllamaClient instance for testing."""
    return OllamaClient(
        url="http://localhost:11434",
        model="llama3.1:8b",
        timeout=30.0,
    )


@pytest.mark.asyncio
async def test_generate_success(ollama_client: OllamaClient):
    """Test successful text generation."""
    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": "The integration failed due to network timeout.",
        "done": True,
    }
    mock_response.raise_for_status = MagicMock()

    # Mock httpx client
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        # Test generation
        result = await ollama_client.generate("Why did the integration fail?")

        assert result == "The integration failed due to network timeout."
        mock_client.post.assert_called_once()

        # Verify request payload
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:11434/api/generate"
        payload = call_args[1]["json"]
        assert payload["model"] == "llama3.1:8b"
        assert payload["prompt"] == "Why did the integration fail?"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_with_options(ollama_client: OllamaClient):
    """Test generation with custom options."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "Test response", "done": True}
    mock_response.raise_for_status = MagicMock()

    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate(
            prompt="Test prompt",
            max_tokens=500,
            temperature=0.5,
            system_prompt="You are a helpful assistant.",
        )

        assert result == "Test response"

        # Verify options
        payload = mock_client.post.call_args[1]["json"]
        assert payload["options"]["num_predict"] == 500
        assert payload["options"]["temperature"] == 0.5
        assert payload["system"] == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_generate_connection_error(ollama_client: OllamaClient):
    """Test handling of connection errors."""
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_timeout(ollama_client: OllamaClient):
    """Test handling of request timeout."""
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_model_not_found(ollama_client: OllamaClient):
    """Test handling of model not found error."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "model not found"

    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=mock_response
            )
        )
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_http_error(ollama_client: OllamaClient):
    """Test handling of generic HTTP errors."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal server error"

    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_response
            )
        )
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_generate_unexpected_error(ollama_client: OllamaClient):
    """Test handling of unexpected errors."""
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_get_client.return_value = mock_client

        result = await ollama_client.generate("Test prompt")

        assert result is None


@pytest.mark.asyncio
async def test_is_available_success(ollama_client: OllamaClient):
    """Test is_available when Ollama is running."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await ollama_client.is_available()

        assert result is True
        mock_client.get.assert_called_once_with("http://localhost:11434/api/tags")


@pytest.mark.asyncio
async def test_is_available_failure(ollama_client: OllamaClient):
    """Test is_available when Ollama is not running."""
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await ollama_client.is_available()

        assert result is False


@pytest.mark.asyncio
async def test_list_models_success(ollama_client: OllamaClient):
    """Test listing available models."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "models": [
            {"name": "llama3.1:8b"},
            {"name": "llama3.1:70b"},
            {"name": "phi-3:mini"},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await ollama_client.list_models()

        assert result == ["llama3.1:8b", "llama3.1:70b", "phi-3:mini"]
        mock_client.get.assert_called_once_with("http://localhost:11434/api/tags")


@pytest.mark.asyncio
async def test_list_models_failure(ollama_client: OllamaClient):
    """Test list_models when request fails."""
    with patch.object(ollama_client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await ollama_client.list_models()

        assert result == []


@pytest.mark.asyncio
async def test_context_manager():
    """Test async context manager protocol."""
    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    async with client as c:
        assert c._client is not None
        assert isinstance(c._client, httpx.AsyncClient)

    # Client should be closed after exiting context
    assert client._client is None


@pytest.mark.asyncio
async def test_close():
    """Test explicit close method."""
    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    # Create client
    await client._get_client()
    assert client._client is not None

    # Close
    await client.close()
    assert client._client is None


@pytest.mark.asyncio
async def test_url_trailing_slash_removed():
    """Test that trailing slash is removed from URL."""
    client = OllamaClient("http://localhost:11434/", "llama3.1:8b")
    assert client.url == "http://localhost:11434"


@pytest.mark.asyncio
async def test_empty_response():
    """Test handling of empty response (missing 'response' field)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"done": True}  # No "response" field
    mock_response.raise_for_status = MagicMock()

    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    with patch.object(client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await client.generate("Test prompt")

        # Should return empty string when field is missing
        assert result == ""


@pytest.mark.asyncio
async def test_none_response():
    """Test handling of null response value."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": None, "done": True}
    mock_response.raise_for_status = MagicMock()

    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    with patch.object(client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await client.generate("Test prompt")

        # Should return empty string when response is null
        assert result == ""


@pytest.mark.asyncio
async def test_temperature_validation_too_low():
    """Test temperature validation rejects values below 0.0."""
    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    with pytest.raises(ValueError, match="temperature must be between 0.0 and 2.0"):
        await client.generate("Test prompt", temperature=-0.1)


@pytest.mark.asyncio
async def test_temperature_validation_too_high():
    """Test temperature validation rejects values above 2.0."""
    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    with pytest.raises(ValueError, match="temperature must be between 0.0 and 2.0"):
        await client.generate("Test prompt", temperature=2.1)


@pytest.mark.asyncio
async def test_temperature_validation_boundary_values():
    """Test temperature validation accepts boundary values."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "test", "done": True}
    mock_response.raise_for_status = MagicMock()

    client = OllamaClient("http://localhost:11434", "llama3.1:8b")

    with patch.object(client, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        # Should accept 0.0
        result = await client.generate("Test", temperature=0.0)
        assert result == "test"

        # Should accept 2.0
        result = await client.generate("Test", temperature=2.0)
        assert result == "test"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skip(reason="Requires running Ollama instance")
async def test_real_ollama_connection():
    """Integration test with real Ollama instance.

    This test is skipped by default. To run it:
    1. Start Ollama: docker run -d -p 11434:11434 ollama/ollama
    2. Pull model: docker exec <container> ollama pull llama3.1:8b
    3. Run: pytest -m integration tests/intelligence/test_ollama_client.py
    """
    client = OllamaClient("http://localhost:11434", "llama3.1:8b", timeout=60.0)

    try:
        # Check availability
        available = await client.is_available()
        assert available, "Ollama should be available"

        # List models
        models = await client.list_models()
        assert "llama3.1:8b" in models, "Test model should be available"

        # Generate text
        result = await client.generate("Say hello in one word.", max_tokens=10)
        assert result is not None, "Should generate response"
        assert len(result) > 0, "Response should not be empty"

    finally:
        await client.close()
