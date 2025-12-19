# Configuration

Complete configuration reference for HA Boss, covering all settings, environment variables, and deployment scenarios.

## Table of Contents

- [Overview](#overview)
- [Configuration Files](#configuration-files)
- [Configuration Sections](#configuration-sections)
  - [Home Assistant](#home-assistant)
  - [Monitoring](#monitoring)
  - [Healing](#healing)
  - [Notifications](#notifications)
  - [Intelligence](#intelligence)
  - [Database](#database)
  - [Logging](#logging)
  - [WebSocket](#websocket)
  - [REST API](#rest-api)
- [Environment Variables](#environment-variables)
- [Operational Modes](#operational-modes)
- [Example Configurations](#example-configurations)
- [Configuration Validation](#configuration-validation)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

HA Boss uses a **hybrid configuration approach**:

1. **YAML Configuration File** (`config/config.yaml`): Primary configuration with all settings
2. **Environment Variables**: Secrets and deployment-specific overrides
3. **Pydantic Validation**: Strong type checking and validation at startup

### Configuration Hierarchy

Settings are loaded in this order (later overrides earlier):
1. Default values (defined in code)
2. YAML configuration file
3. Environment variables (using `__` delimiter for nested fields)

### Quick Start

```bash
# 1. Copy example configuration
cp config/config.yaml.example config/config.yaml

# 2. Copy environment file
cp .env.example .env

# 3. Edit required settings
nano config/config.yaml  # Set Home Assistant URL
nano .env                # Set HA_TOKEN

# 4. Validate configuration
haboss config validate

# 5. Start HA Boss
docker-compose up -d
```

## Configuration Files

### config.yaml Location

HA Boss searches for `config.yaml` in these locations (in order):

1. `./config.yaml` (current directory)
2. `./config/config.yaml` (config subdirectory)
3. `/config/config.yaml` (Docker volume mount)

You can also specify a custom path:

```bash
# Via environment variable
export CONFIG_PATH=/path/to/config.yaml

# Via command line (if supported)
haboss --config /path/to/config.yaml
```

### Environment File Location

- **Docker**: `.env` in project root (same directory as `docker-compose.yml`)
- **Local development**: `config/.env` or `.env` in project root
- **Production**: Use environment-specific files (`.env.production`, etc.)

### File Structure

```
ha_boss/
├── config/
│   ├── config.yaml          # Main configuration
│   └── .env                 # Local development secrets
├── .env                     # Docker secrets (root level)
├── .env.example             # Example environment file
└── config.yaml.example      # Example configuration
```

## Configuration Sections

### Home Assistant

Connection settings for your Home Assistant instance.

| Setting | Type | Required | Default | Description |
|---------|------|----------|---------|-------------|
| `url` | string | Yes | - | Home Assistant instance URL |
| `token` | string | Yes | - | Long-lived access token |

**Example**:
```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "${HA_TOKEN}"  # Load from environment variable
```

**Environment Variables**:
- `HOME_ASSISTANT__URL` or `HA_URL`
- `HOME_ASSISTANT__TOKEN` or `HA_TOKEN`

**Notes**:
- URL is automatically stripped of trailing slashes
- Token can use `${VAR}` syntax to load from environment
- Create token at: `http://your-ha/profile` → Long-Lived Access Tokens
- Token grants full API access (protect like a password)

**Validation**:
- URL must be valid HTTP/HTTPS endpoint
- Token cannot be empty or placeholder (`${...}`)

---

### Monitoring

Entity monitoring configuration for state tracking and health checks.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `include` | list[string] | `[]` | - | Entity patterns to monitor (empty = all) |
| `exclude` | list[string] | See below | - | Entity patterns to exclude |
| `grace_period_seconds` | integer | `300` | ≥ 0 | Grace period before entity considered unavailable |
| `stale_threshold_seconds` | integer | `3600` | ≥ 0 | Threshold for stale entities (no updates) |
| `snapshot_interval_seconds` | integer | `300` | ≥ 60 | REST API snapshot interval for validation |
| `health_check_interval_seconds` | integer | `60` | ≥ 10 | Periodic health check interval |

**Default Exclusions**:
```yaml
monitoring:
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sensor.uptime*"
    - "sun.sun"
```

**Example with Targeted Monitoring**:
```yaml
monitoring:
  # Only monitor specific domains
  include:
    - "light.*"
    - "switch.*"
    - "sensor.temperature_*"
    - "binary_sensor.motion_*"

  # Exclude noisy entities
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sensor.uptime*"
    - "sun.sun"
    - "sensor.last_boot"

  # Faster grace period for critical sensors
  grace_period_seconds: 180  # 3 minutes

  # Longer stale threshold for slow-updating sensors
  stale_threshold_seconds: 7200  # 2 hours

  # More frequent health checks
  health_check_interval_seconds: 30
```

**Environment Variables**:
- `MONITORING__GRACE_PERIOD_SECONDS`
- `MONITORING__STALE_THRESHOLD_SECONDS`
- `MONITORING__SNAPSHOT_INTERVAL_SECONDS`
- `MONITORING__HEALTH_CHECK_INTERVAL_SECONDS`

**Pattern Matching**:
- Uses glob patterns (shell-style wildcards)
- `*` matches any characters within a domain
- `**` not needed (flat namespace)
- Examples: `sensor.temp_*`, `light.*`, `binary_sensor.door_*`

**Performance Notes**:
- Empty `include` list monitors **all entities** (can be hundreds)
- Use `include` to reduce monitoring overhead
- Lower intervals increase CPU/network usage
- Typical setup monitors 50-200 entities

---

### Healing

Auto-healing configuration for integration reload and failure recovery.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `enabled` | boolean | `true` | - | Enable auto-healing |
| `max_attempts` | integer | `3` | 1-10 | Max healing attempts per integration |
| `cooldown_seconds` | integer | `300` | ≥ 0 | Cooldown between attempts |
| `circuit_breaker_threshold` | integer | `10` | ≥ 1 | Stop trying after N total failures |
| `circuit_breaker_reset_seconds` | integer | `3600` | ≥ 0 | Reset circuit breaker after this time |

**Example**:
```yaml
healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300  # 5 minutes
  circuit_breaker_threshold: 10
  circuit_breaker_reset_seconds: 3600  # 1 hour
```

**Aggressive Healing** (faster retries):
```yaml
healing:
  enabled: true
  max_attempts: 5
  cooldown_seconds: 120  # 2 minutes
  circuit_breaker_threshold: 15
  circuit_breaker_reset_seconds: 1800  # 30 minutes
```

**Conservative Healing** (slower, fewer retries):
```yaml
healing:
  enabled: true
  max_attempts: 2
  cooldown_seconds: 600  # 10 minutes
  circuit_breaker_threshold: 5
  circuit_breaker_reset_seconds: 7200  # 2 hours
```

**Environment Variables**:
- `HEALING__ENABLED`
- `HEALING__MAX_ATTEMPTS`
- `HEALING__COOLDOWN_SECONDS`
- `HEALING__CIRCUIT_BREAKER_THRESHOLD`
- `HEALING__CIRCUIT_BREAKER_RESET_SECONDS`

**Healing Strategy**:
1. Wait for grace period after entity becomes unavailable
2. Attempt integration reload (via HA service call)
3. Wait for cooldown period between attempts
4. Stop after `max_attempts` reached
5. Trigger circuit breaker after `circuit_breaker_threshold` total failures
6. Reset circuit breaker after `circuit_breaker_reset_seconds` with no failures

**Safety Features**:
- Respects cooldown to prevent rapid retry loops
- Circuit breaker prevents infinite retry cycles
- Escalates to notification when healing exhausted
- Dry-run mode available for testing (see [Operational Modes](#operational-modes))

---

### Notifications

Notification delivery configuration for alerts and reports.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `on_healing_failure` | boolean | `true` | Notify when healing fails |
| `weekly_summary` | boolean | `true` | Send weekly summary reports |
| `ha_service` | string | `"persistent_notification.create"` | Home Assistant notification service |
| `ai_enhanced` | boolean | `true` | Enable AI-enhanced notifications with LLM analysis |

**Example**:
```yaml
notifications:
  on_healing_failure: true
  weekly_summary: true
  ha_service: "persistent_notification.create"
  ai_enhanced: true  # Requires Ollama or Claude configured
```

**Alternative Notification Services**:
```yaml
notifications:
  # Use mobile app notifications
  ha_service: "notify.mobile_app_iphone"

  # Use Telegram
  ha_service: "notify.telegram"

  # Use multiple services (not yet supported - future feature)
  # ha_services:
  #   - "persistent_notification.create"
  #   - "notify.mobile_app_iphone"
```

**Environment Variables**:
- `NOTIFICATIONS__ON_HEALING_FAILURE`
- `NOTIFICATIONS__WEEKLY_SUMMARY`
- `NOTIFICATIONS__HA_SERVICE`
- `NOTIFICATIONS__AI_ENHANCED`

**AI-Enhanced Notifications**:

Requires Ollama or Claude configured in `intelligence` section. When enabled:
- Adds natural language explanations to failure notifications
- Provides troubleshooting recommendations
- Analyzes failure patterns
- Generates contextual insights

Example notification **without AI**:
```
HA Boss Alert
Entity: sensor.outdoor_temperature
Status: unavailable
Integration: met
```

Example notification **with AI**:
```
HA Boss Alert
Entity: sensor.outdoor_temperature
Status: unavailable
Integration: met

AI Insight:
The Met.no weather integration failed due to API rate limiting.
This typically occurs when polling too frequently. Consider:
1. Increasing update interval to 10+ minutes
2. Reducing number of weather sensors
3. Using local weather station instead
```

**Weekly Summary Reports**:

Sent every Monday at 09:00 (configurable) as Home Assistant persistent notification. Includes:
- Integration reliability scores
- Healing success rates
- Failure patterns and trends
- AI-generated recommendations
- Week-over-week comparison

Disable if you prefer manual reporting via CLI:
```yaml
notifications:
  weekly_summary: false
```

Then generate on-demand:
```bash
haboss report weekly
```

---

### Intelligence

AI/LLM configuration for Phase 3 intelligence features.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `pattern_collection_enabled` | boolean | `true` | - | Enable pattern collection for reliability analysis |
| `anomaly_detection_enabled` | boolean | `true` | - | Enable automatic anomaly detection |
| `anomaly_sensitivity_threshold` | float | `2.0` | 1.0-5.0 | Standard deviations for anomaly detection |
| `anomaly_scan_hours` | integer | `24` | 1-168 | Hours of data to scan for anomalies |
| `ollama_enabled` | boolean | `true` | - | Enable Ollama for AI features |
| `ollama_url` | string | `"http://localhost:11434"` | - | Ollama API URL |
| `ollama_model` | string | `"llama3.1:8b"` | - | Ollama model to use |
| `ollama_timeout_seconds` | float | `30.0` | ≥ 1.0 | Ollama request timeout |
| `claude_enabled` | boolean | `false` | - | Enable Claude API for complex tasks |
| `claude_api_key` | string | `null` | - | Claude API key (optional) |
| `claude_model` | string | `"claude-3-5-sonnet-20241022"` | - | Claude model to use |

**Example - Local LLM Only** (privacy-first):
```yaml
intelligence:
  # Pattern collection (Phase 2)
  pattern_collection_enabled: true

  # Anomaly detection
  anomaly_detection_enabled: true
  anomaly_sensitivity_threshold: 2.0  # Higher = less sensitive
  anomaly_scan_hours: 24

  # Local LLM (Ollama)
  ollama_enabled: true
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"
  ollama_timeout_seconds: 30.0

  # No cloud LLM
  claude_enabled: false
```

**Example - Hybrid LLM** (local + cloud):
```yaml
intelligence:
  pattern_collection_enabled: true
  anomaly_detection_enabled: true

  # Local LLM for routine tasks
  ollama_enabled: true
  ollama_url: "http://ollama:11434"  # Docker service name
  ollama_model: "llama3.1:8b"

  # Cloud LLM for complex tasks (automation generation)
  claude_enabled: true
  claude_api_key: "${CLAUDE_API_KEY}"
  claude_model: "claude-3-5-sonnet-20241022"
```

**Example - No AI Features**:
```yaml
intelligence:
  pattern_collection_enabled: true  # Still collect data
  anomaly_detection_enabled: false
  ollama_enabled: false
  claude_enabled: false
```

**Environment Variables**:
- `INTELLIGENCE__PATTERN_COLLECTION_ENABLED`
- `INTELLIGENCE__ANOMALY_DETECTION_ENABLED`
- `INTELLIGENCE__ANOMALY_SENSITIVITY_THRESHOLD`
- `INTELLIGENCE__ANOMALY_SCAN_HOURS`
- `INTELLIGENCE__OLLAMA_ENABLED`
- `INTELLIGENCE__OLLAMA_URL`
- `INTELLIGENCE__OLLAMA_MODEL`
- `INTELLIGENCE__OLLAMA_TIMEOUT_SECONDS`
- `INTELLIGENCE__CLAUDE_ENABLED`
- `INTELLIGENCE__CLAUDE_API_KEY` or `CLAUDE_API_KEY`
- `INTELLIGENCE__CLAUDE_MODEL`

**Anomaly Detection Sensitivity**:

- **1.0**: Very sensitive (many alerts, potential false positives)
- **2.0**: Balanced (recommended for most setups)
- **3.0**: Conservative (fewer alerts, only major anomalies)
- **5.0**: Very conservative (rare alerts, only severe issues)

**Ollama Models**:

| Model | Size | RAM | Speed | Quality | Use Case |
|-------|------|-----|-------|---------|----------|
| `llama3.1:8b` | 4.6GB | 8GB | Medium | High | Recommended |
| `mistral:7b` | 4.1GB | 8GB | Fast | Good | Alternative |
| `llama3.1:3b` | 2.0GB | 4GB | Very Fast | Fair | Low-resource systems |
| `llama3.1:70b` | 40GB | 64GB | Slow | Excellent | Overkill for HA Boss |

**Claude Models**:

| Model | Context | Speed | Cost | Use Case |
|-------|---------|-------|------|----------|
| `claude-3-5-sonnet-20241022` | 200K | Fast | Medium | Recommended |
| `claude-3-opus-20240229` | 200K | Slow | High | Maximum quality |
| `claude-3-haiku-20240307` | 200K | Very Fast | Low | Budget option |

**LLM Routing Strategy**:

HA Boss automatically routes tasks to the most appropriate LLM:

| Task | LLM Used | Rationale |
|------|----------|-----------|
| Enhanced notifications | Ollama | Fast, local, privacy-first |
| Anomaly detection | Ollama | Pattern matching, low latency |
| Weekly summaries | Ollama | Routine analysis, no complex reasoning |
| Automation analysis | Ollama | Structural analysis, simple patterns |
| Automation generation | Claude | Complex reasoning, YAML structure validation |

**Graceful Degradation**:

All AI features gracefully degrade if LLM unavailable:
- Notifications: Simple text without AI insights
- Anomaly detection: Basic threshold detection
- Weekly summaries: Stats-only reports
- Automation features: Disabled (requires LLM)

See [AI Features Guide](../AI_FEATURES.md) for detailed setup and usage.

---

### Database

SQLite database configuration for state history and pattern storage.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `path` | Path | `/data/ha_boss.db` | - | SQLite database path |
| `echo` | boolean | `false` | - | Enable SQL query logging (debug only) |
| `retention_days` | integer | `30` | ≥ 1 | History retention in days |

**Example**:
```yaml
database:
  path: "/data/ha_boss.db"
  echo: false  # Set true for SQL debugging
  retention_days: 30
```

**Docker Volume Mount**:
```yaml
# docker-compose.yml
services:
  haboss:
    volumes:
      - haboss_data:/data  # Database stored here

volumes:
  haboss_data:
```

**Environment Variables**:
- `DATABASE__PATH`
- `DATABASE__ECHO`
- `DATABASE__RETENTION_DAYS`

**Database Tables**:

| Table | Purpose | Retention |
|-------|---------|-----------|
| `entities` | Entity metadata and current state | Permanent |
| `health_events` | Health check results and state changes | Per `retention_days` |
| `healing_actions` | Healing attempts and outcomes | Per `retention_days` |
| `integration_patterns` | Reliability patterns and statistics | Per `retention_days` |

**Database Maintenance**:

Automatic cleanup runs daily at 02:00 to remove records older than `retention_days`:
```bash
# Manual cleanup
haboss db clean --older-than 30

# Vacuum database (reclaim space)
haboss db vacuum

# Database statistics
haboss db stats
```

**Database Location Recommendations**:

- **Docker**: Use named volume (as shown above)
- **Local development**: Use `./data/ha_boss.db` (relative path)
- **Production**: Use absolute path on persistent storage
- **Testing**: Use `:memory:` for in-memory database

**Backup Recommendations**:

```bash
# Backup database (while HA Boss running)
docker exec haboss sqlite3 /data/ha_boss.db ".backup /data/ha_boss_backup.db"

# Copy backup to host
docker cp haboss:/data/ha_boss_backup.db ./backup/

# Restore from backup
docker cp ./backup/ha_boss_backup.db haboss:/data/ha_boss.db
docker-compose restart haboss
```

---

### Logging

Logging configuration for application logs and debugging.

| Setting | Type | Default | Options | Description |
|---------|------|---------|---------|-------------|
| `level` | string | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Log level |
| `format` | string | `"text"` | `json`, `text` | Log format |
| `file` | Path | `/data/ha_boss.log` | - | Log file path |
| `max_size_mb` | integer | `10` | ≥ 1 | Max log file size in MB |
| `backup_count` | integer | `5` | ≥ 0 | Number of backup log files to keep |

**Example - Development**:
```yaml
logging:
  level: "DEBUG"
  format: "text"
  file: "/data/ha_boss.log"
  max_size_mb: 10
  backup_count: 5
```

**Example - Production**:
```yaml
logging:
  level: "INFO"
  format: "json"  # Structured logging for log aggregation
  file: "/data/ha_boss.log"
  max_size_mb: 50  # Larger files
  backup_count: 10  # More backups
```

**Environment Variables**:
- `LOGGING__LEVEL` or `LOG_LEVEL`
- `LOGGING__FORMAT`
- `LOGGING__FILE`
- `LOGGING__MAX_SIZE_MB`
- `LOGGING__BACKUP_COUNT`

**Log Levels**:

| Level | Use Case | Typical Output |
|-------|----------|----------------|
| `DEBUG` | Development, troubleshooting | All messages including variable values |
| `INFO` | Normal operation | Startup, healing actions, state changes |
| `WARNING` | Potential issues | Configuration warnings, retry attempts |
| `ERROR` | Recoverable errors | Failed API calls, integration reload failures |
| `CRITICAL` | Unrecoverable errors | Database corruption, configuration errors |

**Log Formats**:

**Text** (human-readable):
```
2024-11-30 10:15:23 INFO [ha_boss.monitoring] Entity sensor.temp_bedroom became unavailable
2024-11-30 10:20:23 INFO [ha_boss.healing] Successfully healed integration 'esphome' (attempt 1/3)
```

**JSON** (machine-parseable):
```json
{"timestamp": "2024-11-30T10:15:23Z", "level": "INFO", "logger": "ha_boss.monitoring", "message": "Entity sensor.temp_bedroom became unavailable", "entity_id": "sensor.temp_bedroom"}
{"timestamp": "2024-11-30T10:20:23Z", "level": "INFO", "logger": "ha_boss.healing", "message": "Successfully healed integration", "integration": "esphome", "attempt": 1, "max_attempts": 3}
```

**Log Rotation**:

Logs automatically rotate when reaching `max_size_mb`:
```
/data/ha_boss.log        # Current log
/data/ha_boss.log.1      # Previous log
/data/ha_boss.log.2
...
/data/ha_boss.log.5      # Oldest log (then deleted)
```

**Viewing Logs**:

```bash
# Docker logs (stdout/stderr)
docker-compose logs -f haboss

# File logs
docker exec haboss tail -f /data/ha_boss.log

# Search logs
docker exec haboss grep "ERROR" /data/ha_boss.log

# View JSON logs
docker exec haboss cat /data/ha_boss.log | jq '.'
```

---

### WebSocket

WebSocket client configuration for real-time state monitoring.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `reconnect_delay_seconds` | integer | `5` | ≥ 1 | Reconnect delay after disconnect |
| `heartbeat_interval_seconds` | integer | `30` | ≥ 10 | Heartbeat interval to keep connection alive |
| `timeout_seconds` | integer | `10` | ≥ 5 | Connection timeout |

**Example**:
```yaml
websocket:
  reconnect_delay_seconds: 5
  heartbeat_interval_seconds: 30
  timeout_seconds: 10
```

**Unreliable Network** (frequent disconnects):
```yaml
websocket:
  reconnect_delay_seconds: 3  # Faster reconnection
  heartbeat_interval_seconds: 15  # More frequent heartbeat
  timeout_seconds: 15  # Longer timeout
```

**Stable Network** (optimize for performance):
```yaml
websocket:
  reconnect_delay_seconds: 10
  heartbeat_interval_seconds: 60  # Less frequent heartbeat
  timeout_seconds: 10
```

**Environment Variables**:
- `WEBSOCKET__RECONNECT_DELAY_SECONDS`
- `WEBSOCKET__HEARTBEAT_INTERVAL_SECONDS`
- `WEBSOCKET__TIMEOUT_SECONDS`

**WebSocket Connection Flow**:

1. Connect to `ws://<ha_url>/api/websocket`
2. Receive `auth_required` message
3. Send `auth` with long-lived token
4. Receive `auth_ok` confirmation
5. Subscribe to `state_changed` events
6. Send ping every `heartbeat_interval_seconds`
7. If connection lost, wait `reconnect_delay_seconds` and retry

**Troubleshooting**:

- **Frequent reconnects**: Increase `timeout_seconds` and `heartbeat_interval_seconds`
- **Slow reconnection**: Decrease `reconnect_delay_seconds`
- **Missed events**: Check Home Assistant WebSocket logs for rate limiting

---

### REST API

REST API client configuration for Home Assistant API calls.

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `timeout_seconds` | integer | `10` | ≥ 1 | Request timeout |
| `retry_attempts` | integer | `3` | ≥ 0 | Retry attempts for failed requests |
| `retry_base_delay_seconds` | float | `1.0` | ≥ 0.1 | Base delay for exponential backoff |

**Example**:
```yaml
rest:
  timeout_seconds: 10
  retry_attempts: 3
  retry_base_delay_seconds: 1.0
```

**Slow Network** (high latency):
```yaml
rest:
  timeout_seconds: 30  # Longer timeout
  retry_attempts: 5  # More retries
  retry_base_delay_seconds: 2.0  # Longer delays
```

**Fast Network** (low latency):
```yaml
rest:
  timeout_seconds: 5
  retry_attempts: 2
  retry_base_delay_seconds: 0.5
```

**Environment Variables**:
- `REST__TIMEOUT_SECONDS`
- `REST__RETRY_ATTEMPTS`
- `REST__RETRY_BASE_DELAY_SECONDS`

**Exponential Backoff**:

Retry delays increase exponentially:
- Attempt 1: `retry_base_delay_seconds * 2^0` = 1.0s
- Attempt 2: `retry_base_delay_seconds * 2^1` = 2.0s
- Attempt 3: `retry_base_delay_seconds * 2^2` = 4.0s

**REST API Endpoints Used**:

| Endpoint | Purpose | Frequency |
|----------|---------|-----------|
| `GET /api/states` | Fetch all entity states | Per `snapshot_interval_seconds` |
| `GET /api/states/<entity_id>` | Fetch specific entity | On-demand |
| `POST /api/services/<domain>/<service>` | Call services (e.g., reload) | On healing |
| `GET /api/history/period/<timestamp>` | Replay missed events | On reconnect |

---

## Environment Variables

HA Boss supports environment variable overrides for all configuration settings using the **nested delimiter** pattern.

### Nested Field Naming

Use double underscore (`__`) to access nested fields:

```bash
# Section__Field
HOME_ASSISTANT__URL=http://homeassistant.local:8123
HOME_ASSISTANT__TOKEN=your_token_here
MONITORING__GRACE_PERIOD_SECONDS=300
INTELLIGENCE__OLLAMA_ENABLED=true
```

### Common Environment Variables

```bash
# Required
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here

# Optional shortcuts (alternative to nested format)
LOG_LEVEL=INFO
MODE=production

# Ollama configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# Claude configuration (optional)
CLAUDE_API_KEY=sk-ant-...

# Development
LOG_LEVEL=DEBUG
MODE=dry_run

# Testing
TEST_HA_URL=http://localhost:8123
TEST_HA_TOKEN=test_token
```

### Complete Environment Variable Reference

| Environment Variable | Config Path | Type | Example |
|---------------------|-------------|------|---------|
| `HA_URL` or `HOME_ASSISTANT__URL` | `home_assistant.url` | string | `http://homeassistant.local:8123` |
| `HA_TOKEN` or `HOME_ASSISTANT__TOKEN` | `home_assistant.token` | string | `eyJ0eXAiOiJKV...` |
| `MONITORING__GRACE_PERIOD_SECONDS` | `monitoring.grace_period_seconds` | integer | `300` |
| `MONITORING__STALE_THRESHOLD_SECONDS` | `monitoring.stale_threshold_seconds` | integer | `3600` |
| `MONITORING__SNAPSHOT_INTERVAL_SECONDS` | `monitoring.snapshot_interval_seconds` | integer | `300` |
| `MONITORING__HEALTH_CHECK_INTERVAL_SECONDS` | `monitoring.health_check_interval_seconds` | integer | `60` |
| `HEALING__ENABLED` | `healing.enabled` | boolean | `true` |
| `HEALING__MAX_ATTEMPTS` | `healing.max_attempts` | integer | `3` |
| `HEALING__COOLDOWN_SECONDS` | `healing.cooldown_seconds` | integer | `300` |
| `HEALING__CIRCUIT_BREAKER_THRESHOLD` | `healing.circuit_breaker_threshold` | integer | `10` |
| `HEALING__CIRCUIT_BREAKER_RESET_SECONDS` | `healing.circuit_breaker_reset_seconds` | integer | `3600` |
| `NOTIFICATIONS__ON_HEALING_FAILURE` | `notifications.on_healing_failure` | boolean | `true` |
| `NOTIFICATIONS__WEEKLY_SUMMARY` | `notifications.weekly_summary` | boolean | `true` |
| `NOTIFICATIONS__HA_SERVICE` | `notifications.ha_service` | string | `persistent_notification.create` |
| `NOTIFICATIONS__AI_ENHANCED` | `notifications.ai_enhanced` | boolean | `true` |
| `LOG_LEVEL` or `LOGGING__LEVEL` | `logging.level` | string | `INFO` |
| `LOGGING__FORMAT` | `logging.format` | string | `json` |
| `LOGGING__FILE` | `logging.file` | Path | `/data/ha_boss.log` |
| `LOGGING__MAX_SIZE_MB` | `logging.max_size_mb` | integer | `10` |
| `LOGGING__BACKUP_COUNT` | `logging.backup_count` | integer | `5` |
| `DATABASE__PATH` | `database.path` | Path | `/data/ha_boss.db` |
| `DATABASE__ECHO` | `database.echo` | boolean | `false` |
| `DATABASE__RETENTION_DAYS` | `database.retention_days` | integer | `30` |
| `WEBSOCKET__RECONNECT_DELAY_SECONDS` | `websocket.reconnect_delay_seconds` | integer | `5` |
| `WEBSOCKET__HEARTBEAT_INTERVAL_SECONDS` | `websocket.heartbeat_interval_seconds` | integer | `30` |
| `WEBSOCKET__TIMEOUT_SECONDS` | `websocket.timeout_seconds` | integer | `10` |
| `REST__TIMEOUT_SECONDS` | `rest.timeout_seconds` | integer | `10` |
| `REST__RETRY_ATTEMPTS` | `rest.retry_attempts` | integer | `3` |
| `REST__RETRY_BASE_DELAY_SECONDS` | `rest.retry_base_delay_seconds` | float | `1.0` |
| `INTELLIGENCE__PATTERN_COLLECTION_ENABLED` | `intelligence.pattern_collection_enabled` | boolean | `true` |
| `INTELLIGENCE__ANOMALY_DETECTION_ENABLED` | `intelligence.anomaly_detection_enabled` | boolean | `true` |
| `INTELLIGENCE__ANOMALY_SENSITIVITY_THRESHOLD` | `intelligence.anomaly_sensitivity_threshold` | float | `2.0` |
| `INTELLIGENCE__ANOMALY_SCAN_HOURS` | `intelligence.anomaly_scan_hours` | integer | `24` |
| `INTELLIGENCE__OLLAMA_ENABLED` or `OLLAMA_ENABLED` | `intelligence.ollama_enabled` | boolean | `true` |
| `INTELLIGENCE__OLLAMA_URL` or `OLLAMA_URL` | `intelligence.ollama_url` | string | `http://localhost:11434` |
| `INTELLIGENCE__OLLAMA_MODEL` or `OLLAMA_MODEL` | `intelligence.ollama_model` | string | `llama3.1:8b` |
| `INTELLIGENCE__OLLAMA_TIMEOUT_SECONDS` | `intelligence.ollama_timeout_seconds` | float | `30.0` |
| `INTELLIGENCE__CLAUDE_ENABLED` or `CLAUDE_ENABLED` | `intelligence.claude_enabled` | boolean | `false` |
| `INTELLIGENCE__CLAUDE_API_KEY` or `CLAUDE_API_KEY` | `intelligence.claude_api_key` | string | `sk-ant-...` |
| `INTELLIGENCE__CLAUDE_MODEL` or `CLAUDE_MODEL` | `intelligence.claude_model` | string | `claude-3-5-sonnet-20241022` |
| `MODE` | `mode` | string | `production` |

### Environment Variable Substitution in YAML

Use `${VAR_NAME}` syntax in YAML to load from environment:

```yaml
home_assistant:
  url: "${HA_URL}"
  token: "${HA_TOKEN}"

intelligence:
  claude_api_key: "${CLAUDE_API_KEY}"
```

If environment variable is not set, the placeholder is kept and validation will fail (for required fields).

---

## Operational Modes

HA Boss supports three operational modes controlled by the `mode` setting.

| Mode | Description | Healing | Service Calls | Use Case |
|------|-------------|---------|---------------|----------|
| `production` | Full operation | Enabled | Executed | Normal deployment |
| `dry_run` | Test mode | Simulated | Logged only | Testing configuration |
| `testing` | Unit tests | Disabled | Mocked | Automated testing |

### Production Mode

Full operation with auto-healing enabled.

```yaml
mode: "production"
```

```bash
# Environment variable
MODE=production
```

**Behavior**:
- Monitors all configured entities
- Performs auto-healing when issues detected
- Executes Home Assistant service calls
- Sends real notifications
- All features enabled

**Use when**: Running in production on your Home Assistant instance.

---

### Dry-Run Mode

Test mode that simulates actions without executing them.

```yaml
mode: "dry_run"
```

```bash
# Environment variable
MODE=dry_run
```

**Behavior**:
- Monitors entities (real)
- Detects issues (real)
- Simulates healing (no service calls)
- Logs actions that would be taken
- No notifications sent

**Use when**:
- Testing new configuration
- Validating entity filtering
- Observing detection behavior
- Safe testing on production HA

**Example dry-run log output**:
```
INFO: [DRY-RUN] Would reload integration 'esphome' for entity sensor.temp_bedroom
INFO: [DRY-RUN] Would send notification: "HA Boss Alert - Entity unavailable"
```

---

### Testing Mode

Internal mode for unit tests and CI/CD.

```yaml
mode: "testing"
```

**Behavior**:
- Uses in-memory database
- Mocks Home Assistant API calls
- Disables all external communication
- Fast execution for test suites

**Use when**: Running automated tests (handled by test framework).

---

## Example Configurations

### Minimal Configuration

Basic setup with defaults:

```yaml
# config/config.yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "${HA_TOKEN}"
```

All other settings use defaults. See sections above for default values.

---

### Home Lab Setup

Typical home lab configuration:

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "${HA_TOKEN}"

monitoring:
  grace_period_seconds: 300  # 5 minutes
  stale_threshold_seconds: 3600  # 1 hour
  health_check_interval_seconds: 60  # 1 minute

healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300  # 5 minutes
  circuit_breaker_threshold: 10
  circuit_breaker_reset_seconds: 3600  # 1 hour

notifications:
  on_healing_failure: true
  weekly_summary: true
  ai_enhanced: true

intelligence:
  pattern_collection_enabled: true
  anomaly_detection_enabled: true

  # Local LLM only (privacy-first)
  ollama_enabled: true
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"

  claude_enabled: false

logging:
  level: "INFO"
  format: "text"

database:
  retention_days: 30

mode: "production"
```

---

### Production Setup

Hardened production configuration:

```yaml
home_assistant:
  url: "${HA_URL}"  # From environment
  token: "${HA_TOKEN}"

monitoring:
  # Monitor only critical integrations
  include:
    - "light.*"
    - "switch.*"
    - "climate.*"
    - "binary_sensor.door_*"
    - "binary_sensor.motion_*"
    - "sensor.temperature_*"

  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sensor.uptime*"
    - "sun.sun"

  grace_period_seconds: 180  # Faster response
  health_check_interval_seconds: 30

healing:
  enabled: true
  max_attempts: 5  # More aggressive
  cooldown_seconds: 120
  circuit_breaker_threshold: 15
  circuit_breaker_reset_seconds: 1800

notifications:
  on_healing_failure: true
  weekly_summary: true
  ai_enhanced: true
  ha_service: "notify.mobile_app"  # Mobile notifications

intelligence:
  pattern_collection_enabled: true
  anomaly_detection_enabled: true
  anomaly_sensitivity_threshold: 1.5  # More sensitive

  # Hybrid LLM setup
  ollama_enabled: true
  ollama_url: "http://ollama:11434"
  ollama_model: "llama3.1:8b"
  ollama_timeout_seconds: 30

  claude_enabled: true
  claude_api_key: "${CLAUDE_API_KEY}"
  claude_model: "claude-3-5-sonnet-20241022"

logging:
  level: "INFO"
  format: "json"  # Structured logging
  max_size_mb: 50
  backup_count: 10

database:
  path: "/data/ha_boss.db"
  retention_days: 90  # Longer retention

websocket:
  reconnect_delay_seconds: 3  # Fast reconnection
  heartbeat_interval_seconds: 15

rest:
  timeout_seconds: 15
  retry_attempts: 5

mode: "production"
```

---

### Development Setup

Configuration for local development:

```yaml
home_assistant:
  url: "http://localhost:8123"  # Local HA instance
  token: "${HA_TOKEN}"

monitoring:
  grace_period_seconds: 60  # Faster for testing
  health_check_interval_seconds: 30

healing:
  enabled: true
  max_attempts: 2
  cooldown_seconds: 60  # Short cooldown

notifications:
  on_healing_failure: true
  weekly_summary: false  # Manual reports during dev
  ai_enhanced: true

intelligence:
  pattern_collection_enabled: true
  anomaly_detection_enabled: true

  ollama_enabled: true
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"

  claude_enabled: false  # Avoid API costs during dev

logging:
  level: "DEBUG"  # Verbose logging
  format: "text"
  file: "./data/ha_boss.log"  # Local path

database:
  path: "./data/ha_boss.db"  # Local path
  echo: true  # SQL query logging
  retention_days: 7  # Short retention

mode: "dry_run"  # Safe testing
```

---

### Docker Compose Setup

Complete `docker-compose.yml` configuration:

```yaml
version: '3.8'

services:
  haboss:
    image: jasonthagerty/ha_boss:latest
    container_name: haboss
    restart: unless-stopped
    depends_on:
      - ollama
    environment:
      # Required
      - HA_URL=${HA_URL}
      - HA_TOKEN=${HA_TOKEN}

      # Optional overrides
      - LOG_LEVEL=INFO
      - MODE=production

      # Ollama configuration (use service name)
      - OLLAMA_URL=http://ollama:11434
      - OLLAMA_MODEL=llama3.1:8b

      # Claude API (optional)
      - CLAUDE_API_KEY=${CLAUDE_API_KEY}
      - CLAUDE_ENABLED=true
    volumes:
      - ./config:/config:ro  # Read-only config
      - haboss_data:/data    # Persistent data
    networks:
      - haboss-network

  ollama:
    image: ollama/ollama:latest
    container_name: haboss_ollama
    restart: unless-stopped
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    networks:
      - haboss-network

volumes:
  haboss_data:
  ollama_data:

networks:
  haboss-network:
    driver: bridge
```

Corresponding `.env` file:

```bash
# Required
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here

# Optional
CLAUDE_API_KEY=sk-ant-your_api_key_here
```

---

### Privacy-First Setup

Maximum privacy configuration (no cloud services):

```yaml
home_assistant:
  url: "${HA_URL}"
  token: "${HA_TOKEN}"

monitoring:
  grace_period_seconds: 300
  health_check_interval_seconds: 60

healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300

notifications:
  on_healing_failure: true
  weekly_summary: true
  ai_enhanced: true  # Uses local LLM only

intelligence:
  pattern_collection_enabled: true
  anomaly_detection_enabled: true

  # Local LLM only
  ollama_enabled: true
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"

  # No cloud services
  claude_enabled: false

logging:
  level: "INFO"
  format: "text"

database:
  retention_days: 30

mode: "production"
```

**Privacy guarantees**:
- All data stays local
- No internet connection required (after Ollama model download)
- No cloud API calls
- No external telemetry

---

## Configuration Validation

HA Boss validates configuration at startup using Pydantic. Invalid configuration prevents startup with clear error messages.

### Validation Commands

```bash
# Validate configuration file
haboss config validate

# Validate and show loaded configuration
haboss config show

# Validate specific config file
haboss config validate --config /path/to/config.yaml

# Check environment variables
haboss config env
```

### Common Validation Errors

**Missing Required Fields**:
```
ConfigurationError: Field required: home_assistant.token
```

**Solution**: Set `HA_TOKEN` environment variable or add to config.yaml.

**Invalid Type**:
```
ConfigurationError: Input should be a valid integer, unable to parse string as an integer
```

**Solution**: Check field types match expected values (e.g., `grace_period_seconds: 300` not `"300"`).

**Out of Range**:
```
ConfigurationError: Input should be greater than or equal to 1
```

**Solution**: Adjust value to valid range (see tables above).

**Invalid URL**:
```
ConfigurationError: Invalid URL format: homeassistant.local:8123
```

**Solution**: Add protocol: `http://homeassistant.local:8123`

**Invalid Token**:
```
ConfigurationError: HA_TOKEN environment variable is not set
```

**Solution**: Set `HA_TOKEN` environment variable with valid token.

### Validation Levels

| Level | When | Description |
|-------|------|-------------|
| **Type Checking** | Always | Pydantic validates field types |
| **Range Checking** | Always | Values must be within specified ranges |
| **Format Checking** | Always | URLs, paths must be valid format |
| **Connectivity** | Startup | Verify Home Assistant is reachable |
| **Authentication** | Startup | Verify token is valid |
| **LLM Availability** | Runtime | Check Ollama/Claude accessible |

---

## Best Practices

### Security

1. **Never commit secrets**: Use `.env` files (add to `.gitignore`)
2. **Use environment variables**: For tokens, API keys, passwords
3. **Restrict file permissions**: `chmod 600 .env config.yaml`
4. **Rotate tokens regularly**: Generate new HA tokens periodically
5. **Use read-only volumes**: Mount config as read-only in Docker (`:ro`)

### Performance

1. **Target monitoring**: Use `include` to monitor only critical entities
2. **Adjust intervals**: Balance responsiveness vs. resource usage
3. **Enable pattern collection**: Improves anomaly detection over time
4. **Use local LLM**: Ollama faster than Claude for routine tasks
5. **Monitor resource usage**: Check CPU, RAM, disk I/O regularly

### Reliability

1. **Enable healing**: Set `healing.enabled: true` (default)
2. **Conservative circuit breaker**: Prevent infinite retry loops
3. **Appropriate grace periods**: Avoid false positives from brief outages
4. **Enable notifications**: Stay informed of issues
5. **Review weekly summaries**: Identify reliability trends

### Maintenance

1. **Regular backups**: Backup database weekly (or daily for production)
2. **Log rotation**: Ensure logs don't fill disk (default: 10MB * 5 files)
3. **Database cleanup**: Retention policy prevents unbounded growth
4. **Update regularly**: Pull latest Docker image for bug fixes
5. **Review configuration**: Adjust thresholds based on observed behavior

### Testing

1. **Start with dry-run**: Test configuration safely with `mode: dry_run`
2. **Validate before deploy**: Run `haboss config validate`
3. **Monitor logs**: Check for errors after configuration changes
4. **Test healing manually**: Use CLI to trigger test heals
5. **Verify notifications**: Ensure alerts reach you

---

## Troubleshooting

### Configuration Not Loading

**Symptom**: HA Boss doesn't reflect config changes

**Solutions**:
```bash
# Restart service
docker-compose restart haboss

# Check config file location
docker exec haboss ls -la /config/

# Validate configuration
docker exec haboss haboss config validate

# Check environment variables
docker exec haboss env | grep HA_
```

### Environment Variables Not Working

**Symptom**: Settings don't override config.yaml

**Solutions**:
- Restart container after `.env` changes
- Check `.env` syntax (no spaces around `=`)
- Use correct nested delimiter (`__` not `.`)
- Verify environment loaded: `docker exec haboss env`

### Invalid Configuration Error

**Symptom**: Startup fails with validation error

**Solutions**:
1. Read error message carefully (shows field and issue)
2. Check field type matches expected (string, integer, boolean)
3. Verify values within valid ranges
4. Ensure required fields set (especially `HA_TOKEN`)
5. Validate YAML syntax (indentation, quotes)

### Can't Connect to Home Assistant

**Symptom**: "Connection refused" or "Timeout" errors

**Solutions**:
```bash
# Test connectivity from host
curl http://homeassistant.local:8123/api/

# Test from HA Boss container
docker exec haboss curl http://homeassistant.local:8123/api/

# Check HA URL in config
docker exec haboss haboss config show | grep url

# Verify HA is running
docker ps | grep homeassistant
```

### Authentication Failed

**Symptom**: "401 Unauthorized" errors

**Solutions**:
1. Verify token is correct (copy from HA profile)
2. Check token not expired (default: 10 years)
3. Ensure `${HA_TOKEN}` substitution working
4. Test token manually:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
        http://homeassistant.local:8123/api/
   ```

### Ollama Not Available

**Symptom**: "Ollama not available" in logs

**Solutions**:
```bash
# Check Ollama container running
docker ps | grep ollama

# Test Ollama API
curl http://localhost:11434/api/tags

# Check model downloaded
docker exec haboss_ollama ollama list

# Pull model if missing
docker exec haboss_ollama ollama pull llama3.1:8b
```

### High CPU Usage

**Symptom**: HA Boss consuming excessive CPU

**Possible causes**:
- Monitoring too many entities (thousands)
- Health check interval too low (< 10s)
- Ollama inference running continuously
- WebSocket reconnection loop

**Solutions**:
1. Use `include` patterns to reduce monitored entities
2. Increase `health_check_interval_seconds`
3. Check logs for reconnection issues
4. Monitor Ollama usage: `docker stats haboss_ollama`

### Database Growing Too Large

**Symptom**: `ha_boss.db` file size increasing rapidly

**Solutions**:
```bash
# Check database size
docker exec haboss ls -lh /data/ha_boss.db

# Check retention settings
docker exec haboss haboss config show | grep retention

# Reduce retention period
# Set database.retention_days to lower value (e.g., 14)

# Manual cleanup
docker exec haboss haboss db clean --older-than 14

# Vacuum database
docker exec haboss haboss db vacuum
```

---

## Additional Resources

- **Main Documentation**: [README.md](../../README.md)
- **AI Features Guide**: [AI_FEATURES.md](../AI_FEATURES.md)
- **LLM Setup Guide**: [LLM_SETUP.md](../LLM_SETUP.md)
- **CLI Commands**: [CLI-Commands.md](./CLI-Commands.md)
- **Developer Guide**: [CLAUDE.md](../../CLAUDE.md)
- **Example Configuration**: [config.yaml.example](../../config/config.yaml.example)
- **Example Environment**: [.env.example](../../.env.example)

---

**Last Updated**: 2024-12-19
**HA Boss Version**: Phase 3 (AI-Powered Intelligence Layer)
**Status**: Complete
