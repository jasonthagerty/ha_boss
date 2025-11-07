"""Command-line interface for HA Boss using Typer."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ha_boss.core.config import Config, load_config
from ha_boss.core.database import Database
from ha_boss.core.exceptions import (
    ConfigurationError,
    HomeAssistantAuthError,
    HomeAssistantConnectionError,
)
from ha_boss.core.ha_client import create_ha_client
from ha_boss.service import HABossService

# Create Typer app
app = typer.Typer(
    name="haboss",
    help="HA Boss - Home Assistant monitoring and auto-healing service",
    add_completion=False,
)

# Create Rich console for output
console = Console()


def handle_error(error: Exception, exit_code: int = 1) -> None:
    """Handle CLI errors with user-friendly messages.

    Args:
        error: Exception to handle
        exit_code: Exit code (default: 1)
    """
    console.print(f"\n[bold red]Error:[/bold red] {error}", style="red")

    if isinstance(error, ConfigurationError):
        console.print(
            "\n[yellow]Hint:[/yellow] Run 'haboss init' to create a configuration file",
            style="dim",
        )
    elif isinstance(error, HomeAssistantAuthError):
        console.print(
            "\n[yellow]Hint:[/yellow] Check your HA_TOKEN in .env or config.yaml",
            style="dim",
        )
    elif isinstance(error, HomeAssistantConnectionError):
        console.print(
            "\n[yellow]Hint:[/yellow] Check that Home Assistant is running and accessible",
            style="dim",
        )

    raise typer.Exit(code=exit_code)


@app.command()
def init(
    config_dir: Path = typer.Option(
        Path("config"),
        "--config-dir",
        "-c",
        help="Directory for configuration files",
    ),
    data_dir: Path = typer.Option(
        Path("data"),
        "--data-dir",
        "-d",
        help="Directory for database and runtime data",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration",
    ),
) -> None:
    """Initialize configuration and database for HA Boss.

    Creates:
    - config/config.yaml (from example template)
    - config/.env (environment variables template)
    - data/ directory (for database)
    """
    console.print(
        Panel.fit(
            "[bold cyan]HA Boss Initialization[/bold cyan]",
            subtitle="Setting up configuration and database",
        )
    )

    # Create directories
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Create config.yaml from example
    config_file = config_dir / "config.yaml"
    if config_file.exists() and not force:
        console.print(
            f"\n[yellow]Configuration file already exists:[/yellow] {config_file}",
            style="dim",
        )
        console.print("[dim]Use --force to overwrite[/dim]")
    else:
        config_template = """# HA Boss Configuration

home_assistant:
  url: ${HA_URL}  # e.g., http://homeassistant.local:8123
  token: ${HA_TOKEN}  # Long-lived access token from HA

monitoring:
  grace_period_seconds: 300  # Wait before marking entity as unavailable
  stale_threshold_seconds: 3600  # Threshold for stale entities
  exclude:
    - "sensor.time*"
    - "sensor.date*"
    - "sun.sun"

healing:
  enabled: true
  max_attempts: 3
  cooldown_seconds: 300
  circuit_breaker_threshold: 10

notifications:
  on_healing_failure: true
  weekly_summary: true

logging:
  level: INFO
  format: text

database:
  path: data/ha_boss.db
  retention_days: 30

mode: production  # production, dry_run, or testing
"""
        config_file.write_text(config_template)
        console.print(f"\n[green]✓[/green] Created configuration: {config_file}")

    # Create .env template
    env_file = config_dir / ".env"
    if env_file.exists() and not force:
        console.print(
            f"[yellow]Environment file already exists:[/yellow] {env_file}",
            style="dim",
        )
    else:
        env_template = """# Home Assistant Connection
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token_here

# Optional: Override config file path
# CONFIG_PATH=./config/config.yaml
"""
        env_file.write_text(env_template)
        console.print(f"[green]✓[/green] Created environment file: {env_file}")

    # Initialize database
    console.print("\n[cyan]Initializing database...[/cyan]")
    try:
        db_path = data_dir / "ha_boss.db"
        asyncio.run(_init_database(db_path))
        console.print(f"[green]✓[/green] Database initialized: {db_path}")
    except Exception as e:
        handle_error(e)

    console.print(
        "\n[bold green]✓ Initialization complete![/bold green]",
        style="green",
    )
    console.print("\n[cyan]Next steps:[/cyan]")
    console.print(f"1. Edit {env_file} and add your Home Assistant URL and token")
    console.print(f"2. Review and customize {config_file}")
    console.print("3. Run 'haboss config validate' to check configuration")
    console.print("4. Run 'haboss start' to begin monitoring")


async def _init_database(db_path: Path) -> None:
    """Initialize database schema.

    Args:
        db_path: Path to SQLite database file
    """
    async with Database(str(db_path)) as db:
        await db.init_db()


@app.command()
def start(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="Run in foreground (don't daemonize)",
    ),
) -> None:
    """Start the HA Boss monitoring service.

    This command starts the main monitoring loop that:
    - Connects to Home Assistant via WebSocket
    - Monitors entity health in real-time
    - Automatically heals failed integrations
    - Sends notifications when manual intervention is needed
    """
    console.print(
        Panel.fit(
            "[bold cyan]HA Boss Service[/bold cyan]",
            subtitle="Starting monitoring and auto-healing",
        )
    )

    try:
        # Load configuration
        with console.status("[cyan]Loading configuration...", spinner="dots"):
            config = load_config(config_path)

        console.print("[green]✓[/green] Configuration loaded")

        # Create and start service
        console.print("\n[cyan]Initializing HA Boss service...[/cyan]")
        service = HABossService(config)

        if foreground:
            # Run in foreground (for Docker and development)
            console.print("[cyan]Running in foreground mode (Ctrl+C to stop)[/cyan]\n")
            asyncio.run(service.run_forever())
        else:
            # Background mode
            console.print("[yellow]Background/daemon mode not yet implemented[/yellow]")
            console.print("[cyan]Use --foreground to run in foreground mode[/cyan]")
            console.print(
                "\n[dim]For Docker deployments, use: haboss start --foreground[/dim]"
            )

    except KeyboardInterrupt:
        console.print("\n[yellow]Service interrupted by user[/yellow]")
    except Exception as e:
        handle_error(e)


@app.command()
def status(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed status information",
    ),
) -> None:
    """Show service and entity health status.

    Displays:
    - Connection status to Home Assistant
    - Recent health issues detected
    - Healing actions performed
    - Circuit breaker status
    """
    console.print(
        Panel.fit(
            "[bold cyan]HA Boss Status[/bold cyan]",
            subtitle="Service and entity health overview",
        )
    )

    try:
        # Load configuration
        config = load_config(config_path)

        # Show configuration status
        table = Table(title="Configuration", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("HA URL", config.home_assistant.url)
        table.add_row("Mode", config.mode)
        table.add_row("Healing Enabled", "✓" if config.healing.enabled else "✗")
        table.add_row("Database", str(config.database.path))

        console.print("\n", table)

        # Check HA connection
        console.print("\n[cyan]Checking Home Assistant connection...[/cyan]")
        asyncio.run(_check_ha_connection(config))

        # Show database statistics
        console.print("\n[cyan]Database Statistics:[/cyan]")
        asyncio.run(_show_db_stats(config))

    except Exception as e:
        handle_error(e)


async def _check_ha_connection(config: Config) -> None:
    """Check connection to Home Assistant.

    Args:
        config: HA Boss configuration
    """
    try:
        async with await create_ha_client(config) as client:
            ha_config = await client.get_config()
            console.print(
                f"[green]✓[/green] Connected to Home Assistant "
                f"(version {ha_config.get('version', 'unknown')})"
            )
            console.print(f"  Location: {ha_config.get('location_name', 'Unknown')}")
    except HomeAssistantAuthError:
        console.print("[red]✗[/red] Authentication failed - check your token")
    except HomeAssistantConnectionError as e:
        console.print(f"[red]✗[/red] Connection failed: {e}")


async def _show_db_stats(config: Config) -> None:
    """Show database statistics.

    Args:
        config: HA Boss configuration
    """
    try:
        async with Database(str(config.database.path)) as db:
            # Get statistics from database
            async with db.async_session() as session:
                from sqlalchemy import func, select

                from ha_boss.core.database import Entity, HealingAction, HealthEvent

                # Count records
                entity_count = await session.scalar(select(func.count()).select_from(Entity))
                health_count = await session.scalar(select(func.count()).select_from(HealthEvent))
                healing_count = await session.scalar(
                    select(func.count()).select_from(HealingAction)
                )

                # Count successful healings
                successful_healings = await session.scalar(
                    select(func.count())
                    .select_from(HealingAction)
                    .where(HealingAction.success == True)  # noqa: E712
                )

                table = Table(show_header=False)
                table.add_column("Metric", style="cyan")
                table.add_column("Count", justify="right")

                table.add_row("Tracked Entities", str(entity_count or 0))
                table.add_row("Health Events", str(health_count or 0))
                table.add_row("Healing Attempts", str(healing_count or 0))
                table.add_row("Successful Healings", str(successful_healings or 0))

                if healing_count and healing_count > 0:
                    success_rate = (successful_healings or 0) / healing_count * 100
                    table.add_row("Success Rate", f"{success_rate:.1f}%")

                console.print("\n", table)

    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not read database: {e}", style="dim")


@app.command()
def heal(
    entity_id: str = typer.Argument(..., help="Entity ID to heal (e.g., sensor.temperature)"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Simulate healing without actually executing",
    ),
) -> None:
    """Manually trigger healing for a specific entity.

    This will:
    1. Look up the integration for the entity
    2. Attempt to reload the integration
    3. Report the result

    Example:
        haboss heal sensor.temperature
        haboss heal light.living_room --dry-run
    """
    console.print(
        Panel.fit(
            f"[bold cyan]Manual Healing[/bold cyan]\n{entity_id}",
            subtitle="Triggering integration reload",
        )
    )

    try:
        config = load_config(config_path)
        if dry_run:
            config.mode = "dry_run"
            console.print("\n[yellow]Dry-run mode enabled[/yellow]\n")

        asyncio.run(_perform_healing(config, entity_id))

    except Exception as e:
        handle_error(e)


async def _perform_healing(config: Config, entity_id: str) -> None:
    """Perform healing for an entity.

    Args:
        config: HA Boss configuration
        entity_id: Entity ID to heal
    """
    from ha_boss.core.database import Database
    from ha_boss.healing.heal_strategies import HealingManager
    from ha_boss.healing.integration_manager import IntegrationDiscovery
    from ha_boss.monitoring.health_monitor import HealthIssue

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Initialize components
        progress.add_task("Connecting to Home Assistant...", total=None)

        async with await create_ha_client(config) as ha_client:
            async with Database(str(config.database.path)) as db:
                await db.init_db()

                # Discover integrations
                task = progress.add_task("Discovering integrations...", total=None)
                integration_discovery = IntegrationDiscovery(ha_client, db, config)
                await integration_discovery.discover_all()
                progress.remove_task(task)

                # Create healing manager
                healing_manager = HealingManager(
                    config,
                    db,
                    ha_client,
                    integration_discovery,
                )

                # Check if entity can be healed
                can_heal, reason = await healing_manager.can_heal(entity_id)
                if not can_heal:
                    console.print(f"\n[yellow]Cannot heal entity:[/yellow] {reason}")
                    return

                # Create health issue for the entity
                health_issue = HealthIssue(
                    entity_id=entity_id,
                    issue_type="manual",
                    detected_at=datetime.now(UTC),
                    details={"trigger": "manual_cli"},
                )

                # Attempt healing
                task = progress.add_task(f"Healing {entity_id}...", total=None)
                try:
                    success = await healing_manager.heal(health_issue)
                    progress.remove_task(task)

                    if success:
                        console.print(f"\n[green]✓ Successfully healed {entity_id}[/green]")

                        # Get integration details
                        integration_id = integration_discovery.get_integration_for_entity(entity_id)
                        if integration_id:
                            details = integration_discovery.get_integration_details(integration_id)
                            if details:
                                console.print(
                                    f"[dim]Reloaded integration: {details.get('title', integration_id)}[/dim]"
                                )
                    else:
                        console.print(f"\n[red]✗ Failed to heal {entity_id}[/red]")

                except Exception as e:
                    progress.remove_task(task)
                    console.print(f"\n[red]✗ Healing failed:[/red] {e}")


# Config subcommands
config_app = typer.Typer(name="config", help="Configuration management commands")


@config_app.command("validate")
def validate_config(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Validate configuration file.

    Checks:
    - YAML syntax
    - Required fields present
    - Value types correct
    - Environment variables resolved
    - Home Assistant connection works
    """
    console.print(
        Panel.fit(
            "[bold cyan]Configuration Validation[/bold cyan]",
            subtitle="Checking configuration file and connection",
        )
    )

    try:
        # Load and validate configuration
        console.print("\n[cyan]Loading configuration...[/cyan]")
        config = load_config(config_path)

        console.print("[green]✓[/green] Configuration file valid")
        console.print(f"[dim]  Loaded from: {config_path or 'default locations'}[/dim]")

        # Show configuration summary
        table = Table(title="\nConfiguration Summary", show_header=False)
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("HA URL", config.home_assistant.url)
        table.add_row("Mode", config.mode)
        table.add_row("Monitoring Grace Period", f"{config.monitoring.grace_period_seconds}s")
        table.add_row("Healing Enabled", "Yes" if config.healing.enabled else "No")
        table.add_row("Max Heal Attempts", str(config.healing.max_attempts))
        table.add_row("Database Path", str(config.database.path))
        table.add_row("Log Level", config.logging.level)

        console.print(table)

        # Test HA connection
        console.print("\n[cyan]Testing Home Assistant connection...[/cyan]")
        asyncio.run(_check_ha_connection(config))

        console.print("\n[bold green]✓ Configuration is valid![/bold green]")

    except ConfigurationError as e:
        console.print(f"\n[red]✗ Configuration error:[/red] {e}")
        raise typer.Exit(code=1) from None
    except Exception as e:
        handle_error(e)


# DB subcommands
db_app = typer.Typer(name="db", help="Database management commands")


@db_app.command("cleanup")
def cleanup_database(
    days: int = typer.Option(
        30,
        "--days",
        "-d",
        help="Delete records older than this many days",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without actually deleting",
    ),
) -> None:
    """Clean up old database records.

    Removes:
    - Health events older than specified days
    - Healing actions older than specified days
    - Entities that no longer exist

    This helps keep the database size manageable and performance optimal.

    Example:
        haboss db cleanup --days 30
        haboss db cleanup --days 7 --dry-run
    """
    console.print(
        Panel.fit(
            "[bold cyan]Database Cleanup[/bold cyan]",
            subtitle=f"Removing records older than {days} days",
        )
    )

    if dry_run:
        console.print("\n[yellow]Dry-run mode - no changes will be made[/yellow]\n")

    try:
        config = load_config(config_path)
        asyncio.run(_cleanup_db(config, days, dry_run))

    except Exception as e:
        handle_error(e)


async def _cleanup_db(config: Config, days: int, dry_run: bool) -> None:
    """Clean up old database records.

    Args:
        config: HA Boss configuration
        days: Remove records older than this many days
        dry_run: If True, show what would be deleted without deleting
    """
    from sqlalchemy import delete, func, select

    from ha_boss.core.database import Database, HealingAction, HealthEvent

    cutoff_date = datetime.now(UTC) - timedelta(days=days)

    async with Database(str(config.database.path)) as db:
        async with db.async_session() as session:
            # Count records to be deleted
            health_count = await session.scalar(
                select(func.count())
                .select_from(HealthEvent)
                .where(HealthEvent.timestamp < cutoff_date)
            )

            healing_count = await session.scalar(
                select(func.count())
                .select_from(HealingAction)
                .where(HealingAction.timestamp < cutoff_date)
            )

            table = Table(show_header=False)
            table.add_column("Record Type", style="cyan")
            table.add_column("Count", justify="right")

            table.add_row("Health Events", str(health_count or 0))
            table.add_row("Healing Actions", str(healing_count or 0))

            console.print("\n", table)

            if dry_run:
                console.print(
                    "\n[yellow]Dry-run mode:[/yellow] No records were deleted", style="dim"
                )
                return

            if not health_count and not healing_count:
                console.print("\n[green]No records to delete[/green]")
                return

            # Confirm deletion
            if not typer.confirm(
                f"\nDelete {(health_count or 0) + (healing_count or 0)} records?",
                default=False,
            ):
                console.print("[yellow]Cancelled[/yellow]")
                return

            # Delete old records
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Deleting records...", total=None)

                await session.execute(
                    delete(HealthEvent).where(HealthEvent.timestamp < cutoff_date)
                )
                await session.execute(
                    delete(HealingAction).where(HealingAction.timestamp < cutoff_date)
                )
                await session.commit()

                progress.remove_task(task)

            console.print(
                f"\n[green]✓ Deleted {(health_count or 0) + (healing_count or 0)} records[/green]"
            )


# Register subcommands
app.add_typer(config_app, name="config")
app.add_typer(db_app, name="db")


def main() -> None:
    """Main entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
