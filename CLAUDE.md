# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What HA Boss is (and is not)

HA Boss is a small, **headless monitor-and-notify watchdog** for Home Assistant.
It connects over WebSocket, scopes itself (via auto-discovery) to the entities
referenced in your automations/scenes/scripts, and **notifies** you when one goes
`unavailable`/`unknown` or stale. It is intentionally **read-only**: it does not
modify Home Assistant.

It runs as a single Docker container (SQLite, no HTTP server, process-based
healthcheck).

**Removed and gone — do not reintroduce or assume these exist:**
- ❌ Auto-healing / integration reload (cascade, healers, healing plans)
- ❌ AI / LLM layer (Ollama, Claude, anomaly detection, weekly summaries, pattern
  collection, reliability analysis, AI-enhanced notifications)
- ❌ REST API + web dashboard (FastAPI/uvicorn)
- ❌ MCP server
- ❌ Automation analysis + usage tracking

> Vestigial only: `HealingConfig`, `IntelligenceConfig`, `OutcomeValidationConfig`
> remain in `core/config.py` because `core/config_service.py` still maps their
> runtime settings, but **no runtime code reads them**. Their DB tables are left
> in place (unused). Don't build on them.

## Architecture (current packages under `ha_boss/`)

- `core/` — config (Pydantic), config_service (DB-stored settings + instance
  startup), database (SQLAlchemy async + migrations), ha_client (REST + a one-shot
  WS helper for manifests/entity-registry), encryption, types, exceptions.
- `monitoring/` — `state_tracker` (in-memory cache, **scoped by discovery**),
  `health_monitor` (detects unavailable/unknown/stale + cloud-aware grace),
  `websocket_client` (events + reload-triggered discovery refresh),
  `action_verifier`, `out_of_scope_audit`.
- `discovery/` — `entity_discovery` (auto-discovery from automations/scenes/scripts),
  `integration_classifier` (entity → `iot_class` via HA manifests, cloud detection).
- `notifications/` — `manager` (HA persistent + CLI + mobile-push channels),
  `templates`.
- `healing/` — **slimmed to two kept pieces**: `escalation.py`
  (`NotificationEscalator`, the notify facade) and `integration_manager.py`
  (`IntegrationDiscovery`, entity→integration mapping used by state_tracker and the
  out-of-scope audit). The name is historical; there is no healing engine.
- `service/` — `main.py` orchestration (`HABossService`).
- `cli/` — Typer CLI (`haboss`): `start`, `status`, `init`, `config`, `db`.

Flow: WebSocket → StateTracker (discovery-scoped) → HealthMonitor → (after grace)
NotificationEscalator → HA persistent notification + optional mobile push.
`HealthIssue.is_cloud` (set by the classifier) makes the monitor use a longer grace
and the escalator drop mobile push for cloud entities.

## Development

Python **3.12 only** (CI and all tooling target 3.12).

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

# before pushing:
black --check . && ruff check . && mypy ha_boss && pytest
```

CLI entry point: `haboss = ha_boss.cli.commands:app`.

### Conventions

- Async for all I/O; complete type hints; Google-style docstrings on public APIs.
- Line length 100 (black + ruff).
- New config → Pydantic models in `core/config.py`. New tables/columns → a
  migration in `core/migrations/` (register it + bump `CURRENT_DB_VERSION`; each
  migration inserts its own `schema_version` row).
- Tests mirror source layout under `tests/`; keep coverage high; new behavior
  needs tests.
- Keep PRs small and focused.

### Known pre-existing test wart

`tests/notifications/test_templates.py::test_format_time_ago_naive_datetime` is
DST-sensitive: it fails on a non-UTC host (e.g. America/Chicago in CDT) but passes
in UTC CI. Not caused by current changes.

## Deployment

Production runs in Docker on host `blackbox` (container `ha-boss`, image
`ha-boss:dev` built from this repo via the dev compose overlay). The deployed
`docker-compose.yml` has a **local, uncommitted edit** that uncomments the
`HA_URL`/`HA_TOKEN` `environment:` lines so the container receives them (the repo
template keeps them commented). **Never overwrite blackbox's `docker-compose.yml`,
`.env`, or `config/config.yaml`** — they are deployment-local. Deploy code by
syncing the `ha_boss/` package, then rebuild + restart.

## Workflow

Work on a feature/fix branch off `main`; open a PR; CI (`test (3.12)` +
`claude-review`) must pass; squash-merge. `main` is protected.
