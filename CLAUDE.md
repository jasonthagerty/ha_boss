# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HA Boss is a standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and uses AI to generate and optimize automations. The project follows an MVP-first approach, starting with reliable monitoring and auto-healing, then adding intelligence features incrementally.

### Core Capabilities

**Phase 1 (MVP - Complete)**:
- Real-time monitoring of Home Assistant entities via WebSocket
- Automatic detection of unavailable/stale entities
- Auto-healing via integration reload with safety mechanisms
- Escalated notifications when auto-healing fails
- Docker-first deployment

**Phase 2 (Pattern Collection & Analysis - Complete)**:
- Integration reliability tracking (success rates, failure patterns)
- Database schema for pattern storage
- CLI reports for reliability analysis
- Foundation for future AI-driven insights

**Phase 3 (AI-Powered Intelligence Layer - Complete)**:
- Local LLM integration (Ollama) for enhanced notifications
- Claude API integration for complex reasoning and automation generation
- Intelligent LLM router with local-first fallback strategy
- Pattern-based anomaly detection with AI-generated insights
- Weekly AI-analyzed summary reports
- Automation analysis with optimization suggestions
- Natural language automation generation
- Performance benchmarks validating < 15s response times

**Phase 3 LLM Stack Decision** (see `docs/LLM_SETUP.md` for details):
- **Backend**: Ollama with Llama 3.1 8B (Q4_K_M quantization)
- **Mode**: CPU inference for MVP (9.18 tokens/s)
- **Performance**: Meets < 15s requirement for low-volume use (1-10 requests/day)
- **Future**: GPU acceleration planned (Issue #52) for 2-5x speedup
- **Deployment**: Docker container on blackbox server (Intel ARC A770)

### Design Philosophy

1. **Start Simple**: MVP focuses on monitoring + healing without AI complexity
2. **Safety First**: Dry-run mode, circuit breakers, rollback capability
3. **Fail Gracefully**: Escalate to user when auto-heal fails rather than stay silent
4. **Learn Over Time**: Collect patterns to improve effectiveness
5. **Hybrid AI**: Local LLM for routine tasks, Claude for complex reasoning

## Development Commands

### Prerequisites

- **Python 3.12** (REQUIRED - project standardized on 3.12 only)
  - ⚠️ Using any other Python version will cause CI failures
  - All tooling (black, ruff, mypy) is configured for Python 3.12
  - CI only tests Python 3.12 to ensure consistency
- **uv** (fast Python package installer - https://github.com/astral-sh/uv)
- **GitHub MCP Server** (recommended) - for issue/PR management via Claude Code
  - See "GitHub MCP Server Integration" section below for setup
  - Alternative: `gh` CLI (optional if MCP server configured)

**Note for GitHub Actions/CI**: The following tools are pre-installed in GitHub Actions runners:
- `git` - version control
- `gh` (GitHub CLI) - available as fallback

### Local Development Setup

**Primary method (recommended):**
- Configure GitHub MCP Server (see "GitHub MCP Server Integration" section)
- Claude Code will handle GitHub operations automatically

**Alternative (if MCP not available):**
- **GitHub CLI (gh)** - for manual issue/PR management (https://cli.github.com/)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e ".[dev]"
```

**Alternative (without uv):**
```bash
# Traditional venv approach (slower)
python3.12 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Testing

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

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
# Ensure virtual environment is activated
source .venv/bin/activate

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
- `/uat [--cli-only|--api-only|--full] [--dry-run]` - Run User Acceptance Testing

## Architecture

### Project Structure

```
ha_boss/
├── ha_boss/                    # Main package code
│   ├── core/                   # Core infrastructure
│   │   ├── config.py          # Pydantic configuration models
│   │   ├── ha_client.py       # Home Assistant API wrapper
│   │   ├── database.py        # SQLAlchemy models and DB management
│   │   └── llm_router.py      # LLM task routing
│   ├── monitoring/             # Entity monitoring
│   │   ├── state_tracker.py   # Track entity states
│   │   ├── health_monitor.py  # Health checks and anomaly detection
│   │   ├── websocket_client.py # WebSocket connection manager
│   │   └── anomaly_detector.py # LLM-powered anomaly detection
│   ├── healing/                # Auto-healing system
│   │   ├── integration_manager.py  # Integration discovery and reload
│   │   ├── heal_strategies.py      # Healing strategies and logic
│   │   └── escalation.py           # Notification escalation
│   ├── intelligence/           # AI features
│   │   ├── ollama_client.py   # Ollama client
│   │   ├── claude_client.py   # Claude API client
│   │   ├── llm_router.py      # Intelligent LLM routing
│   │   ├── anomaly_detector.py # Pattern-based anomaly detection
│   │   ├── weekly_summary.py  # AI-generated weekly reports
│   │   ├── pattern_collector.py # Pattern data collection
│   │   └── reliability_analyzer.py # Integration reliability analysis
│   ├── automation/             # Automation management
│   │   ├── analyzer.py        # Automation analysis
│   │   └── generator.py       # AI automation generation
│   ├── notifications/          # Notification system
│   │   ├── manager.py         # Notification routing
│   │   └── templates.py       # Message templates
│   ├── api/                   # REST API (future)
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

## Feature Branch Workflow

### Overview

All development work is tracked via GitHub Issues and managed through feature branches. This ensures clear ownership, tracking, and integration with CI/CD.

### Issue-Driven Development

**GitHub Issues** are the source of truth for all work:
- **View Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Project Board**: https://github.com/users/jasonthagerty/projects/1
- All issues labeled with `claude-task` are assignable to Claude
- Issues include acceptance criteria, technical notes, and branch names

### Label System

Issues use the following labels for organization:

**Phase Labels:**
- `mvp` - MVP Phase 1 features (current focus)
- `phase-1` - Phase 1: Core Monitoring & Healing
- `phase-2` - Phase 2: Intelligence Layer
- `phase-3` - Phase 3: Advanced Features

**Priority Labels:**
- `priority-high` - High priority (work on first)
- `priority-medium` - Medium priority
- `priority-low` - Low priority

**Type Labels:**
- `enhancement` - New feature or request
- `bug` - Something isn't working
- `documentation` - Documentation improvements
- `ci-failure` - CI/CD pipeline failure
- `claude-task` - Task for Claude Code to handle
- `automated` - Automatically created issue

### Branch Naming Convention

**Format:** `<type>/issue-<number>-<brief-description>`

**Types:**
- `feature/` - New features (most common for MVP)
- `fix/` - Bug fixes
- `docs/` - Documentation only changes
- `refactor/` - Code refactoring without functional changes
- `test/` - Adding or updating tests

**Examples:**
- `feature/issue-2-integration-discovery`
- `feature/issue-3-health-monitoring`
- `fix/issue-15-websocket-reconnect`
- `docs/issue-8-update-readme`

### Complete Feature Workflow

1. **Review Issue**: Read description, acceptance criteria, dependencies
2. **Comment**: "Starting work on this issue" (updates project board)
3. **Create Branch**: `git checkout -b feature/issue-{number}-brief-description`
4. **Implement**: Follow acceptance criteria, add type hints, write tests (≥80% coverage)
5. **Test**: Run `make ci-check` before committing
6. **Commit**: Use conventional commits, reference issue number, include co-author
7. **Create PR**: Include "Closes #{number}", summary, and testing notes
8. **After Merge**: Update epic checklist if applicable, notify unblocked issues

### Example: Feature Implementation Workflow

```bash
# Create branch
git checkout -b feature/issue-2-integration-discovery

# Implement, test, and commit
# ... (write code and tests)
make ci-check
git commit -m "feat: implement integration discovery

- Created IntegrationDiscovery class
- Added entity→integration mapping
- Added tests with 85% coverage

Closes #2

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude <noreply@anthropic.com>"

# Push and create PR (via GitHub MCP or gh CLI)
git push origin feature/issue-2-integration-discovery
```

### Managing Epics and Sub-Tasks

Epics track large features consisting of multiple sub-tasks.

**Epic Structure:**
- Use checkboxes to list sub-tasks: `- [ ] #26: Task description`
- Label with `epic` and phase label
- Link sub-tasks back to epic: `**Epic**: #25`

**Workflow:**
1. Create epic with checklist of sub-tasks
2. Create individual issues for each sub-task
3. Update checklist as sub-tasks complete: `- [x] #26: Task ✓`
4. Close epic when all sub-tasks are done

### Getting Assigned Issues

Issues are assigned to Claude in several ways:

1. **Manual Assignment**: User assigns issue to `@claude` in GitHub
2. **@claude Mention**: Comment on issue with `@claude` to trigger assignment
3. **claude-task Label**: Issues labeled `claude-task` are automatically available
4. **CI Failures**: Automatic issues created from CI failures are auto-assigned

### Project Board Management

**Current Project**: https://github.com/users/jasonthagerty/projects/1

All HA Boss work (all phases) is tracked on a single project board organized by phase, priority, and status.

**When to Update:**
- After creating issues → Link to project (usually automatic)
- When starting work → Move to "In Progress"
- After PR merge → Issue closes and moves to "Done" (automatic)
- For epics → Update checklist as sub-tasks complete

**Key Notes:**
- Issues are automatically added to the project when created
- Status updates automatically when issues close
- All phases use the same project (Project #1)

### Branch Protection

- `main` branch is protected
- All changes must go through PRs
- CI checks must pass before merge
- Squash commits on merge to keep history clean

## CI/CD Integration

### GitHub Actions Workflows

**CI Pipeline** (`.github/workflows/ci.yml`):
- Runs on push to main/develop and PRs
- Tests Python 3.11 and 3.12
- Checks: black, ruff, mypy, pytest
- Auto-creates issue on main branch failures (tagged `claude-task`)

**Claude Code Action** (`.github/workflows/claude.yml`):
- Triggers on `@claude` mentions or `claude-task` label
- Enables automated PR creation and issue updates

**Security Scan** (`.github/workflows/security.yml`):
- Runs on push and weekly
- Tools: bandit, safety

### Working with CI Failure Issues

When CI fails on main branch, an automated issue is created. Follow the standard workflow:
1. Read issue description and workflow logs to identify root cause
2. Create fix branch: `fix/issue-{number}-brief-description`
3. Implement fix with regression test if needed
4. Run `make ci-check` locally
5. Create PR with "Closes #{number}"

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

### GitHub MCP Server Integration

**Recommended: GitHub MCP Server** for all GitHub operations

The GitHub MCP (Model Context Protocol) server enables Claude Code to directly create and manage GitHub issues, PRs, and other repository operations without relying on the `gh` CLI. This is particularly useful in environments where the GitHub CLI is not available (containers, CI/CD, etc.).

**Why Use GitHub MCP Server?**

- ✅ Works in any environment (web, desktop, containers, CI/CD)
- ✅ Direct API access through structured MCP tools
- ✅ No dependency on `gh` CLI installation
- ✅ Consistent interface across all Claude Code deployments
- ✅ Enables automated issue creation from CI failures

**Setup Instructions:**

1. **Install GitHub MCP Server** (if not already installed):
   ```bash
   # Install globally via npm (optional, npx can be used without install)
   npm install -g @modelcontextprotocol/server-github
   ```

2. **Create GitHub Personal Access Token**:
   - Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Click "Generate new token (classic)"
   - Select scopes:
     - `repo` (full repository access)
     - `issues` (create/edit issues)
     - `workflow` (trigger workflows, if needed)
   - Copy token immediately (cannot be retrieved later)
   - Store securely (treat like a password)

3. **Configure MCP Server**:

   For **Claude Code Web/Desktop** (user-level configuration):
   - Create or edit `~/.config/claude/mcp.json` (Linux/Mac) or `%APPDATA%\Claude\mcp.json` (Windows)
   - Use the configuration template below

   For **Project Reference** (check-in example for team):
   - See `.claude/mcp.json.example` in this repository
   - Copy to your user-level Claude config directory

   **Configuration Template:**
   ```json
   {
     "mcpServers": {
       "github": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-github"],
         "env": {
           "GITHUB_TOKEN": "ghp_your_actual_token_here"
         }
       }
     }
   }
   ```

4. **Restart Claude Code** to load the MCP server configuration

5. **Verify Installation**:
   - In Claude Code, you should now have access to GitHub tools
   - Available operations include:
     - Create/update/close issues
     - Create/update pull requests
     - Add/remove labels
     - Add comments to issues/PRs
     - Search issues and PRs
     - Get repository information

**Usage Examples:**

Once configured, Claude Code can automatically:

```bash
# Create a new issue
"Create a GitHub issue titled 'Bug: config validation fails' with label 'bug'"

# Add comment to existing issue
"Add a comment to issue #25 explaining the root cause"

# Create PR from current branch
"Create a pull request for this branch with title 'feat: add health monitoring'"
```

**Security Notes:**

⚠️ **CRITICAL - Token Security**:
- **NEVER commit `.claude/mcp.json`** to the repository - it contains your GitHub PAT
- `.claude/mcp.json` is now protected by `.gitignore` to prevent accidental commits
- If you accidentally commit a token, it will be automatically revoked by GitHub
- Store your actual MCP configuration in the user-level config directory (recommended):
  - Linux/Mac: `~/.config/claude/mcp.json`
  - Windows: `%APPDATA%\Claude\mcp.json`
- The `.claude/mcp.json.example` file is for reference only (contains placeholder)
- GitHub tokens grant significant repository access - protect them like passwords
- Consider using a separate GitHub account or bot account for CI/CD automation
- Rotate tokens periodically and revoke unused tokens
- If a token is ever exposed, revoke it immediately in GitHub settings

**Troubleshooting:**

- **"GitHub MCP server not found"**: Ensure `npx` is available (requires Node.js)
- **"Authentication failed"**: Verify token has correct scopes (`repo`, `issues`)
- **"Permission denied"**: Check token hasn't expired and has access to the repository
- **Config not loading**: Ensure `mcp.json` is in the correct location for your OS

**Alternative: GitHub CLI (`gh`)**

If you prefer using the GitHub CLI instead of MCP:
- See the "Local Development Setup" section for `gh` installation
- Note: `gh` CLI may not be available in all environments (containers, CI/CD)
- MCP server is recommended for consistent cross-environment support

**Detailed Setup & Testing Guide:**

For complete step-by-step instructions, troubleshooting, and testing procedures, see:
- `.claude/GITHUB_MCP_SETUP.md` - Comprehensive setup and testing guide
- `.claude/mcp.json.example` - Example MCP configuration file

## Security Considerations

### Protected Files (Never Commit)

The following files are protected by `.gitignore` and must NEVER be committed:
- `.env`, `.env.local` - Environment variables and secrets
- `.claude/mcp.json` - Contains GitHub Personal Access Tokens
- `.claude/settings.local.json` - Local Claude Code settings
- `.claude/*.local.json` - Any local configuration files
- `data/*.db*` - SQLite database files with runtime data
- `secrets.yaml` - Home Assistant secrets

### Best Practices

- Use GitHub Secrets for sensitive values in CI/CD workflows
- Keep dependencies updated (security workflow runs weekly)
- Review bandit security scan results before merging
- Rotate API tokens and PATs periodically
- If a secret is accidentally committed, revoke it immediately and rotate
- Use `.example` files to document required configuration without exposing values

## Common Workflows

### Adding a New Feature

Always start with a GitHub issue, then follow the **Complete Feature Workflow** above.

### Fixing a Bug

1. Review bug issue and reproduce locally
2. Add regression test that reproduces the bug
3. Create branch: `fix/issue-{number}-brief-description`
4. Implement fix and verify test passes
5. Run `make ci-check` and create PR with "Closes #{number}"

### Discovering Bugs During Development

When discovering bugs during feature work:

1. **Create GitHub issue** with description, error messages, and context
2. **Fix immediately if**: blocking, simple, or affects core functionality
3. **Defer if**: complex, not blocking, or needs architectural discussion
4. **If fixing now**: Include in current branch/PR with "Fixes #number" in commit

**Example**:
```bash
# Create issue for tracking
gh issue create --title "bug: invalid config" --label "bug,priority-high"

# Fix in current branch
git commit -m "fix: remove invalid config section

Fixes #21
..."
```

### Reviewing PRs

Use `/review-pr [number]` command to:
- Check code follows style guidelines
- Verify tests are included
- Ensure no security issues
- Validate type hints
- Check documentation updates
