"""FastAPI application factory and configuration."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ha_boss.core.config import load_config
from ha_boss.service.main import HABossService

# Load environment variables from .env file
load_dotenv()

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
        config = load_config()

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

Optional API key authentication can be enabled via configuration:
- Set `api.auth_enabled=true` in config.yaml
- Provide API keys in `api.api_keys` list
- Send requests with `X-API-Key` header

When disabled (default), no authentication is required. Only enable on
trusted networks or with HTTPS.

### CORS

Cross-Origin Resource Sharing (CORS) is configurable:
- Enable/disable via `api.cors_enabled` (default: enabled)
- Configure allowed origins via `api.cors_origins` (default: all)
- Restrict origins in production for security

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

    # CORS middleware - configurable via settings
    config = load_config()
    if config.api.cors_enabled:
        logger.info(f"CORS enabled with origins: {config.api.cors_origins}")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        logger.info("CORS disabled")

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

    # Register routes with optional authentication
    from ha_boss.api.dependencies import verify_api_key
    from ha_boss.api.routes import (
        automations,
        discovery,
        healing,
        monitoring,
        patterns,
        plans,
        status,
        websocket,
    )
    from ha_boss.api.routes import (
        config as config_routes,
    )

    # Add authentication dependency if enabled
    dependencies = []
    if config.api.auth_enabled:
        from fastapi import Depends

        dependencies = [Depends(verify_api_key)]
        logger.info("API authentication enabled")
    else:
        logger.info("API authentication disabled")

    app.include_router(status.router, prefix="/api", tags=["Status"], dependencies=dependencies)
    app.include_router(
        monitoring.router, prefix="/api", tags=["Monitoring"], dependencies=dependencies
    )
    app.include_router(
        patterns.router, prefix="/api", tags=["Pattern Analysis"], dependencies=dependencies
    )
    app.include_router(
        automations.router, prefix="/api", tags=["Automations"], dependencies=dependencies
    )
    app.include_router(healing.router, prefix="/api", tags=["Healing"], dependencies=dependencies)
    app.include_router(
        plans.router, prefix="/api", tags=["Healing Plans"], dependencies=dependencies
    )
    app.include_router(
        discovery.router, prefix="/api", tags=["Discovery"], dependencies=dependencies
    )
    app.include_router(
        config_routes.router, prefix="/api", tags=["Configuration"], dependencies=dependencies
    )

    # WebSocket endpoint (no auth - same-origin only)
    app.include_router(websocket.router, prefix="/api", tags=["WebSocket"])
    logger.info("WebSocket endpoint available at: ws://localhost:8000/api/ws")

    # Static file serving for dashboard
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info(f"Serving static files from: {static_dir}")

        @app.get("/dashboard", include_in_schema=False)
        async def dashboard() -> FileResponse:
            """Serve the API dashboard."""
            dashboard_file = static_dir / "index.html"
            if dashboard_file.exists():
                return FileResponse(dashboard_file)
            raise HTTPException(status_code=404, detail="Dashboard not found")

        logger.info("Dashboard available at: http://localhost:8000/dashboard")
    else:
        logger.warning("Static files directory not found, dashboard unavailable")

    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Root endpoint with links to docs and dashboard."""
        response = {
            "message": "HA Boss API",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        }

        # Include dashboard link if static files exist
        if static_dir.exists():
            response["dashboard"] = "/dashboard"

        return response

    return app
