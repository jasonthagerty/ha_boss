# Issue #29: Add Pattern Analysis CLI & Reports

## 📋 Overview

Add CLI commands to view integration reliability reports with Rich formatted output.

**Epic**: #25 Phase 2 - Pattern Collection & Analysis
**Priority**: P1
**Effort**: 2 hours

## 🎯 Objective

Create user-friendly CLI commands that:
- Display reliability overview for all integrations
- Show detailed failure timeline for specific integration
- Provide actionable recommendations
- Format output beautifully with Rich tables

## 🏗️ Implementation

### New CLI Commands

```bash
# View reliability overview (all integrations)
haboss patterns reliability

# View specific integration
haboss patterns reliability --integration hue

# View last 30 days instead of default 7
haboss patterns reliability --days 30

# View failure timeline
haboss patterns failures --integration zwave

# Get recommendations for an integration
haboss patterns recommendations --integration met
```

### File: `ha_boss/cli/commands.py`

Add new command group:

```python
@app.command()
def patterns(
    command: str = typer.Argument(
        ...,
        help="Pattern command: reliability, failures, recommendations"
    ),
    integration: str | None = typer.Option(
        None,
        "--integration",
        "-i",
        help="Filter by integration domain"
    ),
    days: int = typer.Option(
        7,
        "--days",
        "-d",
        help="Number of days to analyze"
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Analyze integration reliability patterns.

    Commands:
    - reliability: Show reliability overview
    - failures: Show failure timeline
    - recommendations: Get recommendations
    """
    try:
        config = load_config(config_path)

        if command == "reliability":
            asyncio.run(_show_reliability_report(config, integration, days))
        elif command == "failures":
            if not integration:
                console.print("[red]Error:[/red] --integration required for failures command")
                raise typer.Exit(1)
            asyncio.run(_show_failure_timeline(config, integration, days))
        elif command == "recommendations":
            if not integration:
                console.print("[red]Error:[/red] --integration required for recommendations")
                raise typer.Exit(1)
            asyncio.run(_show_recommendations(config, integration, days))
        else:
            console.print(f"[red]Unknown command:[/red] {command}")
            console.print("Valid commands: reliability, failures, recommendations")
            raise typer.Exit(1)

    except Exception as e:
        handle_error(e)


async def _show_reliability_report(
    config: Config,
    integration: str | None,
    days: int
) -> None:
    """Show integration reliability report."""
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    db = Database(config.database.path)
    await db.init_db()

    try:
        analyzer = ReliabilityAnalyzer(db)
        metrics = await analyzer.get_integration_metrics(integration, days)

        if not metrics:
            console.print("[yellow]No reliability data available yet[/yellow]")
            console.print("Patterns will appear after healing events are recorded.")
            return

        # Create Rich table
        title = f"Integration Reliability (Last {days} days)"
        if integration:
            title += f" - {integration}"

        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Integration", style="cyan", no_wrap=True)
        table.add_column("Success Rate", justify="right")
        table.add_column("Rating", justify="center")
        table.add_column("Heals ✓", justify="right", style="green")
        table.add_column("Failures ✗", justify="right", style="red")
        table.add_column("Unavailable", justify="right", style="yellow")

        for metric in metrics:
            # Color code success rate
            rate_str = f"{metric.success_rate * 100:.1f}%"
            if metric.success_rate >= 0.95:
                rate_color = "green"
            elif metric.success_rate >= 0.80:
                rate_color = "yellow"
            else:
                rate_color = "red"

            # Add row
            table.add_row(
                metric.integration_domain,
                f"[{rate_color}]{rate_str}[/{rate_color}]",
                metric.reliability_score,
                str(metric.heal_successes),
                str(metric.heal_failures),
                str(metric.unavailable_events),
            )

        console.print(table)

        # Show recommendations for problematic integrations
        needs_attention = [m for m in metrics if m.needs_attention]
        if needs_attention:
            console.print("\n[bold yellow]⚠️  Recommendations:[/bold yellow]")
            for metric in needs_attention[:3]:  # Top 3
                console.print(
                    f"• [yellow]{metric.integration_domain}[/yellow]: "
                    f"Poor reliability ({metric.success_rate*100:.0f}%) - "
                    f"Check integration configuration"
                )

    finally:
        await db.close()


async def _show_failure_timeline(
    config: Config,
    integration: str,
    days: int
) -> None:
    """Show failure timeline for an integration."""
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    db = Database(config.database.path)
    await db.init_db()

    try:
        analyzer = ReliabilityAnalyzer(db)
        events = await analyzer.get_failure_timeline(integration, days)

        if not events:
            console.print(f"[green]✓[/green] No failures for {integration} in the last {days} days")
            return

        console.print(f"\n[bold]Failure Timeline: {integration}[/bold] (Last {days} days)\n")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Timestamp", style="dim")
        table.add_column("Event", style="yellow")
        table.add_column("Entity", style="cyan")
        table.add_column("Details", style="dim")

        for event in events:
            timestamp = event["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            event_type = "❌ Heal Failed" if event["event_type"] == "heal_failure" else "⚠️  Unavailable"
            entity = event["entity_id"] or "-"
            details = str(event.get("details", ""))[:50]  # Truncate

            table.add_row(timestamp, event_type, entity, details)

        console.print(table)
        console.print(f"\n[bold]Total failures:[/bold] {len(events)}")

    finally:
        await db.close()


async def _show_recommendations(
    config: Config,
    integration: str,
    days: int
) -> None:
    """Show recommendations for an integration."""
    from ha_boss.intelligence.reliability_analyzer import ReliabilityAnalyzer

    db = Database(config.database.path)
    await db.init_db()

    try:
        analyzer = ReliabilityAnalyzer(db)
        recommendations = await analyzer.get_recommendations(integration, days)

        console.print(f"\n[bold cyan]Recommendations for {integration}:[/bold cyan]\n")

        for rec in recommendations:
            console.print(f"  {rec}")

        console.print()

    finally:
        await db.close()
```

## 📊 Example Output

### Reliability Overview

```
                Integration Reliability (Last 7 days)
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Integration  ┃ Success Rate ┃  Rating  ┃ Heals ✓┃ Failures ✗┃ Unavailable ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ met          │ 45.0%        │ Poor     │ 9      │ 11        │ 15          │
│ zwave        │ 75.0%        │ Fair     │ 3      │ 1         │ 5           │
│ hue          │ 95.2%        │ Excellent│ 20     │ 1         │ 2           │
│ mqtt         │ 100.0%       │ Excellent│ 5      │ 0         │ 1           │
└──────────────┴──────────────┴──────────┴────────┴───────────┴─────────────┘

⚠️  Recommendations:
• met: Poor reliability (45%) - Check integration configuration
• zwave: Fair reliability (75%) - Review network health
```

### Failure Timeline

```
Failure Timeline: met (Last 7 days)

┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Timestamp           ┃ Event        ┃ Entity                  ┃ Details  ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 2025-11-10 14:32:15 │ ❌ Heal Failed│ sensor.outdoor_temp     │ timeout  │
│ 2025-11-10 10:15:43 │ ⚠️  Unavailable│ sensor.outdoor_temp     │          │
│ 2025-11-09 22:05:12 │ ❌ Heal Failed│ sensor.wind_speed       │          │
└─────────────────────┴──────────────┴─────────────────────────┴──────────┘

Total failures: 3
```

## ✅ Acceptance Criteria

- [ ] `haboss patterns reliability` command works
- [ ] `haboss patterns failures` shows timeline
- [ ] `haboss patterns recommendations` provides guidance
- [ ] Rich table formatting implemented
- [ ] Color coding for severity (red/yellow/green)
- [ ] Handles empty data gracefully
- [ ] Error messages for missing parameters
- [ ] Database opened and closed properly
- [ ] Tests for CLI commands
- [ ] Help text for all commands

## 🧪 Testing

Create `tests/cli/test_patterns_commands.py`:

```python
def test_reliability_command():
    """Test patterns reliability command."""
    # Use CliRunner to invoke command
    # Mock database with test data
    # Verify table output

def test_reliability_no_data():
    """Test reliability with no data."""
    # Empty database
    # Should show friendly message

def test_failures_timeline():
    """Test patterns failures command."""
    # Add failure events to test database
    # Invoke command
    # Verify timeline displayed

def test_recommendations():
    """Test patterns recommendations command."""
    # Mock analyzer.get_recommendations()
    # Verify recommendations displayed

def test_missing_integration_parameter():
    """Test error when integration parameter missing."""
    # Call failures without --integration
    # Should show error message
```

## 📝 Implementation Notes

1. **Database Management**: Always use try/finally to ensure database is closed

2. **Empty Data**: Show helpful message when no patterns exist yet

3. **Color Scheme**:
   - Green: ≥95% success rate
   - Yellow: 80-95%
   - Red: <80%

4. **Truncation**: Limit details column to prevent overflow

5. **Help Text**: Provide examples in help text

## 🔗 Dependencies

- **Requires**: #28 (reliability analyzer)
- **Nice-to-have**: Pattern data from running service

---

**Labels**: `phase-2`, `cli`, `reporting`, `P1`
