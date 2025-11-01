# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HA Boss is a Home Assistant management service designed to make Home Assistant more robust, easier to manage, and easier to automate. The project is built with Python 3.11+ and follows modern Python development practices.

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
├── ha_boss/           # Main package code
│   └── __init__.py
├── tests/             # Test suite
│   ├── __init__.py
│   └── test_*.py
├── .claude/           # Claude Code configuration
│   ├── commands/      # Custom slash commands
│   └── settings.json  # Project preferences
├── .github/           # GitHub configuration
│   ├── workflows/     # CI/CD pipelines
│   └── ISSUE_TEMPLATE/ # Issue templates
└── pyproject.toml     # Project metadata and dependencies
```

### Key Design Patterns

- **Async-First**: Use `async`/`await` for all I/O operations, especially Home Assistant API calls
- **Type Hints**: All functions must have complete type annotations
- **Dependency Injection**: Use dependency injection for testability
- **Error Handling**: Wrap external API calls in try/except with specific error types

### Code Organization

When adding new features:
1. Create module in `ha_boss/` directory
2. Add corresponding tests in `tests/test_<module>.py`
3. Use async patterns for I/O operations
4. Add type hints to all functions
5. Update this CLAUDE.md if architecture changes

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

### API Interactions

- Use aiohttp for async HTTP requests
- Implement retry logic with exponential backoff
- Cache state when appropriate
- Handle connection errors gracefully
- Respect Home Assistant rate limits

### Configuration

Home Assistant connection details should be loaded from environment variables:
- `HA_URL`: Home Assistant instance URL
- `HA_TOKEN`: Long-lived access token

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
