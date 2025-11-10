# Issue #27: Create PatternCollector Service

## 📋 Overview

Implement a service that listens to healing events and stores reliability patterns in the database.

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P0 (blocking)
**Effort**: 3 hours

## 🎯 Objective

Create `PatternCollector` class that:
- Records healing attempts (success/failure)
- Records entity unavailable events
- Stores events in database asynchronously
- Gracefully handles errors (no crashes)
- Minimal performance impact (< 5ms per event)

## 🏗️ Implementation

### File: `ha_boss/intelligence/__init__.py`

```python
"""Intelligence layer for pattern collection and analysis."""

from ha_boss.intelligence.pattern_collector import PatternCollector

__all__ = ["PatternCollector"]
```

### File: `ha_boss/intelligence/pattern_collector.py`

```python
"""Pattern collection service for integration reliability tracking."""

import logging
from datetime import UTC, datetime
from typing import Any

from ha_boss.core.config import Config
from ha_boss.core.database import Database, IntegrationReliability

logger = logging.getLogger(__name__)


class PatternCollector:
    """Collects and stores integration reliability patterns.

    Tracks:
    - Healing successes/failures
    - Entity availability changes
    - Integration failure frequency
    - Time-of-day patterns
    """

    def __init__(self, database: Database, config: Config) -> None:
        """Initialize pattern collector.

        Args:
            database: Database manager
            config: HA Boss configuration
        """
        self.database = database
        self.config = config
        self._enabled = config.intelligence.pattern_collection_enabled

    async def record_healing_attempt(
        self,
        entity_id: str,
        integration_id: str | None,
        integration_domain: str | None,
        success: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a healing attempt for reliability tracking.

        Args:
            entity_id: Entity that was healed
            integration_id: Integration config entry ID
            integration_domain: Integration domain (e.g., 'hue', 'zwave')
            success: Whether healing succeeded
            details: Additional context
        """
        if not self._enabled:
            return

        if not integration_id or not integration_domain:
            logger.debug(
                f"Skipping pattern collection for {entity_id} - no integration info"
            )
            return

        event_type = "heal_success" if success else "heal_failure"

        try:
            async with self.database.session() as session:
                event = IntegrationReliability(
                    integration_id=integration_id,
                    integration_domain=integration_domain,
                    timestamp=datetime.now(UTC),
                    event_type=event_type,
                    entity_id=entity_id,
                    details=details,
                )
                session.add(event)
                await session.commit()

            logger.debug(
                f"Recorded {event_type} for {integration_domain} "
                f"(entity: {entity_id})"
            )

        except Exception as e:
            logger.error(f"Failed to record healing pattern: {e}", exc_info=True)
            # Don't raise - pattern collection should never crash the service

    async def record_entity_unavailable(
        self,
        entity_id: str,
        integration_id: str | None,
        integration_domain: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record entity becoming unavailable.

        Args:
            entity_id: Entity that became unavailable
            integration_id: Integration config entry ID
            integration_domain: Integration domain
            details: Additional context
        """
        if not self._enabled or not integration_id:
            return

        try:
            async with self.database.session() as session:
                event = IntegrationReliability(
                    integration_id=integration_id,
                    integration_domain=integration_domain,
                    timestamp=datetime.now(UTC),
                    event_type="unavailable",
                    entity_id=entity_id,
                    details=details,
                )
                session.add(event)
                await session.commit()

        except Exception as e:
            logger.error(f"Failed to record unavailable event: {e}", exc_info=True)

    async def get_event_count(self) -> int:
        """Get total number of recorded events.

        Returns:
            Count of reliability events
        """
        try:
            async with self.database.session() as session:
                from sqlalchemy import func, select
                result = await session.execute(
                    select(func.count(IntegrationReliability.id))
                )
                return result.scalar_one()
        except Exception as e:
            logger.error(f"Failed to get event count: {e}")
            return 0
```

## 🔌 Integration Points

This service will be called from:

1. **HealingManager** - After each healing attempt
2. **HealthMonitor** - When entity becomes unavailable
3. **Service Orchestration** - Initialize on startup

Integration details will be handled in Issue #30.

## ✅ Acceptance Criteria

- [ ] `PatternCollector` class implemented
- [ ] Records healing successes
- [ ] Records healing failures
- [ ] Records entity unavailable events
- [ ] Extracts integration info from discovery service
- [ ] Graceful error handling (logs but doesn't crash)
- [ ] Configuration option to enable/disable
- [ ] Performance < 5ms per event
- [ ] Unit tests with mocked database
- [ ] Type hints on all methods

## 🧪 Testing

Create `tests/intelligence/test_pattern_collector.py`:

```python
@pytest.mark.asyncio
async def test_record_healing_success():
    """Test recording successful healing attempt."""
    # Mock database
    # Call record_healing_attempt(success=True)
    # Verify event stored with correct event_type

@pytest.mark.asyncio
async def test_record_healing_failure():
    """Test recording failed healing attempt."""
    # Similar to above with success=False

@pytest.mark.asyncio
async def test_record_unavailable():
    """Test recording entity unavailable event."""
    # Call record_entity_unavailable()
    # Verify event stored

@pytest.mark.asyncio
async def test_disabled_collection():
    """Test that collection respects enabled flag."""
    # Set pattern_collection_enabled=False
    # Call recording methods
    # Verify nothing stored

@pytest.mark.asyncio
async def test_error_handling():
    """Test graceful error handling."""
    # Mock database to raise exception
    # Verify error is logged but not raised
    # Service should continue operating

@pytest.mark.asyncio
async def test_missing_integration_info():
    """Test handling when integration info is None."""
    # Call with integration_id=None
    # Verify gracefully skipped (logged)
```

## 📝 Implementation Notes

1. **Async Context Manager**: Use `async with self.database.session()` for transactions

2. **Error Isolation**: Pattern collection failures must not crash the service
   - Catch all exceptions
   - Log errors
   - Continue operating

3. **Performance**:
   - Async I/O prevents blocking
   - Database writes are fast (local SQLite)
   - Target < 5ms per event

4. **Integration Discovery**:
   - Integration ID/domain provided by caller
   - PatternCollector doesn't do discovery itself
   - Gracefully handle missing info

## 🔗 Dependencies

- **Requires**: #26 (database schema)
- **Blocks**: #30 (service integration)

## 📚 References

- Existing `HealingManager` for integration pattern
- Existing `Database` class for session management
- CLAUDE.md design philosophy (fail gracefully)

---

**Labels**: `phase-2`, `intelligence`, `service`, `P0`
