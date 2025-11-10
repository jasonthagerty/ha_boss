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

### Prerequisites

- **Python 3.12** (required for consistency with CI)
- **uv** (fast Python package installer - https://github.com/astral-sh/uv)

**Note for GitHub Actions/CI**: The following tools are pre-installed in GitHub Actions runners and do not need installation:
- `gh` (GitHub CLI) - already available
- `git` - already available

### Local Development Setup

**If you're working locally** (not in GitHub Actions), you'll also need:
- **GitHub CLI (gh)** - for issue/PR management (https://cli.github.com/)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install GitHub CLI (LOCAL DEVELOPMENT ONLY - skip if running in GitHub Actions)
# Check if gh is already installed
if ! command -v gh &> /dev/null; then
  # macOS
  brew install gh
  # Linux (Debian/Ubuntu)
  # curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
  # echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
  # sudo apt update && sudo apt install gh
  # Windows (via scoop)
  # scoop install gh
fi

# Authenticate with GitHub (required for gh commands)
gh auth login
# Follow prompts: select HTTPS, authenticate via browser, grant required scopes

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

When assigned an issue or tagged with `@claude`:

1. **Read the Issue**
   - Review description, acceptance criteria, and technical notes
   - Check related components and dependencies
   - Understand the branch name to use

2. **Create Feature Branch**
   ```bash
   git checkout -b feature/issue-{number}-brief-description
   ```

3. **Implement Feature**
   - Follow acceptance criteria
   - Add type hints (mypy compliance)
   - Write comprehensive tests (≥80% coverage)
   - Follow code quality standards

4. **Test Locally**
   ```bash
   # Run all CI checks
   make ci-check
   # Or manually:
   black --check . && ruff check . && mypy ha_boss && pytest
   ```

5. **Commit Changes**
   - Use conventional commit messages
   - Include co-authored-by for Claude
   - Reference issue number

6. **Push and Create PR**
   ```bash
   git push origin feature/issue-{number}-brief-description
   gh pr create --title "feat: brief description" --body "Closes #{number}"
   ```

7. **PR Description Must Include**
   - "Closes #{number}" to auto-close issue
   - Summary of changes
   - Testing performed
   - Any breaking changes or notes

8. **After Merge**
   - Issue automatically closes
   - Branch can be deleted
   - Project board updates automatically

### Example: Implementing Issue #2

```bash
# 1. Create branch from main
git checkout main
git pull origin main
git checkout -b feature/issue-2-integration-discovery

# 2. Implement the feature
# ... write code in ha_boss/healing/integration_manager.py
# ... write tests in tests/healing/test_integration_manager.py

# 3. Run CI checks
make ci-check

# 4. Commit
git add .
git commit -m "feat: implement integration discovery system

- Created IntegrationDiscovery class with storage file parsing
- Added entity→integration mapping via HA API
- Built in-memory cache for fast lookups
- Added comprehensive tests with 85% coverage
- Handles missing/unknown integrations gracefully

Closes #2

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# 5. Push and create PR
git push origin feature/issue-2-integration-discovery
gh pr create --title "feat: implement integration discovery system" \
  --body "Closes #2

## Overview
Implements the integration discovery system to map Home Assistant entities to integrations.

## Changes
- Created ha_boss/healing/integration_manager.py
- Added storage file parsing and API mapping
- Built entity→integration cache
- Added 15 tests with 85% coverage

## Testing
- All tests passing (69/69)
- CI checks passing ✓
- Tested with mock HA storage files"
```

### Getting Assigned Issues

Issues are assigned to Claude in several ways:

1. **Manual Assignment**: User assigns issue to `@claude` in GitHub
2. **@claude Mention**: Comment on issue with `@claude` to trigger assignment
3. **claude-task Label**: Issues labeled `claude-task` are automatically available
4. **CI Failures**: Automatic issues created from CI failures are auto-assigned

### Project Board Integration

- **GitHub Project**: https://github.com/users/jasonthagerty/projects/1
- All issues automatically added to project board
- Status updates automatically as issues progress
- Filter by labels to view MVP, phases, or priorities

### Branch Protection

- `main` branch is protected
- All changes must go through PRs
- CI checks must pass before merge
- Squash commits on merge to keep history clean

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

### Working with CI Failure Issues

When CI fails and an automated issue is created:
1. Read the issue description and linked workflow logs
2. Identify root cause of failure (check test output, linting errors, etc.)
3. Follow the **Feature Branch Workflow** (see above) using `fix/` prefix
4. Branch name: `fix/issue-{number}-brief-description`
5. Implement fix with regression test if applicable
6. Ensure all CI checks pass locally (`make ci-check`)
7. Create PR with "Closes #{number}" to auto-close issue

**Note**: For all other issues (features, enhancements, documentation), see the complete "Feature Branch Workflow" section above.

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

### GitHub MCP Server Integration

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

- **Never commit** the actual `mcp.json` with real tokens to the repository
- The `.claude/mcp.json.example` file is for reference only (contains placeholder)
- Store your actual token in the user-level config directory (not tracked by git)
- GitHub tokens grant significant repository access - protect them like passwords
- Consider using a separate GitHub account or bot account for CI/CD automation
- Rotate tokens periodically and revoke unused tokens

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

- Never commit `.env` files or secrets
- Use GitHub Secrets for sensitive values in CI
- Keep dependencies updated (security workflow runs weekly)
- Review bandit security scan results before merging

## Common Workflows

### Adding a New Feature

**Always start with a GitHub issue** (or create one if it doesn't exist):

1. Review issue acceptance criteria and branch name
2. Create feature branch: `feature/issue-{number}-brief-description`
3. Implement feature with type hints (mypy compliance)
4. Add comprehensive tests (≥80% coverage)
5. Run `make ci-check` to verify all checks pass
6. Update documentation if needed
7. Create PR with "Closes #{number}" in description

See **Feature Branch Workflow** section above for complete details.

### Fixing a Bug

**Always reference the bug issue**:

1. Review bug issue and reproduce locally if possible
2. Add regression test that reproduces bug
3. Create branch: `fix/issue-{number}-brief-description`
4. Implement fix
5. Verify test passes
6. Run full test suite (`make ci-check`)
7. Create PR with "Closes #{number}" referencing issue

### Discovering Bugs During Development

**Standard approach when discovering bugs during feature development or testing**:

When you discover a bug while working on a feature or during testing, follow this process:

1. **Create GitHub Issue for Tracking**
   - Document the bug with clear description
   - Include error messages, reproduction steps
   - Tag with appropriate labels (bug, priority)
   - Reference the context where discovered (e.g., "Discovered during Docker deployment testing #7")

2. **Assess Severity and Fix Immediately if Appropriate**
   - **Fix immediately if**:
     - Bug blocks current work or testing
     - Fix is simple and well-understood
     - Bug affects core functionality
   - **Defer if**:
     - Complex fix requiring significant research
     - Not blocking current work
     - Requires architectural discussion

3. **Fix in Current Branch (if immediate fix)**
   - Fix the bug in your current feature branch
   - Commit with reference to bug issue: "Fixes #number"
   - Include bug fix in current PR
   - Document in PR description that bug was discovered and fixed

4. **Update Documentation**
   - If the bug reveals a gap in docs/examples, fix those too
   - Update CLAUDE.md if process improvements are identified

**Example**:
```bash
# Discovered config validation bug during Docker testing
gh issue create --title "bug: invalid config section" --body "..." --label "bug,priority-high"
# Returns issue #21

# Fix immediately (blocking Docker deployment)
git add config/config.yaml.example
git commit -m "fix: remove invalid section

Fixes #21

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude <noreply@anthropic.com>"

# Bug fix included in feature PR with note about discovery
```

**Benefits of this approach**:
- ✅ Proper issue tracking for metrics and project management
- ✅ Clear commit history linking fixes to issues
- ✅ Bugs don't block forward progress
- ✅ Documentation of discovery context helps prevent future issues
- ✅ Single PR for related changes reduces review overhead

### Reviewing PRs

Use `/review-pr [number]` command to:
- Check code follows style guidelines
- Verify tests are included
- Ensure no security issues
- Validate type hints
- Check documentation updates
