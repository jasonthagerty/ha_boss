# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### BREAKING CHANGES

#### Automation Generation Feature Removed

**Removed**: Natural language automation generation via `haboss automation generate`

**Reason**: Home Assistant is developing native natural language automation generation.
To avoid duplication and align with HA Boss's core mission, we've removed this feature
and are focusing on usage-based optimization recommendations instead.

**Migration**:
- For automation generation: Wait for Home Assistant's native feature (coming soon)
- For automation optimization: Use `haboss automation analyze` with enhanced recommendations

**What's Next**: The `haboss automation analyze` command will be enhanced in upcoming releases to provide:
- Optimization recommendations based on real execution patterns from monitoring data
- Service call performance metrics and suggestions
- Entity reliability correlation and warnings
- Timing analysis and conflict detection

See `docs/AUTOMATION_REFACTORING_PLAN.md` for complete implementation details.

### Removed

- `haboss automation generate` CLI command
- `/api/automations/generate` API endpoint
- `/api/automations/create` API endpoint
- `AutomationGenerator` class and related code (387 lines)
- Generator-related API models: `AutomationGenerateRequest`, `AutomationGenerateResponse`, `AutomationCreateRequest`, `AutomationCreateResponse`

### Changed

- README.md updated to reflect new focus on usage-based optimization
- Phase 3 description now emphasizes automation analysis and optimization
