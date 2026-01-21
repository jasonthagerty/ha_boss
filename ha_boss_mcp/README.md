# HA Boss MCP Server

Model Context Protocol server for HA Boss - enables AI agents to monitor and manage Home Assistant instances through 17 specialized tools.

## Features

- **Monitoring**: Query entity states, service status, and health information
- **Healing**: Trigger integration reloads and view healing history
- **Pattern Analysis**: Access reliability statistics and failure patterns
- **Service Management**: Health checks and configuration access
- **Automations**: Analyze automations and track execution history

## Installation

```bash
cd ha_boss_mcp
pip install -e ".[dev]"
```

## Usage

### Local Development (stdio transport)

```bash
ha-boss-mcp
```

### Docker Deployment

See main HA Boss repository for Docker deployment instructions.

## Tool Categories

### Monitoring (4 tools)
- `get_service_status` - Service state and uptime
- `list_entities` - All monitored entities
- `get_entity_state` - Single entity details
- `get_entity_history` - State change history

### Healing (3 tools)
- `trigger_healing` - Manually heal entity
- `get_healing_history` - Recent healing actions
- `get_healing_stats` - Success/failure metrics

### Pattern Analysis (3 tools)
- `get_reliability_stats` - Integration reliability
- `get_failure_patterns` - Temporal failure analysis
- `get_anomalies` - Recent anomalies

### Service Management (2 tools)
- `health_check` - Comprehensive health status
- `get_config` - Current configuration (sanitized)

### Automations (5 tools)
- `analyze_automation` - AI-powered automation analysis with suggestions
- `get_automation_executions` - Execution history with trigger and duration info
- `get_automation_service_calls` - Service calls made by automations
- `get_automation_usage_stats` - Aggregated statistics (execution count, failure rate, etc.)
- `list_automations` - List all automations with current state

## Configuration

Create `config/mcp_config.yaml`:

```yaml
mcp:
  transport: stdio

haboss:
  api_url: http://haboss:8000
  database_path: /app/data/ha_boss.db
```

## Development

```bash
# Run tests
pytest

# Type checking
mypy ha_boss_mcp

# Formatting
black .
ruff check --fix .
```

## License

MIT - See LICENSE file in main HA Boss repository
