# Database Migration Guide

This guide explains how to manage database schema migrations in HA Boss.

## Overview

HA Boss uses SQLite with schema versioning to track and manage database changes. The current schema version is stored in the `schema_version` table and validated on startup.

**Current Schema Version:** v1

## Version Tracking

### DatabaseVersion Model

The `schema_version` table tracks all applied migrations:

```sql
CREATE TABLE schema_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    applied_at DATETIME NOT NULL,
    description TEXT
);
```

### Version Constant

The current expected schema version is defined in `ha_boss/core/database.py`:

```python
CURRENT_DB_VERSION = 1
```

## Startup Validation

On startup, HA Boss validates the database schema version:

1. **New Database**: Automatically creates all tables and sets version to `CURRENT_DB_VERSION`
2. **Current Version**: Proceeds normally
3. **Outdated Version**: Displays error and requires migration
4. **Future Version**: Displays error and requires HA Boss upgrade

## Creating a Migration

When making schema changes:

### 1. Update the Schema

Add/modify models in `ha_boss/core/database.py`:

```python
class NewModel(Base):
    """New table for feature X."""
    __tablename__ = "new_table"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[str] = mapped_column(String(255))
```

### 2. Increment Version

Update `CURRENT_DB_VERSION` in `ha_boss/core/database.py`:

```python
CURRENT_DB_VERSION = 2  # Increment from 1
```

### 3. Create Migration Function

Add migration function to `ha_boss/core/database.py`:

```python
async def migrate_v1_to_v2(db: Database) -> None:
    """Migrate database from v1 to v2.

    Changes:
    - Add new_table for feature X
    - Add column Y to existing_table
    """
    async with db.async_session() as session:
        # Create new table
        async with db.engine.begin() as conn:
            await conn.execute(text('''
                CREATE TABLE new_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL
                )
            '''))

        # Add column to existing table
        async with db.engine.begin() as conn:
            await conn.execute(text('''
                ALTER TABLE existing_table
                ADD COLUMN new_column TEXT
            '''))

        # Record migration
        version = DatabaseVersion(
            version=2,
            description="Added new_table and existing_table.new_column"
        )
        session.add(version)
        await session.commit()
```

### 4. Register Migration

Add to migration registry in `ha_boss/core/database.py`:

```python
MIGRATIONS = {
    (1, 2): migrate_v1_to_v2,
    # Future migrations:
    # (2, 3): migrate_v2_to_v3,
}
```

### 5. Add CLI Command

Update `ha_boss/cli/commands.py` to add migration command:

```python
@app.command()
def db_migrate() -> None:
    """Run pending database migrations."""
    config = load_config()
    db = Database(config.database.path)

    current = asyncio.run(db.get_version())
    if current == CURRENT_DB_VERSION:
        typer.echo("✓ Database already at current version")
        return

    # Run migrations
    for (from_ver, to_ver), migrate_fn in MIGRATIONS.items():
        if current == from_ver:
            typer.echo(f"Migrating v{from_ver} → v{to_ver}...")
            asyncio.run(migrate_fn(db))
            current = to_ver
```

## Migration Best Practices

### Breaking vs Non-Breaking Changes

**Non-Breaking (Safe):**
- Adding new tables
- Adding new columns with defaults
- Adding indexes
- Adding new models

**Breaking (Requires Care):**
- Removing columns
- Renaming columns
- Changing column types
- Removing tables
- Changing constraints

### Testing Migrations

Before releasing:

1. **Test on Empty Database:**
   ```bash
   rm data/ha_boss.db
   haboss start --foreground
   # Should create v2 database directly
   ```

2. **Test Migration Path:**
   ```bash
   # Start with v1 database
   haboss db-migrate
   # Should upgrade to v2
   ```

3. **Test Rollback:**
   ```bash
   # Ensure you can restore from backup
   cp data/ha_boss.db.backup data/ha_boss.db
   ```

### Data Migrations

For data transformations:

```python
async def migrate_v1_to_v2(db: Database) -> None:
    """Migrate with data transformation."""
    async with db.async_session() as session:
        # 1. Schema changes
        async with db.engine.begin() as conn:
            await conn.execute(text("ALTER TABLE..."))

        # 2. Data migration
        result = await session.execute(select(OldModel))
        old_records = result.scalars().all()

        for old in old_records:
            new = NewModel(
                id=old.id,
                data=transform_data(old.old_field)
            )
            session.add(new)

        await session.commit()

        # 3. Record version
        version = DatabaseVersion(version=2, description="...")
        session.add(version)
        await session.commit()
```

## Rollback Strategy

### Backup Before Migration

Always backup before applying migrations:

```bash
# Automatic backup
cp data/ha_boss.db data/ha_boss.db.backup.$(date +%Y%m%d_%H%M%S)

# Or use SQLite backup
sqlite3 data/ha_boss.db ".backup data/ha_boss.db.backup"
```

### Rollback Process

If migration fails:

1. Stop HA Boss
2. Restore backup: `cp data/ha_boss.db.backup data/ha_boss.db`
3. Restart HA Boss with previous version

### Downgrade Migrations (Advanced)

For reversible migrations, create downgrade functions:

```python
DOWNGRADES = {
    (2, 1): downgrade_v2_to_v1,
}

async def downgrade_v2_to_v1(db: Database) -> None:
    """Rollback v2 to v1."""
    async with db.async_session() as session:
        # Remove added table
        async with db.engine.begin() as conn:
            await conn.execute(text("DROP TABLE new_table"))

        # Remove version record
        await session.execute(
            delete(DatabaseVersion).where(DatabaseVersion.version == 2)
        )
        await session.commit()
```

## Version Compatibility Matrix

| HA Boss Version | DB Schema Version | Migration Required |
|----------------|-------------------|-------------------|
| v0.1.0         | v1               | -                 |
| v0.2.0 (future)| v2               | v1 → v2           |

## Future Enhancements

Planned improvements:

1. **Automatic Migrations**: Run migrations automatically on startup (opt-in)
2. **Migration Status**: CLI command to show pending migrations
3. **Dry-Run Mode**: Preview migration changes without applying
4. **Migration History**: Track all applied migrations with timestamps
5. **Health Checks**: Validate schema integrity after migrations

## Common Migration Scenarios

### Adding a Column

```python
async def add_column_migration(db: Database) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(text('''
            ALTER TABLE entities
            ADD COLUMN last_error TEXT
        '''))
```

### Adding an Index

```python
async def add_index_migration(db: Database) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(text('''
            CREATE INDEX idx_entities_domain
            ON entities(domain)
        '''))
```

### Renaming a Column (SQLite-Safe)

SQLite doesn't support RENAME COLUMN in older versions:

```python
async def rename_column_migration(db: Database) -> None:
    """Rename column via table recreation."""
    async with db.engine.begin() as conn:
        # 1. Create new table with new column name
        await conn.execute(text('''
            CREATE TABLE entities_new (
                entity_id TEXT PRIMARY KEY,
                new_column_name TEXT,
                -- other columns...
            )
        '''))

        # 2. Copy data
        await conn.execute(text('''
            INSERT INTO entities_new
            SELECT entity_id, old_column_name, ...
            FROM entities
        '''))

        # 3. Drop old table
        await conn.execute(text("DROP TABLE entities"))

        # 4. Rename new table
        await conn.execute(text(
            "ALTER TABLE entities_new RENAME TO entities"
        ))
```

## Support

For migration questions or issues:
- Create an issue: [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- Check wiki: [Database Documentation](https://github.com/jasonthagerty/ha_boss/wiki/Database)
