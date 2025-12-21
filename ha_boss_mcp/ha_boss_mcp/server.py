"""FastMCP server initialization for HA Boss.

This module creates and configures the MCP server, registers all tools,
and handles server lifecycle.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from ha_boss_mcp.clients.db_reader import DBReader, DBReaderError
from ha_boss_mcp.clients.haboss_api import (
    HABossAPIClient,
    HABossAuthenticationError,
    HABossConnectionError,
)
from ha_boss_mcp.config import MCPConfig, load_config, validate_config
from ha_boss_mcp.tools import healing, monitoring, patterns, service


async def create_server(config: MCPConfig | None = None) -> FastMCP:
    """Create and configure FastMCP server with all HA Boss tools.

    Args:
        config: Optional configuration object. If None, loads from config file.

    Returns:
        Configured FastMCP server instance

    Raises:
        ValueError: If configuration is invalid
        DBReaderError: If database cannot be accessed
        HABossConnectionError: If HA Boss API is unreachable
    """
    # Load configuration if not provided
    if config is None:
        config = load_config()

    # Validate configuration
    validate_config(config)

    # Create FastMCP server instance
    mcp = FastMCP(
        "HA Boss",
        instructions="""
        HA Boss MCP Server provides access to Home Assistant monitoring,
        healing, and pattern analysis capabilities via the Model Context Protocol.

        Available tool categories:
        - Monitoring: Entity states, service status, history
        - Healing: Integration reloads, healing actions, statistics
        - Pattern Analysis: Reliability stats, failure patterns, anomalies
        - Service Management: Health checks, configuration

        All healing operations default to dry-run mode for safety.
        Use with care when executing actual healing actions.
        """,
    )

    # Initialize clients
    print(f"Connecting to HA Boss API at {config.haboss.api_url}...", file=sys.stderr)
    api_client = HABossAPIClient(
        base_url=config.haboss.api_url,
        api_key=config.haboss.api_key,
    )

    # Verify API connection
    try:
        await api_client.get_service_status()
        print("✓ Connected to HA Boss API", file=sys.stderr)
    except HABossConnectionError as e:
        print(f"✗ Failed to connect to HA Boss API: {e}", file=sys.stderr)
        raise
    except HABossAuthenticationError as e:
        print(f"✗ Authentication failed: {e}", file=sys.stderr)
        print("  Check HABOSS_API_KEY environment variable", file=sys.stderr)
        raise

    # Initialize database reader
    print(f"Opening database at {config.haboss.database_path}...", file=sys.stderr)
    try:
        db_reader = DBReader(config.haboss.database_path)
        entity_count = await db_reader.count_entities()
        print(f"✓ Database opened ({entity_count} entities)", file=sys.stderr)
    except DBReaderError as e:
        print(f"✗ Failed to open database: {e}", file=sys.stderr)
        print("  Ensure HA Boss is running and database exists", file=sys.stderr)
        raise

    # Register tools based on enabled categories
    print("Registering MCP tools...", file=sys.stderr)
    tool_count = 0

    if "monitoring" in config.tools.enabled:
        await monitoring.register_tools(mcp, api_client, db_reader)
        print("  ✓ Monitoring tools (4)", file=sys.stderr)
        tool_count += 4

    if "healing" in config.tools.enabled:
        await healing.register_tools(mcp, api_client, db_reader)
        print("  ✓ Healing tools (3)", file=sys.stderr)
        tool_count += 3

    if "patterns" in config.tools.enabled:
        await patterns.register_tools(mcp, api_client, db_reader)
        print("  ✓ Pattern analysis tools (3)", file=sys.stderr)
        tool_count += 3

    if "service" in config.tools.enabled:
        await service.register_tools(mcp, api_client, db_reader)
        print("  ✓ Service management tools (2)", file=sys.stderr)
        tool_count += 2

    print(f"✓ Registered {tool_count} tools", file=sys.stderr)

    return mcp


def main() -> None:
    """Main entry point for HA Boss MCP server.

    Parses command-line arguments, creates server, and starts transport.
    """
    parser = argparse.ArgumentParser(
        description="HA Boss MCP Server - Model Context Protocol interface"
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="MCP transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port for HTTP/SSE transport (default: 8001)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to mcp_config.yaml (default: auto-detect)",
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Override transport from command line if provided
    if args.transport:
        config.mcp.transport = args.transport  # type: ignore
    if args.host:
        config.mcp.host = args.host
    if args.port:
        config.mcp.port = args.port

    # Create server
    try:
        mcp = asyncio.run(create_server(config))
    except Exception as e:
        print(f"Error creating server: {e}", file=sys.stderr)
        sys.exit(1)

    # Start server with configured transport
    print(f"\nStarting HA Boss MCP server ({config.mcp.transport} transport)...", file=sys.stderr)

    if config.mcp.transport == "stdio":
        print("Ready for stdio communication", file=sys.stderr)
        mcp.run(transport="stdio")
    elif config.mcp.transport == "http":
        print(f"Listening on http://{config.mcp.host}:{config.mcp.port}", file=sys.stderr)
        mcp.run(transport="http", host=config.mcp.host, port=config.mcp.port)
    elif config.mcp.transport == "sse":
        print(f"Listening on http://{config.mcp.host}:{config.mcp.port} (SSE)", file=sys.stderr)
        mcp.run(transport="sse", host=config.mcp.host, port=config.mcp.port)


if __name__ == "__main__":
    main()
