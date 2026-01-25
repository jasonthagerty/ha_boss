# Multi-Instance Support

HA Boss supports managing multiple Home Assistant instances from a single deployment, enabling centralized monitoring and management for complex smart home setups.

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Dashboard Usage](#dashboard-usage)
- [Configuration](#configuration)
- [Migration Guide](#migration-guide)
- [Architecture](#architecture)
- [Examples](#examples)

---

## Overview

### What is Multi-Instance Support?

Multi-instance support allows a single HA Boss deployment to simultaneously monitor and manage multiple Home Assistant instances. This is useful for:

- **Multiple Properties** - Monitor vacation home, rental properties, or family members' homes
- **Test/Production Separation** - Separate development and production HA instances
- **Distributed Systems** - Manage multiple HA instances across different buildings or locations
- **Redundancy** - Monitor failover or backup HA instances

### Key Features

- ✅ **Independent Monitoring** - Each instance has separate state tracking, health monitoring, and healing
- ✅ **Isolated Statistics** - Per-instance metrics, failure counts, and healing history
- ✅ **Unified Dashboard** - Switch between instances via dropdown selector
- ✅ **Backward Compatible** - Single-instance deployments work without changes
- ✅ **Secure Isolation** - No data leakage between instances

---

## Getting Started

### Prerequisites

- HA Boss v2.0.0 or later
- Multiple Home Assistant instances with API access
- Long-lived access tokens for each instance

### Quick Start

**1. Configure Multiple Instances**

Edit `config/config.yaml`:

```yaml
# Multi-instance configuration
instances:
  - id: home
    url: http://home-assistant:8123
    token: eyJ0eXAiOiJKV1QiLCJhbGc...  # Home instance token

  - id: vacation
    url: http://vacation-ha:8123
    token: eyJ0eXAiOiJKV1QiLCJhbGN...  # Vacation instance token

  - id: testing
    url: http://test-ha:8123
    token: eyJ0eXAiOiJKV1QiLCJhbGN...  # Test instance token
```

**2. Start HA Boss**

```bash
# Starts monitoring all configured instances
haboss server
```

**3. Access the Dashboard**

Open http://localhost:8000/dashboard and use the instance selector to switch between instances.

---

## API Reference

### Instance Selection

All API endpoints accept an optional `instance_id` query parameter to specify which instance to query.

**Default Behavior:**
- If `instance_id` is omitted, requests default to `"all"` (aggregate mode)
- Use `instance_id=all` explicitly for aggregated data across all instances
- Use a specific instance ID (e.g., `instance_id=home`) for single-instance data

### Aggregate Mode

When `instance_id` is `"all"` or omitted, the API returns aggregated data from all configured instances:

**Aggregate Behavior by Endpoint:**

| Endpoint | Aggregate Behavior |
|----------|-------------------|
| `GET /api/status` | Sums statistics across all instances |
| `GET /api/health` | Checks all instances, worst status determines overall |
| `GET /api/entities` | Returns entities from all instances with `instance_id` field |
| `GET /api/healing/history` | Returns healing actions from all instances |
| `GET /api/patterns/reliability` | Aggregates reliability stats by integration |
| `GET /api/patterns/failures` | Returns failures from all instances |
| `GET /api/patterns/summary` | Aggregates summary statistics |
| `GET /api/automations` | Returns automations from all instances |

**Response Changes in Aggregate Mode:**

When querying multiple instances, responses include an `instance_id` field to identify which instance each item belongs to:

```json
// GET /api/entities?instance_id=all
[
  {
    "entity_id": "sensor.temperature",
    "state": "72.5",
    "instance_id": "home"
  },
  {
    "entity_id": "sensor.humidity",
    "state": "45",
    "instance_id": "vacation"
  }
]
```

**Health Check in Aggregate Mode:**

Component names are prefixed with the instance ID:

```json
// GET /api/health?instance_id=all
{
  "status": "healthy",
  "critical": {
    "home:service_state": { "status": "healthy", ... },
    "vacation:service_state": { "status": "healthy", ... }
  }
}
```

### GET /api/instances

List all configured Home Assistant instances.

**Endpoint:**
```
GET /api/instances
```

**Response:**
```json
[
  {
    "instance_id": "home",
    "url": "http://home-assistant:8123",
    "state": "connected",
    "websocket_connected": true,
    "monitored_entities": 127,
    "last_health_check": "2025-01-10T12:00:00Z"
  },
  {
    "instance_id": "vacation",
    "url": "http://vacation-ha:8123",
    "state": "disconnected",
    "websocket_connected": false,
    "monitored_entities": 45,
    "last_health_check": "2025-01-10T11:55:00Z"
  }
]
```

**Fields:**
- `instance_id` (string) - Unique identifier for the instance
- `url` (string) - Home Assistant URL
- `state` (string) - Connection state: `"connected"`, `"disconnected"`, `"error"`
- `websocket_connected` (boolean) - WebSocket connection status
- `monitored_entities` (integer) - Number of entities being monitored
- `last_health_check` (datetime) - Last successful health check timestamp

### Instance-Specific Endpoints

All standard API endpoints support the `instance_id` parameter:

#### Status & Health

```bash
# Get status for specific instance
GET /api/status?instance_id=home

# Health check for specific instance
GET /api/health?instance_id=vacation
```

#### Monitoring

```bash
# List entities from specific instance
GET /api/entities?instance_id=home&limit=100

# Get entity state from specific instance
GET /api/entities/sensor.temperature?instance_id=vacation

# Get entity history from specific instance
GET /api/entities/sensor.temperature/history?instance_id=home&hours=24
```

#### Discovery

```bash
# Trigger discovery refresh for specific instance
POST /api/discovery/refresh?instance_id=home

# Get discovery stats for specific instance
GET /api/discovery/stats?instance_id=vacation

# List automations from specific instance
GET /api/automations?instance_id=home&state=on

# Get automation details from specific instance
GET /api/automations/automation.bedroom_lights?instance_id=home

# Get entity usage from specific instance
GET /api/entities/light.bedroom/usage?instance_id=home
```

#### Patterns

```bash
# Get reliability stats for specific instance
GET /api/patterns/reliability?instance_id=home

# Get failure events from specific instance
GET /api/patterns/failures?instance_id=vacation&hours=24

# Get weekly summary for specific instance
GET /api/patterns/summary?instance_id=home&days=7
```

#### Healing

```bash
# Trigger healing for entity in specific instance
POST /api/healing/sensor.temperature?instance_id=home

# Get healing history for specific instance
GET /api/healing/history?instance_id=vacation&hours=24
```

#### Automations

```bash
# Analyze automation in specific instance
POST /api/automations/analyze?instance_id=home
{
  "automation_id": "automation.lights_on"
}

# Generate automation for specific instance
POST /api/automations/generate?instance_id=home
{
  "description": "Turn on lights at sunset"
}

# Create automation in specific instance
POST /api/automations/create?instance_id=home
{
  "automation_yaml": "alias: Test\n..."
}
```

### Error Responses

**Instance Not Found (404):**
```json
{
  "detail": "Instance 'invalid' not found. Available instances: ['home', 'vacation', 'testing']"
}
```

**Instance Service Unavailable (503):**
```json
{
  "detail": "State tracker not initialized for this instance"
}
```

---

## Dashboard Usage

### Instance Selector

The dashboard includes an instance selector dropdown in the top-right corner:

**Features:**
- **Dropdown Menu** - Lists all configured instances
- **Connection Indicators** - Visual indicators show connection status:
  - 🟢 Green - Connected and healthy
  - 🟡 Yellow - Connected but degraded
  - 🔴 Red - Disconnected or error
- **Persistent Selection** - Last selected instance saved to browser localStorage
- **Automatic Switching** - All dashboard tabs update when switching instances

**Using the Instance Selector:**

1. Click the instance dropdown in the top-right
2. Select the desired instance
3. Dashboard automatically refreshes all tabs with data from the selected instance
4. Selection persists across page refreshes

**Connection States:**

| State | Icon | Description |
|-------|------|-------------|
| Connected | 🟢 | WebSocket connected, actively monitoring |
| Degraded | 🟡 | REST API working, WebSocket disconnected |
| Disconnected | 🔴 | No connection to Home Assistant |

### Dashboard Tabs

Each dashboard tab operates on the currently selected instance:

- **Overview** - Status, statistics, and health for selected instance
- **Entities** - Monitored entities from selected instance
- **Automations** - Discovered automations from selected instance
- **Patterns** - Reliability and failure analysis for selected instance
- **Healing** - Healing history for selected instance

---

## Configuration

### Basic Multi-Instance Setup

**Minimal Configuration:**

```yaml
# config/config.yaml
instances:
  - id: default  # Required for backward compatibility
    url: http://homeassistant.local:8123
    token: ${HA_TOKEN_DEFAULT}  # Use environment variables

  - id: vacation
    url: http://vacation-ha:8123
    token: ${HA_TOKEN_VACATION}
```

### Advanced Configuration

**Full Configuration Options:**

```yaml
instances:
  - id: home
    url: http://home-assistant:8123
    token: ${HA_TOKEN_HOME}

    # Optional: Per-instance monitoring settings
    monitoring:
      health_check_interval_seconds: 60
      state_change_grace_period_seconds: 30

    # Optional: Per-instance healing settings
    healing:
      enabled: true
      circuit_breaker_threshold: 3
      cooldown_seconds: 300

  - id: vacation
    url: http://vacation-ha:8123
    token: ${HA_TOKEN_VACATION}

    # Disable healing for vacation home (monitoring only)
    healing:
      enabled: false
```

### Environment Variables

Store sensitive tokens in environment variables:

```bash
# .env file
HA_TOKEN_DEFAULT=eyJ0eXAiOiJKV1QiLCJhbGc...
HA_TOKEN_VACATION=eyJ0eXAiOiJKV1QiLCJhbGN...
HA_TOKEN_TESTING=eyJ0eXAiOiJKV1QiLCJhbGN...
```

### Instance Naming Conventions

**Best Practices:**
- Use lowercase, alphanumeric IDs
- No spaces or special characters
- Descriptive names: `home`, `vacation`, `testing`, `production`
- Keep names short for API usage

**Examples:**
- ✅ Good: `home`, `vacation`, `main`, `test`
- ❌ Avoid: `Home Assistant #1`, `my-house`, `test instance`

---

## Migration Guide

### Upgrading from Single-Instance to Multi-Instance

**Step 1: Backup Your Configuration**

```bash
cp config/config.yaml config/config.yaml.backup
```

**Step 2: Update Configuration Format**

**Old (Single-Instance):**
```yaml
home_assistant:
  url: http://homeassistant.local:8123
  token: ${HA_TOKEN}
```

**New (Multi-Instance):**
```yaml
instances:
  - id: default  # Use "default" for main instance
    url: http://homeassistant.local:8123
    token: ${HA_TOKEN}
```

**Step 3: Restart HA Boss**

```bash
haboss server
```

**Step 4: Verify Migration**

```bash
# Check instance list
curl http://localhost:8000/api/instances

# Verify backward compatibility (should still work)
curl http://localhost:8000/api/status
```

### Backward Compatibility

**Single-Instance API Calls:**

Multi-instance HA Boss maintains backward compatibility with single-instance deployments:

```bash
# These calls now return aggregated data from ALL instances by default
# (they implicitly use instance_id=all)

GET /api/status                    # Returns combined stats from all instances
GET /api/entities                  # Returns entities from all instances
GET /api/patterns/reliability      # Returns aggregated reliability stats
POST /api/healing/sensor.temperature  # Heals entity (instance auto-detected)
```

**Note:** If you have a single instance configured, the aggregate behavior returns the same data as before (just from that single instance).

**Database Migration:**

The database schema automatically adds `instance_id` columns:
- Existing data is assigned `instance_id = "default"`
- New multi-instance data gets the correct `instance_id`
- No manual migration required

### Breaking Changes

**v2.1.0+:** Default `instance_id` changed from `"default"` to `"all"`.

- API calls without `instance_id` now return **aggregated data** from all instances
- To get single-instance data, explicitly pass `?instance_id=<your-instance>`
- Response models may now include `instance_id` field in aggregate mode
- Health check component names are prefixed with instance ID in aggregate mode

**Migration for v2.1.0+:**
- If your code expects single-instance responses, add explicit `?instance_id=default` or your instance ID
- Update any response parsing to handle the optional `instance_id` field
- Single-instance configurations continue to work (aggregate of one = same data)

---

## Architecture

### Component Structure

Each instance has its own isolated set of components:

```
HABossService
├── instances:
│   ├── default
│   │   ├── ha_client        (REST API client)
│   │   ├── websocket_client  (WebSocket connection)
│   │   ├── state_tracker     (Entity state cache)
│   │   ├── health_monitor    (Health checking)
│   │   ├── healing_manager   (Auto-healing)
│   │   ├── integration_discovery
│   │   ├── entity_discovery
│   │   ├── pattern_collector
│   │   └── notification_manager
│   │
│   └── vacation
│       ├── ha_client
│       ├── websocket_client
│       └── ... (same components)
│
└── shared:
    ├── database           (Single shared database)
    ├── config             (Global configuration)
    └── llm_router         (Shared AI clients)
```

### Data Isolation

**Per-Instance:**
- State cache (in-memory)
- WebSocket connections
- Health check counters
- Healing statistics
- Component instances

**Shared:**
- Database (with `instance_id` column)
- LLM clients (Ollama, Claude)
- API server
- Configuration

### Database Schema

Multi-instance support adds `instance_id` column to all tables:

```sql
-- Example: entities table
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    instance_id TEXT NOT NULL,  -- NEW
    entity_id TEXT NOT NULL,
    state TEXT,
    last_changed TIMESTAMP,
    UNIQUE(instance_id, entity_id)  -- Composite key
);

-- Example: healing_actions table
CREATE TABLE healing_actions (
    id INTEGER PRIMARY KEY,
    instance_id TEXT NOT NULL,  -- NEW
    entity_id TEXT,
    integration_id TEXT,
    action TEXT,
    success BOOLEAN,
    timestamp TIMESTAMP
);
```

**Index Strategy:**
- Composite indexes on `(instance_id, entity_id)`
- Fast per-instance queries
- No cross-instance contamination

---

## Examples

### Python Multi-Instance Client

```python
import requests
from typing import Optional, List

class MultiInstanceHABossClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key

    def list_instances(self) -> List[dict]:
        """Get all configured instances."""
        response = requests.get(
            f"{self.base_url}/api/instances",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def get_status(self, instance_id: str = "default") -> dict:
        """Get status for specific instance."""
        response = requests.get(
            f"{self.base_url}/api/status",
            params={"instance_id": instance_id},
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def get_all_instance_stats(self) -> dict:
        """Get statistics for all instances."""
        instances = self.list_instances()
        stats = {}
        for instance in instances:
            instance_id = instance["instance_id"]
            stats[instance_id] = self.get_status(instance_id)
        return stats

# Usage
client = MultiInstanceHABossClient("http://localhost:8000")

# List all instances
instances = client.list_instances()
print(f"Managing {len(instances)} instances:")
for inst in instances:
    print(f"  - {inst['instance_id']}: {inst['state']}")

# Get status for each instance
for instance in instances:
    status = client.get_status(instance["instance_id"])
    print(f"{instance['instance_id']}: {status['monitored_entities']} entities")
```

### JavaScript/Node.js Multi-Instance Client

```javascript
class MultiInstanceHABossClient {
  constructor(baseURL, apiKey = null) {
    this.baseURL = baseURL;
    this.headers = {};
    if (apiKey) {
      this.headers['X-API-Key'] = apiKey;
    }
  }

  async listInstances() {
    const response = await fetch(
      `${this.baseURL}/api/instances`,
      { headers: this.headers }
    );
    return response.json();
  }

  async getStatus(instanceId = 'default') {
    const params = new URLSearchParams({ instance_id: instanceId });
    const response = await fetch(
      `${this.baseURL}/api/status?${params}`,
      { headers: this.headers }
    );
    return response.json();
  }

  async getAllInstanceStats() {
    const instances = await this.listInstances();
    const stats = {};

    for (const instance of instances) {
      stats[instance.instance_id] = await this.getStatus(instance.instance_id);
    }

    return stats;
  }
}

// Usage
const client = new MultiInstanceHABossClient('http://localhost:8000');

// Get all instance statistics
const stats = await client.getAllInstanceStats();
console.log('Multi-instance statistics:', stats);
```

### Bash/cURL Examples

```bash
# List all instances
curl http://localhost:8000/api/instances | jq

# Get status for each instance
for instance in home vacation testing; do
  echo "=== $instance ==="
  curl "http://localhost:8000/api/status?instance_id=$instance" | jq
done

# Compare entity counts across instances
curl http://localhost:8000/api/instances | \
  jq -r '.[] | "\(.instance_id): \(.monitored_entities) entities"'

# Trigger healing on specific instance
curl -X POST "http://localhost:8000/api/healing/sensor.temp?instance_id=vacation"
```

### Home Assistant Multi-Instance Sensors

Create sensors for each HA Boss instance:

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: HA Boss Home Status
    resource: http://haboss:8000/api/status?instance_id=home
    value_template: "{{ value_json.state }}"
    json_attributes:
      - monitored_entities
      - healings_succeeded
      - healings_failed
    scan_interval: 60

  - platform: rest
    name: HA Boss Vacation Status
    resource: http://haboss:8000/api/status?instance_id=vacation
    value_template: "{{ value_json.state }}"
    json_attributes:
      - monitored_entities
      - healings_succeeded
      - healings_failed
    scan_interval: 60
```

### Monitoring All Instances Script

```python
#!/usr/bin/env python3
"""Monitor all HA Boss instances and alert on issues."""

import requests
import sys

def check_all_instances(base_url: str):
    """Check health of all instances."""
    instances_resp = requests.get(f"{base_url}/api/instances")
    instances = instances_resp.json()

    issues = []

    for instance in instances:
        instance_id = instance["instance_id"]

        # Check connection
        if not instance["websocket_connected"]:
            issues.append(f"{instance_id}: WebSocket disconnected")

        # Check health
        health_resp = requests.get(
            f"{base_url}/api/health",
            params={"instance_id": instance_id}
        )
        health = health_resp.json()

        if health["status"] == "unhealthy":
            issues.append(f"{instance_id}: Status is unhealthy")
        elif health["status"] == "degraded":
            issues.append(f"{instance_id}: Status is degraded")

    return issues

if __name__ == "__main__":
    base_url = "http://localhost:8000"
    issues = check_all_instances(base_url)

    if issues:
        print("⚠️  Issues detected:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("✅ All instances healthy")
        sys.exit(0)
```

---

**Back to:** [Wiki Home](Home) | [REST API](REST-API) | [Dashboard](Dashboard) | [Configuration](Configuration)
