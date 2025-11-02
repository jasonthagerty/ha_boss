# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HA Boss is a standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and uses AI to generate and optimize automations. The project follows an MVP-first approach, starting with reliable monitoring and auto-healing, then adding intelligence features incrementally.

### Core Capabilities

**Phase 1 (MVP - Current Focus)**:
- Real-time monitoring of Home Assistant entities via WebSocket
- Automatic detection of unavailable/stale entities
- Auto-healing via integration reload with safety mechanisms
- Escalated notifications when auto-healing fails
- Docker-first deployment

**Phase 2 (Intelligence Layer)**:
- Local LLM integration (Ollama) for enhanced notifications
- Usage pattern collection and analysis
- Weekly summary reports

**Phase 3 (Advanced Features)**:
- Pattern-based anomaly detection
- Automation optimization suggestions
- Claude API integration for complex automation generation

### Design Philosophy

1. **Start Simple**: MVP focuses on monitoring + healing without AI complexity
2. **Safety First**: Dry-run mode, circuit breakers, rollback capability
3. **Fail Gracefully**: Escalate to user when auto-heal fails rather than stay silent
4. **Learn Over Time**: Collect patterns to improve effectiveness
5. **Hybrid AI**: Local LLM for routine tasks, Claude for complex reasoning

## Development Commands

### Initial Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests with coverage
pytest --cov=ha_boss --cov-report=html --cov-report=term

# Run specific test file
pytest tests/test_example.py -v

# Run tests matching pattern
pytest -k "test_async" -v

# Run with specific markers
pytest -m "not slow" -v
```

### Code Quality

```bash
# Auto-format code (do this before committing)
black .

# Lint and auto-fix issues
ruff check --fix .

# Type checking
mypy ha_boss

# Complete CI check (run before pushing)
black --check . && ruff check . && mypy ha_boss && pytest
```

### Slash Commands

The project includes custom slash commands in `.claude/commands/`:
- `/test` - Run full test suite with coverage
- `/test-file [path]` - Run tests for specific file
- `/lint` - Run all code quality checks
- `/fix-style` - Auto-fix formatting and style issues
- `/ci-check` - Run complete CI pipeline locally
- `/setup-dev` - Guide through development environment setup
- `/review-pr [number]` - Review a pull request
- `/add-test [module]` - Generate tests for a module

## Architecture

### Project Structure

```
ha_boss/
├── ha_boss/                    # Main package code
│   ├── core/                   # Core infrastructure
│   │   ├── config.py          # Pydantic configuration models
│   │   ├── ha_client.py       # Home Assistant API wrapper
│   │   ├── database.py        # SQLAlchemy models and DB management
│   │   └── llm_router.py      # LLM task routing (Phase 2+)
│   ├── monitoring/             # Entity monitoring
│   │   ├── state_tracker.py   # Track entity states
│   │   ├── health_monitor.py  # Health checks and anomaly detection
│   │   ├── websocket_client.py # WebSocket connection manager
│   │   └── anomaly_detector.py # LLM-powered anomaly detection (Phase 2+)
│   ├── healing/                # Auto-healing system
│   │   ├── integration_manager.py  # Integration discovery and reload
│   │   ├── heal_strategies.py      # Healing strategies and logic
│   │   └── escalation.py           # Notification escalation
│   ├── intelligence/           # AI features (Phase 2+)
│   │   ├── local_llm.py       # Ollama client
│   │   ├── claude_client.py   # Claude API client
│   │   ├── pattern_analyzer.py # Usage pattern analysis
│   │   └── optimization_engine.py # Automation optimization
│   ├── automation/             # Automation management (Phase 3+)
│   │   ├── manager.py         # Automation CRUD operations
│   │   ├── generator.py       # AI automation generation
│   │   └── optimizer.py       # Pattern-based optimization
│   ├── notifications/          # Notification system
│   │   ├── manager.py         # Notification routing
│   │   └── templates.py       # Message templates
│   ├── api/                   # REST API (Phase 2+)
│   │   └── routes.py          # FastAPI routes
│   └── cli/                   # Command-line interface
│       └── commands.py        # CLI commands (Typer)
├── tests/                     # Test suite
│   ├── core/                  # Core component tests
│   ├── monitoring/            # Monitoring tests
│   ├── healing/               # Healing tests
│   └── fixtures/              # Shared pytest fixtures
├── config/                    # Configuration directory
│   ├── config.yaml.example   # Example configuration
│   └── .env.example          # Environment variables
├── data/                      # Runtime data (created by Docker)
│   └── ha_boss.db            # SQLite database
├── .claude/                   # Claude Code configuration
├── .github/                   # GitHub configuration
├── Dockerfile                 # Docker image
├── docker-compose.yml         # Docker Compose config
└── pyproject.toml            # Project metadata
```

### Key Design Patterns

**Async-First Architecture**:
- All I/O operations use `async`/`await`
- WebSocket connections maintained with asyncio
- Concurrent operations with `asyncio.gather()`
- Background tasks with `asyncio.create_task()`

**Safety Mechanisms**:
- **Circuit Breakers**: Stop retrying after threshold failures
- **Cooldowns**: Prevent rapid retry loops
- **Dry-Run Mode**: Test changes without executing
- **Graceful Degradation**: Continue operating with reduced functionality

**Error Handling Strategy**:
```python
# Use specific exceptions with exponential backoff
async def call_ha_api_with_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0
) -> Any:
    for attempt in range(max_attempts):
        try:
            return await func()
        except HomeAssistantConnectionError as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
```

**Database Design**:
- SQLAlchemy async with aiosqlite
- Models defined with type hints
- Migrations via Alembic (future)
- Separate tables for: entities, health_events, healing_actions, integrations

### Component Interactions

```
┌─────────────────────────────────────────┐
│         HA Boss Service (MVP)            │
├─────────────────────────────────────────┤
│                                          │
│  ┌──────────────┐    ┌──────────────┐  │
│  │ WebSocket    │    │ REST API     │  │
│  │ Monitor      │───▶│ Client       │  │
│  │              │    │              │  │
│  │ - Subscribe  │    │ - Services   │  │
│  │ - Reconnect  │    │ - Reload     │  │
│  │ - Heartbeat  │    │ - Snapshots  │  │
│  └──────┬───────┘    └──────┬───────┘  │
│         │                   │           │
│         │  State Changes    │           │
│         ├──────────┬────────┤           │
│         │          │        │           │
│  ┌──────▼──┐  ┌───▼────┐  ┌▼────────┐ │
│  │ State   │  │ Health │  │ Healing │ │
│  │ Tracker │─▶│ Monitor│─▶│ Manager │ │
│  │         │  │        │  │         │ │
│  │ Cache   │  │ Detect │  │ Reload  │ │
│  │ History │  │ Issues │  │ Escalate│ │
│  └─────────┘  └────┬───┘  └────┬────┘ │
│                    │             │      │
│                    │  Notify     │      │
│                    ├─────────────┤      │
│                    │             │      │
│             ┌──────▼─────────────▼───┐ │
│             │  Notification Manager   │ │
│             │  (HA Persistent + CLI)  │ │
│             └─────────────────────────┘ │
│                                          │
│  ┌───────────────────────────────────┐ │
│  │    SQLite Database + Config       │ │
│  └───────────────────────────────────┘ │
│                                          │
└─────────────────────────────────────────┘
              │
              │ REST + WebSocket APIs
              ▼
      ┌───────────────┐
      │ Home Assistant│
      │               │
      │ - REST API    │
      │ - WebSocket   │
      └───────────────┘
```

### Data Flow

**Startup Sequence**:
1. Load configuration from config.yaml and environment
2. Initialize SQLite database (create tables if needed)
3. Connect to Home Assistant REST API (validate token)
4. Discover integrations and build entity→integration mapping
5. Establish WebSocket connection with event subscription
6. Fetch initial state snapshot via REST
7. Start background health monitoring loop

**Runtime Monitoring Loop**:
1. WebSocket receives `state_changed` event
2. State Tracker updates in-memory cache and database
3. Health Monitor checks if state indicates issue (unavailable/unknown)
4. If issue detected and grace period expired → trigger healing
5. Healing Manager attempts integration reload
6. If healing fails → escalate to notification
7. Record all actions in database for analysis

**WebSocket Disconnect Recovery**:
1. Detect disconnection via timeout or connection closed event
2. Log warning and start reconnection loop with exponential backoff
3. Optional: Fall back to REST polling during disconnection
4. On reconnect: fetch state history since last event to catch missed changes
5. Resume normal WebSocket monitoring

### Code Organization Rules

When adding new features:
1. **Module Placement**: Core infrastructure in `core/`, feature-specific code in appropriate subdirectory
2. **Tests**: Mirror source structure in `tests/` directory
3. **Type Hints**: All functions must have complete annotations
4. **Async**: Use async/await for all I/O operations
5. **Error Handling**: Specific exceptions with retry logic
6. **Documentation**: Docstrings for public APIs (Google style)
7. **Configuration**: New settings added to Pydantic models in `core/config.py`
8. **Database**: New tables/columns require schema updates and migration notes

## CI/CD Integration

### GitHub Actions Workflows

**CI Pipeline** (`.github/workflows/ci.yml`):
- Runs on push to main/develop and on PRs
- Tests against Python 3.11 and 3.12
- Runs: black (format), ruff (lint), mypy (types), pytest (tests)
- On main branch failures: automatically creates GitHub issue tagged with `claude-task`

**Claude Code Action** (`.github/workflows/claude.yml`):
- Triggers when `@claude` is mentioned in issues/comments
- Triggers when issue is labeled with `claude-task`
- Claude has write access to create PRs and update issues

**Security Scan** (`.github/workflows/security.yml`):
- Runs on push and weekly schedule
- Uses bandit for security linting
- Uses safety for dependency vulnerability checking

### Automated Issue Creation

When CI fails on main branch, a GitHub issue is automatically created with:
- Link to failed workflow run
- Commit SHA and author
- Tagged with `ci-failure`, `claude-task`, `automated` labels
- Contains `@claude` mention to trigger automatic investigation

### Working with Issues

When assigned an issue:
1. Read the issue description and linked workflow logs
2. Identify root cause of failure
3. Create a branch: `fix/issue-{number}-brief-description`
4. Implement fix with tests
5. Ensure all CI checks pass locally (`/ci-check`)
6. Create PR with reference to issue: "Closes #X"
7. PR will auto-tag Claude for review

## Testing Guidelines

### Test Structure

- Tests mirror the source structure: `ha_boss/module.py` → `tests/test_module.py`
- Use pytest fixtures for common setup
- Mark slow/integration tests with `@pytest.mark.slow` or `@pytest.mark.integration`

### Async Testing

```python
import pytest

@pytest.mark.asyncio
async def test_async_function() -> None:
    result = await some_async_function()
    assert result == expected
```

### Coverage Requirements

- Maintain minimum 80% code coverage
- New features must include tests
- Bug fixes should include regression tests

## Code Quality Standards

### Formatting and Style

- **Line length**: 100 characters (enforced by black and ruff)
- **Import order**: stdlib, third-party, local (managed by ruff)
- **Docstrings**: Use Google-style docstrings for public APIs
- **Type hints**: Required for all function signatures

### Type Checking

All code must pass mypy strict checking:
```python
def process_data(data: dict[str, Any]) -> list[str]:
    """Process data and return list of keys."""
    return list(data.keys())
```

### Error Handling

Prefer specific exceptions over generic ones:
```python
# Good
try:
    result = await ha_client.get_state(entity_id)
except HomeAssistantConnectionError as e:
    logger.error(f"Failed to connect to HA: {e}")
    raise

# Avoid
try:
    result = await ha_client.get_state(entity_id)
except Exception as e:
    pass
```

## Home Assistant Integration

### API Architecture

HA Boss uses a hybrid approach for interacting with Home Assistant:
- **WebSocket API**: Primary method for real-time state monitoring
- **REST API**: Backup for operations, service calls, and periodic validation

### WebSocket API Usage

**Connection Pattern**:
```python
# Connect to ws://ha-url:8123/api/websocket
# 1. Receive auth_required message
# 2. Send auth with long-lived token
# 3. Receive auth_ok
# 4. Subscribe to state_changed events
# 5. Maintain heartbeat with ping/pong every 30 seconds
```

**Key Events**:
- `state_changed`: Entity state transitions (our primary monitoring event)
- `entity_registry_updated`: Entity added/removed/modified

**Important Limitations**:
- Cannot filter events server-side (receives ALL state changes)
- Must implement client-side filtering for monitored entities
- Connection can timeout (implement auto-reconnect)
- Max 512 pending messages before disconnect

### REST API Usage

**Key Endpoints for HA Boss**:
- `GET /api/states` - Fetch all entity states (startup/validation)
- `GET /api/states/<entity_id>` - Get specific entity
- `POST /api/services/<domain>/<service>` - Call services (reload integrations)
- `GET /api/history/period/<timestamp>` - Replay missed events after disconnect

**Service Calls for Healing**:
```python
# Reload specific integration
POST /api/services/homeassistant/reload_config_entry
{
  "entry_id": "abc123..."  # Integration config entry ID
}

# Reload all automations
POST /api/services/automation/reload

# Create persistent notification
POST /api/services/persistent_notification/create
{
  "title": "HA Boss Alert",
  "message": "...",
  "notification_id": "haboss_alert_123"
}
```

### Integration Discovery Challenge

**Problem**: No direct API to get integration config entry IDs (needed for reload)

**Solutions** (in priority order):
1. **Storage File Parsing**: Parse `.storage/core.config_entries` (most reliable)
2. **Entity→Device→Integration Mapping**: Map entity to device, device to config entry
3. **User Input**: Prompt user to manually specify entry IDs for critical integrations
4. **WebSocket Query**: Some integrations expose this via custom WebSocket commands

**Implementation Location**: `ha_boss/healing/integration_manager.py:IntegrationDiscovery`

### Error Handling

**Connection Errors**:
- Network timeout: Retry with exponential backoff
- Connection refused: Log error, retry after 30s
- 401 Unauthorized: Invalid token, alert user immediately, stop service

**Service Call Errors**:
- 404 Not Found: Service/entity doesn't exist (log warning, don't retry)
- Integration reload failed: Increment circuit breaker, escalate if threshold exceeded

**WebSocket Errors**:
- Connection closed: Auto-reconnect, replay missed events via REST history
- Auth timeout (10s): Increase timeout configuration or check network
- Message queue full: Reduce monitored entities or implement filtering

### API Interactions Best Practices

**Rate Limiting**:
- Home Assistant has no enforced rate limits
- Use WebSocket for monitoring (don't poll with REST)
- Batch operations when possible
- Implement local caching to reduce API calls

**Retry Logic**:
```python
# Standard retry pattern for HA Boss
max_attempts = 3
base_delay = 1.0  # seconds

for attempt in range(max_attempts):
    try:
        result = await ha_client.call_service(...)
        return result
    except HomeAssistantConnectionError:
        if attempt == max_attempts - 1:
            raise
        await asyncio.sleep(base_delay * (2 ** attempt))
```

**State Caching**:
- Maintain in-memory cache of entity states from WebSocket
- Periodically validate cache with REST API snapshot (every 5-10 minutes)
- Use cache for health checks to avoid REST API overhead

### Configuration

**Required Settings**:
- `HA_URL`: Home Assistant instance URL (e.g., `http://homeassistant.local:8123`)
- `HA_TOKEN`: Long-lived access token (created in HA user profile)

**Creating Long-Lived Token**:
1. Navigate to HA profile: `http://ha-url/profile`
2. Scroll to "Long-Lived Access Tokens"
3. Click "Create Token"
4. Copy token immediately (cannot be retrieved later)
5. Store in `.env` file as `HA_TOKEN=...`

**Security Notes**:
- Tokens grant full API access (protect like passwords)
- Tokens stored in HA database but not displayed in UI after creation
- Default expiration: 10 years
- Consider separate HA user account for HA Boss with limited permissions (future)

See `.env.example` for complete configuration template.

## Claude Code Features

### Remote Development

The project is configured for remote development:
- **DevContainer**: `.devcontainer/devcontainer.json` for cloud/remote development
- **VS Code Settings**: `.vscode/settings.json` for consistent IDE configuration
- **Claude Settings**: `.claude/settings.json` for project-specific preferences

### Hooks

Pre-commit hooks are available but disabled by default. Enable in `.claude/settings.json`:
```json
{
  "hooks": {
    "pre-commit": {
      "enabled": true,
      "command": "pytest --maxfail=1 -x"
    }
  }
}
```

### GitHub App Integration

To enable full Claude Code integration:
1. Run `/install-github-app` in Claude Code CLI
2. Add `ANTHROPIC_API_KEY` to GitHub repository secrets
3. Ensure workflows have correct permissions (already configured)

## Security Considerations

- Never commit `.env` files or secrets
- Use GitHub Secrets for sensitive values in CI
- Keep dependencies updated (security workflow runs weekly)
- Review bandit security scan results before merging

## Common Workflows

### Adding a New Feature

1. Create feature branch: `feature/brief-description`
2. Implement feature with type hints
3. Add comprehensive tests
4. Run `/ci-check` to verify all checks pass
5. Update documentation if needed
6. Create PR with description of changes

### Fixing a Bug

1. Add regression test that reproduces bug
2. Implement fix
3. Verify test passes
4. Run full test suite
5. Create PR referencing issue

### Reviewing PRs

Use `/review-pr [number]` command to:
- Check code follows style guidelines
- Verify tests are included
- Ensure no security issues
- Validate type hints
- Check documentation updates
