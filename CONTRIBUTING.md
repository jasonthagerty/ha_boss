# Contributing to HA Boss

Thank you for your interest in contributing to HA Boss! This guide will help you get started.

## Quick Start

1. Fork the repository
2. Clone your fork: `git clone https://github.com/yourusername/ha_boss.git`
3. Set up development environment: `make install` or `pip install -e ".[dev]"`
4. Create a branch: `git checkout -b feature/your-feature-name`
5. Make your changes
6. Run tests: `make test`
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

- **Python Version**: 3.11+
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
