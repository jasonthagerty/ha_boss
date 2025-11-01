# HA Boss

A Home Assistant management service to make Home Assistant more robust, easier to manage, and easier to automate.

## Project Status

🚧 **Under Development** - Infrastructure setup phase

## Development

This project uses Claude Code for AI-assisted development with automated CI/CD integration.

### Prerequisites

- Python 3.11+
- Home Assistant (for integration testing)

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ha_boss --cov-report=html

# Run specific test file
pytest tests/test_example.py
```

### Code Quality

```bash
# Format code
black .

# Lint code
flake8 .
ruff check .

# Type check
mypy ha_boss
```

## CI/CD

This project uses GitHub Actions with Claude Code integration:
- Automated testing on push/PR
- CI failures automatically create GitHub issues tagged for Claude
- Claude can be invoked with `@claude` in issue comments

## Contributing

See [CLAUDE.md](CLAUDE.md) for AI development guidelines and project architecture.
