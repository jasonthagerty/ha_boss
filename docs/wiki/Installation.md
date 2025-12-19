# Installation Guide

Complete installation guide for HA Boss, covering Docker deployment (recommended) and local development setup.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Docker)](#quick-start-docker)
- [Docker Installation (Recommended)](#docker-installation-recommended)
  - [Step 1: Install Docker](#step-1-install-docker)
  - [Step 2: Get HA Boss](#step-2-get-ha-boss)
  - [Step 3: Create Long-Lived Token](#step-3-create-long-lived-token)
  - [Step 4: Configure Environment](#step-4-configure-environment)
  - [Step 5: Customize Configuration (Optional)](#step-5-customize-configuration-optional)
  - [Step 6: Start HA Boss](#step-6-start-ha-boss)
  - [Step 7: Verify Operation](#step-7-verify-operation)
- [Local Development Installation](#local-development-installation)
  - [Prerequisites](#prerequisites-1)
  - [Setup with uv (Recommended)](#setup-with-uv-recommended)
  - [Setup with pip (Traditional)](#setup-with-pip-traditional)
  - [Configuration for Local Development](#configuration-for-local-development)
  - [Running Locally](#running-locally)
- [Optional: Ollama LLM Setup](#optional-ollama-llm-setup)
- [Configuration Reference](#configuration-reference)
  - [Environment Variables](#environment-variables)
  - [Configuration File Options](#configuration-file-options)
- [Verification Steps](#verification-steps)
- [Example Configurations](#example-configurations)
- [Troubleshooting](#troubleshooting)
- [Next Steps](#next-steps)

## Prerequisites

### For Docker Deployment

- **Docker Engine** 20.10+ or Docker Desktop
- **Docker Compose** v2.0+ (included with Docker Desktop)
- **Home Assistant** instance (accessible from Docker host)
- **Long-lived access token** from Home Assistant

### For Local Development

- **Python 3.11 or 3.12** (3.12 recommended for consistency with CI)
- **uv** (recommended) - Fast Python package installer
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Alternative: Use pip with standard Python venv
- **Git** for cloning the repository
- **Home Assistant** instance (for integration testing)

### Home Assistant Requirements

- Home Assistant 2023.1 or later
- Network access to Home Assistant from the server running HA Boss
- Ability to create long-lived access tokens (user account required)

## Quick Start (Docker)

Get up and running in 5 minutes:

```bash
# 1. Clone and configure
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss
cp .env.example .env

# 2. Edit .env with your Home Assistant URL and token
nano .env  # or use your preferred editor

# Add these lines:
#   HA_URL=http://homeassistant.local:8123
#   HA_TOKEN=your_long_lived_token_here

# 3. Start the service
docker-compose up -d

# 4. Check status
docker-compose exec haboss haboss status
```

## Docker Installation (Recommended)

Docker is the recommended deployment method for production use. It provides isolation, easy updates, and consistent behavior across platforms.

### Step 1: Install Docker

#### Linux (Ubuntu/Debian)

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

# Verify installation
docker --version
docker compose version
```

#### macOS

```bash
# Download and install Docker Desktop from:
# https://www.docker.com/products/docker-desktop

# Or via Homebrew:
brew install --cask docker

# Verify installation
docker --version
docker compose version
```

#### Windows

1. Download and install Docker Desktop from: https://www.docker.com/products/docker-desktop
2. Follow the installation wizard
3. Restart your computer when prompted
4. Verify installation by opening PowerShell and running:
   ```powershell
   docker --version
   docker compose version
   ```

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

HA Boss requires a long-lived access token to authenticate with Home Assistant.

1. Open your Home Assistant web interface (e.g., `http://homeassistant.local:8123`)
2. Click on your **profile** (bottom left corner, your username/avatar)
3. Scroll down to the **"Long-Lived Access Tokens"** section
4. Click **"Create Token"**
5. Enter a name: `HA Boss`
6. Click **"OK"**
7. **Copy the token immediately** - you won't be able to see it again!
8. Save it somewhere secure temporarily (you'll add it to `.env` in the next step)

The token will look something like:
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI4ZjE...
```

**Security Note**: This token grants full API access to your Home Assistant instance. Treat it like a password and never commit it to version control.

### Step 4: Configure Environment

```bash
# Create .env file from example
cp .env.example .env

# Edit .env file
nano .env  # or vim, code, etc.
```

Add your Home Assistant details:

```bash
# Required: Your Home Assistant URL
HA_URL=http://192.168.1.100:8123
# or: HA_URL=http://homeassistant.local:8123
# or: HA_URL=https://your-domain.duckdns.org

# Required: Long-lived access token (paste from step 3)
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI4ZjE...

# Optional: Set timezone (defaults to UTC)
TZ=America/New_York
```

**Important Notes**:
- Use the **internal** Home Assistant URL (not external/Nabu Casa URL)
- If using Docker on the same host as Home Assistant:
  - **macOS/Windows**: Use `http://host.docker.internal:8123`
  - **Linux**: Use the host's IP address (not `localhost`), e.g., `http://192.168.1.100:8123`
- If Home Assistant uses HTTPS, use `https://` in the URL

### Step 5: Customize Configuration (Optional)

The default configuration works well for most users. To customize:

```bash
# Create config directory (if not exists)
mkdir -p config data

# Copy example configuration
cp config/config.yaml.example config/config.yaml

# Edit configuration (optional)
nano config/config.yaml
```

Key settings to consider:

```yaml
monitoring:
  grace_period_seconds: 300  # Wait 5 min before marking unavailable
  exclude:                   # Add entities to skip monitoring
    - "sensor.time*"
    - "sensor.date*"
    - "device_tracker.*"     # Device trackers often go offline

healing:
  enabled: true
  max_attempts: 3            # Attempts per integration
  cooldown_seconds: 300      # Wait 5 min between attempts
```

See [Configuration Reference](#configuration-reference) for all available options.

### Step 6: Start HA Boss

```bash
# Start in detached mode (background)
docker-compose up -d

# View logs to verify startup
docker-compose logs -f
```

Expected output:
```
haboss | INFO: Connected to Home Assistant 2024.11.1
haboss | INFO: Monitoring 150 entities
haboss | INFO: Auto-healing enabled
haboss | INFO: WebSocket connection established
```

Press `Ctrl+C` to stop following logs.

Check container status:
```bash
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

You should see output like:
```
✓ Connected to Home Assistant 2024.11.1
✓ Monitoring 150 entities
✓ Auto-healing enabled
✓ Database: /app/data/ha_boss.db (30 health events, 12 healing actions)
```

**Common Commands**:

```bash
# Monitor logs in real-time
docker-compose logs -f

# Show last 100 lines
docker-compose logs --tail=100

# Show only errors
docker-compose logs | grep ERROR

# Restart after config changes
docker-compose restart

# Stop HA Boss
docker-compose down

# Update to latest version
git pull origin main
docker-compose build --no-cache
docker-compose up -d

# View resource usage
docker stats ha-boss
```

## Local Development Installation

For contributing to HA Boss or local testing without Docker.

### Prerequisites

- **Python 3.11 or 3.12** (3.12 recommended)
- **uv** (optional but recommended) - https://github.com/astral-sh/uv
- **Git**
- **Home Assistant** instance (for integration testing)

Check your Python version:
```bash
python3 --version
# Should show: Python 3.11.x or Python 3.12.x
```

### Setup with uv (Recommended)

uv is a fast Python package installer that's much quicker than pip.

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Reload shell to get uv in PATH
source ~/.bashrc  # or ~/.zshrc on macOS

# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment with Python 3.12
uv venv --python 3.12

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# Windows: .venv\Scripts\activate

# Install with development dependencies
uv pip install -e ".[dev]"

# Verify installation
haboss --help
```

### Setup with pip (Traditional)

If you prefer the traditional venv approach:

```bash
# Clone repository
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss

# Create virtual environment
python3.12 -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/macOS
# Windows: venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install with development dependencies
pip install -e ".[dev]"

# Verify installation
haboss --help
```

### Configuration for Local Development

```bash
# Initialize config and database directories
haboss init --config-dir ./config --data-dir ./data

# Create .env file
cp .env.example config/.env

# Edit config/.env with your Home Assistant credentials
nano config/.env
```

Add your Home Assistant details:
```bash
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here

# Optional: Enable debug logging
LOG_LEVEL=DEBUG
```

### Running Locally

```bash
# Ensure virtual environment is activated
source .venv/bin/activate  # or venv/bin/activate

# Validate configuration
haboss config validate

# Start monitoring (foreground with debug logging)
LOG_LEVEL=DEBUG haboss start --foreground

# In another terminal, check status
haboss status

# Test healing (dry-run mode - doesn't actually reload)
haboss heal sensor.unavailable_entity --dry-run

# Run tests
pytest

# Run with coverage
pytest --cov=ha_boss --cov-report=html --cov-report=term

# Check code quality
black .                    # Format code
ruff check --fix .        # Lint and auto-fix
mypy ha_boss              # Type checking

# Run complete CI checks before committing
black --check . && ruff check . && mypy ha_boss && pytest
```

## Optional: Ollama LLM Setup

HA Boss includes AI-powered features (enhanced notifications, weekly summaries, automation analysis) using a local LLM via Ollama. This is completely optional.

### Why Use Ollama?

- **Privacy**: All AI processing happens locally (no external API calls)
- **No Cost**: Free, open-source models
- **Offline**: Works without internet (after initial model download)
- **Enhanced Features**: Better notifications and insights

### Quick Ollama Setup

Add to your `docker-compose.yml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: haboss_ollama
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    restart: unless-stopped

  haboss:
    # ... existing config ...
    depends_on:
      - ollama
    environment:
      # ... existing vars ...
      - OLLAMA_URL=http://ollama:11434
      - OLLAMA_MODEL=llama3.1:8b

volumes:
  ollama_data:
```

Pull the model:

```bash
# Start containers
docker-compose up -d

# Download Llama 3.1 8B model (4.6GB, one-time download)
docker exec haboss_ollama ollama pull llama3.1:8b

# Verify model is available
docker exec haboss_ollama ollama list

# Test it works
docker exec haboss_ollama ollama run llama3.1:8b "Say hello"
```

Enable in HA Boss configuration (`config/config.yaml`):

```yaml
intelligence:
  ollama_enabled: true
  ollama_url: "http://ollama:11434"
  ollama_model: "llama3.1:8b"
```

Restart HA Boss:
```bash
docker-compose restart haboss
```

For detailed LLM setup including performance benchmarks and troubleshooting, see: [docs/LLM_SETUP.md](/home/jason/projects/ha_boss/docs/LLM_SETUP.md)

## Configuration Reference

### Environment Variables

HA Boss supports configuration via environment variables (in `.env` file) or YAML config file.

**Required Variables**:

```bash
# Home Assistant URL (internal network address)
HA_URL=http://homeassistant.local:8123

# Long-lived access token from Home Assistant
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Optional Variables**:

```bash
# Timezone (defaults to UTC)
TZ=America/New_York

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Operational mode: production, dry_run, testing
MODE=production

# Ollama LLM configuration (optional)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_ENABLED=true

# Claude API (optional, for advanced features)
CLAUDE_API_KEY=sk-ant-...
CLAUDE_ENABLED=false

# Email notifications (future feature)
EMAIL_PASSWORD=your_app_password_here
```

### Configuration File Options

The `config/config.yaml` file provides fine-grained control over HA Boss behavior.

#### Minimal Configuration

```yaml
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
  path: "/data/ha_boss.db"

mode: "production"
```

#### Key Configuration Sections

**Monitoring Settings**:
```yaml
monitoring:
  # Entities to monitor (empty = all)
  include: []
  # Examples:
  # - "sensor.temperature_*"
  # - "binary_sensor.motion_*"

  # Entities to exclude
  exclude:
    - "sensor.time*"      # Changes constantly
    - "sensor.date*"
    - "device_tracker.*"  # Mobile devices go offline

  # Grace period before marking unavailable (seconds)
  grace_period_seconds: 300  # 5 minutes

  # Stale threshold (no update in X seconds, 0 = disabled)
  stale_threshold_seconds: 3600  # 1 hour
```

**Healing Settings**:
```yaml
healing:
  enabled: true
  max_attempts: 3                      # Per integration
  cooldown_seconds: 300                # Between attempts
  circuit_breaker_threshold: 10        # Total failures before stopping
  circuit_breaker_reset_seconds: 3600  # Reset after 1 hour
```

**Notification Settings**:
```yaml
notifications:
  on_healing_failure: true    # Notify when auto-heal fails
  weekly_summary: true        # Weekly health reports
  ha_service: "persistent_notification.create"
  ai_enhanced: true          # Use LLM for enhanced notifications
```

**Logging Configuration**:
```yaml
logging:
  level: "INFO"           # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "json"          # json or text
  file: "/data/ha_boss.log"
  max_size_mb: 10
  backup_count: 5
```

**Database Configuration**:
```yaml
database:
  path: "/data/ha_boss.db"
  echo: false              # Log SQL queries (debug only)
  retention_days: 30       # Auto-purge old records
```

For complete configuration reference, see: [config/config.yaml.example](/home/jason/projects/ha_boss/config/config.yaml.example)

## Verification Steps

After installation, verify HA Boss is working correctly:

### 1. Check Connection to Home Assistant

```bash
# Docker
docker-compose exec haboss haboss status

# Local
haboss status
```

Expected output:
```
✓ Connected to Home Assistant 2024.11.1
✓ Monitoring 150 entities
✓ Auto-healing enabled
```

### 2. Validate Configuration

```bash
# Docker
docker-compose exec haboss haboss config validate

# Local
haboss config validate
```

Should show no errors.

### 3. Check Database

```bash
# Docker
docker-compose exec haboss haboss db info

# Local
haboss db info
```

Expected output:
```
Database: /data/ha_boss.db
Size: 245 KB
Tables: health_events, healing_actions, integrations, entities
Records: 0 health events, 0 healing actions
```

### 4. Test Healing (Dry Run)

```bash
# Docker
docker-compose exec haboss haboss heal sensor.test --dry-run

# Local
haboss heal sensor.test --dry-run
```

Should log what would happen without actually executing.

### 5. Monitor Logs

```bash
# Docker - watch for state changes and health checks
docker-compose logs -f

# Local - run in foreground with debug logging
LOG_LEVEL=DEBUG haboss start --foreground
```

Look for:
- WebSocket connection established
- Entity state updates
- Health monitoring checks
- No connection errors

## Example Configurations

### Production (Conservative)

For production environments where stability is critical:

```yaml
monitoring:
  grace_period_seconds: 600     # 10 minutes - avoid false positives
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "device_tracker.*"        # Mobile devices often offline
    - "person.*"
  stale_threshold_seconds: 7200  # 2 hours

healing:
  enabled: true
  max_attempts: 2                # Conservative
  cooldown_seconds: 600          # 10 minutes between attempts
  circuit_breaker_threshold: 5   # Lower threshold
  circuit_breaker_reset_seconds: 7200  # 2 hours

logging:
  level: "INFO"
  format: "json"                 # Better for log aggregation
  max_size_mb: 50
  backup_count: 10

database:
  retention_days: 90             # Keep 3 months of history

mode: "production"
```

### Development/Testing (Aggressive)

For testing environments where faster response is acceptable:

```yaml
monitoring:
  grace_period_seconds: 60       # 1 minute - faster detection
  include:
    - "sensor.test_*"            # Only monitor test entities
    - "binary_sensor.test_*"

healing:
  enabled: true
  max_attempts: 5                # More attempts for testing
  cooldown_seconds: 120          # 2 minutes
  circuit_breaker_threshold: 20

logging:
  level: "DEBUG"                 # Verbose logging
  format: "text"                 # Human-readable

database:
  echo: true                     # Log SQL queries
  retention_days: 7              # Short retention

mode: "testing"
```

### Monitor Critical Sensors Only

For focused monitoring of important devices:

```yaml
monitoring:
  include:
    - "sensor.temperature_*"     # All temperature sensors
    - "binary_sensor.door_*"     # All door sensors
    - "binary_sensor.motion_*"   # All motion sensors
    - "climate.*"                # All climate devices
    - "alarm_control_panel.*"    # Security system
  grace_period_seconds: 300

healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300

mode: "production"
```

## Troubleshooting

### Connection Issues

**Problem**: "Can't connect to Home Assistant" or "Connection refused"

**Solutions**:

1. **Verify Home Assistant URL**:
   ```bash
   # Test connectivity
   curl http://your-ha-url:8123/api/

   # Should return: {"message":"API running."}
   ```

2. **Check Docker networking** (if using Docker):
   - macOS/Windows: Try `http://host.docker.internal:8123`
   - Linux: Use host IP address, not `localhost`
   ```bash
   # Find your host IP
   ip addr show | grep inet
   ```

3. **Verify firewall allows connection**:
   ```bash
   # Test from container
   docker-compose exec haboss curl http://your-ha-url:8123/api/
   ```

**Problem**: "401 Unauthorized" or "Invalid token"

**Solutions**:

1. **Regenerate token**:
   - Go to Home Assistant → Profile → Long-Lived Access Tokens
   - Delete old "HA Boss" token
   - Create new token
   - Update `.env` file with new token
   - Restart: `docker-compose restart`

2. **Check token format** (should start with `eyJ...`):
   ```bash
   # View current token (be careful - don't share output!)
   grep HA_TOKEN .env
   ```

### Health Monitoring Issues

**Problem**: Entities not being healed

**Cause**: Circuit breaker tripped or cooldown active

**Solutions**:

```bash
# Check status
docker-compose exec haboss haboss status

# View logs for circuit breaker or cooldown messages
docker-compose logs | grep -E "circuit breaker|cooldown"

# Reset circuit breaker by restarting
docker-compose restart

# Or adjust thresholds in config.yaml:
# healing:
#   circuit_breaker_threshold: 20
#   cooldown_seconds: 180
```

**Problem**: Too many false positives (entities marked unavailable)

**Solution**: Increase grace period in `config.yaml`:
```yaml
monitoring:
  grace_period_seconds: 600  # Increase to 10 minutes
```

### Performance Issues

**Problem**: High memory usage

**Solutions**:

```bash
# Clean up old database records
docker-compose exec haboss haboss db cleanup --older-than 30

# Check database size
ls -lh data/ha_boss.db

# Vacuum database to reclaim space
docker-compose exec haboss sqlite3 /app/data/ha_boss.db "VACUUM;"

# Reduce monitored entities in config.yaml:
monitoring:
  exclude:
    - "sensor.*"  # Exclude all sensors, then include critical ones
  include:
    - "sensor.critical_*"
```

**Problem**: Slow LLM responses (if using Ollama)

**Check**: This is expected in CPU mode (~10-60s depending on response length). See [docs/LLM_SETUP.md](/home/jason/projects/ha_boss/docs/LLM_SETUP.md) for performance benchmarks.

**Solutions**:
- Use smaller model: `llama3.1:3b` (faster but lower quality)
- Disable LLM features: Set `ollama_enabled: false` in config
- Future: GPU acceleration (tracked in Issue #52)

### Docker Issues

**Problem**: Container keeps restarting

**Solutions**:

```bash
# Check logs for errors
docker-compose logs

# Common issues:
# 1. Invalid HA_TOKEN - regenerate token
# 2. Wrong HA_URL - verify URL is accessible
# 3. Network issues - check firewall/routing
```

**Problem**: Permission denied errors

**Solutions**:

```bash
# Ensure data directory is writable
chmod 755 data/
chown 1000:1000 data/  # haboss user UID in container

# Or use sudo if needed
sudo chown -R 1000:1000 data/
```

### Advanced Troubleshooting

**Enable debug logging**:

Docker:
```bash
# Edit docker-compose.yml, add:
# environment:
#   - LOG_LEVEL=DEBUG

docker-compose restart
docker-compose logs -f | grep DEBUG
```

Local:
```bash
LOG_LEVEL=DEBUG haboss start --foreground
```

**Check database directly**:

```bash
# Access database
sqlite3 data/ha_boss.db

# List tables
.tables

# Recent health events
SELECT * FROM health_events ORDER BY detected_at DESC LIMIT 10;

# Recent healing actions
SELECT * FROM healing_actions ORDER BY attempted_at DESC LIMIT 10;

# Exit
.quit
```

**Dry-run mode** (test without executing):

Edit `config/config.yaml`:
```yaml
mode: "dry_run"
```

Restart and watch logs:
```bash
docker-compose restart
docker-compose logs -f

# Check dry run log
cat data/dry_run.log
```

## Next Steps

After successful installation:

1. **Monitor Logs**: Watch logs for a few hours to see HA Boss in action
   ```bash
   docker-compose logs -f
   ```

2. **Review Reliability Reports**: After a few days, check integration reliability
   ```bash
   docker-compose exec haboss haboss patterns reliability
   ```

3. **Set Up Weekly Summaries**: Enable AI-generated weekly health reports
   ```yaml
   # In config.yaml
   notifications:
     weekly_summary: true
   intelligence:
     ollama_enabled: true  # Optional, for enhanced summaries
   ```

4. **Explore CLI Commands**: Learn about available management commands
   ```bash
   docker-compose exec haboss haboss --help
   ```

   See full CLI reference: [CLI-Commands.md](/home/jason/projects/ha_boss/docs/wiki/CLI-Commands.md)

5. **Join the Community**:
   - Read documentation: [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki)
   - Report issues: [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
   - Participate in discussions: [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)

6. **Contribute** (optional):
   - See: [CONTRIBUTING.md](https://github.com/jasonthagerty/ha_boss/blob/main/CONTRIBUTING.md)
   - Development guide: [Development Wiki](https://github.com/jasonthagerty/ha_boss/wiki/Development)

## Support

Need help? Here are your resources:

- **Documentation**:
  - [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki)
  - [README.md](https://github.com/jasonthagerty/ha_boss/blob/main/README.md)
  - [SETUP_GUIDE.md](https://github.com/jasonthagerty/ha_boss/blob/main/SETUP_GUIDE.md)
- **Issues**: [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)
- **Home Assistant Community**: [community.home-assistant.io](https://community.home-assistant.io/)

---

**Happy monitoring!** HA Boss is now watching over your Home Assistant instance, ready to automatically heal integration failures and keep your smart home running smoothly.
