# Architecture

This document provides a comprehensive overview of HA Boss's technical architecture, design patterns, and component interactions.

## Table of Contents

- [System Overview](#system-overview)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Key Design Patterns](#key-design-patterns)
- [Component Architecture](#component-architecture)
- [Data Flow](#data-flow)
- [Database Schema](#database-schema)
- [Home Assistant Integration](#home-assistant-integration)
- [Design Philosophy](#design-philosophy)

## System Overview

HA Boss is a standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and provides AI-powered automation management. The architecture follows an MVP-first approach with three completed phases:

**Phase 1 (MVP - Complete):**
- Real-time monitoring of Home Assistant entities via WebSocket
- Automatic detection of unavailable/stale entities
- Auto-healing via integration reload with safety mechanisms
- Escalated notifications when auto-healing fails
- Docker-first deployment

**Phase 2 (Pattern Collection & Analysis - Complete):**
- Integration reliability tracking (success rates, failure patterns)
- Database schema for pattern storage
- CLI reports for reliability analysis
- Foundation for AI-driven insights

**Phase 3 (AI-Powered Intelligence Layer - Complete):**
- Local LLM integration (Ollama) for enhanced notifications
- Claude API integration for complex reasoning and automation generation
- Intelligent LLM router with local-first fallback strategy
- Pattern-based anomaly detection with AI-generated insights
- Weekly AI-analyzed summary reports
- Automation analysis with optimization suggestions
- Natural language automation generation
- Performance benchmarks validating < 15s response times

### High-Level Architecture Diagram

```
┌──────────────────────────────────────┐
│      HA Boss Service                 │
├──────────────────────────────────────┤
│  WebSocket Monitor ──▶ State Tracker│
│  Health Monitor ──▶ Healing Manager  │
│  Pattern Collector ──▶ AI Analyzer   │
│  Notification Manager ◀── Escalation │
└──────────────────────────────────────┘
         │                    │
         │ REST + WebSocket   │ SQLite
         ▼                    ▼
   ┌─────────────┐      ┌──────────┐
   │ Home        │      │ Pattern  │
   │ Assistant   │      │ Database │
   └─────────────┘      └──────────┘
```

## Technology Stack

### Core Technologies

- **Python 3.12**: Primary programming language (standardized)
- **asyncio**: Asynchronous I/O for concurrent operations
- **aiohttp**: Async HTTP client for REST API calls
- **websockets**: WebSocket client for real-time monitoring
- **SQLAlchemy**: ORM with async support (aiosqlite)
- **Pydantic**: Configuration validation and settings management
- **Typer**: CLI framework with rich formatting
- **Docker**: Containerized deployment with multi-stage builds

### AI/LLM Stack

- **Ollama**: Local LLM inference (Llama 3.1 8B, Q4_K_M quantization)
- **Claude API**: Optional cloud-based LLM for complex reasoning
- **LLM Router**: Intelligent task routing with local-first fallback
- **Performance**: < 15s response time for low-volume use (1-10 requests/day)

### Development Tools

- **pytest**: Testing framework with async support
- **black**: Code formatting (100 char line length)
- **ruff**: Fast linting and import sorting
- **mypy**: Static type checking (strict mode)
- **uv**: Fast Python package installer

## Project Structure

```
ha_boss/
├── ha_boss/                    # Main package code
│   ├── core/                   # Core infrastructure
│   │   ├── config.py          # Pydantic configuration models
│   │   ├── ha_client.py       # Home Assistant API wrapper
│   │   ├── database.py        # SQLAlchemy models and DB management
│   │   └── llm_router.py      # LLM task routing
│   ├── monitoring/             # Entity monitoring
│   │   ├── state_tracker.py   # Track entity states
│   │   ├── health_monitor.py  # Health checks and anomaly detection
│   │   ├── websocket_client.py # WebSocket connection manager
│   │   └── anomaly_detector.py # LLM-powered anomaly detection
│   ├── healing/                # Auto-healing system
│   │   ├── integration_manager.py  # Integration discovery and reload
│   │   ├── heal_strategies.py      # Healing strategies and logic
│   │   └── escalation.py           # Notification escalation
│   ├── intelligence/           # AI features
│   │   ├── ollama_client.py   # Ollama client
│   │   ├── claude_client.py   # Claude API client
│   │   ├── llm_router.py      # Intelligent LLM routing
│   │   ├── anomaly_detector.py # Pattern-based anomaly detection
│   │   ├── weekly_summary.py  # AI-generated weekly reports
│   │   ├── pattern_collector.py # Pattern data collection
│   │   └── reliability_analyzer.py # Integration reliability analysis
│   ├── automation/             # Automation management
│   │   ├── analyzer.py        # Automation analysis
│   │   └── generator.py       # AI automation generation
│   ├── notifications/          # Notification system
│   │   ├── manager.py         # Notification routing
│   │   └── templates.py       # Message templates
│   ├── api/                   # REST API (future)
│   │   └── routes.py          # FastAPI routes
│   └── cli/                   # Command-line interface
│       └── commands.py        # CLI commands (Typer)
├── tests/                     # Test suite
│   ├── core/                  # Core component tests
│   ├── monitoring/            # Monitoring tests
│   ├── healing/               # Healing tests
│   └── fixtures/              # Shared pytest fixtures
├── config/                    # Configuration directory
│   ├── config.yaml.example   # Example configuration
│   └── .env.example          # Environment variables
├── data/                      # Runtime data (created by Docker)
│   └── ha_boss.db            # SQLite database
├── docs/                      # Documentation
│   └── wiki/                  # Wiki pages
├── .claude/                   # Claude Code configuration
├── .github/                   # GitHub configuration
├── Dockerfile                 # Docker image
├── docker-compose.yml         # Docker Compose config
└── pyproject.toml            # Project metadata
```

### Module Placement Guidelines

When adding new features:

1. **Core Infrastructure**: Place in `core/` (config, database, shared clients)
2. **Feature-Specific Code**: Place in appropriate subdirectory (monitoring, healing, intelligence)
3. **Tests**: Mirror source structure in `tests/` directory
4. **Documentation**: Add to `docs/` with wiki pages for major features

## Key Design Patterns

### 1. Async-First Architecture

All I/O operations use `async`/`await` for maximum efficiency:

```python
# WebSocket connections maintained with asyncio
async def connect_websocket():
    async with websockets.connect(url) as ws:
        await ws.send(message)
        response = await ws.recv()

# Concurrent operations with asyncio.gather()
results = await asyncio.gather(
    fetch_entity_state(entity1),
    fetch_entity_state(entity2),
    fetch_entity_state(entity3)
)

# Background tasks with asyncio.create_task()
monitor_task = asyncio.create_task(health_monitor.run())
```

### 2. Safety Mechanisms

Multiple layers of protection prevent cascading failures:

**Circuit Breakers:**
- Stop retrying after threshold failures
- Prevent overwhelming Home Assistant with requests
- Automatic reset after cooldown period

**Cooldowns:**
- Prevent rapid retry loops
- Configurable per-integration timeouts
- Exponential backoff for persistent failures

**Dry-Run Mode:**
- Test changes without executing
- Validate healing strategies safely
- Preview automation changes before applying

**Graceful Degradation:**
- Continue operating with reduced functionality
- Fall back to REST API if WebSocket fails
- Skip unavailable LLMs and continue monitoring

### 3. Error Handling Strategy

Specific exceptions with exponential backoff:

```python
async def call_ha_api_with_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0
) -> Any:
    """Call Home Assistant API with exponential backoff retry."""
    for attempt in range(max_attempts):
        try:
            return await func()
        except HomeAssistantConnectionError as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
```

**Exception Hierarchy:**
- `HomeAssistantError` (base)
  - `HomeAssistantConnectionError` (network issues)
  - `HomeAssistantAuthError` (authentication failures)
  - `HomeAssistantServiceError` (service call failures)
- `HealingError` (base)
  - `IntegrationReloadError` (reload failures)
  - `CircuitBreakerOpenError` (too many failures)

### 4. Database Design

SQLAlchemy async ORM with structured schema:

**Core Tables:**
- `entities`: Entity metadata and current state
- `health_events`: Historical health check results
- `healing_actions`: Healing attempts and outcomes
- `integrations`: Integration reliability metrics
- `patterns`: Failure patterns for AI analysis

**Design Principles:**
- Use type hints for all model fields
- Implement soft deletes where appropriate
- Add indexes on frequently queried columns
- Use UTC timestamps consistently
- Migrations via Alembic (planned)

```python
class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True)
    entity_id = Column(String, unique=True, nullable=False, index=True)
    domain = Column(String, nullable=False, index=True)
    state = Column(String)
    last_updated = Column(DateTime, nullable=False, index=True)
    attributes = Column(JSON)
```

## Component Architecture

### Detailed Component Diagram

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

### Component Descriptions

#### 1. WebSocket Monitor (`monitoring/websocket_client.py`)

**Responsibilities:**
- Establish and maintain WebSocket connection to Home Assistant
- Subscribe to `state_changed` events
- Implement heartbeat/ping-pong for connection health
- Handle automatic reconnection with exponential backoff
- Filter events for monitored entities

**Key Features:**
- Auto-reconnection on disconnect
- Exponential backoff retry logic
- Connection health monitoring
- Event filtering and routing

#### 2. State Tracker (`monitoring/state_tracker.py`)

**Responsibilities:**
- Maintain in-memory cache of entity states
- Track state history for pattern analysis
- Persist state changes to database
- Provide fast state lookups for health checks

**Key Features:**
- LRU cache for recent states
- Configurable history retention
- Efficient state diffing
- Async database writes

#### 3. Health Monitor (`monitoring/health_monitor.py`)

**Responsibilities:**
- Continuously monitor entity health
- Detect unavailable/unknown states
- Implement grace periods before triggering healing
- Identify patterns and anomalies

**Key Features:**
- Configurable health check intervals
- Grace period support (avoid false positives)
- Integration with AI anomaly detection
- Health score calculation

#### 4. Healing Manager (`healing/integration_manager.py`)

**Responsibilities:**
- Discover integration-to-entity mappings
- Execute integration reloads via Home Assistant API
- Implement circuit breakers and cooldowns
- Track healing success/failure rates

**Key Features:**
- Multiple healing strategies
- Circuit breaker pattern
- Cooldown enforcement
- Success rate tracking

#### 5. Notification Manager (`notifications/manager.py`)

**Responsibilities:**
- Route notifications to appropriate channels
- Format messages using templates
- Create persistent notifications in Home Assistant
- Log notifications for audit trail

**Key Features:**
- Multiple notification channels
- Template-based message formatting
- Notification throttling
- Escalation support

#### 6. LLM Router (`intelligence/llm_router.py`)

**Responsibilities:**
- Route LLM tasks to appropriate backend (Ollama/Claude)
- Implement local-first fallback strategy
- Handle LLM failures gracefully
- Track LLM performance metrics

**Key Features:**
- Task complexity analysis
- Automatic fallback on failure
- Response caching
- Performance monitoring

## Data Flow

### Startup Sequence

```
1. Load Configuration
   ├─ Read config.yaml
   ├─ Load environment variables (.env)
   └─ Validate with Pydantic models

2. Initialize Database
   ├─ Connect to SQLite (or create new)
   ├─ Create tables if needed
   └─ Load entity history

3. Connect to Home Assistant
   ├─ Validate REST API connection
   ├─ Authenticate with long-lived token
   └─ Verify API accessibility

4. Discover Integrations
   ├─ Fetch all config entries
   ├─ Build entity→integration mapping
   └─ Cache mapping in memory

5. Establish WebSocket
   ├─ Connect to WebSocket API
   ├─ Authenticate
   ├─ Subscribe to state_changed events
   └─ Start heartbeat loop

6. Fetch Initial State
   ├─ Get all entity states via REST
   ├─ Populate state cache
   └─ Initialize health baselines

7. Start Monitoring
   ├─ Begin WebSocket event loop
   ├─ Start health monitoring background task
   └─ Initialize healing cooldowns
```

### Runtime Monitoring Loop

```
1. WebSocket receives state_changed event
   │
   ▼
2. State Tracker processes event
   ├─ Update in-memory cache
   ├─ Persist to database (async)
   └─ Calculate state diff
   │
   ▼
3. Health Monitor evaluates state
   ├─ Check if state indicates issue
   │  (unavailable, unknown, stale)
   ├─ Apply grace period logic
   └─ Calculate health score
   │
   ▼
4. Decision: Healing needed?
   ├─ No  → Continue monitoring
   └─ Yes → Proceed to healing
      │
      ▼
5. Healing Manager attempts repair
   ├─ Check circuit breaker status
   ├─ Verify cooldown period elapsed
   ├─ Identify target integration
   ├─ Execute integration reload
   └─ Record healing action
   │
   ▼
6. Evaluate healing outcome
   ├─ Success → Reset failure counters
   └─ Failure → Increment counters
      │
      ▼
7. Escalation (if healing failed)
   ├─ Create persistent notification
   ├─ Log to database
   └─ Optional: Send external alert
```

### WebSocket Disconnect Recovery

```
1. Detect Disconnection
   ├─ Connection closed event
   ├─ Timeout on heartbeat
   └─ Read/write error
   │
   ▼
2. Log Warning
   ├─ Record disconnect time
   ├─ Note last successful message
   └─ Increment disconnect counter
   │
   ▼
3. Start Reconnection Loop
   ├─ Wait: exponential backoff
   │  (1s, 2s, 4s, 8s, max 60s)
   ├─ Attempt reconnection
   └─ Repeat until successful
   │
   ▼
4. Optional: REST Polling Fallback
   ├─ Poll /api/states periodically
   ├─ Update state cache
   └─ Continue health monitoring
   │
   ▼
5. Reconnect Successfully
   ├─ Authenticate
   ├─ Subscribe to events
   └─ Resume heartbeat
   │
   ▼
6. Catch Up on Missed Events
   ├─ Fetch history via REST API
   │  GET /api/history/period/<timestamp>
   ├─ Process missed state changes
   └─ Update state cache
   │
   ▼
7. Resume Normal Operation
```

## Database Schema

### Entity State Tracking

**Table: `entities`**
```sql
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    entity_id TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    friendly_name TEXT,
    state TEXT,
    attributes JSON,
    last_changed TIMESTAMP,
    last_updated TIMESTAMP NOT NULL,
    first_seen TIMESTAMP NOT NULL,

    INDEX idx_entity_id (entity_id),
    INDEX idx_domain (domain),
    INDEX idx_last_updated (last_updated)
);
```

**Table: `health_events`**
```sql
CREATE TABLE health_events (
    id INTEGER PRIMARY KEY,
    entity_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    health_status TEXT NOT NULL,  -- healthy, degraded, unhealthy
    state TEXT,
    details JSON,

    INDEX idx_entity_timestamp (entity_id, timestamp),
    INDEX idx_timestamp (timestamp)
);
```

### Healing Actions

**Table: `healing_actions`**
```sql
CREATE TABLE healing_actions (
    id INTEGER PRIMARY KEY,
    entity_id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- reload, restart, etc.
    timestamp TIMESTAMP NOT NULL,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER,
    error_message TEXT,

    INDEX idx_entity_timestamp (entity_id, timestamp),
    INDEX idx_integration (integration_id),
    INDEX idx_success (success)
);
```

### Integration Reliability

**Table: `integrations`**
```sql
CREATE TABLE integrations (
    id INTEGER PRIMARY KEY,
    integration_id TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    total_reloads INTEGER DEFAULT 0,
    successful_reloads INTEGER DEFAULT 0,
    failed_reloads INTEGER DEFAULT 0,
    last_reload_timestamp TIMESTAMP,
    last_failure_timestamp TIMESTAMP,
    circuit_breaker_trips INTEGER DEFAULT 0,

    INDEX idx_integration_id (integration_id),
    INDEX idx_domain (domain)
);
```

### Pattern Storage

**Table: `patterns`**
```sql
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- failure, anomaly, etc.
    entity_id TEXT,
    integration_id TEXT,
    detected_at TIMESTAMP NOT NULL,
    details JSON NOT NULL,
    severity TEXT NOT NULL,  -- low, medium, high, critical
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,

    INDEX idx_pattern_type (pattern_type),
    INDEX idx_detected_at (detected_at),
    INDEX idx_resolved (resolved)
);
```

## Home Assistant Integration

### API Architecture

HA Boss uses a hybrid approach for interacting with Home Assistant:

**WebSocket API** (Primary):
- Real-time state monitoring
- Instant event notifications
- Low latency, efficient
- Requires persistent connection

**REST API** (Secondary):
- Service calls (reload integrations)
- State snapshots (validation)
- History queries (catch-up after disconnect)
- Integration discovery

### WebSocket API Usage

**Connection Pattern:**

```python
# Connect to ws://ha-url:8123/api/websocket
# 1. Receive auth_required message
# 2. Send auth with long-lived token
# 3. Receive auth_ok
# 4. Subscribe to state_changed events
# 5. Maintain heartbeat with ping/pong every 30 seconds
```

**Key Events:**
- `state_changed`: Entity state transitions (primary monitoring event)
- `entity_registry_updated`: Entity added/removed/modified

**Important Limitations:**
- Cannot filter events server-side (receives ALL state changes)
- Must implement client-side filtering for monitored entities
- Connection can timeout (implement auto-reconnect)
- Max 512 pending messages before disconnect

### REST API Usage

**Key Endpoints:**

```
GET /api/states
  └─ Fetch all entity states (startup/validation)

GET /api/states/<entity_id>
  └─ Get specific entity state

POST /api/services/<domain>/<service>
  └─ Call Home Assistant service

GET /api/history/period/<timestamp>
  └─ Replay missed events after WebSocket disconnect

GET /api/config
  └─ Get Home Assistant configuration

GET /api/config/entity_registry/list
  └─ List all registered entities
```

**Service Calls for Healing:**

```python
# Reload specific integration
POST /api/services/homeassistant/reload_config_entry
{
  "entry_id": "abc123..."  # Integration config entry ID
}

# Reload all automations
POST /api/services/automation/reload

# Create persistent notification
POST /api/services/persistent_notification/create
{
  "title": "HA Boss Alert",
  "message": "...",
  "notification_id": "haboss_alert_123"
}
```

### Integration Discovery Challenge

**Problem:** No direct API to get integration config entry IDs (needed for reload)

**Solutions** (in priority order):

1. **Storage File Parsing**: Parse `.storage/core.config_entries` (most reliable)
   - Requires filesystem access to Home Assistant
   - Contains complete integration metadata
   - Updated in real-time by Home Assistant

2. **Entity→Device→Integration Mapping**: Map entity to device, device to config entry
   - Use entity registry API
   - Follow device_id to integration
   - Works remotely without filesystem access

3. **User Input**: Prompt user to manually specify entry IDs
   - Fallback for critical integrations
   - Documented in configuration guide
   - Stored in config.yaml

4. **WebSocket Query**: Some integrations expose via custom WebSocket commands
   - Integration-specific
   - Not universally available
   - Requires per-integration implementation

**Implementation:** `ha_boss/healing/integration_manager.py:IntegrationDiscovery`

### Error Handling

**Connection Errors:**
- Network timeout → Retry with exponential backoff
- Connection refused → Log error, retry after 30s
- 401 Unauthorized → Invalid token, alert user immediately, stop service

**Service Call Errors:**
- 404 Not Found → Service/entity doesn't exist (log warning, don't retry)
- Integration reload failed → Increment circuit breaker, escalate if threshold exceeded

**WebSocket Errors:**
- Connection closed → Auto-reconnect, replay missed events via REST history
- Auth timeout (10s) → Increase timeout configuration or check network
- Message queue full → Reduce monitored entities or implement filtering

### API Best Practices

**Rate Limiting:**
- Home Assistant has no enforced rate limits
- Use WebSocket for monitoring (don't poll with REST)
- Batch operations when possible
- Implement local caching to reduce API calls

**Retry Logic:**

```python
# Standard retry pattern for HA Boss
max_attempts = 3
base_delay = 1.0  # seconds

for attempt in range(max_attempts):
    try:
        result = await ha_client.call_service(...)
        return result
    except HomeAssistantConnectionError:
        if attempt == max_attempts - 1:
            raise
        await asyncio.sleep(base_delay * (2 ** attempt))
```

**State Caching:**
- Maintain in-memory cache of entity states from WebSocket
- Periodically validate cache with REST API snapshot (every 5-10 minutes)
- Use cache for health checks to avoid REST API overhead

### Configuration Requirements

**Required Settings:**
- `HA_URL`: Home Assistant instance URL (e.g., `http://homeassistant.local:8123`)
- `HA_TOKEN`: Long-lived access token (created in HA user profile)

**Creating Long-Lived Token:**
1. Navigate to HA profile: `http://ha-url/profile`
2. Scroll to "Long-Lived Access Tokens"
3. Click "Create Token"
4. Copy token immediately (cannot be retrieved later)
5. Store in `.env` file as `HA_TOKEN=...`

**Security Notes:**
- Tokens grant full API access (protect like passwords)
- Tokens stored in HA database but not displayed in UI after creation
- Default expiration: 10 years
- Consider separate HA user account for HA Boss with limited permissions (future)

## Design Philosophy

### 1. Start Simple

The MVP focuses on core monitoring and healing without unnecessary complexity:
- WebSocket monitoring over polling
- Simple state tracking
- Direct integration reloads
- Basic notifications

Advanced features (AI, pattern analysis, optimization) added incrementally after core stability proven.

### 2. Safety First

Multiple layers of safety prevent cascading failures:
- **Dry-run mode**: Test changes without executing
- **Circuit breakers**: Stop retrying after threshold failures
- **Cooldowns**: Prevent rapid retry loops
- **Rollback capability**: Planned for future versions
- **Graceful degradation**: Continue with reduced functionality

### 3. Fail Gracefully

When auto-healing fails, escalate to the user rather than failing silently:
- Clear, actionable notifications
- Persistent notifications in Home Assistant UI
- Detailed error logs for debugging
- Optional external alerting (future)

### 4. Learn Over Time

Collect patterns to improve effectiveness:
- Track integration reliability metrics
- Identify recurring failure patterns
- Build historical context for AI analysis
- Optimize healing strategies based on success rates

### 5. Hybrid AI

Balance local and cloud LLMs for best results:
- **Local LLM (Ollama)**: Routine tasks, privacy-sensitive operations, offline capability
- **Claude API**: Complex reasoning, automation generation, advanced analysis
- **Intelligent routing**: Automatically select appropriate LLM based on task complexity
- **Graceful fallback**: Continue operation if LLM unavailable

---

**Related Documentation:**
- [Development Guide](Development.md) - Setup, testing, and contribution guidelines
- [AI Features](../AI_FEATURES.md) - Detailed LLM integration documentation
- [Configuration Guide](https://github.com/jasonthagerty/ha_boss/wiki/Configuration) - Complete configuration reference
