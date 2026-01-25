# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **"All Instances" Aggregate Mode**: API endpoints now support aggregating data across all configured Home Assistant instances
  - New default behavior: `instance_id` defaults to `"all"` when omitted
  - All major endpoints support aggregate queries (`/status`, `/health`, `/entities`, `/healing/history`, `/patterns/*`, `/automations`)
  - Response models include `instance_id` field in aggregate mode to identify source instance
  - Dashboard defaults to "All Instances" view with globe icon (🌐)
  - Instance selector shows "All Instances" as first option with visual separator
- New helper functions in `ha_boss/api/utils/instance_helpers.py`:
  - `get_instance_ids()`: Returns list of instance IDs to query based on parameter
  - `is_aggregate_mode()`: Checks if querying all instances

### Changed

- **Default instance_id changed from `"default"` to `"all"`**: API calls without `instance_id` parameter now return aggregated data from all instances instead of just the default instance
- Dashboard instance selector now defaults to "All Instances" instead of the first configured instance
- Health endpoint component names are prefixed with `{instance_id}:` in aggregate mode
- Updated response models to include optional `instance_id` field: `EntityStateResponse`, `HealingActionResponse`, `FailureEventResponse`, `AutomationSummary`

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
