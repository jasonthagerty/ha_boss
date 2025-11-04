# HA Boss - Complete Setup Guide

This guide provides detailed instructions for deploying and configuring HA Boss in production and development environments.

## Table of Contents

- [Production Deployment (Docker)](#production-deployment-docker)
- [Local Development Setup](#local-development-setup)
- [Configuration Guide](#configuration-guide)
- [Troubleshooting](#troubleshooting)
- [GitHub Integration Setup (for Contributors)](#github-integration-setup-for-contributors)

## Production Deployment (Docker)

Docker is the recommended deployment method for production use. It provides isolation, easy updates, and consistent behavior across platforms.

### Prerequisites

- Docker Engine 20.10+ or Docker Desktop
- Docker Compose v2.0+ (included with Docker Desktop)
- Home Assistant instance (accessible from Docker host)
- Long-lived access token from Home Assistant

### Step 1: Install Docker

**Linux (Ubuntu/Debian)**:
```bash
# Install Docker Engine
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose-plugin

# Add your user to docker group (optional, avoids sudo)
sudo usermod -aG docker $USER
newgrp docker
```

**macOS**:
```bash
# Download and install Docker Desktop from:
# https://www.docker.com/products/docker-desktop

# Or via Homebrew:
brew install --cask docker
```

**Windows**:
Download and install Docker Desktop from:
https://www.docker.com/products/docker-desktop

### Step 2: Get HA Boss

```bash
# Clone the repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Or download the latest release
wget https://github.com/jasonthagerty/ha_boss/archive/refs/heads/main.zip
unzip main.zip
cd ha_boss-main
```

### Step 3: Create Long-Lived Token

1. Open your Home Assistant web interface
2. Click on your profile (bottom left corner)
3. Scroll down to **"Long-Lived Access Tokens"** section
4. Click **"Create Token"**
5. Enter a name: `HA Boss`
6. Click **"OK"**
7. **Copy the token immediately** (you won't be able to see it again!)
8. Save it somewhere secure temporarily

### Step 4: Configure Environment

```bash
# Create .env file from example
cp .env.example .env

# Edit .env file
nano .env  # or vim, or your favorite editor
```

Add your Home Assistant details:
```bash
# Required: Your Home Assistant URL
HA_URL=http://192.168.1.100:8123
# or: HA_URL=http://homeassistant.local:8123
# or: HA_URL=https://your-domain.duckdns.org

# Required: Long-lived access token (paste from step 3)
HA_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...

# Optional: Set timezone (defaults to UTC)
TZ=America/New_York
```

**Important Notes**:
- Use the **internal** Home Assistant URL (not external/Nabu Casa)
- If using Docker on same host as HA, you may need `http://host.docker.internal:8123`
- On Linux, you may need to use the host's IP address (not `localhost`)

### Step 5: Customize Configuration (Optional)

```bash
# Create config directory
mkdir -p config data

# Copy example configuration
cp config/config.yaml.example config/config.yaml

# Edit configuration (optional)
nano config/config.yaml
```

The default configuration is suitable for most users. Key settings to consider:

```yaml
monitoring:
  grace_period_seconds: 300  # Wait 5 min before marking unavailable
  exclude:                   # Add entities to skip
    - "sensor.time*"
    - "device_tracker.*"     # Often go offline

healing:
  enabled: true
  max_attempts: 3            # Attempts per integration
  cooldown_seconds: 300      # Wait 5 min between attempts
```

See [Configuration Guide](#configuration-guide) below for all options.

### Step 6: Start HA Boss

```bash
# Start in detached mode (background)
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

Expected output:
```
NAME       STATUS        PORTS
ha-boss    Up (healthy)  8080/tcp
```

### Step 7: Verify Operation

```bash
# Check if HA Boss connected successfully
docker-compose logs | grep "Connected to Home Assistant"

# View current status
docker-compose exec haboss haboss status

# Test configuration
docker-compose exec haboss haboss config validate
```

You should see:
```
✓ Connected to Home Assistant 2024.11.1
✓ Monitoring 150 entities
✓ Auto-healing enabled
```

### Step 8: Monitor Logs

```bash
# Follow logs in real-time
docker-compose logs -f

# Show last 100 lines
docker-compose logs --tail=100

# Show only errors
docker-compose logs | grep ERROR
```

### Managing the Service

```bash
# Stop HA Boss
docker-compose down

# Restart (after config changes)
docker-compose restart

# Update to latest version
git pull origin main
docker-compose build
docker-compose up -d

# View resource usage
docker stats ha-boss

# Access database (for advanced users)
docker-compose exec haboss sqlite3 /app/data/ha_boss.db
```

### Troubleshooting Docker Deployment

**Problem**: Container keeps restarting

**Solution**:
```bash
# Check logs for errors
docker-compose logs

# Common issues:
# 1. Invalid HA_TOKEN - regenerate token
# 2. Wrong HA_URL - verify URL is accessible
# 3. Network issues - check firewall/routing
```

**Problem**: "Can't connect to Home Assistant"

**Solution**:
```bash
# Test connectivity from container
docker-compose exec haboss curl http://your-ha-url:8123/api/

# If using localhost, try host.docker.internal instead
# Edit .env: HA_URL=http://host.docker.internal:8123
```

**Problem**: Permission denied errors

**Solution**:
```bash
# Ensure data directory is writable
chmod 755 data/
chown 1000:1000 data/  # haboss user UID

# Or use sudo if needed
sudo chown -R 1000:1000 data/
```

## Local Development Setup

For contributing to HA Boss or local testing without Docker.

### Prerequisites

- **Python 3.11 or 3.12** (3.12 recommended)
- **uv** (optional but recommended) - Fast Python package installer
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Git**
- Home Assistant instance (for integration testing)

### Setup with uv (Recommended)

```bash
# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e ".[dev]"

# Verify installation
haboss --help
```

### Setup with pip (Traditional)

```bash
# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install with development dependencies
pip install -e ".[dev]"

# Verify installation
haboss --help
```

### Configuration for Local Development

```bash
# Initialize config and database
haboss init --config-dir ./config --data-dir ./data

# Create .env file
cp .env.example config/.env

# Edit config/.env with your HA details
nano config/.env
```

Add your Home Assistant credentials:
```bash
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here
```

### Running Locally

```bash
# Validate configuration
haboss config validate

# Start monitoring (foreground with debug logging)
LOG_LEVEL=DEBUG haboss start --foreground

# In another terminal, check status
haboss status

# Test healing
haboss heal sensor.unavailable_entity --dry-run
```

### Development Workflow

```bash
# Make changes to code
vim ha_boss/core/ha_client.py

# Run tests
pytest

# Run with coverage
pytest --cov=ha_boss --cov-report=html

# Check code quality
black .                    # Format code
ruff check --fix .        # Lint and fix
mypy ha_boss              # Type checking

# Run all CI checks
black --check . && ruff check . && mypy ha_boss && pytest
```

### Using Custom Slash Commands

The project includes custom slash commands for common tasks:

```bash
# In Claude Code CLI
/test                      # Run full test suite
/test-file tests/cli/test_commands.py
/lint                      # Run all code quality checks
/fix-style                 # Auto-fix formatting
/ci-check                  # Full CI pipeline locally
/setup-dev                 # Development environment guide
```

## Configuration Guide

### Complete Configuration Options

The `config/config.yaml` file has the following structure:

#### Home Assistant Connection

```yaml
home_assistant:
  # Home Assistant URL (required)
  url: "http://homeassistant.local:8123"

  # Long-lived access token (required)
  # Can reference environment variable
  token: "${HA_TOKEN}"
```

#### Monitoring Settings

```yaml
monitoring:
  # Entities to monitor (glob patterns)
  # Empty list = monitor all entities
  include: []
  # Examples:
  # - "sensor.temperature_*"
  # - "binary_sensor.motion_*"
  # - "light.*"

  # Entities to exclude from monitoring
  exclude:
    - "sensor.time*"      # Time sensors change constantly
    - "sensor.date*"      # Date sensors change constantly
    - "sensor.uptime*"    # Uptime is not critical
    - "sun.sun"           # Sun sensor changes normally

  # Grace period before considering entity unavailable (seconds)
  # Prevents false positives from temporary glitches
  grace_period_seconds: 300  # 5 minutes

  # Threshold for stale entities (no update in X seconds)
  # 0 = disabled
  stale_threshold_seconds: 3600  # 1 hour

  # REST API snapshot interval (seconds)
  # Used to validate WebSocket cache
  snapshot_interval_seconds: 300  # 5 minutes
```

#### Healing Settings

```yaml
healing:
  # Enable/disable auto-healing
  enabled: true

  # Maximum healing attempts per integration
  max_attempts: 3

  # Cooldown between healing attempts (seconds)
  # Prevents rapid retry loops
  cooldown_seconds: 300  # 5 minutes

  # Circuit breaker threshold
  # Stop trying after N total failures
  circuit_breaker_threshold: 10

  # Circuit breaker reset time (seconds)
  # After this time with no failures, reset counter
  circuit_breaker_reset_seconds: 3600  # 1 hour
```

#### Notification Settings

```yaml
notifications:
  # Send notifications when auto-healing fails
  on_healing_failure: true

  # Send weekly summary reports (future feature)
  weekly_summary: true

  # Home Assistant notification service
  ha_service: "persistent_notification.create"

  # Optional: Email notifications (future feature)
  # email:
  #   enabled: false
  #   smtp_server: "smtp.gmail.com"
  #   smtp_port: 587
  #   username: "your-email@gmail.com"
  #   password: "${EMAIL_PASSWORD}"
  #   from: "haboss@example.com"
  #   to: "your-email@gmail.com"
```

#### Operational Mode

```yaml
# Operational mode
# - production: Full auto-healing enabled
# - dry_run: Log actions but don't execute
# - testing: Use test HA instance
mode: "production"

# Dry run configuration
dry_run:
  # Where to log actions that would be taken
  log_file: "/data/dry_run.log"
```

#### Logging Configuration

```yaml
logging:
  # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  level: "INFO"

  # Format: json or text
  # json is better for log aggregation tools
  format: "json"

  # Log file path
  file: "/data/ha_boss.log"

  # Maximum log file size (MB)
  max_size_mb: 10

  # Number of backup files to keep
  backup_count: 5
```

#### Database Configuration

```yaml
database:
  # SQLite database path
  path: "/data/ha_boss.db"

  # Enable SQL query logging (debug only)
  echo: false

  # History retention (days)
  # Older records are automatically purged
  retention_days: 30
```

#### WebSocket Configuration

```yaml
websocket:
  # Reconnect delay (seconds)
  reconnect_delay_seconds: 5

  # Heartbeat interval (seconds)
  # Send ping every N seconds to keep connection alive
  heartbeat_interval_seconds: 30

  # Connection timeout (seconds)
  timeout_seconds: 10
```

#### REST API Configuration

```yaml
rest:
  # Request timeout (seconds)
  timeout_seconds: 10

  # Retry attempts for failed requests
  retry_attempts: 3

  # Base delay for exponential backoff (seconds)
  retry_base_delay_seconds: 1.0
```

### Configuration Examples

#### Minimal Configuration

```yaml
# config/config-minimal.yaml
home_assistant:
  url: "${HA_URL}"
  token: "${HA_TOKEN}"

monitoring:
  grace_period_seconds: 300
  exclude:
    - "sensor.time*"
    - "sensor.date*"

healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300

logging:
  level: "INFO"

database:
  path: "data/ha_boss.db"

mode: "production"
```

#### Production Configuration (Conservative)

```yaml
# config/config-production.yaml
home_assistant:
  url: "${HA_URL}"
  token: "${HA_TOKEN}"

monitoring:
  # Longer grace period for production stability
  grace_period_seconds: 600  # 10 minutes

  # Exclude non-critical entities
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sensor.uptime*"
    - "device_tracker.*"     # Mobile devices often offline
    - "person.*"

  stale_threshold_seconds: 7200  # 2 hours

healing:
  enabled: true
  max_attempts: 2           # Be conservative
  cooldown_seconds: 600     # Longer cooldown (10 min)
  circuit_breaker_threshold: 5   # Lower threshold
  circuit_breaker_reset_seconds: 7200  # 2 hours

notifications:
  on_healing_failure: true
  weekly_summary: true

logging:
  level: "INFO"
  format: "json"
  file: "/data/ha_boss.log"
  max_size_mb: 50
  backup_count: 10

database:
  path: "/data/ha_boss.db"
  retention_days: 90        # Keep 3 months of history

mode: "production"
```

#### Development/Testing Configuration (Aggressive)

```yaml
# config/config-dev.yaml
home_assistant:
  url: "${TEST_HA_URL}"
  token: "${TEST_HA_TOKEN}"

monitoring:
  # Shorter grace period for faster testing
  grace_period_seconds: 60  # 1 minute

  # Monitor specific test entities
  include:
    - "sensor.test_*"
    - "binary_sensor.test_*"

healing:
  enabled: true
  max_attempts: 5           # More attempts for testing
  cooldown_seconds: 120     # Shorter cooldown (2 min)
  circuit_breaker_threshold: 20
  circuit_breaker_reset_seconds: 1800  # 30 minutes

notifications:
  on_healing_failure: true
  weekly_summary: false

logging:
  level: "DEBUG"            # Verbose logging
  format: "text"            # Human-readable
  file: "/data/ha_boss_dev.log"

database:
  path: "/data/ha_boss_dev.db"
  echo: true                # Log SQL queries
  retention_days: 7         # Short retention for testing

mode: "testing"
```

## Troubleshooting

### Common Issues

#### Issue: "Configuration file not found"

**Cause**: Config file missing or wrong path

**Solution**:
```bash
# Check if config exists
ls -la config/config.yaml

# If missing, copy from example
cp config/config.yaml.example config/config.yaml

# Specify custom path
haboss start --config /path/to/config.yaml
```

#### Issue: "Invalid token" or "401 Unauthorized"

**Cause**: Expired or invalid long-lived token

**Solution**:
1. Go to Home Assistant → Profile
2. Scroll to "Long-Lived Access Tokens"
3. Delete old "HA Boss" token
4. Create new token
5. Update `.env` file with new token
6. Restart HA Boss

#### Issue: "Connection refused" or "Connection timeout"

**Cause**: Can't reach Home Assistant

**Solution**:
```bash
# Test connectivity
curl http://your-ha-url:8123/api/

# Common fixes:
# 1. Wrong URL - check HA_URL in .env
# 2. Firewall blocking - check firewall rules
# 3. HA not running - check HA status
# 4. Docker networking - use host.docker.internal (macOS/Windows)
#    or host IP (Linux)
```

#### Issue: Entities not being healed

**Cause**: Circuit breaker tripped or cooldown active

**Solution**:
```bash
# Check status
haboss status

# Look for circuit breaker messages in logs
docker-compose logs | grep "circuit breaker"

# Check if cooldown is active
docker-compose logs | grep "cooldown"

# Reset by restarting (circuit breaker will reset)
docker-compose restart

# Or reduce thresholds in config.yaml:
# circuit_breaker_threshold: 20
# cooldown_seconds: 180
```

#### Issue: High memory usage

**Cause**: Too many entities or old database records

**Solution**:
```bash
# Clean up old database records
haboss db cleanup --older-than 30

# Reduce monitored entities in config.yaml:
monitoring:
  exclude:
    - "sensor.*"  # Exclude all sensors
    # Then add back only critical ones
  include:
    - "sensor.critical_*"

# Check database size
ls -lh data/ha_boss.db

# If very large, consider vacuum
sqlite3 data/ha_boss.db "VACUUM;"
```

### Advanced Troubleshooting

#### Enable Debug Logging

**Docker**:
```bash
# Edit docker-compose.yml
environment:
  - LOG_LEVEL=DEBUG

# Restart
docker-compose restart

# View debug logs
docker-compose logs -f | grep DEBUG
```

**Local**:
```bash
# Run with debug logging
LOG_LEVEL=DEBUG haboss start --foreground
```

#### Check Database

```bash
# Access database
sqlite3 data/ha_boss.db

# List tables
.tables

# Check recent health events
SELECT * FROM health_events ORDER BY detected_at DESC LIMIT 10;

# Check healing actions
SELECT * FROM healing_actions ORDER BY attempted_at DESC LIMIT 10;

# Exit
.quit
```

#### Dry-Run Mode

Test healing without executing:

```bash
# Edit config.yaml
mode: "dry_run"

# Restart and watch logs
docker-compose restart
docker-compose logs -f

# Check dry run log
cat data/dry_run.log
```

## GitHub Integration Setup (for Contributors)

This section is for developers contributing to HA Boss.

### Prerequisites

- GitHub account
- **GitHub CLI (gh)** - `brew install gh` (macOS) or see https://cli.github.com/
- **Git** configured with your GitHub credentials

### Setup GitHub Authentication

```bash
# Authenticate with GitHub
gh auth login

# Follow prompts:
# - Select HTTPS
# - Authenticate via browser
# - Grant required scopes
```

### Fork and Clone

```bash
# Fork the repository on GitHub
gh repo fork jasonthagerty/ha_boss --clone

# Navigate to repository
cd ha_boss

# Add upstream remote
git remote add upstream https://github.com/jasonthagerty/ha_boss.git
```

### Install Development Tools

```bash
# Install pre-commit hooks (optional but recommended)
pip install pre-commit
pre-commit install

# Install all development dependencies
uv pip install -e ".[dev]"
```

### Development Workflow

```bash
# Create feature branch
git checkout -b feature/my-new-feature

# Make changes and test
# ... edit code ...
pytest
black .
ruff check --fix .
mypy ha_boss

# Commit changes
git add .
git commit -m "feat: add my new feature"

# Push to your fork
git push origin feature/my-new-feature

# Create pull request
gh pr create --title "feat: add my new feature" --body "Description of changes"
```

### Running CI Checks Locally

```bash
# Run the same checks as CI
black --check . && ruff check . && mypy ha_boss && pytest

# Or use the slash command
/ci-check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for complete contribution guidelines.

## Next Steps

- Read [CLAUDE.md](CLAUDE.md) for architecture and design patterns
- Review [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow
- Join discussions: https://github.com/jasonthagerty/ha_boss/discussions
- Report issues: https://github.com/jasonthagerty/ha_boss/issues

## Support

- **Documentation**: [README.md](README.md), [CLAUDE.md](CLAUDE.md)
- **Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Discussions**: https://github.com/jasonthagerty/ha_boss/discussions
- **Home Assistant Community**: https://community.home-assistant.io/

---

**Happy monitoring! 🚀**
