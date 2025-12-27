# CLI Commands Reference

Complete reference guide for the HA Boss command-line interface (CLI).

## Table of Contents

- [Overview](#overview)
- [Installation & Setup](#installation--setup)
- [Main Commands](#main-commands)
  - [init](#init)
  - [start](#start)
  - [status](#status)
  - [heal](#heal)
- [Configuration Commands](#configuration-commands)
  - [config validate](#config-validate)
- [Database Commands](#database-commands)
  - [db cleanup](#db-cleanup)
- [Pattern Analysis Commands](#pattern-analysis-commands)
  - [patterns reliability](#patterns-reliability)
  - [patterns failures](#patterns-failures)
  - [patterns weekly-summary](#patterns-weekly-summary)
  - [patterns recommendations](#patterns-recommendations)
- [Automation Commands](#automation-commands)
  - [automation analyze](#automation-analyze)
  - [automation generate](#automation-generate)
- [Testing Commands](#testing-commands)
  - [uat](#uat)
- [Common Workflows](#common-workflows)
- [Error Handling](#error-handling)

## Overview

The HA Boss CLI provides a comprehensive set of commands for managing your Home Assistant monitoring and auto-healing service. All commands are accessed through the `haboss` command.

**Key Features:**
- Rich terminal UI with colored output and progress indicators
- Async operations for fast performance
- Built-in error handling with helpful hints
- Support for both interactive and automated workflows
- Integration with Home Assistant API

**Command Structure:**
```bash
haboss [COMMAND] [SUBCOMMAND] [OPTIONS] [ARGUMENTS]
```

## Installation & Setup

After installing HA Boss, the `haboss` command is available in your environment:

```bash
# Verify installation
haboss --help

# View version and available commands
haboss --version
```

## Main Commands

### init

Initialize configuration and database for HA Boss.

**Description:**

Creates the necessary directory structure, configuration files, and database schema to get started with HA Boss.

**Creates:**
- `config/config.yaml` - Main configuration file from template
- `config/.env` - Environment variables template
- `data/` - Directory for database and runtime data
- `data/ha_boss.db` - SQLite database with initialized schema

**Syntax:**
```bash
haboss init [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config-dir` | `-c` | `config` | Directory for configuration files |
| `--data-dir` | `-d` | `data` | Directory for database and runtime data |
| `--force` | `-f` | `false` | Overwrite existing configuration |

**Examples:**
```bash
# Standard initialization
haboss init

# Custom directories
haboss init --config-dir /etc/haboss --data-dir /var/lib/haboss

# Force overwrite existing config
haboss init --force
```

**Next Steps After Init:**
1. Edit `config/.env` and add your Home Assistant URL and token
2. Review and customize `config/config.yaml`
3. Run `haboss config validate` to check configuration
4. Run `haboss start` to begin monitoring

---

### start

Start the HA Boss monitoring service.

**Description:**

Launches the main monitoring loop that connects to Home Assistant, monitors entity health in real-time, automatically heals failed integrations, and sends notifications when manual intervention is needed.

**Syntax:**
```bash
haboss start [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config` | `-c` | Auto-detect | Path to configuration file |
| `--foreground` | `-f` | `false` | Run in foreground (don't daemonize) |

**Examples:**
```bash
# Start with default configuration
haboss start --foreground

# Start with custom config
haboss start --config /etc/haboss/config.yaml --foreground

# For Docker deployments (always use foreground)
haboss start --foreground
```

**Notes:**
- Background/daemon mode is not yet implemented - use `--foreground` for now
- Press `Ctrl+C` to stop the service
- For Docker deployments, always use `--foreground` mode
- Service will auto-reconnect if WebSocket connection drops

---

### status

Show service and entity health status.

**Description:**

Displays an overview of the HA Boss service status, Home Assistant connection, and database statistics.

**Shows:**
- Configuration summary (HA URL, mode, healing settings)
- Home Assistant connection status and version
- Database statistics (entities tracked, health events, healing attempts)
- Success rates for healing operations
- Circuit breaker status

**Syntax:**
```bash
haboss status [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config` | `-c` | Auto-detect | Path to configuration file |
| `--verbose` | `-v` | `false` | Show detailed status information |

**Examples:**
```bash
# Check basic status
haboss status

# Detailed status with custom config
haboss status --config /etc/haboss/config.yaml --verbose
```

**Output Example:**
```
Configuration
┌────────────────────┬────────────────────────────────┐
│ HA URL             │ http://homeassistant.local:8123│
│ Mode               │ production                      │
│ Healing Enabled    │ ✓                              │
│ Database           │ data/ha_boss.db                │
└────────────────────┴────────────────────────────────┘

Checking Home Assistant connection...
✓ Connected to Home Assistant (version 2024.12.0)
  Location: Home

Database Statistics:
┌───────────────────┬──────┐
│ Tracked Entities  │   42 │
│ Health Events     │  127 │
│ Healing Attempts  │   18 │
│ Successful Healings│   15 │
│ Success Rate      │ 83.3%│
└───────────────────┴──────┘
```

---

### heal

Manually trigger healing for a specific entity.

**Description:**

Attempts to heal a specific entity by looking up its integration and reloading it. Useful for troubleshooting or manually fixing issues.

**Process:**
1. Looks up the integration for the specified entity
2. Attempts to reload the integration
3. Reports the result

**Syntax:**
```bash
haboss heal ENTITY_ID [OPTIONS]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `ENTITY_ID` | Yes | Entity ID to heal (e.g., `sensor.temperature`) |

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config` | `-c` | Auto-detect | Path to configuration file |
| `--dry-run` | | `false` | Simulate healing without actually executing |

**Examples:**
```bash
# Heal a specific sensor
haboss heal sensor.temperature

# Heal a light with dry-run
haboss heal light.living_room --dry-run

# Heal with custom config
haboss heal sensor.outdoor_temp --config /etc/haboss/config.yaml
```

**Output Example:**
```
Manual Healing
sensor.temperature

Connecting to Home Assistant...
Discovering integrations...
Healing sensor.temperature...

✓ Successfully healed sensor.temperature
Reloaded integration: Met.no
```

---

## Configuration Commands

### config validate

Validate configuration file and test Home Assistant connection.

**Description:**

Checks your configuration file for syntax errors, validates all settings, resolves environment variables, and tests the connection to Home Assistant.

**Checks:**
- YAML syntax validity
- Required fields are present
- Value types are correct
- Environment variables resolve properly
- Home Assistant connection works
- Authentication is successful

**Syntax:**
```bash
haboss config validate [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Examples:**
```bash
# Validate default configuration
haboss config validate

# Validate specific config file
haboss config validate --config /etc/haboss/config.yaml
```

**Output Example:**
```
Configuration Validation
Checking configuration file and connection

Loading configuration...
✓ Configuration file valid
  Loaded from: config/config.yaml

Configuration Summary
┌──────────────────────┬────────────────────────────────┐
│ HA URL               │ http://homeassistant.local:8123│
│ Mode                 │ production                      │
│ Monitoring Grace Period│ 300s                         │
│ Healing Enabled      │ Yes                            │
│ Max Heal Attempts    │ 3                              │
│ Database Path        │ data/ha_boss.db                │
│ Log Level            │ INFO                           │
└──────────────────────┴────────────────────────────────┘

Testing Home Assistant connection...
✓ Connected to Home Assistant (version 2024.12.0)
  Location: Home

✓ Configuration is valid!
```

**Common Errors:**
- **Configuration error**: YAML syntax issue or missing required field
- **Authentication failed**: Invalid or missing HA_TOKEN
- **Connection failed**: Home Assistant unreachable or wrong URL

---

## Database Commands

### db cleanup

Clean up old database records to manage size and performance.

**Description:**

Removes old records from the database based on age. Helps keep database size manageable and queries fast.

**Removes:**
- Health events older than specified days
- Healing actions older than specified days
- Optionally, entities that no longer exist

**Syntax:**
```bash
haboss db cleanup [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--days` | `-d` | `30` | Delete records older than this many days |
| `--config` | `-c` | Auto-detect | Path to configuration file |
| `--dry-run` | | `false` | Show what would be deleted without deleting |

**Examples:**
```bash
# Clean up records older than 30 days
haboss db cleanup --days 30

# Preview what would be deleted (7 days)
haboss db cleanup --days 7 --dry-run

# Clean up 90 days with custom config
haboss db cleanup --days 90 --config /etc/haboss/config.yaml
```

**Interactive Confirmation:**

The command will show you what will be deleted and ask for confirmation:

```
Database Cleanup
Removing records older than 30 days

┌─────────────────┬───────┐
│ Health Events   │   142 │
│ Healing Actions │    23 │
└─────────────────┴───────┘

Delete 165 records? [y/N]: y

Deleting records...
✓ Deleted 165 records
```

**Safety:**
- Requires confirmation before deletion (unless scripted)
- Use `--dry-run` to preview first
- Database is backed up automatically before large deletions
- Entities table is preserved (only event history is removed)

---

## Pattern Analysis Commands

### patterns reliability

Display integration reliability reports with success rates and health metrics.

**Description:**

Analyzes integration performance over a specified period, showing success rates, failure counts, and reliability scores.

**Shows:**
- Success rate for healing attempts
- Total healing successes and failures
- Unavailable event counts
- Reliability score (Excellent/Good/Fair/Poor)
- Recommendations for problematic integrations

**Syntax:**
```bash
haboss patterns reliability [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--integration` | `-i` | All | Show reliability for specific integration |
| `--days` | `-d` | `7` | Number of days to analyze |
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Examples:**
```bash
# Show reliability for all integrations (last 7 days)
haboss patterns reliability

# Show reliability for specific integration
haboss patterns reliability --integration hue

# Analyze last 30 days
haboss patterns reliability --days 30

# Specific integration, longer period
haboss patterns reliability --integration zwave --days 60
```

**Output Example:**
```
Integration Reliability Report
Period: Last 7 days

Integration Reliability (Last 7 days)
┌─────────────┬──────────────┬──────────┬─────────┬────────────┬─────────────┐
│ Integration │ Success Rate │ Rating   │ Heals ✓ │ Failures ✗ │ Unavailable │
├─────────────┼──────────────┼──────────┼─────────┼────────────┼─────────────┤
│ hue         │ 100.0%       │ Excellent│    12   │      0     │      2      │
│ zwave       │  85.7%       │ Good     │     6   │      1     │      8      │
│ mqtt        │  66.7%       │ Fair     │     4   │      2     │     15      │
│ esphome     │  50.0%       │ Poor     │     2   │      2     │     22      │
└─────────────┴──────────────┴──────────┴─────────┴────────────┴─────────────┘

⚠️  Recommendations:

• mqtt: Fair reliability (66.7%) - Check integration configuration
• esphome: Poor reliability (50.0%) - Check integration configuration
```

**Reliability Scores:**
- **Excellent**: 95%+ success rate - integration is very stable
- **Good**: 80-94% success rate - generally reliable with minor issues
- **Fair**: 60-79% success rate - some instability, needs attention
- **Poor**: <60% success rate - significant reliability issues

---

### patterns failures

Show timeline of failure events for troubleshooting.

**Description:**

Displays a chronological list of healing failures and entity unavailable events, useful for identifying patterns and troubleshooting recurring issues.

**Shows:**
- Healing failures
- Entity unavailable events
- Integration-specific issues
- Timestamps for correlation

**Syntax:**
```bash
haboss patterns failures [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--integration` | `-i` | All | Filter by integration domain |
| `--days` | `-d` | `7` | Number of days to look back |
| `--limit` | `-l` | `50` | Maximum number of events to show |
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Examples:**
```bash
# Show recent failures (last 7 days, limit 50)
haboss patterns failures

# Show failures for specific integration
haboss patterns failures --integration zwave

# Show more failures from longer period
haboss patterns failures --days 30 --limit 100

# Combined filters
haboss patterns failures --integration mqtt --days 14 --limit 25
```

**Output Example:**
```
Failure Timeline
Period: Last 7 days

Failure Events (Last 7 days, showing 12)
┌──────────────┬─────────────┬──────────────┬───────────────────────────┐
│ Timestamp    │ Integration │ Event Type   │ Entity                    │
├──────────────┼─────────────┼──────────────┼───────────────────────────┤
│ 12-18 14:23  │ zwave       │ Unavailable  │ sensor.bedroom_motion     │
│ 12-18 09:15  │ mqtt        │ Heal Failed  │ sensor.temperature_garage │
│ 12-17 22:07  │ zwave       │ Unavailable  │ light.hallway             │
│ 12-17 18:30  │ esphome     │ Heal Failed  │ sensor.power_monitor      │
│ 12-16 11:42  │ mqtt        │ Unavailable  │ binary_sensor.door        │
└──────────────┴─────────────┴──────────────┴───────────────────────────┘

Summary: 2 heal failures, 10 unavailable events
```

**Use Cases:**
- Identify integrations with recurring issues
- Correlate failures with external events (power outages, network issues)
- Debug specific entity problems
- Generate reports for troubleshooting

---

### patterns weekly-summary

Generate and display weekly summary report.

**Description:**

Analyzes the past week of integration health data and generates a comprehensive summary with AI-powered insights and recommendations.

**Includes:**
- Overall success rate and healing statistics
- Top performing integrations
- Integrations needing attention
- Trends compared to previous week
- AI-powered analysis and recommendations (if enabled)

**Syntax:**
```bash
haboss patterns weekly-summary [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--config` | `-c` | Auto-detect | Path to configuration file |
| `--no-notify` | | `false` | Skip sending notification to Home Assistant |
| `--no-ai` | | `false` | Skip AI-generated analysis |

**Examples:**
```bash
# Generate full weekly summary with AI
haboss patterns weekly-summary

# Generate summary without HA notification
haboss patterns weekly-summary --no-notify

# Generate basic summary without AI analysis
haboss patterns weekly-summary --no-ai

# Just the summary, no AI or notifications
haboss patterns weekly-summary --no-notify --no-ai
```

**Output Example:**
```
Weekly Summary Report
AI-Powered Health Analysis

Initializing AI...
Generating weekly summary...

╭─────────────────────── Weekly Summary ───────────────────────╮
│                                                               │
│ 📊 HA Boss Weekly Summary - December 12-18, 2024            │
│                                                               │
│ Overall Health: Good                                          │
│                                                               │
│ 🎯 Top Performers:                                           │
│   • hue: 100% success (12 heals)                             │
│   • tasmota: 95% success (20 heals)                          │
│                                                               │
│ ⚠️  Needs Attention:                                         │
│   • mqtt: 67% success (increased failures this week)         │
│   • esphome: 50% success (network connectivity issues)       │
│                                                               │
│ 🤖 AI Recommendations:                                       │
│   The MQTT integration shows degraded performance compared   │
│   to last week. Consider checking broker stability and       │
│   network connectivity. ESPHome devices may benefit from     │
│   firmware updates.                                          │
│                                                               │
╰───────────────────────────────────────────────────────────────╯

Statistics
┌──────────────────────┬────────┐
│ Integrations Monitored│    8   │
│ Healing Attempts     │   45   │
│ Successful Healings  │   38   │
│ Failed Healings      │    7   │
│ Success Rate         │ 84.4%  │
│ vs Last Week         │ +2.1%  │
└──────────────────────┴────────┘

✓ Notification sent to Home Assistant
✓ Weekly summary generated successfully
```

**AI Analysis:**

When AI is enabled (default), the summary includes:
- Pattern identification (degrading vs improving trends)
- Root cause suggestions
- Specific actionable recommendations
- Comparative analysis vs previous week

**Notifications:**

By default, sends a persistent notification to Home Assistant with the summary. Use `--no-notify` to skip this.

---

### patterns recommendations

Get actionable recommendations for a specific integration.

**Description:**

Analyzes a specific integration's performance and provides targeted recommendations to improve reliability.

**Provides:**
- Health assessment for the integration
- Specific issues identified
- Suggested actions to improve reliability
- Configuration recommendations

**Syntax:**
```bash
haboss patterns recommendations INTEGRATION [OPTIONS]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `INTEGRATION` | Yes | Integration domain (e.g., `hue`, `zwave`, `mqtt`) |

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--days` | `-d` | `7` | Number of days to analyze |
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Examples:**
```bash
# Get recommendations for Hue integration
haboss patterns recommendations hue

# Analyze Z-Wave over 30 days
haboss patterns recommendations zwave --days 30

# Recommendations for MQTT with custom config
haboss patterns recommendations mqtt --config /etc/haboss/config.yaml --days 14
```

**Output Example:**
```
Recommendations
Integration: mqtt
Period: Last 7 days

Recommendations for mqtt:

  • ⚠️ High failure rate (33%) - check broker connectivity and stability
  • Check MQTT broker logs for connection errors
  • Verify network stability between HA and MQTT broker
  • Consider increasing connection timeout in integration settings
  • Review QoS settings for critical sensors
```

**Recommendation Types:**

Recommendations are color-coded by severity:
- **Red (CRITICAL)**: Immediate action required
- **Yellow (WARNING)**: Should be addressed soon
- **Green (✓)**: Informational or confirmation of good state
- **Cyan (Default)**: General suggestions

---

## Automation Commands

### automation analyze

Analyze Home Assistant automations for optimization opportunities.

**Description:**

Examines your Home Assistant automations and provides suggestions for improvements, including AI-powered recommendations.

**Provides:**
- Structure overview (triggers, conditions, actions)
- Static analysis for common anti-patterns
- AI-powered optimization suggestions (if enabled)
- Actionable recommendations

**Syntax:**
```bash
haboss automation analyze [AUTOMATION_ID] [OPTIONS]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `AUTOMATION_ID` | Optional | Automation ID (e.g., `bedroom_lights` or `automation.bedroom_lights`) |

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--all` | `-a` | `false` | Analyze all automations |
| `--no-ai` | | `false` | Skip AI-powered analysis |
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Examples:**
```bash
# Analyze specific automation
haboss automation analyze bedroom_lights

# Analyze with full entity ID
haboss automation analyze automation.morning_routine

# Analyze all automations
haboss automation analyze --all

# Analyze without AI (faster)
haboss automation analyze bedroom_lights --no-ai

# Analyze all without AI
haboss automation analyze --all --no-ai
```

**Output Example (Single Automation):**
```
Automation Analyzer
Optimization Suggestions

Analyzing bedroom_lights...

Automation: Bedroom Light Automation
Entity ID: automation.bedroom_lights

State: on | Triggers: 2 | Conditions: 1 | Actions: 3

Analysis:
⚠ Multiple triggers with similar conditions
   Consider consolidating to reduce complexity

✓ Well-structured action sequence
   Actions are properly organized and readable

AI Suggestions:
╭────────────────────────────────────────────────────────────╮
│ This automation could be simplified by combining the motion│
│ and time-based triggers into a single trigger with a       │
│ condition. This would reduce redundancy and make the       │
│ automation easier to maintain. Also consider adding a      │
│ 5-minute cooldown to prevent rapid on/off cycling.        │
╰────────────────────────────────────────────────────────────╯
```

**Output Example (All Automations):**
```
Automation Analyzer
Optimization Suggestions

Analyzing automations...

Found 8 automations

Automation Analysis Summary
┌───────────────────────────┬───────┬─────┬────────┬────────┐
│ Automation                │ State │ T/C/A│ Issues │ Status │
├───────────────────────────┼───────┼─────┼────────┼────────┤
│ Morning Routine           │  on   │ 1/2/4│   0    │ Good   │
│ Bedroom Lights            │  on   │ 2/1/3│   2    │ Review │
│ Security Alert            │  on   │ 3/0/2│   1    │ Review │
│ Garage Door Reminder      │  on   │ 1/1/1│   3    │ Needs Fix│
└───────────────────────────┴───────┴─────┴────────┴────────┘

Summary: 5 good, 2 need review, 1 needs fix

Automations Needing Attention (3):

────────────────────────────────────────────────────────────

Bedroom Lights (automation.bedroom_lights)
State: on | Triggers: 2 | Conditions: 1 | Actions: 3
⚠ Multiple triggers with similar conditions
⚠ Missing error handling in service calls

[... details for other automations with issues ...]
```

**Analysis Categories:**

- **Errors (Red ✗)**: Serious issues that may cause automation failures
- **Warnings (Yellow ⚠)**: Potential problems or anti-patterns
- **Info (Green ✓)**: Positive findings or confirmations

**Common Suggestions:**

- Consolidate redundant triggers
- Add error handling for service calls
- Simplify complex condition logic
- Add timeout safeguards
- Improve automation naming
- Document complex logic

---

### automation generate

Generate Home Assistant automation from natural language.

**Description:**

Uses Claude API to translate your natural language description into a valid Home Assistant automation YAML. By default, generates a preview for review. Use `--create` to create the automation directly in Home Assistant. Requires Claude API to be configured.

**Syntax:**
```bash
haboss automation generate PROMPT [OPTIONS]
```

**Arguments:**
| Argument | Required | Description |
|----------|----------|-------------|
| `PROMPT` | Yes | Natural language description of the automation |

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--mode` | `-m` | `single` | Automation mode (single/restart/queued/parallel) |
| `--create` | | `false` | Create automation in Home Assistant (default: preview only) |
| `--config` | `-c` | Auto-detect | Path to configuration file |

**Automation Modes:**
- **single**: Only one instance runs at a time (default)
- **restart**: Restart automation if triggered while running
- **queued**: Queue triggers and run sequentially
- **parallel**: Multiple instances can run simultaneously

**Workflow:**
1. **Preview First (Recommended)**: Run without `--create` to review the generated YAML
2. **Review & Validate**: Check the automation logic, entities, and conditions
3. **Create**: Run again with `--create` flag to create in Home Assistant
4. **Test**: Test the automation in Home Assistant UI

**Examples:**
```bash
# Preview automation (default - recommended first step)
haboss automation generate "Turn on lights when motion detected after sunset"

# Create automation directly in Home Assistant
haboss automation generate "Turn on lights when motion detected after sunset" --create

# Preview with specific mode
haboss automation generate "Send notification if garage door open > 10 minutes" --mode restart

# Create complex automation
haboss automation generate "When I arrive home between 5-8pm, turn on living room lights to 50% and play welcome announcement" --create

# Typical workflow: preview then create
haboss automation generate "Turn off all lights at 11pm"  # Review output
haboss automation generate "Turn off all lights at 11pm" --create  # Create if looks good
```

**Output Example:**
```
Automation Generator
AI-Powered Automation Creation

Initializing Claude API...
Generating automation with Claude API...

╭─────────────────────── Generated Automation ───────────────────╮
│                                                                 │
│ alias: Motion Activated Evening Lights                         │
│ description: Turn on lights when motion detected after sunset  │
│ mode: single                                                    │
│                                                                 │
│ trigger:                                                        │
│   - platform: state                                            │
│     entity_id: binary_sensor.motion_detector                   │
│     to: 'on'                                                   │
│                                                                 │
│ condition:                                                      │
│   - condition: sun                                             │
│     after: sunset                                              │
│     after_offset: "-00:30:00"                                  │
│                                                                 │
│ action:                                                         │
│   - service: light.turn_on                                     │
│     target:                                                     │
│       entity_id: light.living_room                             │
│     data:                                                       │
│       brightness_pct: 75                                       │
│       transition: 2                                            │
│                                                                 │
╰─────────────────────────────────────────────────────────────────╯

(Preview only - use --create to create in Home Assistant)

To create this automation:
  Run again with: --create

Or create manually:
1. Go to Home Assistant → Configuration → Automations
2. Click '+ Add Automation' → '...' menu → 'Edit in YAML'
3. Copy and paste the YAML above
4. Save the automation
```

**Output Example (with --create):**
```
Creating automation in Home Assistant...

✓ Automation created successfully!
  ID: 1734670542123
  Alias: Motion Activated Evening Lights

View in Home Assistant: Configuration → Automations → Motion Activated Evening Lights
```

**Requirements:**

- Claude API must be configured in `config.yaml`:
  ```yaml
  intelligence:
    claude_enabled: true
    claude_api_key: your_api_key_here
  ```

**Best Practices for Prompts:**

- Be specific about triggers (motion, time, state change, etc.)
- Specify conditions clearly (after sunset, when home, etc.)
- Detail the desired actions
- Mention any delays or transitions
- Include safety conditions if needed

**Examples of Good Prompts:**

```bash
# Specific and detailed
"When bedroom motion sensor detects motion between 6am-8am on weekdays, gradually turn on bedroom lights to 30% over 60 seconds"

# With safety conditions
"If washing machine has been running for more than 3 hours, send critical notification and turn on alert light"

# Time-based with conditions
"Every night at 10:30pm, if anyone is home, lock all doors and turn off all lights except bedroom lamp"

# Complex multi-action
"When front door unlocks and it's after sunset, turn on entry lights, unlock inner door, and announce 'Welcome home' on speakers"
```

---

## Testing Commands

### uat

Run User Acceptance Testing (UAT) to validate CLI and API against documentation.

**Description:**

Executes comprehensive automated tests that validate HA Boss functionality against the official documentation. The UAT agent parses README, SETUP_GUIDE, and CLI source code to generate and execute test cases for CLI commands and API endpoints. Failed tests automatically create GitHub issues for tracking.

**Capabilities:**
- Automatically generates test cases from documentation
- Tests CLI commands for expected behavior
- Validates API endpoints against OpenAPI spec
- Creates GitHub issues for all failures
- Generates comprehensive test reports (console + JSON)
- Safe execution (only runs non-destructive tests)

**Syntax:**
```bash
haboss uat [OPTIONS]
```

**Options:**
| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--cli-only` | | `false` | Test CLI commands only |
| `--api-only` | | `false` | Test API endpoints only |
| `--full` | | `true` | Run complete test suite (CLI + API) |
| `--dry-run` | | `false` | Generate test plan without execution |

**Examples:**
```bash
# Run full test suite (CLI + API)
haboss uat

# Test CLI commands only
haboss uat --cli-only

# Test API endpoints only
haboss uat --api-only

# Preview test plan without executing
haboss uat --dry-run

# Dry run for API tests only
haboss uat --api-only --dry-run
```

**Output Example:**
```
User Acceptance Testing
Validating CLI and API against documentation

Generating test cases from documentation...
✓ Parsed README.md - found 5 CLI examples
✓ Parsed SETUP_GUIDE.md - found 8 setup steps
✓ Parsed CLI source - found 12 commands

Test Plan: 25 test cases
- CLI: 15 tests
- API: 10 tests

Executing tests...

CLI Tests (15/15)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

API Tests (10/10)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

Results Summary
┌──────────────┬───────┐
│ Total Tests  │   25  │
│ Passed       │   23  │
│ Failed       │    2  │
│ Skipped      │    0  │
│ Pass Rate    │ 92.0% │
└──────────────┴───────┘

Failed Tests (2):
• test_cli_heal_invalid_entity - Heal command error handling
  Issue #142 created: https://github.com/user/repo/issues/142

• test_api_automation_generate_no_claude - API returns 503 when Claude unavailable
  Issue #143 created: https://github.com/user/repo/issues/143

✓ Test report saved: UAT_TEST_REPORT.md
✓ GitHub issues created for all failures
```

**Test Report:**

UAT generates a detailed markdown report (`UAT_TEST_REPORT.md`) containing:
- Summary statistics and pass rates
- Detailed failure analysis with stack traces
- GitHub issue links for all failures
- Recommendations for fixes
- Full test execution log

**GitHub Integration:**

Failed tests automatically create GitHub issues with:
- Descriptive title (e.g., "UAT Failure: test_cli_status")
- Full error message and stack trace
- Test case details and expected behavior
- Labels: `automated`, `ci-failure`, `claude-task`
- Assignment to appropriate milestone

**Best Practices:**

- Run UAT before major releases to catch regressions
- Use `--dry-run` to preview test coverage without execution
- Use `--cli-only` for quick validation during CLI development
- Use `--api-only` for quick validation during API development
- Review generated issues and fix high-priority failures first
- Re-run UAT after fixes to verify resolution

**Requirements:**

- HA Boss installed and configured
- API server running (for API tests)
- GitHub PAT with `repo` scope (for issue creation)
- Network access to Home Assistant instance

**Notes:**

- Only executes safe, non-destructive tests
- Skips tests that would modify HA configuration
- Requires API server to be running for API tests
- Test execution time varies (typically 2-5 minutes)
- GitHub rate limits apply to issue creation

---

## Common Workflows

### Initial Setup

Complete workflow for setting up HA Boss for the first time:

```bash
# 1. Initialize configuration and database
haboss init

# 2. Edit .env file with your HA credentials
nano config/.env
# Add: HA_URL=http://homeassistant.local:8123
# Add: HA_TOKEN=your_long_lived_access_token

# 3. Review and customize configuration
nano config/config.yaml

# 4. Validate configuration
haboss config validate

# 5. Start monitoring
haboss start --foreground
```

### Weekly Maintenance

Recommended weekly maintenance tasks:

```bash
# 1. Check overall status
haboss status

# 2. Review reliability reports
haboss patterns reliability --days 7

# 3. Generate weekly summary
haboss patterns weekly-summary

# 4. Check for failures
haboss patterns failures --days 7

# 5. Clean up old data (optional, monthly)
haboss db cleanup --days 30 --dry-run
haboss db cleanup --days 30  # After reviewing
```

### Troubleshooting Integration Issues

Steps to diagnose and fix integration problems:

```bash
# 1. Check reliability for specific integration
haboss patterns reliability --integration zwave

# 2. View failure timeline
haboss patterns failures --integration zwave --days 30

# 3. Get specific recommendations
haboss patterns recommendations zwave --days 30

# 4. Try manual healing
haboss heal sensor.problematic_sensor

# 5. Check if issue resolved
haboss status --verbose
```

### Automation Optimization

Workflow for improving Home Assistant automations:

```bash
# 1. Analyze all automations
haboss automation analyze --all

# 2. Deep dive on specific automation
haboss automation analyze bedroom_lights

# 3. Generate improved version (if needed)
haboss automation generate "Improved version of bedroom lights: ..."  # Preview first
haboss automation generate "Improved version of bedroom lights: ..." --create  # Then create

# 4. Re-analyze after changes
haboss automation analyze bedroom_lights --no-ai  # Quick check
```

### CI/CD Integration

Useful for automated workflows and monitoring:

```bash
# Validation in CI pipeline
haboss config validate --config /path/to/config.yaml || exit 1

# Generate weekly reports (scheduled job)
haboss patterns weekly-summary --no-notify > weekly_report.txt

# Export reliability metrics
haboss patterns reliability --days 7 > reliability_metrics.txt

# Check for critical failures
haboss patterns failures --days 1 --limit 10
```

---

## Error Handling

The CLI includes comprehensive error handling with helpful hints:

### Configuration Errors

**Error:**
```
Error: Configuration file not found
```

**Solution:**
```
Hint: Run 'haboss init' to create a configuration file
```

### Authentication Errors

**Error:**
```
Error: 401 Unauthorized - Authentication failed
```

**Solution:**
```
Hint: Check your HA_TOKEN in .env or config.yaml
```

### Connection Errors

**Error:**
```
Error: Failed to connect to Home Assistant
```

**Solution:**
```
Hint: Check that Home Assistant is running and accessible
```

### Common Issues

**Problem**: Command not found
```bash
# Ensure HA Boss is installed
pip install -e .

# Or reinstall
pip install --force-reinstall ha-boss
```

**Problem**: Permission denied on database
```bash
# Check file permissions
ls -la data/ha_boss.db

# Fix permissions
chmod 644 data/ha_boss.db
```

**Problem**: Configuration validation fails
```bash
# Check YAML syntax
haboss config validate

# Review error message and fix indicated issue
# Common: missing required field, wrong type, invalid URL
```

**Problem**: Claude API not working
```bash
# Verify API key is set
grep claude_api_key config/config.yaml

# Test with a simple command (preview mode - default)
haboss automation generate "turn on lights"

# Check API key has correct permissions
```

---

## Exit Codes

The CLI uses standard exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Configuration error |
| `3` | Connection error |
| `4` | Authentication error |

Useful for scripting:

```bash
#!/bin/bash
haboss config validate
if [ $? -eq 0 ]; then
    echo "Configuration valid"
    haboss start --foreground
else
    echo "Configuration invalid, please fix"
    exit 1
fi
```

---

## Environment Variables

The CLI respects these environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `CONFIG_PATH` | Override default config path | `/etc/haboss/config.yaml` |
| `HA_URL` | Home Assistant URL | `http://homeassistant.local:8123` |
| `HA_TOKEN` | Long-lived access token | `eyJ0eXAiOiJKV1...` |
| `HABOSS_LOG_LEVEL` | Override log level | `DEBUG` |

**Usage:**
```bash
# Temporary override
HA_URL=http://192.168.1.100:8123 haboss status

# Persistent (add to .env)
export CONFIG_PATH=/etc/haboss/config.yaml
haboss start --foreground
```

---

## Tips and Best Practices

### Performance

- Use `--no-ai` flag for faster analysis when AI insights aren't needed
- Limit query periods with `--days` to reduce database load
- Use `--dry-run` before destructive operations
- Run `db cleanup` monthly to maintain performance

### Automation

- Schedule `weekly-summary` with cron for automatic reports
- Use `--no-notify` in scripts to prevent spam
- Combine commands with shell scripting for complex workflows
- Export reliability data for external monitoring systems

### Development

- Use `--foreground` during development for better visibility
- Test with `--dry-run` before production changes
- Validate config changes before restarting service
- Monitor logs while running commands for debugging

### Security

- Protect config files with appropriate permissions (`chmod 600`)
- Never commit `.env` files with real tokens
- Rotate HA tokens periodically
- Use separate tokens for different environments (dev/prod)

---

**Need Help?**

- View command help: `haboss [command] --help`
- Check logs: `tail -f logs/ha_boss.log`
- Report issues: https://github.com/jasonthagerty/ha_boss/issues
- Documentation: https://github.com/jasonthagerty/ha_boss/wiki
