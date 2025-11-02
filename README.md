# HA Boss

A Home Assistant management service to make Home Assistant more robust, easier to manage, and easier to automate.

## Project Status

🚧 **Under Development** - MVP Phase 1 (Core Infrastructure Complete)

**What's Working:**
- ✅ Configuration system with Pydantic validation
- ✅ SQLAlchemy async database models
- ✅ Test infrastructure (18/18 tests passing)
- ✅ CI/CD with GitHub Actions

**Next Up:**
- Home Assistant API client (REST + WebSocket)
- Real-time monitoring and health detection
- Auto-healing with circuit breakers

## Development

This project uses **Python 3.12** and **uv** for fast, reliable package management. Claude Code is used for AI-assisted development with automated CI/CD integration.

### Prerequisites

- **Python 3.12** (required - matches CI environment)
- **uv** - Fast Python package installer (recommended)
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Home Assistant instance (for integration testing)

### Setup

**With uv (recommended):**
```bash
# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -e ".[dev]"
```

**Without uv (traditional):**
```bash
# Create virtual environment
python3.12 -m venv venv
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

# Lint and auto-fix
ruff check --fix .

# Type check
mypy ha_boss

# Run all CI checks locally
black --check . && ruff check . && mypy ha_boss && pytest
```

## CI/CD

This project uses GitHub Actions with Claude Code integration:
- Automated testing on push/PR
- CI failures automatically create GitHub issues tagged for Claude
- Claude can be invoked with `@claude` in issue comments

## Contributing

See [CLAUDE.md](CLAUDE.md) for AI development guidelines and project architecture.
