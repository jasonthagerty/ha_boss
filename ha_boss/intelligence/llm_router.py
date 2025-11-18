"""LLM router for intelligently selecting between local and cloud AI."""

import logging
from enum import Enum

from ha_boss.intelligence.claude_client import ClaudeClient
from ha_boss.intelligence.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Task complexity levels for LLM routing.

    SIMPLE: Local LLM only (notifications, quick explanations)
    MODERATE: Prefer local, fall back to Claude (pattern analysis, summaries)
    COMPLEX: Prefer Claude, fall back to local (automation generation, deep analysis)
    """

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class LLMRouter:
    """Routes AI tasks to appropriate LLM based on complexity and availability.

    Intelligently selects between local Ollama and Claude API based on:
    - Task complexity
    - User configuration (local-only mode)
    - LLM availability
    - Graceful fallback when primary LLM unavailable
    """

    def __init__(
        self,
        ollama_client: OllamaClient | None,
        claude_client: ClaudeClient | None,
        local_only: bool = False,
    ) -> None:
        """Initialize LLM router.

        Args:
            ollama_client: Ollama client instance (None if disabled)
            claude_client: Claude client instance (None if disabled)
            local_only: If True, never use Claude API (privacy mode)
        """
        self.ollama = ollama_client
        self.claude = claude_client
        self.local_only = local_only

        # Log configuration
        available = []
        if self.ollama:
            available.append("Ollama")
        if self.claude and not local_only:
            available.append("Claude")

        if available:
            logger.info(f"LLM Router initialized with: {', '.join(available)}")
        else:
            logger.warning("LLM Router initialized with NO available LLMs")

        if local_only and self.claude:
            logger.info("Local-only mode enabled - Claude API will not be used")

    async def generate(
        self,
        prompt: str,
        complexity: TaskComplexity,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str | None:
        """Route prompt to appropriate LLM based on complexity.

        Args:
            prompt: Text prompt for generation
            complexity: Task complexity level
            max_tokens: Maximum tokens to generate (None = model default)
            temperature: Sampling temperature (0.0-2.0). Note: Automatically
                clamped to 1.0 when routing to Claude API.
            system_prompt: Optional system prompt for context

        Returns:
            Generated text, or None if no LLM available or all failed

        Raises:
            ValueError: If temperature is not in range [0.0, 2.0]

        Example:
            >>> router = LLMRouter(ollama, claude, local_only=False)
            >>> # Simple task - routes to Ollama
            >>> result = await router.generate(
            ...     "Explain why sensor.temp failed",
            ...     TaskComplexity.SIMPLE
            ... )
            >>> # Complex task - routes to Claude, falls back to Ollama
            >>> result = await router.generate(
            ...     "Generate automation for...",
            ...     TaskComplexity.COMPLEX
            ... )
        """
        # Validate temperature parameter
        if not 0.0 <= temperature <= 2.0:
            raise ValueError(f"temperature must be between 0.0 and 2.0, got {temperature}")

        # Determine primary and fallback LLMs based on complexity
        primary: OllamaClient | ClaudeClient | None
        fallback: OllamaClient | ClaudeClient | None
        primary_name: str | None
        fallback_name: str | None

        if complexity == TaskComplexity.SIMPLE:
            # SIMPLE: Prefer Ollama, fall back to Claude if Ollama not available
            primary = self.ollama
            fallback = self.claude if not self.local_only else None
            primary_name = "Ollama" if primary else None
            fallback_name = "Claude" if fallback else None
        elif complexity == TaskComplexity.MODERATE:
            # MODERATE: Prefer Ollama, fall back to Claude
            primary = self.ollama
            fallback = self.claude if not self.local_only else None
            primary_name = "Ollama" if primary else None
            fallback_name = "Claude" if fallback else None
        else:  # COMPLEX
            # COMPLEX: Prefer Claude, fall back to Ollama
            if not self.local_only:
                primary = self.claude
                fallback = self.ollama
                primary_name = "Claude" if primary else None
                fallback_name = "Ollama" if fallback else None
            else:
                primary = self.ollama
                fallback = None
                primary_name = "Ollama" if primary else None
                fallback_name = None

        # Try primary LLM
        if primary:
            logger.debug(
                f"Routing {complexity.value} task to {primary_name} "
                f"(prompt length: {len(prompt)} chars)"
            )

            result = await self._generate_with_client(
                primary,
                prompt,
                max_tokens,
                temperature,
                system_prompt,
            )

            if result is not None:
                logger.debug(f"{primary_name} succeeded " f"(response length: {len(result)} chars)")
                return result

            logger.warning(f"{primary_name} failed or unavailable")

        # Try fallback LLM
        if fallback:
            logger.info(f"Falling back to {fallback_name} for {complexity.value} task")

            result = await self._generate_with_client(
                fallback,
                prompt,
                max_tokens,
                temperature,
                system_prompt,
            )

            if result is not None:
                logger.debug(
                    f"{fallback_name} fallback succeeded " f"(response length: {len(result)} chars)"
                )
                return result

            logger.error(f"{fallback_name} fallback also failed")

        # Both failed or no LLMs available
        logger.error(
            f"Cannot process {complexity.value} task - no LLMs available. "
            f"Primary: {primary_name or 'None'}, Fallback: {fallback_name or 'None'}"
        )
        return None

    async def _generate_with_client(
        self,
        client: OllamaClient | ClaudeClient,
        prompt: str,
        max_tokens: int | None,
        temperature: float,
        system_prompt: str | None,
    ) -> str | None:
        """Generate text with specific LLM client.

        Args:
            client: LLM client to use
            prompt: Text prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            system_prompt: Optional system prompt

        Returns:
            Generated text, or None if failed
        """
        try:
            # Adjust temperature for Claude (0.0-1.0) vs Ollama (0.0-2.0)
            if isinstance(client, ClaudeClient):
                # Claude uses 0.0-1.0 range
                adjusted_temp = min(temperature, 1.0)
            else:
                # Ollama uses 0.0-2.0 range
                adjusted_temp = temperature

            # Call generate with appropriate parameters
            if max_tokens is not None:
                result = await client.generate(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=adjusted_temp,
                    system_prompt=system_prompt,
                )
            else:
                # Let client use default max_tokens
                result = await client.generate(
                    prompt=prompt,
                    temperature=adjusted_temp,
                    system_prompt=system_prompt,
                )

            return result

        except Exception as e:
            logger.error(f"Error generating with {type(client).__name__}: {e}", exc_info=True)
            return None

    async def get_available_llms(self) -> list[str]:
        """Get list of currently available LLMs.

        Returns:
            List of available LLM names (e.g., ['Ollama', 'Claude'])

        Example:
            >>> router = LLMRouter(ollama, claude)
            >>> available = await router.get_available_llms()
            >>> print(f"Available: {available}")
            Available: ['Ollama', 'Claude']
        """
        available = []

        # Check Ollama
        if self.ollama:
            try:
                if await self.ollama.is_available():
                    available.append("Ollama")
            except Exception as e:
                logger.debug(f"Ollama availability check failed: {e}")

        # Check Claude (unless local-only mode)
        if self.claude and not self.local_only:
            try:
                if await self.claude.is_available():
                    available.append("Claude")
            except Exception as e:
                logger.debug(f"Claude availability check failed: {e}")

        return available
