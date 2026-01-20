"""HTTP client for HA Boss REST API."""

from typing import Any

import httpx


class HABossAPIError(Exception):
    """Base exception for HA Boss API errors."""

    pass


class HABossConnectionError(HABossAPIError):
    """Raised when connection to HA Boss API fails."""

    pass


class HABossAuthenticationError(HABossAPIError):
    """Raised when API key authentication fails."""

    pass


class HABossAPIClient:
    """Async HTTP client for HA Boss REST API.

    Provides methods to interact with HA Boss monitoring, healing,
    pattern analysis, and service management endpoints.

    Attributes:
        base_url: HA Boss API base URL (e.g., "http://haboss:8000")
        api_key: Optional API key for authentication
        client: Async httpx client instance
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize HA Boss API client.

        Args:
            base_url: HA Boss API base URL
            api_key: Optional API key for X-API-Key header
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        # Set up headers
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key

        # Create async client
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close the HTTP client connection."""
        await self.client.aclose()

    async def __aenter__(self) -> "HABossAPIClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an HTTP request to the HA Boss API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx request

        Returns:
            Response JSON data

        Raises:
            HABossConnectionError: If connection fails
            HABossAuthenticationError: If authentication fails (401/403)
            HABossAPIError: For other API errors
        """
        try:
            response = await self.client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise HABossConnectionError(
                f"Failed to connect to HA Boss at {self.base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise HABossAuthenticationError(
                    f"Authentication failed: {e.response.status_code}"
                ) from e
            raise HABossAPIError(
                f"API request failed: {e.response.status_code} - {e.response.text}"
            ) from e
        except httpx.TimeoutException as e:
            raise HABossConnectionError(f"Request timeout after {self.timeout}s") from e
        except Exception as e:
            raise HABossAPIError(f"Unexpected error: {e}") from e

    # Service Status & Health
    async def get_service_status(self) -> dict[str, Any]:
        """Get HA Boss service status and uptime.

        Returns:
            Service status including uptime, health, and statistics
        """
        return await self._request("GET", "/api/status")

    async def get_health_check(self) -> dict[str, Any]:
        """Get comprehensive health check (22 components across 5 tiers).

        Returns:
            Health status for all components with tier breakdown
        """
        return await self._request("GET", "/api/health")

    # Entity Monitoring
    async def get_entities(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get list of monitored entities.

        Args:
            limit: Maximum entities to return (1-1000)
            offset: Pagination offset

        Returns:
            List of entities with states and metadata
        """
        response = await self._request(
            "GET", "/api/entities", params={"limit": limit, "offset": offset}
        )
        return response.get("entities", [])

    async def get_entity_state(self, entity_id: str) -> dict[str, Any]:
        """Get current state for a specific entity.

        Args:
            entity_id: Entity ID (e.g., "sensor.temperature")

        Returns:
            Entity state with attributes and timestamps
        """
        return await self._request("GET", f"/api/entities/{entity_id}")

    async def get_entity_history(self, entity_id: str, hours: int = 24) -> list[dict[str, Any]]:
        """Get state change history for an entity.

        Args:
            entity_id: Entity ID
            hours: Hours of history to retrieve (1-168)

        Returns:
            List of state changes with timestamps
        """
        response = await self._request(
            "GET", f"/api/entities/{entity_id}/history", params={"hours": hours}
        )
        return response.get("history", [])

    # Healing Operations
    async def trigger_healing(self, entity_id: str, dry_run: bool = True) -> dict[str, Any]:
        """Trigger healing for an entity (reloads associated integration).

        Args:
            entity_id: Entity ID to heal
            dry_run: Test without executing (default: True)

        Returns:
            Healing action result with success status
        """
        return await self._request(
            "POST",
            f"/api/healing/{entity_id}",
            json={"dry_run": dry_run},
        )

    async def get_healing_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent healing actions.

        Args:
            limit: Maximum actions to return

        Returns:
            List of healing actions with results
        """
        response = await self._request("GET", "/api/healing/history", params={"limit": limit})
        return response.get("actions", [])

    # Pattern Analysis
    async def get_reliability_stats(
        self, integration_domain: str | None = None, days: int = 7
    ) -> dict[str, Any]:
        """Get integration reliability statistics.

        Args:
            integration_domain: Optional domain filter (e.g., "hue")
            days: Days of data to analyze (1-90)

        Returns:
            Reliability metrics and failure counts
        """
        params = {"days": days}
        if integration_domain:
            params["integration"] = integration_domain
        return await self._request("GET", "/api/patterns/reliability", params=params)

    async def get_failure_patterns(
        self, integration_domain: str | None = None, days: int = 7, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get failure event timeline.

        Args:
            integration_domain: Optional domain filter
            days: Days of events to retrieve
            limit: Maximum events to return

        Returns:
            List of failure events with timestamps and resolution status
        """
        params = {"days": days, "limit": limit}
        if integration_domain:
            params["integration"] = integration_domain
        response = await self._request("GET", "/api/patterns/failures", params=params)
        return response.get("failures", [])

    async def get_weekly_summary(self, include_ai_insights: bool = False) -> dict[str, Any]:
        """Get weekly pattern summary.

        Args:
            include_ai_insights: Include AI-generated insights

        Returns:
            Weekly summary with aggregated statistics and optional AI analysis
        """
        params = {"ai_insights": include_ai_insights}
        return await self._request("GET", "/api/patterns/summary", params=params)

    # Automation Analysis
    async def analyze_automation(
        self,
        automation_id: str,
        include_ai: bool = True,
        include_usage: bool = False,
        days: int = 30,
        instance_id: str = "default",
    ) -> dict[str, Any]:
        """Analyze automation for optimization suggestions.

        Args:
            automation_id: Automation ID from Home Assistant
            include_ai: Include AI-powered suggestions
            include_usage: Include usage-based analysis from execution history
            days: Days of usage data to analyze (1-90)
            instance_id: Home Assistant instance identifier

        Returns:
            Analysis with suggestions, complexity score, and optional usage statistics
        """
        return await self._request(
            "POST",
            "/api/automations/analyze",
            json={"automation_id": automation_id},
            params={
                "include_ai": include_ai,
                "include_usage": include_usage,
                "days": days,
                "instance_id": instance_id,
            },
        )

    async def list_automations(self, instance_id: str = "default") -> list[dict[str, Any]]:
        """List all automations from Home Assistant.

        Args:
            instance_id: Home Assistant instance identifier

        Returns:
            List of automation entities with states and attributes
        """
        response = await self._request(
            "GET",
            "/api/automations",
            params={"instance_id": instance_id},
        )
        return response.get("automations", [])
