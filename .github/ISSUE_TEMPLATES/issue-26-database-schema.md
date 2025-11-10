# Issue #26: Design and Implement Pattern Database Schema

## 📋 Overview

Design and implement database tables to efficiently store and query integration reliability patterns.

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P0 (blocking other issues)
**Effort**: 2 hours

## 🎯 Objective

Create database schema that supports:
- Recording individual reliability events (healing attempts, failures, unavailable states)
- Aggregating metrics by time period (hourly, daily, weekly)
- Efficient querying for analysis
- Long-term storage with configurable retention

## 📊 Database Design

### Table 1: `integration_reliability`
**Purpose**: Store individual reliability events

```sql
CREATE TABLE integration_reliability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    integration_id TEXT NOT NULL,           -- Config entry ID
    integration_domain TEXT NOT NULL,       -- e.g., 'hue', 'zwave', 'met'
    timestamp DATETIME NOT NULL,
    event_type TEXT NOT NULL,               -- 'heal_success', 'heal_failure', 'unavailable'
    entity_id TEXT,                         -- Which entity triggered this
    details JSON,                           -- Additional context
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_integration_id (integration_id),
    INDEX idx_domain_timestamp (integration_domain, timestamp),
    INDEX idx_event_type (event_type),
    INDEX idx_timestamp (timestamp)
);
```

**Event Types**:
- `heal_success`: Integration reload succeeded
- `heal_failure`: Integration reload failed
- `unavailable`: Entity became unavailable (problem detected)

### Table 2: `integration_metrics`
**Purpose**: Aggregated metrics for faster queries

```sql
CREATE TABLE integration_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    integration_id TEXT NOT NULL,
    integration_domain TEXT NOT NULL,
    period_start DATETIME NOT NULL,
    period_end DATETIME NOT NULL,
    total_events INTEGER DEFAULT 0,
    heal_successes INTEGER DEFAULT 0,
    heal_failures INTEGER DEFAULT 0,
    unavailable_events INTEGER DEFAULT 0,
    success_rate REAL,                      -- heal_successes / (successes + failures)

    UNIQUE(integration_id, period_start),
    INDEX idx_domain_period (integration_domain, period_start)
);
```

### Table 3: `pattern_insights`
**Purpose**: Store pre-calculated insights

```sql
CREATE TABLE pattern_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,             -- 'top_failures', 'time_of_day', 'correlation'
    period TEXT NOT NULL,                   -- 'daily', 'weekly', 'monthly'
    period_start DATETIME NOT NULL,
    data JSON NOT NULL,                     -- Flexible JSON for different insight types
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_type_period (insight_type, period_start)
);
```

## 🏗️ Implementation

### File: `ha_boss/core/database.py`

Add SQLAlchemy models:

```python
class IntegrationReliability(Base):
    """Track individual integration reliability events."""
    __tablename__ = "integration_reliability"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[str] = mapped_column(String, index=True)
    integration_domain: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC)
    )


class IntegrationMetrics(Base):
    """Aggregated integration reliability metrics."""
    __tablename__ = "integration_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[str] = mapped_column(String, index=True)
    integration_domain: Mapped[str] = mapped_column(String, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    total_events: Mapped[int] = mapped_column(Integer, default=0)
    heal_successes: Mapped[int] = mapped_column(Integer, default=0)
    heal_failures: Mapped[int] = mapped_column(Integer, default=0)
    unavailable_events: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class PatternInsight(Base):
    """Store pre-calculated pattern insights."""
    __tablename__ = "pattern_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    insight_type: Mapped[str] = mapped_column(String, index=True)
    period: Mapped[str] = mapped_column(String)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC)
    )
```

## ✅ Acceptance Criteria

- [ ] Three new tables created in SQLite
- [ ] SQLAlchemy models defined with proper types
- [ ] Indexes created for query performance
- [ ] Tables created automatically on first run
- [ ] Migration strategy documented
- [ ] Tests verify table creation
- [ ] Foreign key relationships (if needed) properly defined
- [ ] JSON column support verified

## 🧪 Testing

Create `tests/core/test_database_patterns.py`:

```python
async def test_integration_reliability_model():
    """Test IntegrationReliability model creation."""
    # Verify model can be created
    # Verify all fields work
    # Verify indexes exist

async def test_integration_metrics_model():
    """Test IntegrationMetrics model."""
    # Test aggregation calculations
    # Test unique constraint on (integration_id, period_start)

async def test_pattern_insight_model():
    """Test PatternInsight model."""
    # Test JSON serialization
    # Test query by insight_type
```

## 📝 Implementation Notes

1. **Database Migration**:
   - Tables auto-created on first run (via `Base.metadata.create_all`)
   - Document manual migration if upgrading existing database

2. **Index Strategy**:
   - Index on timestamp for time-range queries
   - Composite index on (domain, timestamp) for per-integration queries
   - Index on event_type for filtering

3. **JSON Storage**:
   - SQLite JSON support verified (available in SQLite 3.9+)
   - Store additional context without schema changes

4. **Retention**:
   - Plan for cleanup of old records (implement in separate issue)
   - Consider partitioning for very large datasets (future)

## 🔗 Dependencies

- **Blocks**: #27, #28, #29, #30
- **Requires**: MVP database infrastructure (complete)

## 📚 References

- SQLAlchemy async documentation
- SQLite JSON functions: https://www.sqlite.org/json1.html
- Existing database.py for pattern

---

**Labels**: `phase-2`, `database`, `schema`, `P0`
