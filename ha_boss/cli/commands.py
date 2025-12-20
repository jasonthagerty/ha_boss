"""Command-line interface for HA Boss using Typer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ha_boss.core.config import Config, load_config

if TYPE_CHECKING:
    from ha_boss.automation.analyzer import AnalysisResult
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

intelligence:
  pattern_collection_enabled: true  # Enable pattern collection for reliability analysis

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
            console.print("\n[dim]For Docker deployments, use: haboss start --foreground[/dim]")

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


# Patterns subcommands
patterns_app = typer.Typer(name="patterns", help="Pattern analysis and reliability reports")


@patterns_app.command("reliability")
def reliability_report(
    integration: str | None = typer.Option(
        None,
        "--integration",
        "-i",
        help="Show reliability for specific integration (e.g., hue, zwave)",
    ),
    days: int = typer.Option(
        7,
        "--days",
        "-d",
        help="Number of days to analyze (default: 7)",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Display integration reliability reports with success rates and health metrics.

    Shows:
    - Success rate for healing attempts
    - Total healing successes and failures
    - Unavailable event counts
    - Reliability score (Excellent/Good/Fair/Poor)
    - Recommendations for problematic integrations

    Examples:
        haboss patterns reliability
        haboss patterns reliability --integration hue
        haboss patterns reliability --days 30
    """
    console.print(
        Panel.fit(
            f"[bold cyan]Integration Reliability Report[/bold cyan]\n" f"Period: Last {days} days",
            subtitle="Pattern Analysis",
        )
    )

    try:
        config = load_config(config_path)
        asyncio.run(_show_reliability(config, days, integration))

    except Exception as e:
        handle_error(e)


async def _show_reliability(config: Config, days: int, integration_domain: str | None) -> None:
    """Show reliability report.

    Args:
        config: HA Boss configuration
        days: Number of days to analyze
        integration_domain: Optional integration filter
    """
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    async with Database(str(config.database.path)) as db:
        analyzer = ReliabilityAnalyzer(db)

        # Get metrics
        metrics = await analyzer.get_integration_metrics(
            days=days, integration_domain=integration_domain
        )

        if not metrics:
            if integration_domain:
                console.print(
                    f"\n[yellow]No data found for integration '{integration_domain}' "
                    f"in the last {days} days.[/yellow]"
                )
            else:
                console.print(
                    "\n[yellow]No reliability data available yet.[/yellow]\n"
                    "[dim]Run 'haboss start' to begin collecting patterns.[/dim]"
                )
            return

        # Create table
        table = Table(
            title=f"\nIntegration Reliability (Last {days} days)",
            show_header=True,
        )
        table.add_column("Integration", style="cyan", no_wrap=True)
        table.add_column("Success Rate", justify="right")
        table.add_column("Rating", justify="center")
        table.add_column("Heals ✓", justify="right", style="green")
        table.add_column("Failures ✗", justify="right", style="red")
        table.add_column("Unavailable", justify="right", style="yellow")

        # Add rows
        for metric in metrics:
            # Color code success rate based on reliability score
            if metric.reliability_score == "Excellent":
                rate_color = "green"
            elif metric.reliability_score == "Good":
                rate_color = "cyan"
            elif metric.reliability_score == "Fair":
                rate_color = "yellow"
            else:  # Poor
                rate_color = "red"

            # Color code rating
            if metric.reliability_score == "Excellent":
                rating_color = "green"
            elif metric.reliability_score == "Good":
                rating_color = "cyan"
            elif metric.reliability_score == "Fair":
                rating_color = "yellow"
            else:  # Poor
                rating_color = "red"

            table.add_row(
                metric.integration_domain,
                f"[{rate_color}]{metric.success_rate * 100:.1f}%[/{rate_color}]",
                f"[{rating_color}]{metric.reliability_score}[/{rating_color}]",
                str(metric.heal_successes),
                str(metric.heal_failures),
                str(metric.unavailable_events),
            )

        console.print(table)

        # Show recommendations for problematic integrations
        problematic = [m for m in metrics if m.needs_attention]
        if problematic:
            console.print("\n[bold yellow]⚠️  Recommendations:[/bold yellow]\n")
            for metric in problematic:
                console.print(
                    f"• [yellow]{metric.integration_domain}[/yellow]: "
                    f"{metric.reliability_score} reliability ({metric.success_rate * 100:.1f}%) "
                    f"- Check integration configuration"
                )


@patterns_app.command("failures")
def failures_timeline(
    integration: str | None = typer.Option(
        None,
        "--integration",
        "-i",
        help="Filter by integration (e.g., zwave, hue)",
    ),
    days: int = typer.Option(
        7,
        "--days",
        "-d",
        help="Number of days to look back (default: 7)",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Maximum number of events to show (default: 50)",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Show timeline of failure events for troubleshooting.

    Displays chronological list of:
    - Healing failures
    - Entity unavailable events
    - Integration-specific issues

    Examples:
        haboss patterns failures
        haboss patterns failures --integration zwave
        haboss patterns failures --days 30 --limit 100
    """
    console.print(
        Panel.fit(
            f"[bold cyan]Failure Timeline[/bold cyan]\n" f"Period: Last {days} days",
            subtitle="Event History",
        )
    )

    try:
        config = load_config(config_path)
        asyncio.run(_show_failures(config, integration, days, limit))

    except Exception as e:
        handle_error(e)


async def _show_failures(
    config: Config, integration_domain: str | None, days: int, limit: int
) -> None:
    """Show failure timeline.

    Args:
        config: HA Boss configuration
        integration_domain: Optional integration filter
        days: Number of days to analyze
        limit: Maximum number of events to show
    """
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    async with Database(str(config.database.path)) as db:
        analyzer = ReliabilityAnalyzer(db)

        # Get failure events
        events = await analyzer.get_failure_timeline(
            integration_domain=integration_domain, days=days, limit=limit
        )

        if not events:
            if integration_domain:
                console.print(
                    f"\n[green]No failures found for integration '{integration_domain}' "
                    f"in the last {days} days.[/green] ✓"
                )
            else:
                console.print(f"\n[green]No failures recorded in the last {days} days.[/green] ✓")
            return

        # Create table
        table = Table(
            title=f"\nFailure Events (Last {days} days, showing {len(events)})",
            show_header=True,
        )
        table.add_column("Timestamp", style="dim")
        table.add_column("Integration", style="cyan")
        table.add_column("Event Type", justify="center")
        table.add_column("Entity", style="yellow", overflow="fold")

        # Add rows
        for event in events:
            # Color code event type
            if event.event_type == "heal_failure":
                event_display = "[red]Heal Failed[/red]"
            else:  # unavailable
                event_display = "[yellow]Unavailable[/yellow]"

            # Format timestamp
            timestamp_str = event.timestamp.strftime("%m-%d %H:%M:%S")

            # Truncate entity_id if too long
            entity_display = event.entity_id or "-"
            if len(entity_display) > 40:
                entity_display = entity_display[:37] + "..."

            table.add_row(
                timestamp_str,
                event.integration_domain,
                event_display,
                entity_display,
            )

        console.print(table)

        # Show summary statistics
        heal_failures = sum(1 for e in events if e.event_type == "heal_failure")
        unavailable = sum(1 for e in events if e.event_type == "unavailable")

        console.print(
            f"\n[dim]Summary: {heal_failures} heal failures, {unavailable} unavailable events[/dim]"
        )


@patterns_app.command("weekly-summary")
def weekly_summary(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    no_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Skip sending notification to Home Assistant",
    ),
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help="Skip AI-generated analysis",
    ),
) -> None:
    """Generate and display weekly summary report.

    Analyzes the past week of integration health data and generates
    a summary including:
    - Overall success rate and healing statistics
    - Top performing integrations
    - Integrations needing attention
    - Trends compared to previous week
    - AI-powered analysis and recommendations

    Examples:
        haboss patterns weekly-summary
        haboss patterns weekly-summary --no-notify
        haboss patterns weekly-summary --no-ai
    """
    console.print(
        Panel.fit(
            "[bold cyan]Weekly Summary Report[/bold cyan]",
            subtitle="AI-Powered Health Analysis",
        )
    )

    try:
        config = load_config(config_path)

        # Override AI setting if requested
        if no_ai:
            config.notifications.ai_enhanced = False

        asyncio.run(_generate_weekly_summary(config, send_notify=not no_notify))

    except Exception as e:
        handle_error(e)


async def _generate_weekly_summary(config: Config, send_notify: bool) -> None:
    """Generate and display weekly summary.

    Args:
        config: HA Boss configuration
        send_notify: Whether to send HA notification
    """
    from ha_boss.core.ha_client import create_ha_client
    from ha_boss.intelligence.claude_client import ClaudeClient
    from ha_boss.intelligence.llm_router import LLMRouter
    from ha_boss.intelligence.ollama_client import OllamaClient
    from ha_boss.intelligence.weekly_summary import WeeklySummaryGenerator
    from ha_boss.notifications.manager import NotificationManager

    async with Database(str(config.database.path)) as db:
        await db.init_db()

        # Set up LLM router if AI is enabled
        llm_router = None
        if config.notifications.ai_enhanced:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing AI...", total=None)

                ollama_client = None
                claude_client = None

                if config.intelligence.ollama_enabled:
                    ollama_client = OllamaClient(
                        url=config.intelligence.ollama_url,
                        model=config.intelligence.ollama_model,
                        timeout=config.intelligence.ollama_timeout_seconds,
                    )

                if config.intelligence.claude_enabled and config.intelligence.claude_api_key:
                    claude_client = ClaudeClient(
                        api_key=config.intelligence.claude_api_key,
                        model=config.intelligence.claude_model,
                    )

                llm_router = LLMRouter(
                    ollama_client=ollama_client,
                    claude_client=claude_client,
                    local_only=not config.intelligence.claude_enabled,
                )

                progress.remove_task(task)

        # Set up notification manager if needed
        notification_manager = None
        ha_client = None
        if send_notify:
            try:
                ha_client = await create_ha_client(config)
                notification_manager = NotificationManager(config, ha_client)
            except Exception as e:
                console.print(
                    f"[yellow]Warning:[/yellow] Cannot connect to HA for notifications: {e}",
                    style="dim",
                )

        # Generate summary
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating weekly summary...", total=None)

            generator = WeeklySummaryGenerator(
                config=config,
                database=db,
                llm_router=llm_router,
                notification_manager=notification_manager,
            )

            summary = await generator.generate_summary()

            # Store in database
            await generator.store_in_database(summary)

            progress.remove_task(task)

        # Display report
        report = generator.format_report(summary)
        console.print(Panel(report, title="Weekly Summary", expand=False))

        # Show statistics table
        table = Table(title="\nStatistics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Integrations Monitored", str(summary.total_integrations))
        table.add_row("Healing Attempts", str(summary.total_healing_attempts))
        table.add_row("Successful Healings", f"[green]{summary.successful_healings}[/green]")
        table.add_row("Failed Healings", f"[red]{summary.failed_healings}[/red]")
        table.add_row(
            "Success Rate",
            f"[{'green' if summary.overall_success_rate >= 0.8 else 'yellow' if summary.overall_success_rate >= 0.6 else 'red'}]"
            f"{summary.overall_success_rate:.1%}[/]",
        )

        if summary.success_rate_change is not None:
            if summary.success_rate_change > 0:
                change_str = f"[green]+{summary.success_rate_change:.1f}%[/green]"
            elif summary.success_rate_change < 0:
                change_str = f"[red]{summary.success_rate_change:.1f}%[/red]"
            else:
                change_str = "0%"
            table.add_row("vs Last Week", change_str)

        console.print(table)

        # Send notification if requested
        if send_notify and notification_manager:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Sending notification...", total=None)
                await generator.send_notification(summary)
                progress.remove_task(task)

            console.print("\n[green]✓[/green] Notification sent to Home Assistant")
        elif send_notify and not notification_manager:
            console.print("\n[yellow]Notification skipped (HA not available)[/yellow]")

        # Close HA client if we opened one
        if ha_client:
            await ha_client.close()

        console.print("\n[green]✓ Weekly summary generated successfully[/green]")


@patterns_app.command("recommendations")
def integration_recommendations(
    integration: str = typer.Argument(..., help="Integration domain (e.g., hue, zwave, met)"),
    days: int = typer.Option(
        7,
        "--days",
        "-d",
        help="Number of days to analyze (default: 7)",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Get actionable recommendations for a specific integration.

    Provides:
    - Health assessment
    - Specific issues identified
    - Suggested actions to improve reliability

    Examples:
        haboss patterns recommendations hue
        haboss patterns recommendations zwave --days 30
    """
    console.print(
        Panel.fit(
            f"[bold cyan]Recommendations[/bold cyan]\n"
            f"Integration: {integration}\n"
            f"Period: Last {days} days",
            subtitle="Actionable Insights",
        )
    )

    try:
        config = load_config(config_path)
        asyncio.run(_show_recommendations(config, integration, days))

    except Exception as e:
        handle_error(e)


async def _show_recommendations(config: Config, integration_domain: str, days: int) -> None:
    """Show recommendations for an integration.

    Args:
        config: HA Boss configuration
        integration_domain: Integration to analyze
        days: Number of days to analyze
    """
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    async with Database(str(config.database.path)) as db:
        analyzer = ReliabilityAnalyzer(db)

        # Get recommendations
        recommendations = await analyzer.get_recommendations(
            integration_domain=integration_domain, days=days
        )

        if not recommendations:
            console.print(
                f"\n[yellow]No data available for integration '{integration_domain}' "
                f"in the last {days} days.[/yellow]"
            )
            return

        # Display recommendations
        console.print(f"\n[bold]Recommendations for {integration_domain}:[/bold]\n")
        for rec in recommendations:
            # Color code based on severity markers
            if "CRITICAL" in rec or "⚠️" in rec:
                console.print(f"  [red]• {rec}[/red]")
            elif "WARNING" in rec or "⚡" in rec:
                console.print(f"  [yellow]• {rec}[/yellow]")
            elif "✓" in rec:
                console.print(f"  [green]• {rec}[/green]")
            else:
                console.print(f"  [cyan]• {rec}[/cyan]")


# Automation subcommands
automation_app = typer.Typer(name="automation", help="Automation analysis and optimization")


@automation_app.command("analyze")
def analyze_automation(
    automation_id: str | None = typer.Argument(
        None,
        help="Automation ID to analyze (e.g., bedroom_lights or automation.bedroom_lights)",
    ),
    all_automations: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Analyze all automations",
    ),
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help="Skip AI-powered analysis",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Analyze Home Assistant automations for optimization opportunities.

    Provides:
    - Structure overview (triggers, conditions, actions)
    - Static analysis for common anti-patterns
    - AI-powered optimization suggestions
    - Actionable recommendations

    Examples:
        haboss automation analyze bedroom_lights
        haboss automation analyze automation.morning_routine
        haboss automation analyze --all
        haboss automation analyze bedroom_lights --no-ai
    """
    if not automation_id and not all_automations:
        console.print("[red]Error:[/red] Either provide an automation ID or use --all")
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            "[bold cyan]Automation Analyzer[/bold cyan]",
            subtitle="Optimization Suggestions",
        )
    )

    try:
        config = load_config(config_path)

        # Override AI setting if requested
        if no_ai:
            config.notifications.ai_enhanced = False

        if all_automations:
            asyncio.run(_analyze_all_automations(config, include_ai=not no_ai))
        elif automation_id:  # Type guard for mypy
            asyncio.run(_analyze_single_automation(config, automation_id, include_ai=not no_ai))

    except Exception as e:
        handle_error(e)


async def _analyze_single_automation(config: Config, automation_id: str, include_ai: bool) -> None:
    """Analyze a single automation.

    Args:
        config: HA Boss configuration
        automation_id: Automation entity ID (validated by CLI before calling)
        include_ai: Whether to include AI analysis
    """
    from ha_boss.automation.analyzer import AutomationAnalyzer
    from ha_boss.intelligence.claude_client import ClaudeClient
    from ha_boss.intelligence.llm_router import LLMRouter
    from ha_boss.intelligence.ollama_client import OllamaClient

    async with await create_ha_client(config) as ha_client:
        # Set up LLM router if AI is enabled
        llm_router = None
        if include_ai and config.notifications.ai_enhanced:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing AI...", total=None)

                ollama_client = None
                claude_client = None

                if config.intelligence.ollama_enabled:
                    ollama_client = OllamaClient(
                        url=config.intelligence.ollama_url,
                        model=config.intelligence.ollama_model,
                        timeout=config.intelligence.ollama_timeout_seconds,
                    )

                if config.intelligence.claude_enabled and config.intelligence.claude_api_key:
                    claude_client = ClaudeClient(
                        api_key=config.intelligence.claude_api_key,
                        model=config.intelligence.claude_model,
                    )

                llm_router = LLMRouter(
                    ollama_client=ollama_client,
                    claude_client=claude_client,
                    local_only=not config.intelligence.claude_enabled,
                )

                progress.remove_task(task)

        # Create analyzer
        analyzer = AutomationAnalyzer(ha_client, config, llm_router)

        # Analyze automation
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Analyzing {automation_id}...", total=None)
            result = await analyzer.analyze_automation(automation_id, include_ai=include_ai)
            progress.remove_task(task)

        if not result:
            console.print(f"\n[red]Error:[/red] Automation '{automation_id}' not found")
            return

        # Display results
        _display_analysis_result(result)


async def _analyze_all_automations(config: Config, include_ai: bool) -> None:
    """Analyze all automations.

    Args:
        config: HA Boss configuration
        include_ai: Whether to include AI analysis
    """
    from ha_boss.automation.analyzer import AutomationAnalyzer
    from ha_boss.intelligence.claude_client import ClaudeClient
    from ha_boss.intelligence.llm_router import LLMRouter
    from ha_boss.intelligence.ollama_client import OllamaClient

    async with await create_ha_client(config) as ha_client:
        # Set up LLM router if AI is enabled
        llm_router = None
        if include_ai and config.notifications.ai_enhanced:
            ollama_client = None
            claude_client = None

            if config.intelligence.ollama_enabled:
                ollama_client = OllamaClient(
                    url=config.intelligence.ollama_url,
                    model=config.intelligence.ollama_model,
                    timeout=config.intelligence.ollama_timeout_seconds,
                )

            if config.intelligence.claude_enabled and config.intelligence.claude_api_key:
                claude_client = ClaudeClient(
                    api_key=config.intelligence.claude_api_key,
                    model=config.intelligence.claude_model,
                )

            llm_router = LLMRouter(
                ollama_client=ollama_client,
                claude_client=claude_client,
                local_only=not config.intelligence.claude_enabled,
            )

        # Create analyzer
        analyzer = AutomationAnalyzer(ha_client, config, llm_router)

        # Get all automations
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching automations...", total=None)
            automations = await analyzer.get_automations()
            progress.remove_task(task)

        if not automations:
            console.print("\n[yellow]No automations found in Home Assistant[/yellow]")
            return

        console.print(f"\n[cyan]Found {len(automations)} automations[/cyan]\n")

        # Analyze each automation with single progress bar
        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing automations...", total=len(automations))
            for automation in automations:
                result = await analyzer.analyze_automation_state(automation, include_ai=include_ai)
                if result:
                    results.append(result)
                progress.advance(task)

        # Display summary table
        _display_analysis_summary(results)

        # Show details for automations with issues
        automations_with_issues = [r for r in results if r.has_issues]
        if automations_with_issues:
            console.print(
                f"\n[bold yellow]Automations Needing Attention ({len(automations_with_issues)}):[/bold yellow]"
            )
            for result in automations_with_issues:
                console.print(f"\n[cyan]{'─' * 60}[/cyan]")
                _display_analysis_result(result, compact=True)


@automation_app.command("generate")
def generate_automation(
    prompt: str = typer.Argument(..., help="Natural language description of the automation"),
    mode: str = typer.Option(
        "single",
        "--mode",
        "-m",
        help="Automation mode (single, restart, queued, parallel)",
    ),
    create: bool = typer.Option(
        False,
        "--create",
        help="Create the automation in Home Assistant (default: preview only)",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Generate Home Assistant automation from natural language.

    Uses Claude API to translate your description into a valid Home Assistant
    automation YAML. By default, shows preview only. Use --create to actually
    create the automation in Home Assistant.

    Requires Claude API to be configured in config.yaml.

    Examples:
        # Preview automation (default)
        haboss automation generate "Turn on lights when motion detected after sunset"

        # Create automation in Home Assistant
        haboss automation generate "Turn off all lights at 11pm" --create

        # Create with custom mode
        haboss automation generate "Send notification if garage door open > 10 minutes" --mode restart --create
    """
    console.print(
        Panel.fit(
            "[bold cyan]Automation Generator[/bold cyan]",
            subtitle="AI-Powered Automation Creation",
        )
    )

    if mode not in ["single", "restart", "queued", "parallel"]:
        console.print(
            f"[red]Error:[/red] Invalid mode '{mode}'. Must be single, restart, queued, or parallel"
        )
        raise typer.Exit(code=1)

    try:
        config = load_config(config_path)

        # Check Claude API is configured
        if not config.intelligence.claude_enabled or not config.intelligence.claude_api_key:
            console.print(
                "[red]Error:[/red] Claude API must be configured to generate automations\n"
                "[yellow]Hint:[/yellow] Set claude_enabled: true and claude_api_key in config.yaml"
            )
            raise typer.Exit(code=1)

        asyncio.run(_generate_automation(config, prompt, mode, create))

    except Exception as e:
        handle_error(e)


async def _generate_automation(
    config: Config,
    prompt: str,
    mode: str,
    create: bool,
) -> None:
    """Generate automation using Claude API.

    Args:
        config: HA Boss configuration
        prompt: Natural language description
        mode: Automation mode
        create: Whether to create automation in HA (default: preview only)
    """
    from ha_boss.automation.generator import AutomationGenerator
    from ha_boss.intelligence.claude_client import ClaudeClient
    from ha_boss.intelligence.llm_router import LLMRouter
    from ha_boss.intelligence.ollama_client import OllamaClient

    async with await create_ha_client(config) as ha_client:
        # Set up LLM router with Claude
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Initializing Claude API...", total=None)

            ollama_client = None
            if config.intelligence.ollama_enabled:
                ollama_client = OllamaClient(
                    url=config.intelligence.ollama_url,
                    model=config.intelligence.ollama_model,
                    timeout=config.intelligence.ollama_timeout_seconds,
                )

            # API key is guaranteed to be set due to check above
            assert config.intelligence.claude_api_key is not None
            claude_client = ClaudeClient(
                api_key=config.intelligence.claude_api_key,
                model=config.intelligence.claude_model,
            )

            llm_router = LLMRouter(
                ollama_client=ollama_client,
                claude_client=claude_client,
                local_only=False,  # Need Claude for generation
            )

            progress.remove_task(task)

        # Create generator
        generator = AutomationGenerator(ha_client, config, llm_router)

        # Generate automation
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating automation with Claude API...", total=None)
            automation = await generator.generate_from_prompt(prompt, mode)
            progress.remove_task(task)

        if not automation:
            console.print("\n[red]Error:[/red] Failed to generate automation")
            console.print(
                "[yellow]Hint:[/yellow] Try rephrasing your prompt or check Claude API configuration"
            )
            return

        # Display preview
        console.print("\n" + generator.format_automation_preview(automation))

        if not automation.is_valid:
            console.print(
                "\n[red]Warning:[/red] Generated automation has validation errors. Review carefully before using."
            )

        # Create in HA if requested
        if create:
            # Don't create if validation failed
            if not automation.is_valid:
                console.print(
                    "\n[red]Error:[/red] Cannot create automation with validation errors. "
                    "Review and fix the issues first."
                )
                return

            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task("Creating automation in Home Assistant...", total=None)
                    result = await ha_client.create_automation(automation.yaml_config)
                    progress.remove_task(task)

                automation_id = result.get("id", "unknown")
                console.print(
                    f"\n[green]✓[/green] Automation created successfully!"
                )
                console.print(f"  [dim]ID:[/dim] {automation_id}")
                console.print(f"  [dim]Alias:[/dim] {automation.yaml_config.get('alias', 'Unknown')}")
                console.print(
                    f"\n[cyan]View in Home Assistant:[/cyan] Configuration → Automations → {automation.yaml_config.get('alias')}"
                )

            except Exception as e:
                console.print(f"\n[red]Error:[/red] Failed to create automation: {e}")
                console.print("\n[bold]Manual Creation Instructions:[/bold]")
                console.print("1. Go to Home Assistant → Configuration → Automations")
                console.print("2. Click '+ Add Automation' → '...' menu → 'Edit in YAML'")
                console.print("3. Copy and paste the YAML above")
                console.print("4. Save the automation\n")
        else:
            # Preview only mode
            console.print("\n[dim](Preview only - use --create to create in Home Assistant)[/dim]")
            console.print("\n[bold]To create this automation:[/bold]")
            console.print("  Run again with: --create")
            console.print("\n[bold]Or create manually:[/bold]")
            console.print("1. Go to Home Assistant → Configuration → Automations")
            console.print("2. Click '+ Add Automation' → '...' menu → 'Edit in YAML'")
            console.print("3. Copy and paste the YAML above")
            console.print("4. Save the automation")


def _display_analysis_result(result: AnalysisResult, compact: bool = False) -> None:
    """Display analysis result with formatting.

    Args:
        result: Analysis result to display
        compact: Use compact format
    """
    from ha_boss.automation.analyzer import SuggestionSeverity

    # Header
    if not compact:
        console.print(f"\n[bold]Automation:[/bold] {result.friendly_name}")
        console.print(f"[dim]Entity ID: {result.automation_id}[/dim]")
    else:
        console.print(f"\n[bold]{result.friendly_name}[/bold] ({result.automation_id})")

    # Structure overview
    state_color = "green" if result.state == "on" else "yellow"
    console.print(
        f"State: [{state_color}]{result.state}[/{state_color}] | "
        f"Triggers: {result.trigger_count} | "
        f"Conditions: {result.condition_count} | "
        f"Actions: {result.action_count}"
    )

    # Suggestions
    if result.suggestions:
        if not compact:
            console.print("\n[bold]Analysis:[/bold]")

        for suggestion in result.suggestions:
            if suggestion.severity == SuggestionSeverity.ERROR:
                icon = "[red]✗[/red]"
                title_style = "red"
            elif suggestion.severity == SuggestionSeverity.WARNING:
                icon = "[yellow]⚠[/yellow]"
                title_style = "yellow"
            else:  # INFO
                icon = "[green]✓[/green]"
                title_style = "green"

            console.print(f"{icon} [{title_style}]{suggestion.title}[/{title_style}]")
            if not compact:
                console.print(f"   [dim]{suggestion.description}[/dim]")
    else:
        console.print("\n[green]✓ No issues found[/green]")

    # AI analysis
    if result.ai_analysis and not compact:
        console.print("\n[bold]AI Suggestions:[/bold]")
        console.print(Panel(result.ai_analysis, expand=False, border_style="blue"))


def _display_analysis_summary(results: list[AnalysisResult]) -> None:
    """Display summary table of all analyzed automations.

    Args:
        results: List of analysis results
    """
    from ha_boss.automation.analyzer import SuggestionSeverity

    table = Table(title="Automation Analysis Summary", show_header=True)
    table.add_column("Automation", style="cyan", no_wrap=True, overflow="ellipsis", max_width=35)
    table.add_column("State", justify="center")
    table.add_column("T/C/A", justify="center")  # Triggers/Conditions/Actions
    table.add_column("Issues", justify="center")
    table.add_column("Status", justify="center")

    for result in results:
        # State formatting
        state_color = "green" if result.state == "on" else "yellow"
        state_display = f"[{state_color}]{result.state}[/{state_color}]"

        # Structure counts
        tca_display = f"{result.trigger_count}/{result.condition_count}/{result.action_count}"

        # Count issues
        errors = sum(1 for s in result.suggestions if s.severity == SuggestionSeverity.ERROR)
        warnings = sum(1 for s in result.suggestions if s.severity == SuggestionSeverity.WARNING)

        if errors > 0:
            issues_display = f"[red]{errors} errors[/red]"
        elif warnings > 0:
            issues_display = f"[yellow]{warnings} warnings[/yellow]"
        else:
            issues_display = "[green]0[/green]"

        # Overall status
        if errors > 0:
            status = "[red]Needs Fix[/red]"
        elif warnings > 0:
            status = "[yellow]Review[/yellow]"
        else:
            status = "[green]Good[/green]"

        table.add_row(
            result.friendly_name,
            state_display,
            tca_display,
            issues_display,
            status,
        )

    console.print(table)

    # Summary stats
    total = len(results)
    with_errors = sum(
        1 for r in results if any(s.severity == SuggestionSeverity.ERROR for s in r.suggestions)
    )
    with_warnings = sum(
        1
        for r in results
        if any(s.severity == SuggestionSeverity.WARNING for s in r.suggestions)
        and not any(s.severity == SuggestionSeverity.ERROR for s in r.suggestions)
    )
    good = total - with_errors - with_warnings

    console.print(
        f"\n[dim]Summary: {good} good, {with_warnings} need review, {with_errors} need fix[/dim]"
    )


# Register subcommands
app.add_typer(config_app, name="config")
app.add_typer(db_app, name="db")
app.add_typer(patterns_app, name="patterns")
app.add_typer(automation_app, name="automation")


def main() -> None:
    """Main entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
