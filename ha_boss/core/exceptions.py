"""Custom exceptions for HA Boss."""


class HABossError(Exception):
    """Base exception for all HA Boss errors."""

    pass


class ConfigurationError(HABossError):
    """Configuration validation or loading error."""

    pass


class HomeAssistantError(HABossError):
    """Base exception for Home Assistant related errors."""

    pass


class HomeAssistantConnectionError(HomeAssistantError):
    """Failed to connect to Home Assistant."""

    pass


class HomeAssistantAuthError(HomeAssistantError):
    """Home Assistant authentication failed."""

    pass


class HomeAssistantAPIError(HomeAssistantError):
    """Home Assistant API returned an error."""

    pass


class HealingError(HABossError):
    """Base exception for healing related errors."""

    pass


class IntegrationNotFoundError(HealingError):
    """Integration not found or cannot be discovered."""

    pass


class IntegrationDiscoveryError(HealingError):
    """Failed to discover integrations through all available methods."""

    pass


class HealingFailedError(HealingError):
    """Healing attempt failed."""

    pass


class CircuitBreakerOpenError(HealingError):
    """Circuit breaker is open, refusing to attempt healing."""

    pass


class HealingPlanError(HealingError):
    """Base exception for healing plan errors."""

    pass


class HealingPlanNotFoundError(HealingPlanError):
    """Healing plan not found."""

    pass


class HealingPlanValidationError(HealingPlanError):
    """Healing plan validation failed."""

    pass


class HealingPlanExecutionError(HealingPlanError):
    """Healing plan execution failed."""

    pass


class DatabaseError(HABossError):
    """Database operation error."""

    pass


class ConfigServiceError(HABossError):
    """Configuration service operation error."""

    pass
