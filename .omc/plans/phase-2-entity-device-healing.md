# Phase 2: Entity & Device Level Healing - Implementation Plan

**Epic**: #177 - Goal-Oriented Healing Architecture
**Phase**: 2 of 4
**Created**: 2026-01-31
**Status**: Ready for Implementation

## Overview

Phase 2 builds on Phase 1's outcome validation foundation to implement intelligent, multi-level healing. Instead of only reloading entire integrations, we'll target failures at the appropriate level: entity → device → integration.

## Core Requirements

### 1. Trigger Failure Detection
**Method**: State-change monitoring after automation execution

When an automation completes:
1. Wait for validation window (configurable, default 10s)
2. Check if expected state changes occurred
3. Validate against desired state from Phase 1
4. If mismatch detected → trigger healing cascade

**Example Flow**:
```
Automation: "Turn on Apple TV" executes
↓
Expected states: media_player.apple_tv = "on", switch.tv_input_hdmi2 = "on"
↓
Wait 10s for state propagation
↓
Check actual states vs. expected
↓
If mismatch → Trigger failure detected
```

### 2. Multi-Level Healing Hierarchy

**Full Cascade Strategy** (for all failure types):

```
Level 1: Entity-Level Healing
├─ Retry service call with same parameters
├─ Retry service call with alternative parameters
└─ Record failure, escalate to Level 2

Level 2: Device-Level Healing
├─ Device reconnect (if integration supports it)
├─ Device reboot/power cycle (if integration supports it)
├─ Re-discover device
└─ Record failure, escalate to Level 3

Level 3: Integration-Level Healing
├─ Reload integration (existing mechanism from Phase 1)
├─ Restart integration process
└─ Record failure, escalate to notifications

Level 4: Notification Escalation
└─ Alert user with detailed failure analysis
```

### 3. Consecutive Execution Validation Gating

**Requirement**: Multiple consecutive successful executions before marking automation as "healthy"

Configuration:
```yaml
outcome_validation:
  consecutive_success_threshold: 3  # Default: require 3 consecutive successes
  validation_window: 10             # Seconds to wait for state propagation
```

**State Tracking**:
- Track consecutive success/failure count per automation
- Reset counter on any failure
- Only mark automation as "validated healthy" after threshold met
- Use this for reliability scoring

### 4. Intelligent vs. Sequential Routing

**Hybrid Approach**:

**Known Pattern** (intelligent routing):
- Check `AutomationOutcomePattern` table for similar past failures
- If pattern found with successful healing strategy → apply that strategy directly
- Skip unnecessary healing levels

**Unknown Pattern** (sequential cascade):
- No matching pattern found
- Execute full cascade: Level 1 → Level 2 → Level 3 → Level 4
- Record pattern and successful strategy for future use

**Example**:
```python
async def route_healing(failure: FailureContext) -> HealingStrategy:
    # Check for known pattern
    pattern = await db.get_matching_pattern(
        automation_id=failure.automation_id,
        failed_entities=failure.failed_entities
    )

    if pattern and pattern.successful_strategy:
        # Intelligent: Jump to known working strategy
        return pattern.successful_strategy
    else:
        # Sequential: Start cascade from Level 1
        return HealingCascade.start_from_entity_level()
```

## Database Schema Changes (Migration v8)

### New Tables

#### 1. `healing_strategies`
Defines available healing actions at each level.

```sql
CREATE TABLE healing_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,  -- 'entity', 'device', 'integration'
    strategy_type TEXT NOT NULL,  -- 'retry_service_call', 'device_reconnect', etc.
    parameters JSON,  -- Strategy-specific parameters
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 2. `device_healing_actions`
Tracks healing actions performed on devices.

```sql
CREATE TABLE device_healing_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- 'reconnect', 'reboot', 'rediscover'
    triggered_by TEXT,  -- 'automation_failure', 'manual', 'pattern'
    automation_id TEXT,  -- If triggered by automation failure
    execution_id INTEGER,  -- Link to automation_executions
    success BOOLEAN,
    error_message TEXT,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instance_id) REFERENCES instances(id),
    FOREIGN KEY (execution_id) REFERENCES automation_executions(id)
);
```

#### 3. `entity_healing_actions`
Tracks entity-level healing attempts.

```sql
CREATE TABLE entity_healing_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- 'retry_service_call', 'alternative_params'
    service_domain TEXT,
    service_name TEXT,
    service_data JSON,
    triggered_by TEXT,
    automation_id TEXT,
    execution_id INTEGER,
    success BOOLEAN,
    error_message TEXT,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (instance_id) REFERENCES instances(id),
    FOREIGN KEY (execution_id) REFERENCES automation_executions(id)
);
```

#### 4. `healing_cascade_executions`
Tracks full healing cascade attempts.

```sql
CREATE TABLE healing_cascade_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    automation_id TEXT NOT NULL,
    execution_id INTEGER,  -- Link to automation execution that failed
    trigger_type TEXT NOT NULL,  -- 'trigger_failure', 'outcome_failure'
    failed_entities JSON,  -- List of entities that didn't reach desired state

    -- Cascade progression
    entity_level_attempted BOOLEAN DEFAULT FALSE,
    entity_level_success BOOLEAN,
    device_level_attempted BOOLEAN DEFAULT FALSE,
    device_level_success BOOLEAN,
    integration_level_attempted BOOLEAN DEFAULT FALSE,
    integration_level_success BOOLEAN,

    -- Routing
    routing_strategy TEXT NOT NULL,  -- 'intelligent', 'sequential'
    matched_pattern_id INTEGER,  -- If intelligent routing used

    -- Results
    final_success BOOLEAN,
    total_duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (instance_id) REFERENCES instances(id),
    FOREIGN KEY (execution_id) REFERENCES automation_executions(id),
    FOREIGN KEY (matched_pattern_id) REFERENCES automation_outcome_patterns(id)
);
```

#### 5. `automation_health_status`
Tracks consecutive success/failure counts for validation gating.

```sql
CREATE TABLE automation_health_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    automation_id TEXT NOT NULL,

    -- Consecutive tracking
    consecutive_successes INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,

    -- Validation gating
    is_validated_healthy BOOLEAN DEFAULT FALSE,
    last_validation_at TIMESTAMP,

    -- Statistics
    total_executions INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(instance_id, automation_id),
    FOREIGN KEY (instance_id) REFERENCES instances(id)
);
```

### Schema Updates to Existing Tables

#### `automation_outcome_patterns`
Add fields for healing strategy tracking:

```sql
ALTER TABLE automation_outcome_patterns ADD COLUMN successful_healing_level TEXT;
ALTER TABLE automation_outcome_patterns ADD COLUMN successful_healing_strategy TEXT;
ALTER TABLE automation_outcome_patterns ADD COLUMN healing_success_count INTEGER DEFAULT 0;
```

## Core Components

### 1. Trigger Failure Detector (`ha_boss/automation/trigger_detector.py`)

**Responsibilities**:
- Monitor state changes after automation execution
- Compare actual vs. expected trigger conditions
- Detect when automation should have run but didn't

**Key Classes**:

```python
@dataclass
class TriggerFailureContext:
    """Context for a detected trigger failure."""
    automation_id: str
    instance_id: str
    expected_trigger: dict[str, Any]
    actual_state: dict[str, Any]
    timestamp: datetime
    detection_method: str  # 'state_change_monitoring'

class TriggerFailureDetector:
    """Detects when automation triggers fail to fire."""

    async def monitor_state_changes(
        self,
        automation_id: str,
        expected_trigger: dict[str, Any],
        validation_window: int = 10
    ) -> TriggerFailureContext | None:
        """Monitor for expected state changes within validation window."""
        pass

    async def validate_trigger_fired(
        self,
        automation_id: str,
        state_change: dict[str, Any]
    ) -> bool:
        """Check if state change should have triggered automation."""
        pass
```

### 2. Healing Cascade Orchestrator (`ha_boss/healing/cascade_orchestrator.py`)

**Responsibilities**:
- Route failures to appropriate healing level
- Execute healing cascade (entity → device → integration)
- Track cascade execution and results
- Learn from successful healing strategies

**Key Classes**:

```python
class HealingLevel(str, Enum):
    ENTITY = "entity"
    DEVICE = "device"
    INTEGRATION = "integration"

@dataclass
class HealingContext:
    """Context for healing cascade execution."""
    instance_id: str
    automation_id: str
    execution_id: int | None
    trigger_type: str  # 'trigger_failure', 'outcome_failure'
    failed_entities: list[str]
    desired_states: dict[str, Any]

class CascadeOrchestrator:
    """Orchestrates multi-level healing cascade."""

    async def execute_cascade(
        self,
        context: HealingContext
    ) -> CascadeResult:
        """Execute full healing cascade with intelligent routing."""
        # 1. Check for known pattern
        pattern = await self._get_matching_pattern(context)

        if pattern:
            # Intelligent routing
            return await self._execute_intelligent_healing(context, pattern)
        else:
            # Sequential cascade
            return await self._execute_sequential_cascade(context)

    async def _execute_sequential_cascade(
        self,
        context: HealingContext
    ) -> CascadeResult:
        """Execute Level 1 → Level 2 → Level 3 cascade."""
        cascade_id = await self._create_cascade_execution(context)

        # Level 1: Entity healing
        entity_result = await self.entity_healer.heal(context)
        if entity_result.success:
            return self._finalize_cascade(cascade_id, HealingLevel.ENTITY)

        # Level 2: Device healing
        device_result = await self.device_healer.heal(context)
        if device_result.success:
            return self._finalize_cascade(cascade_id, HealingLevel.DEVICE)

        # Level 3: Integration healing
        integration_result = await self.integration_healer.heal(context)
        if integration_result.success:
            return self._finalize_cascade(cascade_id, HealingLevel.INTEGRATION)

        # All levels failed - escalate
        await self._escalate_to_notifications(context, cascade_id)
        return CascadeResult(success=False, cascade_id=cascade_id)
```

### 3. Entity-Level Healer (`ha_boss/healing/entity_healer.py`)

**Responsibilities**:
- Retry service calls
- Try alternative service parameters
- Track entity-level healing actions

**Key Methods**:

```python
class EntityHealer:
    """Entity-level healing strategies."""

    async def heal(self, context: HealingContext) -> HealingResult:
        """Attempt entity-level healing."""
        for entity_id in context.failed_entities:
            # Strategy 1: Retry original service call
            result = await self._retry_service_call(entity_id, context)
            if result.success:
                continue

            # Strategy 2: Try alternative parameters
            result = await self._try_alternative_params(entity_id, context)
            if result.success:
                continue

            # Entity healing failed
            return HealingResult(success=False, failed_entities=[entity_id])

        return HealingResult(success=True)

    async def _retry_service_call(
        self,
        entity_id: str,
        context: HealingContext,
        max_retries: int = 3
    ) -> EntityHealingResult:
        """Retry the original service call."""
        pass

    async def _try_alternative_params(
        self,
        entity_id: str,
        context: HealingContext
    ) -> EntityHealingResult:
        """Try alternative service parameters based on entity type."""
        pass
```

### 4. Device-Level Healer (`ha_boss/healing/device_healer.py`)

**Responsibilities**:
- Device reconnection
- Device reboot (if integration supports it)
- Device re-discovery
- Track device-level healing actions

**Key Methods**:

```python
class DeviceHealer:
    """Device-level healing strategies."""

    async def heal(self, context: HealingContext) -> HealingResult:
        """Attempt device-level healing."""
        # Get devices associated with failed entities
        devices = await self._get_devices_for_entities(context.failed_entities)

        for device_id in devices:
            # Strategy 1: Device reconnect
            result = await self._reconnect_device(device_id, context)
            if result.success:
                continue

            # Strategy 2: Device reboot
            result = await self._reboot_device(device_id, context)
            if result.success:
                continue

            # Strategy 3: Re-discover device
            result = await self._rediscover_device(device_id, context)
            if result.success:
                continue

            # Device healing failed
            return HealingResult(success=False, failed_devices=[device_id])

        return HealingResult(success=True)

    async def _get_devices_for_entities(
        self,
        entity_ids: list[str]
    ) -> list[str]:
        """Map entities to their parent devices via HA device registry."""
        pass
```

### 5. Consecutive Execution Tracker (`ha_boss/automation/health_tracker.py`)

**Responsibilities**:
- Track consecutive success/failure counts
- Update validation gating status
- Calculate automation reliability scores

**Key Methods**:

```python
class AutomationHealthTracker:
    """Tracks automation health and validation gating."""

    async def record_execution_result(
        self,
        instance_id: str,
        automation_id: str,
        success: bool
    ) -> HealthStatus:
        """Record execution result and update consecutive counts."""
        status = await self._get_or_create_status(instance_id, automation_id)

        if success:
            status.consecutive_successes += 1
            status.consecutive_failures = 0
            status.total_successes += 1

            # Check validation gating threshold
            threshold = self.config.consecutive_success_threshold
            if status.consecutive_successes >= threshold:
                status.is_validated_healthy = True
                status.last_validation_at = datetime.now(UTC)
        else:
            status.consecutive_failures += 1
            status.consecutive_successes = 0
            status.total_failures += 1
            status.is_validated_healthy = False

        status.total_executions += 1
        status.updated_at = datetime.now(UTC)

        await self._save_status(status)
        return status

    async def get_reliability_score(
        self,
        instance_id: str,
        automation_id: str
    ) -> float:
        """Calculate reliability score (0.0-1.0) for automation."""
        status = await self._get_status(instance_id, automation_id)
        if not status or status.total_executions == 0:
            return 0.0

        return status.total_successes / status.total_executions
```

## Configuration Updates

Add to `ha_boss/core/config.py`:

```python
class HealingConfig(BaseSettings):
    """Healing system configuration."""

    # Validation gating
    consecutive_success_threshold: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of consecutive successes required for validated healthy status"
    )

    validation_window: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Seconds to wait for state propagation after automation execution"
    )

    # Entity-level healing
    entity_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    entity_retry_delay: float = Field(default=2.0, ge=0.5, le=10.0)

    # Device-level healing
    device_reconnect_timeout: int = Field(default=30, ge=5, le=120)
    device_reboot_timeout: int = Field(default=60, ge=10, le=300)

    # Cascade behavior
    enable_intelligent_routing: bool = Field(
        default=True,
        description="Use pattern matching to skip healing levels when possible"
    )

    cascade_timeout: int = Field(
        default=300,
        ge=30,
        le=600,
        description="Maximum time for full healing cascade (seconds)"
    )
```

## Integration with Existing Systems

### 1. AutomationTracker Integration

Modify `ha_boss/automation/tracker.py`:

```python
async def _handle_automation_triggered(self, event: dict[str, Any]) -> None:
    """Handle automation triggered event."""
    # Existing execution tracking
    execution_id = await self._record_execution(event)

    # NEW: Start trigger failure monitoring
    automation_id = event["data"]["entity_id"]
    desired_state = await self.desired_state_service.get_desired_state(
        self.instance_id, automation_id
    )

    if desired_state:
        # Monitor for state changes within validation window
        asyncio.create_task(
            self.trigger_detector.monitor_state_changes(
                automation_id=automation_id,
                expected_trigger=desired_state.expected_states,
                validation_window=self.config.healing.validation_window
            )
        )
```

### 2. OutcomeValidator Integration

Modify `ha_boss/automation/outcome_validator.py`:

```python
async def validate_execution(
    self,
    instance_id: str,
    automation_id: str,
    execution_id: int
) -> ValidationResult:
    """Validate automation execution outcome."""
    # Existing validation logic
    result = await self._check_desired_states(instance_id, automation_id, execution_id)

    # NEW: Update health tracker
    await self.health_tracker.record_execution_result(
        instance_id=instance_id,
        automation_id=automation_id,
        success=result.success
    )

    # NEW: Trigger healing cascade if failed
    if not result.success:
        healing_context = HealingContext(
            instance_id=instance_id,
            automation_id=automation_id,
            execution_id=execution_id,
            trigger_type="outcome_failure",
            failed_entities=result.failed_entities,
            desired_states=result.expected_states
        )

        asyncio.create_task(
            self.cascade_orchestrator.execute_cascade(healing_context)
        )

    return result
```

## API Endpoints

### New Endpoints

Add to `ha_boss/api/routes/healing.py`:

```python
@router.get("/healing/cascade/{cascade_id}")
async def get_cascade_execution(
    cascade_id: int,
    instance_id: str = Query("default")
) -> CascadeExecutionResponse:
    """Get details of a healing cascade execution."""
    pass

@router.get("/healing/statistics")
async def get_healing_statistics(
    instance_id: str = Query("default"),
    automation_id: str | None = None
) -> HealingStatisticsResponse:
    """Get healing statistics (success rates by level)."""
    pass

@router.get("/automations/{automation_id}/health")
async def get_automation_health(
    automation_id: str,
    instance_id: str = Query("default")
) -> AutomationHealthResponse:
    """Get automation health status and consecutive execution tracking."""
    pass

@router.post("/healing/cascade/{cascade_id}/retry")
async def retry_cascade(
    cascade_id: int,
    instance_id: str = Query("default")
) -> CascadeExecutionResponse:
    """Manually retry a failed healing cascade."""
    pass
```

## Testing Strategy

### Unit Tests

**Test Coverage Requirements**: ≥85% for all new modules

1. **TriggerFailureDetector** (`tests/automation/test_trigger_detector.py`):
   - State change monitoring
   - Validation window behavior
   - Edge cases (rapid state changes, missed events)

2. **CascadeOrchestrator** (`tests/healing/test_cascade_orchestrator.py`):
   - Sequential cascade execution
   - Intelligent routing with pattern matching
   - Cascade timeout handling
   - Failure escalation

3. **EntityHealer** (`tests/healing/test_entity_healer.py`):
   - Service call retries
   - Alternative parameter strategies
   - Action recording

4. **DeviceHealer** (`tests/healing/test_device_healer.py`):
   - Device reconnection
   - Entity→device mapping
   - Action recording

5. **AutomationHealthTracker** (`tests/automation/test_health_tracker.py`):
   - Consecutive success/failure tracking
   - Validation gating threshold
   - Reliability score calculation

### Integration Tests

**Test Coverage**: All component interactions

1. **End-to-End Cascade** (`tests/integration/test_healing_cascade.py`):
   - Automation failure → trigger detection → cascade → resolution
   - Pattern learning and intelligent routing
   - Database consistency

2. **Multi-Instance Healing** (`tests/integration/test_multi_instance_healing.py`):
   - Healing across multiple HA instances
   - Instance-specific configuration

3. **API Integration** (`tests/api/test_healing_routes.py`):
   - All new API endpoints
   - Response models
   - Error handling

## Implementation Phases

Break implementation into discrete, reviewable issues:

### Issue #190: Database Schema for Multi-Level Healing (v8 migration)
**Scope**: Database schema only
**Deliverables**:
- Migration script v7→v8
- New tables: healing_strategies, device_healing_actions, entity_healing_actions, healing_cascade_executions, automation_health_status
- Schema updates to automation_outcome_patterns
- Migration tests

**Estimated Size**: ~300 lines (schema + migration)

### Issue #191: Trigger Failure Detector
**Scope**: State-change monitoring and trigger validation
**Deliverables**:
- `ha_boss/automation/trigger_detector.py`
- State change monitoring logic
- Validation window implementation
- Unit tests (≥85% coverage)

**Estimated Size**: ~400 lines (200 implementation + 200 tests)

### Issue #192: Automation Health Tracker
**Scope**: Consecutive execution tracking and validation gating
**Deliverables**:
- `ha_boss/automation/health_tracker.py`
- Consecutive success/failure tracking
- Validation gating logic
- Reliability score calculation
- Unit tests (≥85% coverage)

**Estimated Size**: ~350 lines (175 implementation + 175 tests)

### Issue #193: Entity-Level Healer
**Scope**: Entity-level healing strategies
**Deliverables**:
- `ha_boss/healing/entity_healer.py`
- Service call retry logic
- Alternative parameter strategies
- Action recording to database
- Unit tests (≥85% coverage)

**Estimated Size**: ~500 lines (250 implementation + 250 tests)

### Issue #194: Device-Level Healer
**Scope**: Device-level healing strategies
**Deliverables**:
- `ha_boss/healing/device_healer.py`
- Device reconnect implementation
- Device reboot support
- Entity→device mapping
- Action recording to database
- Unit tests (≥85% coverage)

**Estimated Size**: ~500 lines (250 implementation + 250 tests)

### Issue #195: Healing Cascade Orchestrator
**Scope**: Multi-level cascade orchestration
**Deliverables**:
- `ha_boss/healing/cascade_orchestrator.py`
- Sequential cascade execution (Level 1→2→3)
- Intelligent routing with pattern matching
- Cascade execution recording
- Pattern learning
- Unit tests (≥85% coverage)

**Estimated Size**: ~600 lines (300 implementation + 300 tests)

### Issue #196: Integration with AutomationTracker and OutcomeValidator
**Scope**: Wire up healing cascade to existing systems
**Deliverables**:
- Update `ha_boss/automation/tracker.py`
- Update `ha_boss/automation/outcome_validator.py`
- Trigger cascade on validation failure
- Start trigger monitoring on execution
- Integration tests

**Estimated Size**: ~400 lines (150 implementation + 250 tests)

### Issue #197: Configuration and API Endpoints
**Scope**: Healing configuration and REST API
**Deliverables**:
- Update `ha_boss/core/config.py` with HealingConfig
- New routes in `ha_boss/api/routes/healing.py`
- API response models
- API tests (≥85% coverage)

**Estimated Size**: ~450 lines (200 implementation + 250 tests)

### Issue #198: End-to-End Healing Integration Tests
**Scope**: Comprehensive integration testing
**Deliverables**:
- `tests/integration/test_healing_cascade.py`
- `tests/integration/test_multi_instance_healing.py`
- Full cascade verification
- Pattern learning verification
- Multi-instance scenarios

**Estimated Size**: ~600 lines (all tests)

## Success Criteria

Phase 2 is complete when:

- [x] All 9 issues (#190-#198) are closed and merged
- [x] Database migration v8 is applied successfully
- [x] All tests passing with ≥85% coverage for new code
- [x] Healing cascade successfully resolves entity-level failures
- [x] Healing cascade successfully resolves device-level failures
- [x] Intelligent routing skips unnecessary healing levels for known patterns
- [x] Consecutive execution tracking correctly gates validation
- [x] API endpoints return correct data for healing statistics
- [x] Documentation updated with Phase 2 features

## Dependencies and Risks

### Dependencies
- **Phase 1 Complete**: ✅ (All Phase 1 issues merged)
- **Database Migration v7**: ✅ (Applied)
- **Multi-instance support**: ✅ (Merged in PR #115)

### Risks

**Risk 1: Device-level healing integration support variance**
- **Mitigation**: Implement feature detection per integration, graceful fallback to integration-level healing

**Risk 2: State propagation timing variability**
- **Mitigation**: Configurable validation window, exponential backoff for state checks

**Risk 3: Cascade timeout on slow devices**
- **Mitigation**: Per-level timeouts, configurable cascade timeout, early termination on success

**Risk 4: Pattern matching false positives**
- **Mitigation**: Require minimum pattern match confidence, fallback to sequential cascade

## Future Enhancements (Phase 3+)

Items deferred to later phases:
- Community healing plans (YAML-based, shareable)
- AI-generated healing strategies for unknown failures
- Learning from user manual interventions
- Device-specific healing plan templates
- Integration-specific healing capabilities discovery

## References

- **Epic #177**: /tmp/epic-177-body-updated.md
- **Phase 1 Completion Summary**: Issue #177 comments
- **Multi-instance PR**: #115
- **Outcome Validation**: PRs #178-#183, #188-#189

---

**Plan Status**: Ready for Review and Implementation
**Next Step**: Create Issue #190 (Database Schema) to begin implementation
