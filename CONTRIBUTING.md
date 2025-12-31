# Contributing to HA Boss

Thank you for your interest in contributing to HA Boss! This guide will help you get started.

## Quick Start

### Prerequisites
- **Python 3.12** (required for CI compatibility)
- **uv** (recommended) - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Steps

1. Fork the repository
2. Clone your fork: `git clone https://github.com/jasonthagerty/ha_boss.git`
3. Set up development environment:
   ```bash
   # With uv (recommended)
   uv venv --python 3.12
   source .venv/bin/activate
   uv pip install -e ".[dev]"

   # Or use make
   make install
   ```
4. Create a branch: `git checkout -b feature/your-feature-name`
5. Make your changes
6. Run tests: `make test` or `pytest`
7. Run CI checks: `make ci-check`
8. Commit and push
9. Open a Pull Request

## Development with Claude Code

This project is optimized for development with Claude Code. You can:

- Use `@claude` in issues to get AI assistance
- Use custom slash commands like `/test`, `/lint`, `/ci-check`
- CI failures automatically create issues for Claude to investigate
- Claude can create PRs directly from issue descriptions

### Custom Slash Commands

- `/test` - Run full test suite with coverage
- `/lint` - Run all code quality checks
- `/fix-style` - Auto-fix formatting issues
- `/ci-check` - Run complete CI pipeline locally
- `/review-pr [number]` - Get AI code review

See `.claude/commands/` for all available commands.

## Code Standards

### Style Guide

- **Python Version**: 3.12 (required for CI consistency)
- **Package Manager**: uv (recommended for speed)
- **Line Length**: 100 characters
- **Formatting**: Black
- **Linting**: Ruff
- **Type Checking**: mypy with strict mode

### Code Quality Checklist

Before submitting a PR, ensure:

- [ ] Code is formatted with black (`make format`)
- [ ] No linting errors (`make lint`)
- [ ] All tests pass (`make test`)
- [ ] Type hints added to all functions
- [ ] Code coverage maintained (minimum 80%)
- [ ] Docstrings added for public APIs
- [ ] No security vulnerabilities introduced

### Commit Messages

Write clear, descriptive commit messages:

```
feat: add support for Home Assistant webhook automation

- Implement webhook receiver endpoint
- Add validation for webhook payloads
- Include tests for error cases
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## Testing

### Writing Tests

- Place tests in `tests/` directory
- Mirror source structure: `ha_boss/module.py` → `tests/test_module.py`
- Use descriptive test names: `test_webhook_validates_payload()`
- Use pytest fixtures for common setup
- Add markers for slow/integration tests

Example:
```python
import pytest
from ha_boss.module import function

@pytest.mark.asyncio
async def test_async_function() -> None:
    """Test that function works correctly."""
    result = await function()
    assert result == expected_value
```

### Running Tests

```bash
# All tests
make test

# Specific test file
pytest tests/test_module.py

# Specific test
pytest tests/test_module.py::test_function_name

# With verbose output
pytest -v

# Skip slow tests
pytest -m "not slow"
```

## CI/CD Pipeline

All PRs must pass CI checks:

1. **Format Check**: Black formatting
2. **Lint Check**: Ruff linting
3. **Type Check**: mypy type checking
4. **Tests**: pytest with coverage

Run locally before pushing:
```bash
make ci-check
```

## Pull Request Process

1. **Update Documentation**: If you change functionality, update relevant docs
2. **Add Tests**: New features need tests
3. **Update CLAUDE.md**: For architectural changes
4. **Link Issues**: Reference related issues in PR description
5. **Request Review**: Tag `@claude` for AI review

### PR Scope Guidelines

**Keep PRs Small and Focused** - Smaller PRs are easier to review, test, and merge safely.

**Size Limits** (aim for these targets):
- **Lines Changed**: < 500 lines (ideal), < 1000 lines (acceptable), > 1000 (split it!)
- **Files Changed**: < 10 files (ideal), < 20 files (max)
- **Commits**: 1-5 commits per PR (squash related changes)
- **Review Time**: Should be reviewable in < 30 minutes

**When to Split a PR**:
- Refactoring + new features → Separate PRs
- Multiple unrelated bug fixes → Separate PRs
- Large architectural changes → Phase into multiple PRs
- Changes affecting > 20 test files → Split by component

**Good PR Examples**:
- ✅ "Add WebSocket reconnection logic" (1 file, 150 lines, 5 tests)
- ✅ "Fix config validation for multi-instance" (3 files, 200 lines)
- ✅ "Refactor StateTracker to use async" (2 files, 300 lines)

**Bad PR Examples**:
- ❌ "Implement multi-instance support" (50 files, 3000 lines) → Split into:
  - PR 1: Add multi-instance config structure
  - PR 2: Update database models for multi-instance
  - PR 3: Refactor components to accept instance_id
  - PR 4: Update CLI for multi-instance
  - PR 5: Update tests for multi-instance

**Exception**: Breaking changes that must be atomic CAN be larger, but:
- Require detailed migration guide
- Include comprehensive test coverage
- Update ALL affected tests in the same PR
- Get approval from maintainers first

### PR Template

The PR template will guide you through providing:
- Description of changes
- Type of change
- Testing performed
- Code quality checklist

## Getting Help

- **Issues**: Open a GitHub issue
- **Discussions**: Use GitHub Discussions for questions
- **Claude Code**: Tag `@claude` in issues for AI assistance

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
