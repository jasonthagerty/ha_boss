"""Shared test fixtures for HA Boss MCP server tests."""

import asyncio
from pathlib import Path
from typing import AsyncGenerator

import pytest
from unittest.mock import AsyncMock, MagicMock

from ha_boss_mcp.clients.db_reader import DBReader
from ha_boss_mcp.clients.haboss_api import HABossAPIClient
from ha_boss_mcp.config import MCPConfig, HABossSettings, MCPSettings, AuthSettings, ToolsSettings


@pytest.fixture
def mock_config() -> MCPConfig:
    """Create a mock MCP configuration for testing."""
    return MCPConfig(
        mcp=MCPSettings(transport="stdio", host="localhost", port=8001),
        haboss=HABossSettings(
            api_url="http://localhost:8000",
            api_key=None,
            database_path=":memory:",
        ),
        auth=AuthSettings(enabled=False),
        tools=ToolsSettings(enabled=["monitoring", "healing", "patterns", "service"]),
    )


@pytest.fixture
def mock_api_client() -> AsyncMock:
    """Create a mock HA Boss API client."""
    client = AsyncMock(spec=HABossAPIClient)

    # Mock common API responses
    client.get_service_status.return_value = {
        "status": "running",
        "uptime_seconds": 3600.0,
        "total_entities": 100,
        "total_healing_attempts": 10,
        "successful_healings": 8,
    }

    client.get_health_check.return_value = {
        "overall_status": "healthy",
        "timestamp": "2024-01-01T00:00:00Z",
        "components": [
            {
                "component": "service",
                "status": "healthy",
                "message": "Service operational",
                "tier": 1,
            }
        ],
    }

    client.get_entities.return_value = [
        {
            "entity_id": "sensor.test",
            "domain": "sensor",
            "last_state": "23.5",
            "friendly_name": "Test Sensor",
            "integration_id": "test_integration",
            "last_seen": "2024-01-01T00:00:00Z",
        }
    ]

    return client


@pytest.fixture
def mock_db_reader() -> AsyncMock:
    """Create a mock database reader."""
    reader = AsyncMock(spec=DBReader)

    # Mock common database queries
    reader.get_entity.return_value = {
        "entity_id": "sensor.test",
        "domain": "sensor",
        "last_state": "23.5",
        "friendly_name": "Test Sensor",
        "integration_id": "test_integration",
        "last_seen": "2024-01-01T00:00:00Z",
        "is_monitored": True,
    }

    reader.list_entities.return_value = [
        {
            "entity_id": "sensor.test1",
            "domain": "sensor",
            "last_state": "10.0",
            "friendly_name": "Test Sensor 1",
            "integration_id": "test_integration",
            "last_seen": "2024-01-01T00:00:00Z",
            "is_monitored": True,
        },
        {
            "entity_id": "sensor.test2",
            "domain": "sensor",
            "last_state": "20.0",
            "friendly_name": "Test Sensor 2",
            "integration_id": "test_integration",
            "last_seen": "2024-01-01T00:00:00Z",
            "is_monitored": True,
        },
    ]

    reader.count_entities.return_value = 100

    reader.get_healing_stats.return_value = {
        "total_attempts": 10,
        "successful_attempts": 8,
        "failed_attempts": 2,
        "success_rate": 80.0,
        "days": 7,
    }

    return reader


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
