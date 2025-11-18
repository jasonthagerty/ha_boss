"""Claude API client for complex AI tasks."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Client for interacting with Claude API.

    Provides async interface for LLM text generation with graceful error handling.
    All methods return None on errors to support graceful degradation.
    """

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        """Initialize Claude client.

        Args:
            api_key: Anthropic API key
            model: Model name to use (e.g., claude-3-5-sonnet-20241022)
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._base_url = "https://api.anthropic.com/v1"

    async def __aenter__(self) -> "ClaudeClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Note: Prefer using async context manager to ensure proper cleanup.
        If using directly, call close() when done to avoid resource leaks.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str | None:
        """Generate text completion from prompt.

        Args:
            prompt: Text prompt for generation
            max_tokens: Maximum tokens to generate (default 1024)
            temperature: Sampling temperature (0.0-1.0, default 0.7)
            system_prompt: Optional system prompt for context

        Returns:
            Generated text, or None if generation failed

        Raises:
            ValueError: If temperature is not in range [0.0, 1.0]

        Example:
            >>> client = ClaudeClient(api_key="...", model="claude-3-5-sonnet-20241022")
            >>> text = await client.generate("Generate an automation for...")
            >>> if text:
            ...     print(text)
        """
        # Validate temperature parameter
        if not 0.0 <= temperature <= 1.0:
            raise ValueError(f"temperature must be between 0.0 and 1.0, got {temperature}")

        try:
            client = await self._get_client()

            # Build request payload
            messages = [{"role": "user", "content": prompt}]

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if system_prompt:
                payload["system"] = system_prompt

            # Make request
            response = await client.post(
                f"{self._base_url}/messages",
                json=payload,
            )
            response.raise_for_status()

            # Parse response
            data = response.json()
            content_blocks = data.get("content", [])
            if content_blocks and len(content_blocks) > 0:
                text = content_blocks[0].get("text", "")
                return str(text) if text else ""
            return ""

        except httpx.ConnectError as e:
            logger.warning(f"Cannot connect to Claude API: {e}")
            logger.info("AI features degraded - Claude API not available")
            return None

        except httpx.TimeoutException:
            logger.error(
                f"Claude request timed out after {self.timeout}s. "
                "Consider increasing timeout or using simpler prompts."
            )
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Claude API authentication failed - check API key")
            elif e.response.status_code == 429:
                logger.warning("Claude API rate limit exceeded - try again later")
            else:
                logger.error(f"Claude API error: {e.response.status_code} - {e.response.text}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {e}", exc_info=True)
            return None

    async def is_available(self) -> bool:
        """Check if Claude API is available and authenticated.

        Returns:
            True if Claude API is available, False otherwise
        """
        try:
            # Quick health check with minimal token usage
            result = await self.generate(
                prompt="Respond with 'OK' if you can read this.",
                max_tokens=10,
                temperature=0.0,
            )
            return result is not None

        except Exception as e:
            logger.debug(f"Claude API not available: {e}")
            return False

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
