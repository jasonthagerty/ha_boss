# Automation Refactoring Plan

**Date**: 2026-01-13
**Status**: Proposed
**Reason**: Home Assistant is developing native natural language automation generation, making our feature redundant. Refocus on HA Boss's core strength: optimization based on real-world monitoring data.

---

## Executive Summary

**Remove**: Natural language automation generation (`AutomationGenerator`)
**Keep & Enhance**: Automation analysis and optimization recommendations (`AutomationAnalyzer`)

**Rationale**:
1. **Home Assistant Building This** - Native NL automation generation in development
2. **Duplicate Effort** - No value in competing with parent project's feature
3. **Core Competency** - HA Boss's strength is pattern analysis from real monitoring data
4. **Better Fit**: Usage-based optimization recommendations align with HA Boss's purpose

---

## Current State Analysis

### Components to Remove

#### 1. **`ha_boss/automation/generator.py`** (387 lines)
**Purpose**: Generate automations from natural language descriptions

**Key Classes**:
- `GeneratedAutomation` - Data class for generated automation
- `AutomationGenerator` - Main generation class using Claude API

**Usage**:
- API endpoint: `POST /api/automations/generate`
- CLI command: `haboss automation generate "<description>"`
- README feature: Listed as Phase 3 feature

**Dependencies**:
- `LLMRouter` - For Claude API access
- `HomeAssistantClient` - For validation
- YAML parsing and generation
- Validation logic for automation structure

#### 2. **API Route**: `/automations/generate`
**File**: `ha_boss/api/routes/automations.py:133-234`

**Functionality**:
- Accepts natural language prompt
- Returns generated YAML with validation
- Used by dashboard (if frontend exists)

#### 3. **CLI Command**: `haboss automation generate`
**File**: `ha_boss/cli/commands.py:1605-1704`

**Functionality**:
- Interactive generation from CLI
- Preview or create automation in HA
- Requires Claude API configuration

#### 4. **API Models**:
**File**: `ha_boss/api/models.py`
- `AutomationGenerateRequest` - Request model for generation
- `AutomationGenerateResponse` - Response model with YAML
- `AutomationCreateRequest` - Request for creating in HA
- `AutomationCreateResponse` - Response after creation

**Used by**: Generate endpoint, potentially create endpoint

### Components to Keep & Enhance

#### 1. **`ha_boss/automation/analyzer.py`** (611 lines)
**Purpose**: Analyze existing automations for optimization opportunities

**Key Classes**:
- `SuggestionSeverity` - Enum for suggestion importance
- `Suggestion` - Data class for recommendations
- `AnalysisResult` - Complete analysis with AI insights
- `AutomationAnalyzer` - Main analyzer class

**Current Features**:
- ✅ Static analysis (anti-patterns, complexity, best practices)
- ✅ AI-powered analysis via LLMRouter
- ✅ Detailed suggestions with categories
- ✅ Batch analysis of all automations

**Usage**:
- API endpoint: `POST /api/automations/analyze`
- CLI command: `haboss automation analyze`
- Widely used for optimization recommendations

**What's Missing** (Enhancement Opportunity):
- ❌ **Usage-based recommendations** - No integration with monitoring data
- ❌ **Historical pattern analysis** - No tracking of automation executions
- ❌ **Performance metrics** - No execution time/frequency analysis
- ❌ **Entity reliability correlation** - Not using entity failure patterns
- ❌ **Service call optimization** - Not analyzing actual service performance

---

## Proposed Changes

### Phase 1: Remove Generation Feature

#### Files to Delete
```
ha_boss/automation/generator.py
```

#### Files to Modify

**`ha_boss/api/routes/automations.py`**:
- ❌ Remove: `AutomationGenerator` import
- ❌ Remove: `/automations/generate` endpoint (lines 133-234)
- ❌ Remove: `/automations/create` endpoint if exists
- ✅ Keep: `/automations/analyze` endpoint

**`ha_boss/api/models.py`**:
- ❌ Remove: `AutomationGenerateRequest`
- ❌ Remove: `AutomationGenerateResponse`
- ❌ Remove: `AutomationCreateRequest`
- ❌ Remove: `AutomationCreateResponse`
- ✅ Keep: `AutomationAnalysisRequest`
- ✅ Keep: `AutomationAnalysisResponse`

**`ha_boss/cli/commands.py`**:
- ❌ Remove: `@automation_app.command("generate")` (lines 1605-1674)
- ❌ Remove: `_generate_automation()` helper (lines 1676-1704+)
- ✅ Keep: `@automation_app.command("analyze")`
- ✅ Keep: `_analyze_single_automation()`
- ✅ Keep: `_analyze_all_automations()`

**`README.md`**:
- ❌ Remove: "automation generation" from features
- ❌ Remove: `haboss automation generate` from examples
- ✅ Update: Focus on "automation optimization based on real usage"
- ✅ Add: Clarify that HA has native generation coming

**`ha_boss/automation/__init__.py`**:
- ❌ Remove: `from .generator import AutomationGenerator, GeneratedAutomation`
- ✅ Keep: `from .analyzer import AutomationAnalyzer, AnalysisResult, Suggestion`

#### Tests to Remove/Update

**Tests to Delete**:
- `tests/automation/test_generator.py` (if exists)
- `tests/api/test_automations_generate.py` (if exists)
- `tests/cli/test_automation_generate.py` (if exists)

**Tests to Keep**:
- `tests/automation/test_analyzer.py`
- `tests/api/test_automations_analyze.py`
- `tests/cli/test_automation_analyze.py`

### Phase 2: Enhance Analysis with Usage Data

#### New Functionality: Usage-Based Optimization

**Goal**: Integrate monitoring data to provide recommendations based on:
- Actual automation execution patterns
- Entity reliability correlated with automations
- Service call success rates
- Timing patterns and conflicts

#### 1. **Add Database Schema** (`ha_boss/core/database.py`)

**New Tables**:

```python
class AutomationExecution(Base):
    """Track automation executions for pattern analysis."""

    __tablename__ = "automation_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[str] = mapped_column(String, nullable=False)
    automation_id: Mapped[str] = mapped_column(String, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)


class AutomationServiceCall(Base):
    """Track service calls made by automations."""

    __tablename__ = "automation_service_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[str] = mapped_column(String, nullable=False)
    automation_id: Mapped[str] = mapped_column(String, nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String)
    called_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
```

**Indexes**:
```python
Index("idx_automation_executions_instance_automation",
      AutomationExecution.instance_id,
      AutomationExecution.automation_id)
Index("idx_automation_executions_executed_at",
      AutomationExecution.executed_at)
Index("idx_automation_service_calls_instance_automation",
      AutomationServiceCall.instance_id,
      AutomationServiceCall.automation_id)
```

#### 2. **Extend AutomationAnalyzer** (`ha_boss/automation/analyzer.py`)

**New Methods**:

```python
class AutomationAnalyzer:
    # ... existing methods ...

    async def analyze_with_usage_data(
        self,
        automation_id: str,
        instance_id: str,
        days: int = 30,
        include_ai: bool = True,
    ) -> AnalysisResult:
        """Analyze automation with real usage patterns.

        Extends static analysis with:
        - Execution frequency and timing patterns
        - Service call performance metrics
        - Entity reliability correlation
        - Timing conflicts with other automations
        """
        # Get base analysis
        result = await self.analyze_automation(automation_id, include_ai=False)

        # Fetch usage data from database
        async with self.database.async_session() as session:
            # Get execution history
            executions = await self._get_execution_history(
                session, automation_id, instance_id, days
            )

            # Get service call metrics
            service_calls = await self._get_service_call_metrics(
                session, automation_id, instance_id, days
            )

            # Get entity reliability data
            entity_reliability = await self._get_entity_reliability(
                session, automation_id, instance_id, days
            )

        # Generate usage-based suggestions
        usage_suggestions = self._analyze_usage_patterns(
            executions, service_calls, entity_reliability
        )
        result.suggestions.extend(usage_suggestions)

        # Add AI analysis with usage context if enabled
        if include_ai and self.llm_router:
            ai_analysis = await self._generate_ai_analysis_with_usage(
                result, executions, service_calls, entity_reliability
            )
            result.ai_analysis = ai_analysis

        return result

    def _analyze_usage_patterns(
        self,
        executions: list[AutomationExecution],
        service_calls: list[AutomationServiceCall],
        entity_reliability: dict[str, float],
    ) -> list[Suggestion]:
        """Generate suggestions based on usage patterns."""
        suggestions = []

        # 1. Execution frequency analysis
        if executions:
            exec_count = len(executions)
            time_range_days = (executions[-1].executed_at - executions[0].executed_at).days

            if exec_count / max(time_range_days, 1) > 100:
                # Runs more than 100x per day
                suggestions.append(
                    Suggestion(
                        title="High execution frequency",
                        description=(
                            f"This automation runs ~{exec_count // max(time_range_days, 1)} "
                            f"times per day. Consider adding conditions to reduce triggers."
                        ),
                        severity=SuggestionSeverity.WARNING,
                        category="performance",
                    )
                )

            # Check for execution failures
            failed = [e for e in executions if not e.success]
            if len(failed) / len(executions) > 0.1:
                # >10% failure rate
                suggestions.append(
                    Suggestion(
                        title="High failure rate",
                        description=(
                            f"This automation fails {len(failed)}/{len(executions)} times "
                            f"({len(failed)/len(executions)*100:.1f}%). Review error conditions."
                        ),
                        severity=SuggestionSeverity.ERROR,
                        category="reliability",
                    )
                )

        # 2. Service call performance
        if service_calls:
            slow_calls = [s for s in service_calls if s.response_time_ms and s.response_time_ms > 5000]
            if slow_calls:
                # Calls taking >5s
                slow_services = set(s.service_name for s in slow_calls)
                suggestions.append(
                    Suggestion(
                        title="Slow service calls detected",
                        description=(
                            f"Services {', '.join(slow_services)} are slow (>5s). "
                            f"Consider using scenes or scripts for batch operations."
                        ),
                        severity=SuggestionSeverity.WARNING,
                        category="performance",
                    )
                )

        # 3. Entity reliability correlation
        unreliable_entities = [
            entity_id for entity_id, reliability in entity_reliability.items()
            if reliability < 0.9
        ]
        if unreliable_entities:
            suggestions.append(
                Suggestion(
                    title="Uses unreliable entities",
                    description=(
                        f"Entities {', '.join(unreliable_entities)} have <90% uptime. "
                        f"Add conditions to check entity state or add fallback actions."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="reliability",
                )
            )

        # 4. Timing pattern analysis
        if executions:
            # Analyze execution times
            hours = [e.executed_at.hour for e in executions]
            from collections import Counter
            hour_counts = Counter(hours)
            peak_hour = max(hour_counts, key=hour_counts.get)
            peak_count = hour_counts[peak_hour]

            if peak_count / len(executions) > 0.5:
                # More than 50% of executions in one hour
                suggestions.append(
                    Suggestion(
                        title="Concentrated execution pattern",
                        description=(
                            f"{peak_count/len(executions)*100:.0f}% of executions occur "
                            f"at hour {peak_hour}:00. Consider if this is intentional."
                        ),
                        severity=SuggestionSeverity.INFO,
                        category="timing",
                    )
                )

        return suggestions
```

#### 3. **Add Monitoring Integration** (`ha_boss/monitoring/automation_tracker.py` - NEW FILE)

```python
"""Track automation executions for pattern analysis."""

import logging
from datetime import UTC, datetime

from ha_boss.core.database import Database, AutomationExecution, AutomationServiceCall

logger = logging.getLogger(__name__)


class AutomationTracker:
    """Tracks automation executions and service calls for pattern analysis."""

    def __init__(self, instance_id: str, database: Database):
        """Initialize automation tracker.

        Args:
            instance_id: Home Assistant instance identifier
            database: Database instance
        """
        self.instance_id = instance_id
        self.database = database

    async def record_execution(
        self,
        automation_id: str,
        trigger_type: str | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """Record an automation execution.

        Args:
            automation_id: Automation entity ID
            trigger_type: Type of trigger that fired
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            error_message: Error message if failed
        """
        async with self.database.async_session() as session:
            execution = AutomationExecution(
                instance_id=self.instance_id,
                automation_id=automation_id,
                executed_at=datetime.now(UTC),
                trigger_type=trigger_type,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
            )
            session.add(execution)
            await session.commit()

        logger.debug(f"[{self.instance_id}] Recorded execution: {automation_id}")

    async def record_service_call(
        self,
        automation_id: str,
        service_name: str,
        entity_id: str | None = None,
        response_time_ms: int | None = None,
        success: bool = True,
    ) -> None:
        """Record a service call made by an automation.

        Args:
            automation_id: Automation entity ID
            service_name: Service called (e.g., "light.turn_on")
            entity_id: Target entity if applicable
            response_time_ms: Service response time in milliseconds
            success: Whether call succeeded
        """
        async with self.database.async_session() as session:
            service_call = AutomationServiceCall(
                instance_id=self.instance_id,
                automation_id=automation_id,
                service_name=service_name,
                entity_id=entity_id,
                called_at=datetime.now(UTC),
                response_time_ms=response_time_ms,
                success=success,
            )
            session.add(service_call)
            await session.commit()

        logger.debug(
            f"[{self.instance_id}] Recorded service call: "
            f"{automation_id} -> {service_name}"
        )
```

#### 4. **Update API Endpoint** (`ha_boss/api/routes/automations.py`)

**Enhance `/automations/analyze` endpoint**:

```python
@router.post("/automations/analyze", response_model=AutomationAnalysisResponse)
async def analyze_automation(
    request: AutomationAnalysisRequest,
    instance_id: str = Query("default", description="Instance identifier"),
    include_usage: bool = Query(
        True,
        description="Include usage-based recommendations from monitoring data"
    ),
    days: int = Query(
        30,
        ge=1,
        le=365,
        description="Number of days of usage data to analyze"
    ),
) -> AutomationAnalysisResponse:
    """Analyze an existing Home Assistant automation.

    Now supports usage-based optimization recommendations by analyzing:
    - Execution patterns and frequency
    - Service call performance
    - Entity reliability correlation
    - Timing conflicts

    Args:
        request: Automation analysis request
        instance_id: Instance identifier
        include_usage: Include usage-based recommendations
        days: Days of usage data to analyze

    Returns:
        Enhanced analysis with usage-based suggestions
    """
    # ... existing code ...

    # Use enhanced analysis if usage data requested
    if include_usage:
        result = await analyzer.analyze_with_usage_data(
            automation_id=request.automation_id,
            instance_id=instance_id,
            days=days,
            include_ai=request.include_ai,
        )
    else:
        result = await analyzer.analyze_automation(
            automation_id=request.automation_id,
            include_ai=request.include_ai,
        )

    # ... existing response code ...
```

#### 5. **WebSocket Integration** (`ha_boss/monitoring/websocket_client.py`)

**Add automation execution tracking**:

```python
# In WebSocketClient.handle_event_message()

if event_type == "automation_triggered":
    # Track automation execution
    automation_tracker = service.automation_trackers.get(self.instance_id)
    if automation_tracker:
        await automation_tracker.record_execution(
            automation_id=data.get("entity_id"),
            trigger_type=data.get("trigger"),
        )

elif event_type == "call_service":
    # Track service calls (correlate with automation if context available)
    automation_id = data.get("context", {}).get("parent_id")
    if automation_id and automation_id.startswith("automation."):
        automation_tracker = service.automation_trackers.get(self.instance_id)
        if automation_tracker:
            await automation_tracker.record_service_call(
                automation_id=automation_id,
                service_name=data.get("service"),
                entity_id=data.get("service_data", {}).get("entity_id"),
            )
```

---

## Migration Path

### Step 1: Feature Removal (Breaking Changes)

**Branch**: `refactor/remove-automation-generation`

1. Delete `generator.py`
2. Remove generate endpoint from API
3. Remove generate command from CLI
4. Update documentation
5. Remove related models and tests

**Communicate**:
- Add deprecation notice in CHANGELOG
- Update README with reason for removal
- Link to Home Assistant's native feature when available
- Provide migration guide for users relying on this

### Step 2: Database Migration

**Branch**: `feature/automation-usage-tracking`

1. Add new database tables (AutomationExecution, AutomationServiceCall)
2. Create migration script
3. Add indexes for performance
4. Test with sample data

### Step 3: Tracking Integration

**Branch**: `feature/automation-usage-tracking` (continued)

1. Implement `AutomationTracker` class
2. Integrate with WebSocket events
3. Add to service initialization
4. Test execution and service call recording

### Step 4: Enhanced Analysis

**Branch**: `feature/usage-based-optimization`

1. Extend `AutomationAnalyzer` with usage methods
2. Add usage pattern analysis logic
3. Enhance AI prompts with usage context
4. Update API endpoint with new parameters
5. Add tests for usage-based suggestions

### Step 5: Documentation & Examples

1. Update README with new focus
2. Add examples of usage-based recommendations
3. Document new API parameters
4. Create user guide for optimization workflow

---

## Testing Strategy

### Unit Tests

**Remove**:
- `test_automation_generator.py`
- All generation-related tests

**Keep & Enhance**:
- `test_automation_analyzer.py` - Add usage-based analysis tests
- Mock database queries for usage data
- Test suggestion generation from patterns

### Integration Tests

**New Tests**:
- Test automation execution tracking
- Test service call tracking
- Test usage data retrieval from database
- Test enhanced analysis endpoint

### Performance Tests

**New Benchmarks**:
- Database query performance with 10k executions
- Analysis time with vs without usage data
- Impact of usage tracking on WebSocket processing

---

## Benefits

### For Users

1. **Better Recommendations** - Based on real-world usage, not just static structure
2. **Performance Insights** - Identify slow service calls and high-frequency triggers
3. **Reliability Warnings** - Detect automations using unreliable entities
4. **Timing Analysis** - Understand execution patterns and conflicts
5. **Aligned with HA** - No duplicate features with parent project

### For HA Boss

1. **Differentiation** - Unique value proposition: usage-based optimization
2. **Core Strength** - Leverages monitoring data (HA Boss's main feature)
3. **Reduced Complexity** - Remove generation code (387 lines)
4. **Focus** - Double down on pattern analysis and optimization
5. **Future-Proof** - Won't compete with HA's native features

---

## Timeline Estimate

**Phase 1 - Removal** (2-3 days):
- Day 1: Remove generator code, API endpoint, CLI command
- Day 2: Update documentation, remove tests
- Day 3: Testing and validation

**Phase 2 - Usage Tracking** (3-4 days):
- Day 1: Database schema and migration
- Day 2: AutomationTracker implementation
- Day 3: WebSocket integration
- Day 4: Testing

**Phase 3 - Enhanced Analysis** (4-5 days):
- Day 1-2: Extend AutomationAnalyzer with usage methods
- Day 3: Update API endpoint
- Day 4: AI prompt enhancement
- Day 5: Testing and documentation

**Total**: 9-12 days for complete refactoring

---

## Risks & Mitigation

### Risk 1: Users Relying on Generation Feature

**Likelihood**: Low (feature is in Phase 3, likely low adoption)
**Impact**: Medium (some users may be upset)

**Mitigation**:
- Clear communication in CHANGELOG
- Provide link to Home Assistant's feature when available
- Offer alternative: Manual automation creation with analysis

### Risk 2: Database Growth from Tracking

**Likelihood**: High (executions can be frequent)
**Impact**: Medium (storage/performance)

**Mitigation**:
- Add configurable retention period
- Implement automatic cleanup of old data
- Add database size monitoring
- Provide option to disable tracking per instance

### Risk 3: WebSocket Performance Impact

**Likelihood**: Medium
**Impact**: Low (async recording)

**Mitigation**:
- Use async database writes
- Batch writes during high load
- Add circuit breaker for tracking failures
- Make tracking optional per instance

---

## Conclusion

This refactoring aligns HA Boss with its core mission: **intelligent monitoring and optimization based on real-world patterns**. By removing the generation feature and enhancing analysis with usage data, we:

1. Avoid competing with Home Assistant's native features
2. Leverage HA Boss's unique monitoring capabilities
3. Provide more valuable, data-driven recommendations
4. Simplify the codebase by removing 387+ lines

**Recommendation**: Proceed with refactoring, starting with Phase 1 (removal) to unblock development and clarify HA Boss's direction.

---

**Next Steps**:
1. Get user approval for refactoring
2. Create GitHub issue for tracking
3. Begin Phase 1 implementation
4. Communicate changes in CHANGELOG and README

---

## Implementation Guide

This section provides detailed, step-by-step instructions for implementing the refactoring plan. Each phase includes exact file modifications, line numbers, code snippets, and validation steps.

### Phase 1: Remove Generation Feature (Detailed)

#### Checklist

- [ ] **1.1** Delete `ha_boss/automation/generator.py`
- [ ] **1.2** Update `ha_boss/automation/__init__.py` (remove imports/exports)
- [ ] **1.3** Update `ha_boss/api/models.py` (remove 4 model classes)
- [ ] **1.4** Update `ha_boss/api/routes/automations.py` (remove endpoints)
- [ ] **1.5** Update `ha_boss/cli/commands.py` (remove command)
- [ ] **1.6** Delete `tests/automation/test_generator.py` (if exists)
- [ ] **1.7** Update `README.md` (remove generation references)
- [ ] **1.8** Add deprecation notice to `CHANGELOG.md`
- [ ] **1.9** Run tests to verify no broken imports
- [ ] **1.10** Run linters (black, ruff, mypy)

#### Detailed File Modifications

##### 1.1 Delete generator.py

```bash
# Delete the file
rm ha_boss/automation/generator.py

# Verify deletion
git status  # Should show deleted: ha_boss/automation/generator.py
```

##### 1.2 Update ha_boss/automation/__init__.py

**Current (lines 1-19)**:
```python
"""Automation analysis and optimization module."""

from ha_boss.automation.analyzer import (
    AnalysisResult,
    AutomationAnalyzer,
    Suggestion,
    SuggestionSeverity,
)
from ha_boss.automation.generator import AutomationGenerator, GeneratedAutomation

__all__ = [
    "AnalysisResult",
    "AutomationAnalyzer",
    "AutomationGenerator",
    "GeneratedAutomation",
    "Suggestion",
    "SuggestionSeverity",
]
```

**After (remove line 9, lines 14-15)**:
```python
"""Automation analysis and optimization module."""

from ha_boss.automation.analyzer import (
    AnalysisResult,
    AutomationAnalyzer,
    Suggestion,
    SuggestionSeverity,
)

__all__ = [
    "AnalysisResult",
    "AutomationAnalyzer",
    "Suggestion",
    "SuggestionSeverity",
]
```

##### 1.3 Update ha_boss/api/models.py

**Remove lines 195-225** (4 model classes):
- `AutomationGenerateRequest` (lines 195-200)
- `AutomationGenerateResponse` (lines 202-211)
- `AutomationCreateRequest` (lines 213-217)
- `AutomationCreateResponse` (lines 219-225)

##### 1.4 Update ha_boss/api/routes/automations.py

**Remove**:
- Line 17: `from ha_boss.automation.generator import AutomationGenerator`
- Lines 133-234: `generate_automation()` function
- Lines 237-299: `create_automation()` function (if only used by generation)

**Check**: If `create_automation` endpoint is used independently, keep it. Otherwise remove.

##### 1.5 Update ha_boss/cli/commands.py

**Remove lines 1605-1804**:
- Lines 1605-1674: `@automation_app.command("generate")` decorator and function
- Lines 1676-1803: `_generate_automation()` helper function

**Imports to check** (top of file):
- Remove `from ha_boss.automation.generator import AutomationGenerator` if present
- Remove `from ha_boss.intelligence.claude_client import ClaudeClient` if only used for generation

##### 1.6 Delete test files

```bash
# Check if these files exist and delete them
rm -f tests/automation/test_generator.py
rm -f tests/api/test_automations_generate.py
rm -f tests/cli/test_automation_generate.py

# Verify
git status
```

##### 1.7 Update README.md

**Find and remove** (use grep to find):
```bash
grep -n "automation generate" README.md
grep -n "natural language" README.md
```

**Sections to update**:
- Remove "Natural Language Automation Generation" from feature list
- Remove `haboss automation generate` examples
- Add note: "Home Assistant is building native automation generation. HA Boss focuses on optimization of existing automations based on real usage patterns."

##### 1.8 Add CHANGELOG entry

**Add to CHANGELOG.md**:
```markdown
## [Unreleased]

### BREAKING CHANGES

#### Automation Generation Feature Removed

**Removed**: Natural language automation generation via `haboss automation generate`

**Reason**: Home Assistant is developing native natural language automation generation.
To avoid duplication and align with HA Boss's core mission, we've removed this feature
and are focusing on usage-based optimization recommendations instead.

**Migration**:
- For automation generation: Wait for Home Assistant's native feature (coming soon)
- For automation optimization: Use `haboss automation analyze` with new usage-based recommendations

**Enhanced**: `haboss automation analyze` now provides optimization recommendations based on:
- Real execution patterns from monitoring data
- Service call performance metrics
- Entity reliability correlation
- Timing analysis and conflict detection

See docs/AUTOMATION_REFACTORING_PLAN.md for complete details.
```

##### 1.9 Validation Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/ -v --tb=short

# Check for import errors
python -c "from ha_boss.automation import AutomationAnalyzer"
python -c "from ha_boss.api.routes import automations"
python -c "from ha_boss.cli.commands import automation_app"

# Run linters
black ha_boss/ tests/ --check
ruff check ha_boss/ tests/
mypy ha_boss/ --strict
```

#### Expected Test Failures

After Phase 1, the following tests may fail (this is expected):
- Any test importing `AutomationGenerator`
- API tests for `/automations/generate` endpoint
- CLI tests for `automation generate` command

These should be deleted or updated in step 1.6.

---

### Phase 2: Add Database Schema (Detailed)

#### Checklist

- [ ] **2.1** Add new table classes to `ha_boss/core/database.py`
- [ ] **2.2** Create Alembic migration script
- [ ] **2.3** Add indexes for query performance
- [ ] **2.4** Run migration on test database
- [ ] **2.5** Validate schema with sample data
- [ ] **2.6** Update database init to create tables

#### 2.1 Add Database Tables

**File**: `ha_boss/core/database.py`

**Add after existing table definitions** (around line 100):

```python
class AutomationExecution(Base):
    """Track automation executions for pattern analysis.

    Records each time an automation runs, including success/failure,
    trigger type, and execution duration. Used by AutomationAnalyzer
    to provide usage-based optimization recommendations.
    """

    __tablename__ = "automation_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    trigger_type: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "idx_automation_executions_instance_automation",
            "instance_id",
            "automation_id",
        ),
        Index("idx_automation_executions_executed_at", "executed_at"),
    )


class AutomationServiceCall(Base):
    """Track service calls made by automations.

    Records each service call triggered by an automation, including
    response times and success status. Used to identify slow or
    unreliable service calls in optimization analysis.
    """

    __tablename__ = "automation_service_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    automation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String)
    called_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index(
            "idx_automation_service_calls_instance_automation",
            "instance_id",
            "automation_id",
        ),
        Index("idx_automation_service_calls_called_at", "called_at"),
        Index("idx_automation_service_calls_service_name", "service_name"),
    )
```

#### 2.2 Create Alembic Migration

**Create migration file**: `alembic/versions/YYYYMMDD_add_automation_tracking.py`

```python
"""Add automation execution tracking tables

Revision ID: abc123def456
Revises: previous_revision_id
Create Date: 2026-01-14 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'abc123def456'
down_revision = 'previous_revision_id'  # Update with actual previous revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add automation_executions and automation_service_calls tables."""

    # Create automation_executions table
    op.create_table(
        'automation_executions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('instance_id', sa.String(), nullable=False),
        sa.Column('automation_id', sa.String(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=False),
        sa.Column('trigger_type', sa.String(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for automation_executions
    op.create_index(
        'idx_automation_executions_instance_automation',
        'automation_executions',
        ['instance_id', 'automation_id']
    )
    op.create_index(
        'idx_automation_executions_executed_at',
        'automation_executions',
        ['executed_at']
    )
    op.create_index(
        op.f('ix_automation_executions_instance_id'),
        'automation_executions',
        ['instance_id']
    )
    op.create_index(
        op.f('ix_automation_executions_automation_id'),
        'automation_executions',
        ['automation_id']
    )

    # Create automation_service_calls table
    op.create_table(
        'automation_service_calls',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('instance_id', sa.String(), nullable=False),
        sa.Column('automation_id', sa.String(), nullable=False),
        sa.Column('service_name', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('called_at', sa.DateTime(), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for automation_service_calls
    op.create_index(
        'idx_automation_service_calls_instance_automation',
        'automation_service_calls',
        ['instance_id', 'automation_id']
    )
    op.create_index(
        'idx_automation_service_calls_called_at',
        'automation_service_calls',
        ['called_at']
    )
    op.create_index(
        'idx_automation_service_calls_service_name',
        'automation_service_calls',
        ['service_name']
    )
    op.create_index(
        op.f('ix_automation_service_calls_instance_id'),
        'automation_service_calls',
        ['instance_id']
    )
    op.create_index(
        op.f('ix_automation_service_calls_automation_id'),
        'automation_service_calls',
        ['automation_id']
    )


def downgrade() -> None:
    """Remove automation tracking tables."""

    # Drop indexes first
    op.drop_index('idx_automation_service_calls_service_name', table_name='automation_service_calls')
    op.drop_index('idx_automation_service_calls_called_at', table_name='automation_service_calls')
    op.drop_index('idx_automation_service_calls_instance_automation', table_name='automation_service_calls')
    op.drop_index(op.f('ix_automation_service_calls_automation_id'), table_name='automation_service_calls')
    op.drop_index(op.f('ix_automation_service_calls_instance_id'), table_name='automation_service_calls')

    op.drop_index(op.f('ix_automation_executions_automation_id'), table_name='automation_executions')
    op.drop_index(op.f('ix_automation_executions_instance_id'), table_name='automation_executions')
    op.drop_index('idx_automation_executions_executed_at', table_name='automation_executions')
    op.drop_index('idx_automation_executions_instance_automation', table_name='automation_executions')

    # Drop tables
    op.drop_table('automation_service_calls')
    op.drop_table('automation_executions')
```

#### 2.3 Run Migration

```bash
# Activate virtual environment
source .venv/bin/activate

# Generate migration (if using Alembic auto-generate)
alembic revision --autogenerate -m "Add automation execution tracking"

# Or manually create migration file (see 2.2 above)

# Review migration file
cat alembic/versions/YYYYMMDD_add_automation_tracking.py

# Run migration
alembic upgrade head

# Verify tables created
sqlite3 data/ha_boss.db ".schema automation_executions"
sqlite3 data/ha_boss.db ".schema automation_service_calls"
```

#### 2.4 Validate Schema

```bash
# Insert test data
sqlite3 data/ha_boss.db <<EOF
INSERT INTO automation_executions (instance_id, automation_id, executed_at, success)
VALUES ('default', 'automation.test', '2026-01-14 12:00:00', 1);

INSERT INTO automation_service_calls (instance_id, automation_id, service_name, called_at, success)
VALUES ('default', 'automation.test', 'light.turn_on', '2026-01-14 12:00:01', 1);
EOF

# Verify data
sqlite3 data/ha_boss.db "SELECT * FROM automation_executions;"
sqlite3 data/ha_boss.db "SELECT * FROM automation_service_calls;"

# Check indexes
sqlite3 data/ha_boss.db ".indexes automation_executions"
sqlite3 data/ha_boss.db ".indexes automation_service_calls"
```

---

### Phase 3: Add Tracking and Enhanced Analysis

#### Checklist

- [ ] **3.1** Create `AutomationTracker` class
- [ ] **3.2** Integrate tracker with WebSocket events
- [ ] **3.3** Add tracker to service initialization
- [ ] **3.4** Extend `AutomationAnalyzer` with usage methods
- [ ] **3.5** Update API endpoint with new parameters
- [ ] **3.6** Add CLI options for usage-based analysis
- [ ] **3.7** Write comprehensive tests
- [ ] **3.8** Update documentation

#### 3.1 Create AutomationTracker

**File**: `ha_boss/monitoring/automation_tracker.py` (NEW)

See Phase 2 section in main plan (lines 375-467) for complete implementation.

#### 3.2 WebSocket Integration

**File**: `ha_boss/monitoring/websocket_client.py`

**Add to event handler** (in `handle_event_message()` method):

```python
# Around line 200, add automation tracking
if event_type == "automation_triggered":
    # Get automation tracker from service
    automation_tracker = self.service.automation_trackers.get(self.instance_id)
    if automation_tracker:
        await automation_tracker.record_execution(
            automation_id=event_data.get("entity_id"),
            trigger_type=event_data.get("trigger", {}).get("platform"),
        )

elif event_type == "call_service":
    # Track service calls from automations
    context = event_data.get("context", {})
    parent_id = context.get("parent_id")

    # If parent is an automation, track the service call
    if parent_id and parent_id.startswith("automation."):
        automation_tracker = self.service.automation_trackers.get(self.instance_id)
        if automation_tracker:
            await automation_tracker.record_service_call(
                automation_id=parent_id,
                service_name=f"{event_data.get('domain')}.{event_data.get('service')}",
                entity_id=event_data.get("service_data", {}).get("entity_id"),
            )
```

#### 3.3 Service Initialization

**File**: `ha_boss/core/service.py`

**Add to `__init__` method**:

```python
from ha_boss.monitoring.automation_tracker import AutomationTracker

class HABossService:
    def __init__(self, config: Config):
        # ... existing code ...

        # Initialize automation trackers for each instance
        self.automation_trackers: dict[str, AutomationTracker] = {}
        for instance_id in self.ha_clients.keys():
            self.automation_trackers[instance_id] = AutomationTracker(
                instance_id=instance_id,
                database=self.database,
            )
```

---

### Sample Test Cases

#### Test 1: Import Validation (Phase 1)

```python
# tests/automation/test_imports.py

def test_generator_removed_from_imports():
    """Verify AutomationGenerator no longer importable."""
    import ha_boss.automation

    # Should NOT be in __all__
    assert "AutomationGenerator" not in ha_boss.automation.__all__
    assert "GeneratedAutomation" not in ha_boss.automation.__all__

    # Should raise ImportError
    with pytest.raises(ImportError):
        from ha_boss.automation import AutomationGenerator


def test_analyzer_still_available():
    """Verify AutomationAnalyzer still works."""
    from ha_boss.automation import AutomationAnalyzer, AnalysisResult

    assert AutomationAnalyzer is not None
    assert AnalysisResult is not None
```

#### Test 2: API Endpoint Removed (Phase 1)

```python
# tests/api/test_automations_api.py

@pytest.mark.asyncio
async def test_generate_endpoint_removed(client):
    """Verify /automations/generate endpoint is removed."""
    response = await client.post(
        "/api/automations/generate",
        json={"description": "test", "mode": "single"}
    )

    # Should return 404 Not Found
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analyze_endpoint_still_works(client, mock_ha_client):
    """Verify /automations/analyze endpoint still works."""
    response = await client.post(
        "/api/automations/analyze",
        json={"automation_id": "automation.test"}
    )

    assert response.status_code == 200
    assert "analysis" in response.json()
```

#### Test 3: Database Tracking (Phase 2)

```python
# tests/monitoring/test_automation_tracker.py

@pytest.mark.asyncio
async def test_record_execution(database):
    """Test recording automation execution."""
    from ha_boss.monitoring.automation_tracker import AutomationTracker

    tracker = AutomationTracker(instance_id="test", database=database)

    await tracker.record_execution(
        automation_id="automation.test",
        trigger_type="state",
        success=True,
    )

    # Verify recorded in database
    async with database.async_session() as session:
        result = await session.execute(
            "SELECT * FROM automation_executions WHERE automation_id = 'automation.test'"
        )
        row = result.fetchone()

        assert row is not None
        assert row["instance_id"] == "test"
        assert row["success"] is True


@pytest.mark.asyncio
async def test_record_service_call(database):
    """Test recording service call from automation."""
    from ha_boss.monitoring.automation_tracker import AutomationTracker

    tracker = AutomationTracker(instance_id="test", database=database)

    await tracker.record_service_call(
        automation_id="automation.test",
        service_name="light.turn_on",
        entity_id="light.bedroom",
        success=True,
    )

    # Verify recorded in database
    async with database.async_session() as session:
        result = await session.execute(
            "SELECT * FROM automation_service_calls WHERE automation_id = 'automation.test'"
        )
        row = result.fetchone()

        assert row is not None
        assert row["service_name"] == "light.turn_on"
        assert row["entity_id"] == "light.bedroom"
```

#### Test 4: Usage-Based Analysis (Phase 3)

```python
# tests/automation/test_analyzer_usage.py

@pytest.mark.asyncio
async def test_analyze_with_usage_data(database, mock_ha_client, mock_llm_router):
    """Test usage-based automation analysis."""
    from ha_boss.automation.analyzer import AutomationAnalyzer
    from ha_boss.monitoring.automation_tracker import AutomationTracker
    from datetime import datetime, timedelta, UTC

    # Create sample execution data
    tracker = AutomationTracker(instance_id="test", database=database)
    for i in range(100):
        await tracker.record_execution(
            automation_id="automation.high_frequency",
            executed_at=datetime.now(UTC) - timedelta(hours=i),
            success=True,
        )

    # Analyze automation with usage data
    analyzer = AutomationAnalyzer(
        ha_client=mock_ha_client,
        config=mock_config,
        llm_router=mock_llm_router,
    )

    result = await analyzer.analyze_with_usage_data(
        automation_id="automation.high_frequency",
        instance_id="test",
        days=30,
    )

    # Should include usage-based suggestions
    assert len(result.suggestions) > 0

    # Should flag high execution frequency
    frequency_suggestions = [
        s for s in result.suggestions
        if "frequency" in s.title.lower()
    ]
    assert len(frequency_suggestions) > 0
```

---

### Rollback Procedures

If issues arise during implementation, use these rollback procedures:

#### Rollback Phase 1 (File Deletions)

```bash
# Restore deleted files from git
git checkout HEAD -- ha_boss/automation/generator.py
git checkout HEAD -- ha_boss/automation/__init__.py
git checkout HEAD -- ha_boss/api/models.py
git checkout HEAD -- ha_boss/api/routes/automations.py
git checkout HEAD -- ha_boss/cli/commands.py
git checkout HEAD -- tests/automation/test_generator.py

# Reset any other modified files
git checkout HEAD -- README.md CHANGELOG.md

# Verify
git status  # Should show "nothing to commit, working tree clean"
python -c "from ha_boss.automation import AutomationGenerator"  # Should work
```

#### Rollback Phase 2 (Database Changes)

```bash
# Downgrade database migration
alembic downgrade -1

# Verify tables removed
sqlite3 data/ha_boss.db ".tables"  # Should NOT show automation_executions

# If migration file was committed, remove it
git rm alembic/versions/YYYYMMDD_add_automation_tracking.py
git commit -m "chore: rollback automation tracking migration"
```

#### Rollback Phase 3 (Code Changes)

```bash
# Remove new files
rm ha_boss/monitoring/automation_tracker.py

# Restore modified files
git checkout HEAD -- ha_boss/monitoring/websocket_client.py
git checkout HEAD -- ha_boss/core/service.py
git checkout HEAD -- ha_boss/automation/analyzer.py
git checkout HEAD -- ha_boss/api/routes/automations.py

# Verify
python -c "from ha_boss.monitoring import websocket_client"  # Should work
pytest tests/ -v  # All tests should pass
```

---

### Acceptance Criteria

#### Phase 1 Complete When:
- ✅ `generator.py` deleted and no longer in git
- ✅ No imports of `AutomationGenerator` anywhere in codebase
- ✅ `/automations/generate` endpoint returns 404
- ✅ `haboss automation generate` command removed from CLI
- ✅ All tests pass (no import errors)
- ✅ Linters pass (black, ruff, mypy)
- ✅ README updated with new focus
- ✅ CHANGELOG documents breaking change

#### Phase 2 Complete When:
- ✅ `automation_executions` table exists in database
- ✅ `automation_service_calls` table exists in database
- ✅ All indexes created successfully
- ✅ Alembic migration runs without errors
- ✅ Can insert/query sample data
- ✅ Migration has working `downgrade()` function
- ✅ Database schema matches SQLAlchemy models

#### Phase 3 Complete When:
- ✅ `AutomationTracker` class implemented with tests
- ✅ WebSocket events trigger execution recording
- ✅ Service calls are tracked and stored
- ✅ `analyze_with_usage_data()` method works
- ✅ Usage-based suggestions generated correctly
- ✅ API endpoint accepts new parameters
- ✅ CLI supports usage-based analysis
- ✅ All tests pass with >80% coverage
- ✅ Documentation updated with examples

---

### Final Validation Checklist

Run these commands to verify complete implementation:

```bash
# 1. Code quality checks
black ha_boss/ tests/ --check
ruff check ha_boss/ tests/
mypy ha_boss/ --strict

# 2. Test suite
pytest tests/ -v --cov=ha_boss --cov-report=term --cov-report=html

# 3. Import verification
python -c "from ha_boss.automation import AutomationAnalyzer; print('✓ Analyzer imports')"
python -c "from ha_boss.monitoring.automation_tracker import AutomationTracker; print('✓ Tracker imports')"

# 4. Database verification
sqlite3 data/ha_boss.db <<EOF
.tables
.schema automation_executions
.schema automation_service_calls
EOF

# 5. CLI verification
haboss automation --help  # Should show 'analyze' but not 'generate'
haboss automation analyze --help  # Should work

# 6. API verification (if server running)
curl -X GET http://localhost:8000/api/automations/generate  # Should return 404
curl -X POST http://localhost:8000/api/automations/analyze \
  -H "Content-Type: application/json" \
  -d '{"automation_id": "automation.test"}'  # Should work

# 7. Documentation verification
grep -q "usage-based optimization" README.md && echo "✓ README updated"
grep -q "Automation Generation Feature Removed" CHANGELOG.md && echo "✓ CHANGELOG updated"

# 8. Git verification
git diff --stat  # Review all changes
git log --oneline -10  # Review commit messages
```

**Expected Output**: All checks should pass with no errors. Coverage should remain >80%.

---

**Implementation Notes**:
- Each phase should be implemented in a separate feature branch
- Create PR after each phase for incremental review
- Run full test suite after each phase
- Update this document if implementation differs from plan
- Track progress using GitHub issue checklist
