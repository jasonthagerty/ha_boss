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

**Phase 2 (Pattern Collection & Analysis - Current Focus)**:
- Integration reliability tracking (success rates, failure patterns)
- Database schema for pattern storage
- CLI reports for reliability analysis
- Foundation for future AI-driven insights

**Phase 3 (Intelligence Layer)**:
- Local LLM integration (Ollama) for enhanced notifications
- Pattern-based anomaly detection
- Weekly summary reports with AI analysis
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
   - Verify issue is on project board

2. **Start Work (Update Project)**
   - Comment on issue: "Starting work on this issue"
   - If epic: Update epic checklist to mark sub-task as in-progress
   - Project board should auto-update to "In Progress"

3. **Create Feature Branch**
   ```bash
   git checkout -b feature/issue-{number}-brief-description
   ```

4. **Implement Feature**
   - Follow acceptance criteria
   - Add type hints (mypy compliance)
   - Write comprehensive tests (≥80% coverage)
   - Follow code quality standards

5. **Test Locally**
   ```bash
   # Run all CI checks
   make ci-check
   # Or manually:
   black --check . && ruff check . && mypy ha_boss && pytest
   ```

6. **Commit Changes**
   - Use conventional commit messages
   - Include co-authored-by for Claude
   - Reference issue number

7. **Push and Create PR**
   ```bash
   git push origin feature/issue-{number}-brief-description

   # If using GitHub MCP (recommended):
   # Claude Code will offer to create PR automatically

   # Alternatively, use gh CLI:
   gh pr create --title "feat: brief description" --body "Closes #{number}"
   ```

8. **PR Description Must Include**
   - "Closes #{number}" to auto-close issue
   - Summary of changes
   - Testing performed
   - Any breaking changes or notes

9. **After Merge (Update Project)**
   - Issue automatically closes (via "Closes #" in PR)
   - Branch can be deleted
   - Project board updates to "Done" automatically
   - **If Epic**: Update epic issue checklist to mark sub-task complete
   - **If Blocked Others**: Comment on unblocked issues to notify
   - Move to next issue in dependency chain

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

# With GitHub MCP configured, Claude Code can create the PR:
# "Create a pull request with title 'feat: implement integration discovery system'"

# Or manually with gh CLI:
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

### Managing Epics and Sub-Tasks

Epics track large features or phases that consist of multiple sub-tasks.

#### Epic Management Workflow

**When Creating an Epic:**
1. Create the epic issue with:
   - Clear overview and goals
   - List of sub-tasks with checkboxes (use `- [ ]` syntax)
   - Success criteria
   - Timeline estimates
2. Label with `epic` and appropriate phase label
3. Create individual issues for each sub-task
4. Link sub-tasks to epic in both directions:
   - Epic body: `- [ ] #26: Task description`
   - Sub-task body: `**Epic**: #25 Phase 2`

**When Working on Sub-Tasks:**
1. Start work: Comment on epic to notify progress
2. Complete sub-task: Update epic checklist
   - Change `- [ ] #26: Task` to `- [x] #26: Task`
   - Or use GitHub's automatic linking via PR mentions

**When Epic is Complete:**
1. Verify all sub-tasks are complete (all checkboxes checked)
2. Add summary comment with outcomes
3. Close the epic issue
4. Celebrate! 🎉

#### Example: Phase 2 Epic (#32)

```markdown
## 📋 Subtasks

### Foundation
- [ ] #26: Design and implement pattern database schema
- [ ] #27: Create PatternCollector service
- [ ] #28: Implement integration reliability tracking

### User-Facing
- [ ] #29: Add pattern analysis queries and reports
- [ ] #30: Integrate pattern collection with service orchestration

### Quality
- [ ] #31: Add comprehensive tests
```

**After completing #26:**
```markdown
- [x] #26: Design and implement pattern database schema ✓
- [ ] #27: Create PatternCollector service
...
```

### Getting Assigned Issues

Issues are assigned to Claude in several ways:

1. **Manual Assignment**: User assigns issue to `@claude` in GitHub
2. **@claude Mention**: Comment on issue with `@claude` to trigger assignment
3. **claude-task Label**: Issues labeled `claude-task` are automatically available
4. **CI Failures**: Automatic issues created from CI failures are auto-assigned

### Project Board Management

GitHub Projects provide a visual way to track work across phases and priorities. Claude Code should proactively manage the project board to keep it synchronized with actual work status.

#### Project Structure

- **Current Project**: https://github.com/users/jasonthagerty/projects/1
- **Purpose**: Track all HA Boss work (Phase 1, Phase 2, Phase 3+)
- **Organization**: By phase, priority, and status

#### When to Update the Project Board

Update the project board at these key moments:

1. **After Creating Issues** - Link new issues to project
2. **When Starting Work** - Move issue to "In Progress"
3. **After Completing Work** - Move issue to "Done" when PR merged
4. **After Creating Epics** - Ensure epic is tracked on board
5. **When Work is Blocked** - Update status to reflect blockers

#### Checking if Project Exists

Before creating a new project, verify the current project exists and is appropriate:

```bash
# Use GitHub MCP to check projects
# If project doesn't exist or you need to create a new one for a phase:
# Ask the user first: "Should I create a new project for Phase 2, or add to the existing project?"
```

**Decision Criteria:**
- **Same Project**: If work is part of the same product/repository
- **New Project**: If starting a completely separate effort or major initiative
- **For HA Boss**: All phases use the same project (Project #1)

#### Managing Issues on the Project Board

**Using GitHub MCP (Recommended):**

While the GitHub MCP server doesn't have direct project management tools yet, you can:
1. Issues are automatically added to the project when created
2. Update issue status by changing labels or closing issues
3. Ask the user if manual project board updates are needed

**Manual Updates (when needed):**
- Issues typically auto-link when created in the repository
- Status can be updated via the GitHub web UI
- Claude can remind the user to update project status

#### Project Board Best Practices

1. **Proactive Updates**: Update status as work progresses, not at the end
2. **Status Accuracy**: Ensure status reflects reality:
   - **Todo**: Not yet started
   - **In Progress**: Actively working on it
   - **Done**: PR merged and issue closed
3. **Epic Tracking**: Keep epics updated with completion status of sub-tasks
4. **Blocked Items**: If blocked, comment on the issue with details
5. **Regular Reviews**: Suggest project board reviews during phase transitions

#### Example: Creating Issues for Phase 2

```python
# After creating issues #26-#32 for Phase 2:

# 1. Verify issues were created
#    ✓ All 7 issues created

# 2. Check if they're on the project board
#    (Usually automatic for repository issues)

# 3. If not automatic, inform the user:
#    "Issues #26-#32 have been created for Phase 2. They should
#     automatically appear on the project board. You can view them at:
#     https://github.com/users/jasonthagerty/projects/1"

# 4. Suggest organizing by phase:
#    "I recommend filtering the project board by 'phase-2' label to
#     see all Phase 2 work items."
```

#### Example: Updating Status After Completing Work

```python
# After merging PR for Issue #26:

# 1. Issue automatically closes (via "Closes #26" in PR)
# 2. Project board status updates to "Done" (automatic in most cases)
# 3. Update epic checklist (if applicable)
# 4. Move to next issue in the dependency chain

# No manual project board update needed in most cases!
```

#### Troubleshooting Project Board Issues

**Issue doesn't appear on project board:**
- Check if repository is linked to the project
- Manually add via issue sidebar → "Projects"
- Verify project permissions

**Status not updating:**
- GitHub Projects (v2) usually auto-update based on issue state
- Classic Projects may need manual updates
- Check project automation rules

**Creating a New Project (if needed):**

Ask the user first, then if approved:
```bash
# Using gh CLI (if available):
gh project create --owner jasonthagerty --title "HA Boss Phase 2" \
  --body "Track Phase 2 pattern collection work"

# Or guide the user through GitHub web UI:
# 1. Go to https://github.com/users/jasonthagerty/projects
# 2. Click "New project"
# 3. Choose template (Board, Table, or Roadmap)
# 4. Configure fields and views
```

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

### GitHub Integration

**Recommended: GitHub MCP Server** (see section below)
- Provides direct GitHub API access for issues, PRs, and repository operations
- Works in all environments (web, desktop, CI/CD)
- No CLI dependencies required

**Alternative: GitHub App Integration** (legacy)
- For workflow automation and CI/CD triggers
- Steps:
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
