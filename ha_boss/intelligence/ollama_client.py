"""Ollama LLM client for AI-powered features."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for interacting with Ollama API.

    Provides async interface for LLM text generation with graceful error handling.
    All methods return None on errors to support graceful degradation.
    """

    def __init__(self, url: str, model: str, timeout: float = 30.0) -> None:
        """Initialize Ollama client.

        Args:
            url: Ollama API base URL (e.g., http://localhost:11434)
            model: Model name to use (e.g., llama3.1:8b)
            timeout: Request timeout in seconds
        """
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OllamaClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def generate(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str | None:
        """Generate text completion from prompt.

        Args:
            prompt: Text prompt for generation
            max_tokens: Maximum tokens to generate (None = model default)
            temperature: Sampling temperature (0.0-1.0, default 0.7)
            system_prompt: Optional system prompt for context

        Returns:
            Generated text, or None if generation failed

        Example:
            >>> client = OllamaClient("http://localhost:11434", "llama3.1:8b")
            >>> text = await client.generate("Explain why integrations fail")
            >>> if text:
            ...     print(text)
        """
        try:
            client = await self._get_client()

            # Build request payload
            payload: dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                },
            }

            if max_tokens is not None:
                payload["options"]["num_predict"] = max_tokens

            if system_prompt:
                payload["system"] = system_prompt

            # Make request
            response = await client.post(
                f"{self.url}/api/generate",
                json=payload,
            )
            response.raise_for_status()

            # Parse response
            data = response.json()
            response_text = data.get("response", "")
            return str(response_text) if response_text is not None else ""

        except httpx.ConnectError as e:
            logger.warning(f"Cannot connect to Ollama at {self.url}: {e}")
            logger.info("AI features disabled - Ollama not available")
            return None

        except httpx.TimeoutException:
            logger.error(
                f"Ollama request timed out after {self.timeout}s. "
                "Consider increasing ollama_timeout_seconds in config."
            )
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Pull it with: docker exec haboss_ollama ollama pull {self.model}"
                )
            else:
                logger.error(f"Ollama API error: {e.response.status_code} - {e.response.text}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error calling Ollama: {e}", exc_info=True)
            return None

    async def is_available(self) -> bool:
        """Check if Ollama is available and responsive.

        Returns:
            True if Ollama is available, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.url}/api/tags")
            response.raise_for_status()
            return True

        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            return False

    async def list_models(self) -> list[str]:
        """List available models in Ollama.

        Returns:
            List of model names, empty list if unavailable
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.url}/api/tags")
            response.raise_for_status()

            data = response.json()
            models = data.get("models", [])
            return [model["name"] for model in models]

        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
