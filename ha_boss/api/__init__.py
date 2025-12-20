"""REST API for HA Boss.

This module provides a FastAPI-based REST API for dashboard and UI integration.
The API provides endpoints for:
- Service status and health monitoring
- Entity state monitoring and history
- Pattern analysis and reliability statistics
- Automation management (analyze, generate, create)
- Manual healing triggers

The API is self-documenting with OpenAPI/Swagger documentation available at:
- /docs - Interactive Swagger UI
- /redoc - ReDoc documentation
- /openapi.json - OpenAPI schema
"""

from ha_boss.api.app import create_app

__all__ = ["create_app"]
