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

## Quick Start with Docker (Recommended)

The easiest way to run HA Boss is with Docker:

```bash
# 1. Clone the repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# 2. Create .env file with your Home Assistant credentials
cp .env.example .env
# Edit .env and add your HA_URL and HA_TOKEN

# 3. Create config directory and copy example config
mkdir -p config data
cp config/config.yaml.example config/config.yaml
# Optionally customize config/config.yaml

# 4. Start with Docker Compose
docker-compose up -d

# 5. Check status
docker-compose logs -f
docker-compose ps
```

### Docker Configuration

**Environment Variables** (`.env` file):
- `HA_URL` - Your Home Assistant URL (e.g., `http://homeassistant.local:8123`)
- `HA_TOKEN` - Long-lived access token from Home Assistant
- `TZ` - Timezone (optional, defaults to UTC)

**Volume Mounts**:
- `./config` - Configuration files (mounted read-only)
- `./data` - Database and runtime data (persistent)

**Health Checks**:
The container includes automatic health checks that verify:
- Database initialization
- Service process running

**Resource Limits**:
Default limits: 1 CPU, 512MB RAM (adjust in docker-compose.yml if needed)

### Docker Commands

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Check health status
docker-compose ps

# Stop the service
docker-compose down

# Rebuild after code changes
docker-compose build
docker-compose up -d

# Run CLI commands
docker-compose exec haboss haboss status
docker-compose exec haboss haboss config validate
docker-compose exec haboss haboss heal sensor.example
```

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
