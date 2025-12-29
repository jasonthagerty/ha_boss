# Development Guide

This comprehensive guide covers everything you need to know to contribute to HA Boss, from initial setup to submitting pull requests.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Contributing Guidelines](#contributing-guidelines)
- [CI/CD Integration](#cicd-integration)
- [Claude Code Integration](#claude-code-integration)

## Prerequisites

### Required Tools

- **Python 3.12** (required for consistency with CI)
  - Why 3.12: Ensures local development matches CI environment
  - Install: See [python.org/downloads](https://www.python.org/downloads/)

- **uv** (fast Python package installer - recommended)
  - Why uv: 10-100x faster than pip for installations
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Alternative: Standard pip/venv (slower but works)

### Optional Tools

- **GitHub MCP Server** (recommended for issue/PR management)
  - See [Claude Code Integration](#claude-code-integration) section
  - Alternative: GitHub CLI (`gh`)

### Tools Pre-installed in CI

The following are available in GitHub Actions runners:
- `git` - version control
- `gh` (GitHub CLI) - available as fallback

## Development Setup

### Method 1: Using uv (Recommended)

Fast setup with modern Python package management:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install with development dependencies
uv pip install -e ".[dev]"
```

### Method 2: Traditional venv

Standard Python virtual environment approach:

```bash
# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment with Python 3.12
python3.12 -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate    # Windows

# Install with development dependencies
pip install -e ".[dev]"
```

### Method 3: Using Make

Simplified setup with Makefile:

```bash
# Clone and setup
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Install everything (creates venv, installs deps)
make install

# Activate the created virtual environment
source .venv/bin/activate
```

### Verify Installation

```bash
# Check HA Boss is installed
haboss --version

# Verify development dependencies
pytest --version
black --version
ruff --version
mypy --version
```

## Testing

### Test Structure

Tests follow the source code structure:

```
ha_boss/
├── core/
│   └── config.py
└── monitoring/
    └── health_monitor.py

tests/
├── core/
│   └── test_config.py
└── monitoring/
    └── test_health_monitor.py
```

### Running Tests

**Run all tests:**
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Run with coverage report
pytest --cov=ha_boss --cov-report=html --cov-report=term

# Or use make
make test
```

**Run specific test file:**
```bash
pytest tests/test_example.py -v
```

**Run specific test function:**
```bash
pytest tests/test_example.py::test_function_name -v
```

**Run tests matching pattern:**
```bash
pytest -k "test_async" -v
```

**Run with specific markers:**
```bash
# Skip slow tests
pytest -m "not slow" -v

# Run only integration tests
pytest -m "integration" -v
```

**Run with verbose output:**
```bash
pytest -v
pytest -vv  # Extra verbose
```

### Writing Tests

**Basic test structure:**

```python
import pytest
from ha_boss.module import function

def test_basic_function() -> None:
    """Test that function works correctly."""
    result = function(input_value)
    assert result == expected_value
```

**Async test structure:**

```python
import pytest

@pytest.mark.asyncio
async def test_async_function() -> None:
    """Test async function behavior."""
    result = await some_async_function()
    assert result == expected_value
```

**Using fixtures:**

```python
import pytest
from ha_boss.core.config import Config

@pytest.fixture
def sample_config() -> Config:
    """Provide sample configuration for tests."""
    return Config(
        home_assistant_url="http://localhost:8123",
        home_assistant_token="test_token"
    )

def test_with_fixture(sample_config: Config) -> None:
    """Test using fixture."""
    assert sample_config.home_assistant_url == "http://localhost:8123"
```

**Marking tests:**

```python
import pytest

@pytest.mark.slow
def test_slow_operation() -> None:
    """Test that takes a long time."""
    # Slow operation here
    pass

@pytest.mark.integration
async def test_integration_with_ha() -> None:
    """Test integration with Home Assistant."""
    # Integration test here
    pass
```

### Coverage Requirements

- **Minimum coverage**: 80% (currently at 81%)
- **New features**: Must include tests
- **Bug fixes**: Should include regression tests
- **View coverage**: Open `htmlcov/index.html` after running tests

### Test Guidelines

1. **Mirror source structure**: `ha_boss/module.py` → `tests/test_module.py`
2. **Use pytest fixtures**: For common setup and teardown
3. **Mark appropriately**: Use `@pytest.mark.slow` or `@pytest.mark.integration`
4. **Test edge cases**: Not just the happy path
5. **Use descriptive names**: `test_webhook_validates_invalid_payload()`
6. **Add docstrings**: Explain what the test validates
7. **Keep tests isolated**: Each test should be independent
8. **Mock external services**: Don't rely on live Home Assistant for unit tests

## Code Quality

### Formatting and Style

**Standards:**
- **Line length**: 100 characters (enforced by black and ruff)
- **Import order**: stdlib, third-party, local (managed by ruff)
- **Docstrings**: Google-style docstrings for public APIs
- **Type hints**: Required for all function signatures

**Auto-format code:**

```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Format all Python files
black .

# Or use make
make format
```

**Lint and auto-fix:**

```bash
# Lint with automatic fixes
ruff check --fix .

# Or use make
make lint
```

**Type checking:**

```bash
# Run mypy type checker
mypy ha_boss

# Or use make
make typecheck
```

**Complete CI check:**

```bash
# Run all checks (format, lint, type, test)
black --check . && ruff check . && mypy ha_boss && pytest

# Or use make
make ci-check
```

### Type Hints Example

All functions must have complete type annotations:

```python
from typing import Any

def process_data(data: dict[str, Any], timeout: int = 30) -> list[str]:
    """
    Process data and return list of keys.

    Args:
        data: Dictionary to process
        timeout: Operation timeout in seconds

    Returns:
        List of dictionary keys

    Raises:
        ValueError: If data is empty
    """
    if not data:
        raise ValueError("Data cannot be empty")
    return list(data.keys())
```

### Docstring Format (Google Style)

```python
def complex_function(
    entity_id: str,
    timeout: int = 30,
    retry: bool = True
) -> dict[str, Any]:
    """
    Fetch entity state with retry capability.

    This function retrieves the current state of a Home Assistant entity,
    with optional retry logic for handling transient failures.

    Args:
        entity_id: The Home Assistant entity ID (e.g., "sensor.temperature")
        timeout: Request timeout in seconds (default: 30)
        retry: Whether to retry on failure (default: True)

    Returns:
        Dictionary containing entity state and attributes:
        {
            "state": "on",
            "attributes": {...},
            "last_updated": "2024-01-01T00:00:00"
        }

    Raises:
        HomeAssistantConnectionError: If connection fails after retries
        ValueError: If entity_id format is invalid

    Example:
        >>> state = complex_function("sensor.temperature", timeout=60)
        >>> print(state["state"])
        "23.5"
    """
    # Implementation here
    pass
```

### Error Handling

**Prefer specific exceptions:**

```python
# Good - specific exception with context
try:
    result = await ha_client.get_state(entity_id)
except HomeAssistantConnectionError as e:
    logger.error(f"Failed to connect to HA: {e}")
    raise
except HomeAssistantAuthError as e:
    logger.error(f"Authentication failed: {e}")
    # Alert user and stop service
    raise

# Avoid - generic exception swallowing
try:
    result = await ha_client.get_state(entity_id)
except Exception as e:
    pass  # Never do this!
```

**Implement retry logic:**

```python
async def fetch_with_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0
) -> Any:
    """
    Call function with exponential backoff retry.

    Args:
        func: Async function to call
        max_attempts: Maximum retry attempts
        base_delay: Base delay in seconds (doubles each retry)

    Returns:
        Result from successful function call

    Raises:
        Exception from func if all retries exhausted
    """
    for attempt in range(max_attempts):
        try:
            return await func()
        except HomeAssistantConnectionError as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s")
            await asyncio.sleep(delay)
```

## Development Workflow

### Feature Branch Workflow

All development work is tracked via GitHub Issues and managed through feature branches.

#### 1. Issue-Driven Development

**GitHub Issues are the source of truth:**
- View issues: https://github.com/jasonthagerty/ha_boss/issues
- Project board: https://github.com/users/jasonthagerty/projects/1
- Issues labeled `claude-task` are assignable to Claude Code
- Issues include acceptance criteria, technical notes, and branch names

#### 2. Branch Naming Convention

**Format:** `<type>/issue-<number>-<brief-description>`

**Types:**
- `feature/` - New features (most common)
- `fix/` - Bug fixes
- `docs/` - Documentation only changes
- `refactor/` - Code refactoring without functional changes
- `test/` - Adding or updating tests

**Examples:**
- `feature/issue-2-integration-discovery`
- `fix/issue-15-websocket-reconnect`
- `docs/issue-8-update-readme`
- `refactor/issue-20-simplify-state-tracker`

#### 3. Complete Feature Workflow

```bash
# 1. Review the issue on GitHub
#    - Read description and acceptance criteria
#    - Check for dependencies
#    - Understand scope

# 2. Comment on the issue
#    "Starting work on this issue"

# 3. Create feature branch
git checkout -b feature/issue-42-new-feature

# 4. Implement the feature
#    - Follow acceptance criteria
#    - Add complete type hints
#    - Write tests (≥80% coverage)
#    - Add docstrings for public APIs

# 5. Run tests locally
pytest

# 6. Run code quality checks
black --check . && ruff check . && mypy ha_boss

# 7. Or run complete CI check
make ci-check

# 8. Commit with conventional commit message
git add .
git commit -m "feat: implement new feature

- Created FeatureClass with full type hints
- Added comprehensive test coverage (85%)
- Updated documentation

Closes #42

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 9. Push to your fork or origin
git push origin feature/issue-42-new-feature

# 10. Create Pull Request
#     - Include "Closes #42" in description
#     - Add summary of changes
#     - List testing performed
```

#### 4. Managing Epics and Sub-Tasks

**Epics** track large features with multiple sub-tasks.

**Epic Structure:**
- Use checkboxes: `- [ ] #26: Task description`
- Label with `epic` and phase label
- Link sub-tasks back to epic: `**Epic**: #25`

**Workflow:**
1. Create epic with checklist of sub-tasks
2. Create individual issues for each sub-task
3. Update checklist as sub-tasks complete: `- [x] #26: Task ✓`
4. Close epic when all sub-tasks are done

#### 5. Branch Protection

- `main` branch is protected
- All changes must go through PRs
- CI checks must pass before merge
- Squash commits on merge to keep history clean

## Code Standards

### Code Organization Rules

When adding new features:

1. **Module Placement**
   - Core infrastructure → `core/`
   - Feature-specific code → appropriate subdirectory
   - Example: Monitoring features → `monitoring/`

2. **Tests**
   - Mirror source structure in `tests/` directory
   - Example: `ha_boss/core/config.py` → `tests/core/test_config.py`

3. **Type Hints**
   - All functions must have complete annotations
   - Use modern type syntax: `dict[str, Any]` not `Dict[str, Any]`

4. **Async**
   - Use async/await for all I/O operations
   - Use `asyncio.gather()` for concurrent operations

5. **Error Handling**
   - Specific exceptions with retry logic
   - Never use bare `except:` or `except Exception:`

6. **Documentation**
   - Docstrings for all public APIs (Google style)
   - Inline comments for complex logic
   - Update relevant wiki pages for major changes

7. **Configuration**
   - New settings → Pydantic models in `core/config.py`
   - Environment variables in `.env.example`
   - Document in Configuration wiki page

8. **Database**
   - New tables/columns → schema updates in `core/database.py`
   - Add migration notes in comments
   - Update database schema documentation

### Formatting Standards

**Line Length:**
```python
# Maximum 100 characters
def long_function_name(
    parameter_one: str,
    parameter_two: int,
    parameter_three: bool = False
) -> dict[str, Any]:
    """Function with many parameters."""
    pass
```

**Import Order:**
```python
# 1. Standard library imports
import asyncio
import logging
from typing import Any

# 2. Third-party imports
import aiohttp
from pydantic import BaseModel

# 3. Local imports
from ha_boss.core.config import Config
from ha_boss.core.database import Database
```

**Docstrings:**
```python
def public_function() -> None:
    """
    All public functions must have docstrings.

    Use Google-style format with Args, Returns, Raises sections.
    """
    pass

def _private_function() -> None:
    # Private functions can have brief comments instead
    pass
```

## Contributing Guidelines

### Before You Start

1. **Check existing issues**: Avoid duplicate work
2. **Discuss major changes**: Open an issue first for architectural changes
3. **Read the docs**: Familiarize yourself with the codebase
4. **Fork the repository**: Work in your own fork

### Pull Request Process

1. **Update Documentation**
   - README.md for user-facing changes
   - CLAUDE.md for architectural changes
   - Wiki pages for major features

2. **Add Tests**
   - Unit tests for new functionality
   - Integration tests for external interactions
   - Regression tests for bug fixes

3. **Maintain Coverage**
   - Ensure coverage stays ≥80%
   - Run `pytest --cov` to verify

4. **Follow Code Standards**
   - Run `make ci-check` before pushing
   - Fix all linting, type, and test issues

5. **Write Clear Commit Messages**
   - Use conventional commits
   - Reference issue numbers
   - Include co-author attribution

6. **Create Comprehensive PR**
   - Fill out PR template completely
   - Link related issues
   - Describe testing performed

### Commit Message Format

**Conventional Commits:**

```
<type>: <description>

[optional body]

[optional footer(s)]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**

```
feat: add webhook automation support

- Implement webhook receiver endpoint
- Add payload validation
- Include comprehensive tests

Closes #42
```

```
fix: prevent WebSocket reconnection loop

The WebSocket client was not respecting the maximum backoff
time, causing infinite reconnection attempts. This adds a
maximum backoff check and circuit breaker.

Fixes #56
```

```
docs: update configuration guide with LLM settings

Added documentation for:
- Ollama configuration
- Claude API setup
- LLM router behavior

Closes #78
```

### Code Quality Checklist

Before submitting a PR, verify:

- [ ] Code is formatted with black (`make format`)
- [ ] No linting errors (`ruff check .`)
- [ ] Type checking passes (`mypy ha_boss`)
- [ ] All tests pass (`pytest`)
- [ ] Code coverage ≥80% (`pytest --cov`)
- [ ] Type hints added to all functions
- [ ] Docstrings added for public APIs
- [ ] No security vulnerabilities (`bandit ha_boss`)
- [ ] Documentation updated (README, wiki, etc.)
- [ ] CLAUDE.md updated (for architectural changes)

## CI/CD Integration

### GitHub Actions Workflows

**CI Pipeline** (`.github/workflows/ci.yml`):
- Runs on: push to main/develop, all PRs
- Tests: Python 3.12 only (standardized)
- Checks: black, ruff, mypy, pytest
- Auto-creates issue on main branch failures (tagged `claude-task`)

**Claude Code Action** (`.github/workflows/claude.yml`):
- Triggers on: `@claude` mentions or `claude-task` label
- Enables: automated PR creation and issue updates

**Security Scan** (`.github/workflows/security.yml`):
- Runs on: push and weekly schedule
- Tools: bandit (code security), safety (dependency security)

### Working with CI Failures

When CI fails on main branch:

1. **Review the Issue**
   - Automated issue created with failure details
   - Check workflow logs for root cause
   - Identify which check failed

2. **Create Fix Branch**
   ```bash
   git checkout -b fix/issue-{number}-ci-failure
   ```

3. **Implement Fix**
   - Fix the failing check
   - Add regression test if applicable
   - Run `make ci-check` locally to verify

4. **Submit PR**
   ```bash
   git commit -m "fix: resolve CI failure

   - Fixed failing test/lint/type check
   - Added regression test

   Closes #{number}"

   git push origin fix/issue-{number}-ci-failure
   ```

### Local CI Simulation

Run the complete CI pipeline locally:

```bash
# Complete check
make ci-check

# Or manually
black --check .
ruff check .
mypy ha_boss
pytest --cov=ha_boss --cov-report=term
```

## Claude Code Integration

### Slash Commands

Custom slash commands available in `.claude/commands/`:

**Testing:**
- `/test` - Run full test suite with coverage
- `/test-file [path]` - Run tests for specific file
- `/add-test [module]` - Generate tests for a module

**Code Quality:**
- `/lint` - Run all code quality checks
- `/fix-style` - Auto-fix formatting and style issues
- `/ci-check` - Run complete CI pipeline locally

**Development:**
- `/setup-dev` - Guide through development environment setup
- `/review-pr [number]` - Review a pull request

**Usage:**
```bash
# In Claude Code chat
/test                           # Run all tests
/test-file tests/test_config.py # Run specific test file
/lint                           # Check code quality
/ci-check                       # Full CI simulation
```

### GitHub MCP Server Integration

**Recommended** for all GitHub operations (issues, PRs, labels).

**Why Use GitHub MCP Server?**

- Works in any environment (web, desktop, containers, CI/CD)
- Direct API access through structured MCP tools
- No dependency on `gh` CLI installation
- Consistent interface across all Claude Code deployments
- Enables automated issue creation from CI failures

**Setup Instructions:**

1. **Install GitHub MCP Server:**
   ```bash
   # Install globally via npm (optional, npx can be used without install)
   npm install -g @modelcontextprotocol/server-github
   ```

2. **Create GitHub Personal Access Token:**
   - GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Click "Generate new token (classic)"
   - Select scopes: `repo`, `issues`, `workflow`
   - Copy token immediately (cannot be retrieved later)

3. **Configure MCP Server:**

   Create or edit user-level config:
   - Linux/Mac: `~/.config/claude/mcp.json`
   - Windows: `%APPDATA%\Claude\mcp.json`

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

4. **Restart Claude Code** to load configuration

5. **Verify Installation:**
   - GitHub tools should be available in Claude Code
   - Can create/update issues, PRs, add labels, etc.

**Security Notes:**

- **NEVER commit** `mcp.json` with real tokens
- Store in user-level config directory (not tracked by git)
- `.claude/mcp.json.example` is for reference only
- Protect tokens like passwords
- Rotate tokens periodically

**Troubleshooting:**

- "GitHub MCP server not found" → Ensure `npx` is available (requires Node.js)
- "Authentication failed" → Verify token has correct scopes (`repo`, `issues`)
- "Permission denied" → Check token hasn't expired
- Config not loading → Ensure `mcp.json` is in correct OS location

**Detailed Guide:** See `.claude/GITHUB_MCP_SETUP.md` for comprehensive setup instructions.

### Remote Development

Project configured for remote development:

- **DevContainer**: `.devcontainer/devcontainer.json`
- **VS Code Settings**: `.vscode/settings.json`
- **Claude Settings**: `.claude/settings.json`

### Pre-commit Hooks

Pre-commit hooks available but disabled by default.

**Enable in `.claude/settings.json`:**
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

## Common Workflows

### Adding a New Feature

1. Find or create GitHub issue
2. Comment "Starting work on this issue"
3. Create branch: `feature/issue-{number}-description`
4. Implement feature with tests
5. Run `make ci-check`
6. Commit with conventional commit message
7. Push and create PR with "Closes #{number}"

### Fixing a Bug

1. Review bug issue and reproduce locally
2. Add regression test that reproduces the bug
3. Create branch: `fix/issue-{number}-description`
4. Implement fix and verify test passes
5. Run `make ci-check`
6. Create PR with "Closes #{number}"

### Discovering Bugs During Development

When discovering bugs during feature work:

1. **Create GitHub issue** with description and error messages
2. **Fix immediately if**: blocking, simple, or affects core functionality
3. **Defer if**: complex, not blocking, or needs discussion
4. **If fixing now**: Include in current branch/PR with "Fixes #number"

**Example:**
```bash
# Create issue for tracking
gh issue create --title "bug: invalid config validation" --label "bug,priority-high"

# Fix in current branch
git commit -m "fix: correct config validation logic

This also addresses a bug where invalid configs were
accepted during startup.

Fixes #21
Closes #42"
```

### Reviewing PRs

Use `/review-pr [number]` command for AI-assisted review:

- Check code follows style guidelines
- Verify tests are included
- Ensure no security issues
- Validate type hints
- Check documentation updates

## Getting Help

- **Issues**: [Open a GitHub issue](https://github.com/jasonthagerty/ha_boss/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)
- **Claude Code**: Tag `@claude` in issues for AI assistance
- **Documentation**: [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki)

---

**Related Documentation:**
- [Architecture Guide](Architecture.md) - Technical design and component overview
- [Contributing Guide](../../CONTRIBUTING.md) - Quick start for contributors
- [Configuration Guide](https://github.com/jasonthagerty/ha_boss/wiki/Configuration) - Complete configuration reference
