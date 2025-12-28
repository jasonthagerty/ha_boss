# Auto-Discovery

HA Boss automatically discovers which entities matter by analyzing your Home Assistant automations, scenes, and scripts. This intelligent approach ensures you only monitor entities that are actually being used, eliminating manual configuration.

## Overview

**Auto-Discovery** scans your Home Assistant configuration to find:
- 🤖 **Automations** - Entities used in triggers, conditions, and actions
- 🎬 **Scenes** - Entities controlled by scenes
- 📜 **Scripts** - Entities referenced in script sequences

The system builds a **monitored entity set** by combining auto-discovered entities with your manual include/exclude patterns from `config.yaml`.

## How It Works

### 1. Discovery Process

When HA Boss starts (or when manually triggered), it:

1. **Fetches** all automations, scenes, and scripts from Home Assistant
2. **Filters** disabled automations (optional, enabled by default)
3. **Extracts** entity references from configurations using deep recursive search
4. **Stores** relationships in the database (which entities are used where)
5. **Builds** the final monitored set using the merge formula

### 2. Config Merge Formula

```
monitored_entities = (auto_discovered ∪ config.include) - config.exclude
```

**Translation**:
- Start with entities found in automations/scenes/scripts
- **Add** entities matching `monitoring.include` patterns
- **Remove** entities matching `monitoring.exclude` patterns

**Example**:
```yaml
monitoring:
  auto_discovery:
    enabled: true

  include:
    - "input_boolean.*"  # Add all input booleans

  exclude:
    - "sensor.time*"     # Remove time sensors
    - "sun.sun"          # Remove sun entity
```

**Result**: All entities from automations + all input_booleans - time sensors - sun

### 3. Relationship Mapping

The discovery system builds a complete relationship graph:

```
Entity → Automations (where is this entity used?)
Entity → Scenes (which scenes control this entity?)
Entity → Scripts (which scripts reference this entity?)
Entity → Integration (which integration provides this entity?)
```

This enables powerful reverse-lookup queries via the API.

## Configuration

### Full Configuration Example

```yaml
monitoring:
  auto_discovery:
    # Enable/disable auto-discovery
    enabled: true

    # Skip disabled automations during discovery
    skip_disabled_automations: true

    # Include entities from scenes
    include_scenes: true

    # Include entities from scripts
    include_scripts: true

    # Periodic refresh interval (seconds, 0 = disabled)
    refresh_interval_seconds: 3600  # Hourly

    # Trigger refresh on reload events
    refresh_on_automation_reload: true
    refresh_on_scene_reload: true
    refresh_on_script_reload: true

  # Manual include patterns (ADDITIVE)
  include:
    - "input_boolean.guest_mode"
    - "sensor.manual_*"

  # Exclude patterns (applied after include)
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sun.sun"

  # Per-entity overrides
  entity_overrides:
    "sensor.critical_temperature":
      grace_period_seconds: 60  # 1 minute for critical entities
```

### Configuration Options

#### `auto_discovery.enabled`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable/disable auto-discovery. When disabled, only manual include/exclude patterns are used.

#### `auto_discovery.skip_disabled_automations`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Skip automations with state "off" during discovery.

#### `auto_discovery.include_scenes`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Include entities from scene configurations.

#### `auto_discovery.include_scripts`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Include entities from script sequences.

#### `auto_discovery.refresh_interval_seconds`
- **Type**: Integer
- **Default**: `3600` (1 hour)
- **Description**: Periodic background refresh interval. Set to `0` to disable.

#### `auto_discovery.refresh_on_*_reload`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Trigger discovery refresh when automations/scenes/scripts are reloaded in HA.

## Refresh Triggers

Discovery automatically refreshes in these situations:

### 1. Startup (Always)
Every time HA Boss starts, discovery runs to build the initial monitored set.

### 2. Periodic (Hourly)
Background task refreshes discovery every hour (configurable via `refresh_interval_seconds`).

### 3. Reload Events (WebSocket)
When you reload automations/scenes/scripts in Home Assistant, HA Boss detects the event and triggers discovery.

**Example**: After editing an automation in the HA UI and clicking "Reload Automations", discovery automatically runs.

### 4. Manual (API)
Trigger on-demand via REST API:

```bash
curl -X POST http://localhost:8000/api/discovery/refresh \
  -H "Content-Type: application/json" \
  -d '{"trigger_source": "user_action"}'
```

## REST API

### Discovery Endpoints

#### `POST /api/discovery/refresh`
Trigger manual discovery refresh.

**Request**:
```json
{
  "trigger_source": "user_action"
}
```

**Response**:
```json
{
  "success": true,
  "automations_found": 45,
  "scenes_found": 12,
  "scripts_found": 8,
  "entities_discovered": 127,
  "duration_seconds": 2.3,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### `GET /api/discovery/stats`
Get current discovery statistics.

**Response**:
```json
{
  "auto_discovery_enabled": true,
  "total_automations": 45,
  "enabled_automations": 42,
  "total_scenes": 12,
  "total_scripts": 8,
  "total_entities": 127,
  "monitored_entities": 115,
  "last_refresh": "2024-01-15T10:30:00Z",
  "next_refresh": "2024-01-15T11:30:00Z",
  "refresh_interval_seconds": 3600
}
```

#### `GET /api/automations`
List all discovered automations.

**Query Parameters**:
- `state` (optional): Filter by state (`on` or `off`)
- `limit`: Max results (default: 100, max: 1000)
- `offset`: Pagination offset (default: 0)

**Response**:
```json
[
  {
    "entity_id": "automation.bedroom_lights",
    "friendly_name": "Bedroom Motion Lights",
    "state": "on",
    "entity_count": 5,
    "discovered_at": "2024-01-15T10:30:00Z"
  }
]
```

#### `GET /api/automations/{automation_id}`
Get detailed automation information with entities.

**Response**:
```json
{
  "entity_id": "automation.bedroom_lights",
  "friendly_name": "Bedroom Motion Lights",
  "state": "on",
  "mode": "single",
  "discovered_at": "2024-01-15T10:30:00Z",
  "last_seen": "2024-01-15T10:30:00Z",
  "entities": {
    "trigger": ["binary_sensor.bedroom_motion"],
    "condition": ["sun.sun"],
    "action": ["light.bedroom", "light.bedroom_accent"]
  },
  "entity_count": 4
}
```

#### `GET /api/entities/{entity_id}/usage`
Reverse lookup: Find all automations/scenes/scripts using an entity.

**Response**:
```json
{
  "entity_id": "light.bedroom",
  "automations": [
    {
      "id": "automation.bedroom_lights",
      "friendly_name": "Bedroom Motion Lights",
      "type": "automation",
      "relationship_type": "action"
    },
    {
      "id": "automation.good_night",
      "friendly_name": "Good Night Routine",
      "type": "automation",
      "relationship_type": "action"
    }
  ],
  "scenes": [
    {
      "id": "scene.movie_time",
      "friendly_name": "Movie Time",
      "type": "scene",
      "relationship_type": null
    }
  ],
  "scripts": [],
  "total_usage": 3
}
```

## Use Cases

### 1. Minimal Configuration
Let auto-discovery handle everything:

```yaml
monitoring:
  auto_discovery:
    enabled: true
  include: []
  exclude:
    - "sensor.time*"  # Just exclude noise
```

### 2. Supplement Auto-Discovery
Add entities not found in automations:

```yaml
monitoring:
  auto_discovery:
    enabled: true
  include:
    - "input_boolean.*"  # Monitor all input booleans
    - "sensor.ups_*"     # Monitor UPS sensors
  exclude:
    - "sensor.time*"
```

### 3. Override Grace Periods
Set custom grace periods for critical entities:

```yaml
monitoring:
  auto_discovery:
    enabled: true

  entity_overrides:
    "sensor.freezer_temperature":
      grace_period_seconds: 60  # Alert faster for freezer
    "binary_sensor.water_leak":
      grace_period_seconds: 30  # Alert immediately for leaks
```

### 4. Disable Auto-Discovery
Use manual patterns only:

```yaml
monitoring:
  auto_discovery:
    enabled: false

  include:
    - "sensor.*"
    - "binary_sensor.*"
  exclude:
    - "sensor.time*"
```

## Database Schema

Discovery stores data in 7 new tables:

### Core Tables
- **`automations`** - Automation registry
- **`scenes`** - Scene registry
- **`scripts`** - Script registry

### Junction Tables (Relationships)
- **`automation_entities`** - Automation ↔ Entity relationships
- **`scene_entities`** - Scene ↔ Entity relationships
- **`script_entities`** - Script ↔ Entity relationships

### Audit Table
- **`discovery_refreshes`** - Discovery run history

See [Database Migrations](Database-Migrations.md) for schema details.

## Performance

### Discovery Speed
- **100 automations**: ~2-3 seconds
- **500 automations**: ~8-12 seconds

### Resource Usage
- **Memory**: ~50MB for 500 automations
- **Database**: ~5KB per automation (with entities)

### Optimization Tips
1. **Disable periodic refresh** if you rarely change automations: `refresh_interval_seconds: 0`
2. **Skip disabled automations** to reduce processing: `skip_disabled_automations: true`
3. **Disable scenes/scripts** if you don't use them: `include_scenes: false`

## Troubleshooting

### Discovery Not Finding Entities

**Problem**: Some entities aren't being discovered.

**Solutions**:
1. Check if the automation is enabled (disabled automations are skipped by default)
2. Verify entity is referenced in automation config (triggers, conditions, or actions)
3. Enable debug logging: `logging.level: DEBUG`
4. Manually trigger refresh: `POST /api/discovery/refresh`

### Too Many Entities Monitored

**Problem**: Discovery found entities you don't want to monitor.

**Solution**: Use exclude patterns:
```yaml
monitoring:
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "automation.*"  # Don't monitor automation entities themselves
```

### Entities Missing After Reload

**Problem**: After reloading automations, some entities disappeared.

**Cause**: You deleted/disabled automations that referenced those entities.

**Solution**: Either re-enable the automations or manually include the entities:
```yaml
monitoring:
  include:
    - "sensor.important_entity"
```

### Refresh Not Triggering

**Problem**: Discovery doesn't refresh when reloading automations.

**Solutions**:
1. Check WebSocket connection: `GET /api/health`
2. Verify refresh setting: `refresh_on_automation_reload: true`
3. Check logs for WebSocket subscription errors

## Best Practices

### 1. Start with Defaults
Begin with auto-discovery enabled and default settings. Only customize if needed.

### 2. Use Exclude for Noise
Rather than manually including everything, let auto-discovery find entities and exclude noisy ones:
```yaml
exclude:
  - "sensor.time*"
  - "sensor.uptime*"
  - "sun.sun"
```

### 3. Override Critical Entities
Use entity overrides for critical sensors that need faster alerts:
```yaml
entity_overrides:
  "binary_sensor.smoke_detector":
    grace_period_seconds: 30
```

### 4. Review Discovery Stats
Periodically check `GET /api/discovery/stats` to understand what's being monitored.

### 5. Use Reverse Lookup
Before deleting an automation, check entity usage:
```bash
GET /api/entities/light.bedroom/usage
```

## Migration from Manual Config

If you're migrating from manual entity configuration:

### Before (Manual):
```yaml
monitoring:
  include:
    - "sensor.temperature"
    - "sensor.humidity"
    - "binary_sensor.door"
    - "light.bedroom"
    # ... 100 more entities
```

### After (Auto-Discovery):
```yaml
monitoring:
  auto_discovery:
    enabled: true
  include: []  # Empty - auto-discovery handles it
  exclude:
    - "sensor.time*"  # Just exclude noise
```

**Benefits**:
- ✅ No manual maintenance
- ✅ Automatically updates when automations change
- ✅ Only monitors entities actually in use
- ✅ Shows relationships via API

## Related Documentation

- [Configuration Guide](Configuration.md)
- [REST API Reference](REST-API.md)
- [Database Migrations](../DATABASE_MIGRATIONS.md)
- [Troubleshooting](Troubleshooting.md)
