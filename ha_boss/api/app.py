"""FastAPI application factory and configuration."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ha_boss.core.config import Config
from ha_boss.service.main import HABossService

logger = logging.getLogger(__name__)

# Global service instance (set by lifespan)
_service: HABossService | None = None


def get_service() -> HABossService:
    """Get the global HA Boss service instance.

    Returns:
        HA Boss service instance

    Raises:
        RuntimeError: Service not initialized
    """
    if _service is None:
        raise RuntimeError("HA Boss service not initialized")
    return _service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager.

    Initializes and starts the HA Boss service on startup,
    and gracefully shuts it down on exit.

    Args:
        app: FastAPI application instance

    Yields:
        None
    """
    global _service

    # Startup
    logger.info("Starting HA Boss API server...")

    try:
        # Load configuration
        config = Config.load()

        # Create and start service
        _service = HABossService(config)
        await _service.start()

        logger.info("✓ HA Boss service started successfully")
        logger.info("API docs available at: http://localhost:8000/docs")

        yield

    finally:
        # Shutdown
        logger.info("Shutting down HA Boss API server...")
        if _service:
            await _service.stop()
            _service = None
        logger.info("✓ HA Boss service stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="HA Boss API",
        description="""
## HA Boss REST API

A RESTful API for monitoring, managing, and analyzing Home Assistant instances.

### Features

- **Status Monitoring** - Real-time service status, uptime, and statistics
- **Entity Monitoring** - Track entity states and history
- **Pattern Analysis** - Integration reliability and failure analysis
- **Automation Management** - Analyze and generate automations with AI
- **Manual Healing** - Trigger integration reloads on demand

### Authentication

**Note:** Authentication is not yet implemented. This API is intended for
internal network use only. Do not expose to the public internet.

### Rate Limiting

No rate limiting is currently enforced. Use responsibly.

### Getting Started

1. Explore the interactive documentation below
2. Try the `/api/status` endpoint to verify the service is running
3. Use `/api/entities` to see monitored entities
4. Check `/api/patterns/reliability` for integration health

For more information, visit the [HA Boss documentation](https://github.com/jasonthagerty/ha_boss/wiki).
        """,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware - allow all origins for development
    # TODO: Restrict origins in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Any, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions.

        Args:
            request: FastAPI request
            exc: Exception that was raised

        Returns:
            JSON error response
        """
        logger.error(f"Unexpected error handling {request.url}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc),
            },
        )

    # Register routes
    from ha_boss.api.routes import automations, healing, monitoring, patterns, status

    app.include_router(status.router, prefix="/api", tags=["Status"])
    app.include_router(monitoring.router, prefix="/api", tags=["Monitoring"])
    app.include_router(patterns.router, prefix="/api", tags=["Pattern Analysis"])
    app.include_router(automations.router, prefix="/api", tags=["Automations"])
    app.include_router(healing.router, prefix="/api", tags=["Healing"])

    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Root endpoint - redirect to docs."""
        return {
            "message": "HA Boss API",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        }

    return app
