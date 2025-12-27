---
description: Run User Acceptance Testing - validates CLI and API against documentation
allowed-tools: [Bash(.venv/bin/python*), Bash(pytest*), Read, Glob, Grep]
argument-hint: "[--cli-only | --api-only | --full] [--dry-run]"
---

Run User Acceptance Testing (UAT) for HA Boss:

!`.venv/bin/python -m ha_boss.testing.uat_agent $ARGUMENTS`

The UAT agent will:
1. Parse project documentation (README, SETUP_GUIDE, CLI source code)
2. Generate test cases for CLI commands and API endpoints
3. Execute non-destructive tests safely
4. Create GitHub issues for all failures
5. Generate comprehensive test report (console + JSON)

Analyze the results and report:
1. Number of tests passed/failed/skipped
2. Pass rate percentage
3. Any critical failures requiring immediate attention
4. GitHub issues created for failures
5. Recommendations for improvements

Usage options:
- `/uat` - Run full test suite (CLI + API)
- `/uat --cli-only` - Test CLI commands only
- `/uat --api-only` - Test API endpoints only
- `/uat --dry-run` - Generate test plan without execution
