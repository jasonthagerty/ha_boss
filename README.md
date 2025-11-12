# HA Boss

[![CI Status](https://github.com/jasonthagerty/ha_boss/workflows/CI/badge.svg)](https://github.com/jasonthagerty/ha_boss/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and provides intelligent automation management. HA Boss acts as a watchdog for your smart home, detecting issues before they become problems and fixing them automatically.

## 🎯 Project Status

**✅ MVP Phase 1 Complete** - Production Ready!

All core monitoring and auto-healing features are fully implemented, tested, and ready for deployment:

- ✅ Real-time entity monitoring via WebSocket
- ✅ Automatic detection of unavailable/stale entities
- ✅ Auto-healing via integration reload with safety mechanisms
- ✅ Circuit breakers and cooldown periods
- ✅ Escalated notifications when auto-healing fails
- ✅ Docker-first deployment with health checks
- ✅ Service orchestration with full lifecycle management
- ✅ 237 comprehensive tests with full coverage
- ✅ Complete CLI with 6 commands
- ✅ SQLite database for tracking and analysis

**Phase 2 - Ready to Start:**
- Pattern collection & analysis (Epic #25 planned)
- Integration reliability tracking
- CLI reports for failure trends
- Foundation for ML-based anomaly detection

## ✨ Key Features

### Monitoring & Detection
- **Real-time Monitoring**: WebSocket connection to Home Assistant for instant state updates
- **Health Detection**: Automatically identifies unavailable or stale entities
- **Grace Periods**: Configurable delays to avoid false positives
- **Entity Filtering**: Include/exclude patterns for focused monitoring

### Auto-Healing
- **Integration Reload**: Automatically reloads failed integrations
- **Circuit Breakers**: Stops trying after repeated failures to prevent loops
- **Cooldown Periods**: Prevents rapid retry storms
- **Dry-Run Mode**: Test healing actions without executing them
- **Manual Healing**: Trigger healing for specific entities via CLI

### Safety & Reliability
- **Graceful Degradation**: Continues operating with reduced functionality if HA disconnects
- **Automatic Reconnection**: Resilient WebSocket with exponential backoff
- **Database Tracking**: Complete history of all health events and healing actions
- **Escalation**: Persistent notifications when auto-healing fails

### Deployment & Operations
- **Docker-First**: Multi-stage build, non-root user, health checks
- **Resource Efficient**: ~128MB RAM usage, minimal CPU
- **Easy Configuration**: YAML config + environment variables
- **Rich CLI**: Beautiful terminal UI with status tables and progress indicators

## 🚀 Quick Start with Docker (Recommended)

The easiest way to run HA Boss is with Docker Compose:

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

### Creating a Home Assistant Long-Lived Token

1. Open Home Assistant in your browser
2. Click your profile (bottom left)
3. Scroll to "Long-Lived Access Tokens"
4. Click "Create Token"
5. Give it a name (e.g., "HA Boss")
6. Copy the token immediately (you won't see it again!)
7. Add it to your `.env` file as `HA_TOKEN=<your_token>`

### Docker Configuration

**Environment Variables** (`.env` file):
```bash
HA_URL=http://homeassistant.local:8123  # Your Home Assistant URL
HA_TOKEN=eyJ0eXAiOiJKV1...              # Long-lived access token
TZ=America/New_York                      # Optional: Timezone
```

**Volume Mounts**:
- `./config` - Configuration files (mounted read-only)
- `./data` - Database and runtime data (persistent)

**Health Checks**:
The container includes automatic health checks that verify:
- Database initialization
- Service process running

**Resource Limits**:
Default limits: 1 CPU core, 512MB RAM (adjust in `docker-compose.yml` if needed)

### Docker Commands

```bash
# Start the service
docker-compose up -d

# View logs (follow mode)
docker-compose logs -f

# Check health status
docker-compose ps

# Stop the service
docker-compose down

# Rebuild after code changes
docker-compose build
docker-compose up -d

# Run CLI commands inside container
docker-compose exec haboss haboss status
docker-compose exec haboss haboss config validate
docker-compose exec haboss haboss heal sensor.example
docker-compose exec haboss haboss db cleanup --older-than 30
```

## 📦 Installation (Local Development)

### Prerequisites

- **Python 3.11 or 3.12** (3.12 recommended)
- **uv** (optional but recommended) - Fast Python package installer
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Home Assistant instance with API access

### Setup with uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e ".[dev]"
```

### Setup with pip (Traditional)

```bash
# Clone the repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev]"
```

### Configuration

```bash
# Initialize configuration and database
haboss init

# Edit configuration files
# 1. config/.env - Add your HA_URL and HA_TOKEN
# 2. config/config.yaml - Customize settings (optional)

# Validate configuration
haboss config validate
```

## 🎮 Usage

### CLI Commands

HA Boss provides a comprehensive command-line interface:

#### `haboss init`
Initialize configuration and database:
```bash
haboss init
haboss init --config-dir ./config --data-dir ./data
haboss init --force  # Overwrite existing configuration
```

#### `haboss start`
Start the monitoring service:
```bash
haboss start                    # Start in background
haboss start --foreground       # Start in foreground (for Docker)
haboss start --config ./config/config.yaml
```

**Note**: The `start` command launches the full monitoring and auto-healing service. It will:
1. Connect to Home Assistant via WebSocket
2. Load current entity states
3. Begin monitoring for state changes
4. Automatically heal unavailable entities
5. Send notifications on failures

#### `haboss status`
Show service and entity health status:
```bash
haboss status
haboss status --detailed        # Show all monitored entities
haboss status --config ./config/config.yaml
```

Example output:
```
╭─ HA Boss Status ─────────────────────────────────────╮
│  Service        Status     Since                     │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  Connection     Connected  2025-11-04 10:30:15       │
│  Monitoring     Active     150 entities              │
│  Auto-Healing   Enabled    3 heals today             │
╰──────────────────────────────────────────────────────╯

Recent Health Events:
  • sensor.temperature_outdoor: unavailable → available (healed)
  • light.living_room: unavailable (healing failed, escalated)
  • binary_sensor.door: recovered automatically
```

#### `haboss heal`
Manually trigger healing for a specific entity:
```bash
haboss heal sensor.temperature_outdoor
haboss heal light.living_room --dry-run  # Show what would be done
haboss heal switch.garage_door --config ./config/config.yaml
```

#### `haboss config validate`
Validate configuration and test Home Assistant connection:
```bash
haboss config validate
haboss config validate --config ./config/config.yaml
```

Example output:
```
✓ Configuration file loaded successfully
✓ Home Assistant URL: http://homeassistant.local:8123
✓ Authentication successful
✓ Connected to Home Assistant 2024.11.1
✓ Database accessible
✓ All checks passed!
```

#### `haboss db cleanup`
Clean up old database records:
```bash
haboss db cleanup                    # Use retention_days from config
haboss db cleanup --older-than 30   # Delete records older than 30 days
haboss db cleanup --dry-run         # Show what would be deleted
```

### Configuration File

The `config/config.yaml` file controls all aspects of HA Boss behavior:

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "${HA_TOKEN}"  # References environment variable

monitoring:
  # Entities to monitor (empty = all)
  include: []

  # Entities to exclude
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sun.sun"

  # Wait 5 minutes before marking entity unavailable
  grace_period_seconds: 300

  # Threshold for stale entities (no update)
  stale_threshold_seconds: 3600

  # Periodic REST snapshot interval (validate WebSocket cache)
  snapshot_interval_seconds: 300

healing:
  enabled: true
  max_attempts: 3                 # Per integration
  cooldown_seconds: 300           # Between attempts
  circuit_breaker_threshold: 10   # Total failures before stopping
  circuit_breaker_reset_seconds: 3600

notifications:
  on_healing_failure: true
  weekly_summary: true
  ha_service: "persistent_notification.create"

logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "json"  # json or text
  file: "/data/ha_boss.log"

database:
  path: "/data/ha_boss.db"
  retention_days: 30

mode: "production"  # production, dry_run, or testing
```

See `config/config.yaml.example` for the complete configuration template with detailed comments.

## 🏗️ Architecture

### Component Overview

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

### Key Design Patterns

- **Async-First**: All I/O operations use `async`/`await`
- **Safety Mechanisms**: Circuit breakers, cooldowns, dry-run mode
- **Graceful Degradation**: Continues operating with reduced functionality
- **Error Handling**: Specific exceptions with exponential backoff retry logic

### Database Schema

HA Boss maintains a SQLite database tracking:
- **entities**: Entity registry and current states
- **health_events**: All detected health issues
- **healing_actions**: All healing attempts and results
- **integrations**: Integration discovery cache

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=ha_boss --cov-report=html --cov-report=term

# Run specific test file
pytest tests/cli/test_commands.py -v

# Run tests matching a pattern
pytest -k "test_heal" -v

# Run without slow tests
pytest -m "not slow" -v
```

Current test coverage: **237 tests**, all passing ✅

## 🔧 Development

### Code Quality Tools

```bash
# Format code (auto-fix)
black .

# Lint and auto-fix issues
ruff check --fix .

# Type checking
mypy ha_boss

# Run all CI checks locally
black --check . && ruff check . && mypy ha_boss && pytest
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development workflow
- Code style guidelines
- Testing requirements
- Pull request process

### Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete architecture and AI development guidelines
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Detailed setup and GitHub integration guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines

## 📝 Example Use Cases

### Monitor Critical Sensors
Automatically heal sensor failures that control automations:
```yaml
monitoring:
  include:
    - "sensor.temperature_*"
    - "binary_sensor.motion_*"
    - "sensor.power_*"
```

### Exclude Noisy Entities
Skip entities that frequently go unavailable without issues:
```yaml
monitoring:
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "device_tracker.*"  # May go offline frequently
```

### Conservative Healing
For production, use longer grace periods and cooldowns:
```yaml
monitoring:
  grace_period_seconds: 600  # 10 minutes

healing:
  enabled: true
  cooldown_seconds: 600      # 10 minutes between attempts
  circuit_breaker_threshold: 5
```

### Aggressive Monitoring
For development/testing with faster response:
```yaml
monitoring:
  grace_period_seconds: 60   # 1 minute

healing:
  cooldown_seconds: 120      # 2 minutes between attempts
```

## 🔐 Security Considerations

- **Long-Lived Tokens**: Store in `.env` file, never commit to git
- **Docker Security**: Non-root user (UID 1000), no new privileges
- **Network Access**: HA Boss only needs outbound access to Home Assistant
- **File Permissions**: Config mounted read-only, data directory read-write

## 🐛 Troubleshooting

### Connection Issues

**Problem**: Can't connect to Home Assistant

**Solutions**:
1. Verify HA_URL is correct and accessible: `curl $HA_URL/api/`
2. Check token is valid: `haboss config validate`
3. Ensure Home Assistant is running
4. Check firewall rules

### Authentication Errors

**Problem**: 401 Unauthorized errors

**Solutions**:
1. Regenerate long-lived token in Home Assistant
2. Update HA_TOKEN in `.env` file
3. Restart HA Boss service

### High Memory Usage

**Problem**: Container using more than 512MB RAM

**Solutions**:
1. Reduce number of monitored entities
2. Increase `retention_days` threshold (clean up old records)
3. Run `haboss db cleanup` manually

### Healing Not Working

**Problem**: Entities stay unavailable

**Solutions**:
1. Check healing is enabled in config: `healing.enabled: true`
2. Verify circuit breaker not tripped: Check logs for "circuit breaker"
3. Ensure cooldown period has passed
4. Try manual healing: `haboss heal sensor.entity_id`
5. Check Home Assistant logs for integration-specific errors

## 📜 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🤝 Acknowledgments

- Built with [Claude Code](https://claude.com/claude-code) for AI-assisted development
- Powered by [Home Assistant](https://www.home-assistant.io/)
- Uses [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/) for beautiful CLI

## 📞 Support

- **Documentation**: See [CLAUDE.md](CLAUDE.md) and [SETUP_GUIDE.md](SETUP_GUIDE.md)
- **Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Discussions**: https://github.com/jasonthagerty/ha_boss/discussions

---

**Made with ❤️ for the Home Assistant community**
