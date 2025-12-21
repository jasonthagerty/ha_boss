"""Tests for monitoring MCP tools."""

import pytest
from fastmcp import FastMCP
from unittest.mock import AsyncMock

from ha_boss_mcp.tools import monitoring
from ha_boss_mcp.models import EntityState, ServiceStatus


@pytest.mark.asyncio
async def test_get_service_status(mock_api_client: AsyncMock, mock_db_reader: AsyncMock) -> None:
    """Test get_service_status tool."""
    # Create MCP instance and register tools
    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    # Get the tool function
    tool_func = None
    for tool in mcp.tools:
        if tool.name == "get_service_status":
            tool_func = tool.fn
            break

    assert tool_func is not None, "get_service_status tool not found"

    # Call the tool
    result = await tool_func()

    # Verify result type and values
    assert isinstance(result, ServiceStatus)
    assert result.status == "running"
    assert result.uptime_seconds == 3600.0
    assert result.total_entities == 100
    assert result.total_healing_attempts == 10
    assert result.successful_healings == 8

    # Verify API client was called
    mock_api_client.get_service_status.assert_called_once()


@pytest.mark.asyncio
async def test_list_entities(mock_api_client: AsyncMock, mock_db_reader: AsyncMock) -> None:
    """Test list_entities tool."""
    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    # Get the tool function
    tool_func = None
    for tool in mcp.tools:
        if tool.name == "list_entities":
            tool_func = tool.fn
            break

    assert tool_func is not None, "list_entities tool not found"

    # Call with default parameters
    result = await tool_func()

    # Verify result
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(entity, EntityState) for entity in result)
    assert result[0].entity_id == "sensor.test1"
    assert result[1].entity_id == "sensor.test2"

    # Verify DB reader was called
    mock_db_reader.list_entities.assert_called_once_with(
        limit=100, offset=0, monitored_only=True
    )


@pytest.mark.asyncio
async def test_list_entities_with_pagination(
    mock_api_client: AsyncMock, mock_db_reader: AsyncMock
) -> None:
    """Test list_entities tool with custom pagination."""
    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    tool_func = None
    for tool in mcp.tools:
        if tool.name == "list_entities":
            tool_func = tool.fn
            break

    assert tool_func is not None

    # Call with custom parameters
    result = await tool_func(limit=50, offset=10)

    # Verify DB reader was called with correct parameters
    mock_db_reader.list_entities.assert_called_once_with(
        limit=50, offset=10, monitored_only=True
    )


@pytest.mark.asyncio
async def test_get_entity_state(mock_api_client: AsyncMock, mock_db_reader: AsyncMock) -> None:
    """Test get_entity_state tool."""
    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    tool_func = None
    for tool in mcp.tools:
        if tool.name == "get_entity_state":
            tool_func = tool.fn
            break

    assert tool_func is not None, "get_entity_state tool not found"

    # Call the tool
    result = await tool_func("sensor.test")

    # Verify result
    assert isinstance(result, EntityState)
    assert result.entity_id == "sensor.test"
    assert result.domain == "sensor"
    assert result.state == "23.5"
    assert result.friendly_name == "Test Sensor"

    # Verify DB reader was called
    mock_db_reader.get_entity.assert_called_once_with("sensor.test")


@pytest.mark.asyncio
async def test_get_entity_state_not_found(
    mock_api_client: AsyncMock, mock_db_reader: AsyncMock
) -> None:
    """Test get_entity_state tool with non-existent entity."""
    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    # Configure mock to return None (entity not found)
    mock_db_reader.get_entity.return_value = None

    tool_func = None
    for tool in mcp.tools:
        if tool.name == "get_entity_state":
            tool_func = tool.fn
            break

    assert tool_func is not None

    # Call should raise ValueError
    with pytest.raises(ValueError, match="Entity 'sensor.nonexistent' not found"):
        await tool_func("sensor.nonexistent")


@pytest.mark.asyncio
async def test_get_entity_history(mock_api_client: AsyncMock, mock_db_reader: AsyncMock) -> None:
    """Test get_entity_history tool."""
    # Configure mock to return history data
    mock_db_reader.get_entity_history.return_value = [
        {
            "old_state": "20.0",
            "new_state": "23.5",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        {
            "old_state": "23.5",
            "new_state": "25.0",
            "timestamp": "2024-01-01T01:00:00Z",
        },
    ]

    mcp = FastMCP("Test")
    await monitoring.register_tools(mcp, mock_api_client, mock_db_reader)

    tool_func = None
    for tool in mcp.tools:
        if tool.name == "get_entity_history":
            tool_func = tool.fn
            break

    assert tool_func is not None, "get_entity_history tool not found"

    # Call the tool
    result = await tool_func("sensor.test", hours=24)

    # Verify result
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].old_state == "20.0"
    assert result[0].new_state == "23.5"
    assert result[1].new_state == "25.0"

    # Verify DB reader was called
    mock_db_reader.get_entity_history.assert_called_once_with(
        "sensor.test", hours=24, limit=1000
    )
