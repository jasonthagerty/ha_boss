"""FastAPI dependencies for request validation and authentication."""

import logging
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ha_boss.api.app import get_service

logger = logging.getLogger(__name__)

# API Key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)] = None,
) -> None:
    """Verify API key if authentication is enabled.

    Args:
        api_key: API key from X-API-Key header

    Raises:
        HTTPException: 401 if auth is enabled and key is invalid
    """
    try:
        service = get_service()

        # Skip auth if not enabled
        if not service.config.api.auth_enabled:
            return

        # Check if API key is provided
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Provide X-API-Key header.",
            ) from None

        # Validate API key
        if api_key not in service.config.api.api_keys:
            logger.warning(f"Invalid API key attempt: {api_key[:8]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            ) from None

        logger.debug(f"API key validated: {api_key[:8]}...")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying API key: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error",
        ) from e


async def require_https(request: any) -> None:
    """Require HTTPS if configured.

    Args:
        request: FastAPI request object

    Raises:
        HTTPException: 403 if HTTPS is required but not used
    """
    try:
        service = get_service()

        # Skip check if not required
        if not service.config.api.require_https:
            return

        # Check if request is HTTPS
        if request.url.scheme != "https":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="HTTPS required for API access",
            ) from None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking HTTPS requirement: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Security check error",
        ) from e
