"""Enhanced notification generator with LLM-powered context."""

import logging
from datetime import datetime
from typing import Any

from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)

# Performance target: < 2s for notification generation
DEFAULT_MAX_TOKENS = 256
DEFAULT_TIMEOUT_SECONDS = 2.0


class EnhancedNotificationGenerator:
    """Generate AI-enhanced context for notifications.

    Uses local LLM (via LLMRouter) to generate helpful analysis and
    remediation suggestions for failure notifications.
    """

    def __init__(self, llm_router: LLMRouter) -> None:
        """Initialize enhanced notification generator.

        Args:
            llm_router: LLM router for AI generation
        """
        self.llm_router = llm_router

    async def generate_failure_analysis(
        self,
        entity_id: str,
        issue_type: str,
        error: str,
        attempts: int,
        healing_stats: dict[str, Any] | None = None,
        integration_info: dict[str, Any] | None = None,
    ) -> dict[str, str] | None:
        """Generate AI analysis for a healing failure.

        Args:
            entity_id: Entity that failed healing
            issue_type: Type of issue (unavailable, stale, etc.)
            error: Error message from healing attempt
            attempts: Number of healing attempts made
            healing_stats: Historical healing statistics for this entity
            integration_info: Integration details (domain, title, etc.)

        Returns:
            Dict with 'analysis' and 'suggestions' keys, or None if generation fails

        Example:
            >>> generator = EnhancedNotificationGenerator(llm_router)
            >>> result = await generator.generate_failure_analysis(
            ...     entity_id="sensor.outdoor_temp",
            ...     issue_type="unavailable",
            ...     error="Integration reload failed: timeout",
            ...     attempts=3,
            ...     healing_stats={"success_rate": 45.0, "total_attempts": 20},
            ...     integration_info={"domain": "met", "title": "Met.no"}
            ... )
            >>> if result:
            ...     print(result["analysis"])
            ...     print(result["suggestions"])
        """
        try:
            # Build context for LLM prompt
            prompt = self._build_failure_prompt(
                entity_id=entity_id,
                issue_type=issue_type,
                error=error,
                attempts=attempts,
                healing_stats=healing_stats,
                integration_info=integration_info,
            )

            # Use SIMPLE complexity for quick response (local LLM only)
            # This ensures we meet the < 2s performance requirement
            response = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.SIMPLE,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.3,  # Lower temperature for more consistent output
                system_prompt=self._get_system_prompt(),
            )

            if response is None:
                logger.debug("LLM returned no response for failure analysis")
                return None

            # Parse response into analysis and suggestions
            return self._parse_response(response)

        except Exception as e:
            logger.warning(f"Failed to generate AI analysis: {e}")
            return None

    def _build_failure_prompt(
        self,
        entity_id: str,
        issue_type: str,
        error: str,
        attempts: int,
        healing_stats: dict[str, Any] | None,
        integration_info: dict[str, Any] | None,
    ) -> str:
        """Build prompt for failure analysis.

        Args:
            entity_id: Entity that failed
            issue_type: Type of issue
            error: Error message
            attempts: Number of attempts
            healing_stats: Historical stats
            integration_info: Integration details

        Returns:
            Formatted prompt string
        """
        parts = [
            f"Entity: {entity_id}",
            f"Issue: {issue_type}",
            f"Error: {error}",
            f"Healing attempts: {attempts}",
        ]

        # Add integration context if available
        if integration_info:
            domain = integration_info.get("domain", "unknown")
            title = integration_info.get("title", domain)
            parts.append(f"Integration: {title} ({domain})")

        # Add historical context if available
        if healing_stats:
            success_rate = healing_stats.get("success_rate", 0)
            total_attempts = healing_stats.get("total_attempts", 0)
            if total_attempts > 0:
                parts.append(f"Historical success rate: {success_rate:.0f}%")
                parts.append(f"Total healing attempts: {total_attempts}")

        prompt = "\n".join(parts)
        prompt += "\n\nProvide a brief analysis of why this might be failing and 2-3 actionable suggestions."

        return prompt

    def _get_system_prompt(self) -> str:
        """Get system prompt for failure analysis.

        Returns:
            System prompt string
        """
        return """You are a Home Assistant expert assistant. Analyze the healing failure and provide:

1. ANALYSIS: A brief (2-3 sentences) explanation of the likely cause based on the error and context.

2. SUGGESTIONS: 2-3 specific, actionable steps the user can take to resolve the issue.

Format your response as:
ANALYSIS:
[Your analysis here]

SUGGESTIONS:
1. [First suggestion]
2. [Second suggestion]
3. [Third suggestion if needed]

Be concise and practical. Focus on the most likely causes and solutions."""

    def _parse_response(self, response: str) -> dict[str, str]:
        """Parse LLM response into structured format.

        Args:
            response: Raw LLM response

        Returns:
            Dict with 'analysis' and 'suggestions' keys
        """
        analysis = ""
        suggestions = ""

        # Try to parse structured response
        response_upper = response.upper()

        if "ANALYSIS:" in response_upper and "SUGGESTIONS:" in response_upper:
            # Find the sections
            analysis_start = response_upper.find("ANALYSIS:")
            suggestions_start = response_upper.find("SUGGESTIONS:")

            if analysis_start < suggestions_start:
                # Extract analysis (between ANALYSIS: and SUGGESTIONS:)
                analysis_content = response[analysis_start + 9 : suggestions_start]
                analysis = analysis_content.strip()

                # Extract suggestions (after SUGGESTIONS:)
                suggestions_content = response[suggestions_start + 12 :]
                suggestions = suggestions_content.strip()
            else:
                # Unexpected order, use full response as analysis
                analysis = response.strip()
        else:
            # No clear structure, use full response as analysis
            analysis = response.strip()

        return {
            "analysis": analysis,
            "suggestions": suggestions,
        }

    async def generate_circuit_breaker_analysis(
        self,
        integration_name: str,
        failure_count: int,
        reset_time: datetime,
        healing_stats: dict[str, Any] | None = None,
    ) -> dict[str, str] | None:
        """Generate AI analysis for circuit breaker opening.

        Args:
            integration_name: Integration that triggered circuit breaker
            failure_count: Number of consecutive failures
            reset_time: When circuit breaker will reset
            healing_stats: Historical healing statistics

        Returns:
            Dict with 'analysis' and 'suggestions' keys, or None if generation fails
        """
        try:
            time_until_reset = reset_time - datetime.now()
            minutes_until = max(0, int(time_until_reset.total_seconds() / 60))

            parts = [
                f"Integration: {integration_name}",
                f"Consecutive failures: {failure_count}",
                f"Circuit breaker reset in: {minutes_until} minutes",
            ]

            if healing_stats:
                success_rate = healing_stats.get("success_rate", 0)
                total_attempts = healing_stats.get("total_attempts", 0)
                if total_attempts > 0:
                    parts.append(f"Historical success rate: {success_rate:.0f}%")

            prompt = "\n".join(parts)
            prompt += "\n\nThe circuit breaker has opened due to repeated failures. "
            prompt += "Explain what this means and provide suggestions for investigation."

            response = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.SIMPLE,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.3,
                system_prompt=self._get_system_prompt(),
            )

            if response is None:
                return None

            return self._parse_response(response)

        except Exception as e:
            logger.warning(f"Failed to generate circuit breaker analysis: {e}")
            return None
