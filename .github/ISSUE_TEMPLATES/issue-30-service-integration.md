# Issue #30: Integrate Pattern Collection with Service Orchestration

## 📋 Overview

Integrate PatternCollector into the main service orchestration so patterns are automatically collected during normal operation.

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P0 (makes pattern collection actually work)
**Effort**: 2 hours

## 🎯 Objective

Wire up PatternCollector to:
- Initialize on service startup (if enabled)
- Receive callbacks from HealingManager
- Receive callbacks from HealthMonitor
- Extract integration info from IntegrationDiscovery
- Have zero performance impact on MVP operation

## 🏗️ Implementation

### Step 1: Add Configuration

**File**: `ha_boss/core/config.py`

Add IntelligenceConfig:

```python
class IntelligenceConfig(BaseModel):
    """Intelligence layer configuration."""

    # Pattern Collection
    pattern_collection_enabled: bool = Field(
        default=True,
        description="Enable collection of integration reliability patterns"
    )
    pattern_retention_days: int = Field(
        default=90,
        ge=1,
        description="How long to keep pattern data (days)"
    )

    # Future: weekly summaries, LLM, etc.


class Config(BaseSettings):
    """HA Boss configuration."""

    home_assistant: HomeAssistantConfig
    monitoring: MonitoringConfig
    healing: HealingConfig
    notifications: NotificationsConfig
    logging: LoggingConfig
    database: DatabaseConfig
    websocket: WebSocketConfig
    rest: RESTConfig

    # Phase 2: Intelligence
    intelligence: IntelligenceConfig = IntelligenceConfig()

    mode: str = "production"
```

### Step 2: Initialize in Service

**File**: `ha_boss/service/main.py`

Update HABossService class:

```python
class HABossService:
    """Main service orchestration."""

    def __init__(self, config: Config):
        # ... existing fields ...

        # Phase 2: Intelligence
        self.pattern_collector: PatternCollector | None = None

    async def start(self):
        # ... after healing manager initialization ...

        # 9. Initialize pattern collector (if enabled)
        if self.config.intelligence.pattern_collection_enabled:
            logger.info("Initializing pattern collector...")
            from ha_boss.intelligence.pattern_collector import PatternCollector

            self.pattern_collector = PatternCollector(
                database=self.database,
                config=self.config,
            )
            logger.info("✓ Pattern collector initialized")
        else:
            logger.info("Pattern collection disabled in configuration")

        # ... continue with WebSocket, etc. ...
```

### Step 3: Hook into Healing Manager

**File**: `ha_boss/service/main.py`

Update `_on_health_issue` method:

```python
async def _on_health_issue(self, issue: HealthIssue) -> None:
    """Callback when health issue is detected.

    Args:
        issue: Detected health issue
    """
    logger.info(
        f"Health issue detected: {issue.entity_id} - {issue.issue_type} "
        f"(detected at {issue.detected_at})"
    )

    # Skip healing for recovery events
    if issue.issue_type == "recovered":
        logger.info(f"Entity {issue.entity_id} recovered automatically")
        return

    # Record entity became unavailable (before healing)
    if self.pattern_collector and issue.issue_type in ("unavailable", "unknown"):
        integration_id = None
        integration_domain = None

        # Try to get integration info
        if self.integration_discovery:
            try:
                integration_id = self.integration_discovery.get_integration_for_entity(
                    issue.entity_id
                )
                if integration_id:
                    integration_domain = self.integration_discovery.get_domain(integration_id)
            except Exception as e:
                logger.debug(f"Could not get integration info: {e}")

        await self.pattern_collector.record_entity_unavailable(
            entity_id=issue.entity_id,
            integration_id=integration_id,
            integration_domain=integration_domain,
            details={"issue_type": issue.issue_type}
        )

    # Attempt auto-healing if enabled
    if self.config.healing.enabled and self.healing_manager:
        try:
            logger.info(f"Attempting auto-heal for {issue.entity_id}...")
            self.healings_attempted += 1

            success = await self.healing_manager.heal_entity(issue.entity_id)

            # Record healing attempt pattern
            if self.pattern_collector:
                integration_id = None
                integration_domain = None

                if self.integration_discovery:
                    try:
                        integration_id = self.integration_discovery.get_integration_for_entity(
                            issue.entity_id
                        )
                        if integration_id:
                            integration_domain = self.integration_discovery.get_domain(integration_id)
                    except Exception as e:
                        logger.debug(f"Could not get integration info: {e}")

                await self.pattern_collector.record_healing_attempt(
                    entity_id=issue.entity_id,
                    integration_id=integration_id,
                    integration_domain=integration_domain,
                    success=success,
                    details={"issue_type": issue.issue_type}
                )

            if success:
                logger.info(f"✓ Successfully healed {issue.entity_id}")
                self.healings_succeeded += 1
            else:
                logger.warning(f"✗ Healing failed for {issue.entity_id}")
                # ... existing escalation code ...

        except Exception as e:
            logger.error(f"Error during healing: {e}", exc_info=True)
    else:
        logger.info("Auto-healing disabled, issue logged only")
```

### Step 4: Add Helper Methods to IntegrationDiscovery

**File**: `ha_boss/healing/integration_manager.py`

Add methods if they don't exist:

```python
def get_integration_for_entity(self, entity_id: str) -> str | None:
    """Get integration ID for an entity.

    Args:
        entity_id: Entity to look up

    Returns:
        Integration config entry ID or None
    """
    return self._entity_to_integration.get(entity_id)

def get_domain(self, integration_id: str) -> str | None:
    """Get domain for an integration.

    Args:
        integration_id: Integration config entry ID

    Returns:
        Integration domain (e.g., 'hue', 'zwave') or None
    """
    integration = self._integrations.get(integration_id)
    if integration:
        return integration.get("domain")
    return None
```

### Step 5: Update Configuration Examples

**File**: `config/config.yaml.example`

Add intelligence section:

```yaml
# Phase 2: Intelligence Layer
intelligence:
  # Enable pattern collection for reliability tracking
  pattern_collection_enabled: true

  # How long to keep pattern data (days)
  pattern_retention_days: 90

  # Future: weekly_summaries_enabled, ollama_enabled, etc.
```

## ✅ Acceptance Criteria

- [ ] `IntelligenceConfig` added to config.py
- [ ] PatternCollector initialized in service.start()
- [ ] Patterns recorded on healing attempts
- [ ] Patterns recorded on unavailable events
- [ ] Integration info extracted correctly
- [ ] Configuration option works (enable/disable)
- [ ] Example config updated
- [ ] No performance regression (< 5ms per event)
- [ ] Integration tests pass
- [ ] Service still works if pattern collection disabled
- [ ] Service still works if integration info unavailable

## 🧪 Testing

### Update Existing Tests

**File**: `tests/service/test_main.py`

Update service startup test to mock pattern collector:

```python
@patch("ha_boss.service.main.PatternCollector")
async def test_service_start_with_pattern_collection(mock_collector_class):
    """Test service starts with pattern collection enabled."""
    # Set pattern_collection_enabled=True
    # Verify PatternCollector initialized
    # Verify it's added to service instance
```

### New Integration Test

**File**: `tests/test_integration_patterns.py`

```python
@pytest.mark.integration
async def test_pattern_collection_integration():
    """Test end-to-end pattern collection."""
    # Start service with pattern collection enabled
    # Trigger health issue
    # Verify pattern recorded in database
    # Query pattern
    # Verify data correct
```

### Performance Test

```python
async def test_pattern_collection_performance():
    """Verify pattern collection has minimal performance impact."""
    # Measure time for healing without pattern collection
    # Measure time for healing with pattern collection
    # Verify difference < 5ms
```

## 📝 Implementation Notes

1. **Conditional Import**: Import PatternCollector only if enabled to avoid unnecessary dependencies

2. **Graceful Degradation**:
   - If PatternCollector fails, log error but don't crash
   - If integration info unavailable, still record event with NULL integration

3. **Performance**:
   - Pattern recording is async (non-blocking)
   - Database writes happen in background
   - Errors in pattern collection don't affect healing

4. **Configuration**:
   - Default to enabled (users want this feature)
   - Easy to disable if needed
   - Document in config.yaml.example

5. **Integration Info**:
   - Try to get from IntegrationDiscovery
   - Gracefully handle None (unknown integration)
   - Log at DEBUG level to avoid noise

## 🔗 Dependencies

- **Requires**: #26, #27, #28 (all pattern infrastructure)
- **Blocks**: None (this makes patterns actually work!)

## 📚 References

- Existing service orchestration in service/main.py
- HealingManager for pattern
- Configuration management in core/config.py

---

**Labels**: `phase-2`, `service`, `integration`, `P0`
