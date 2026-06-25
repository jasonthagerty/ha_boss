# HA Boss

[![CI Status](https://github.com/jasonthagerty/ha_boss/workflows/CI/badge.svg)](https://github.com/jasonthagerty/ha_boss/actions)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A small, headless watchdog for Home Assistant. HA Boss watches the entities your
automations actually depend on and **notifies you when something is stuck,
offline, or didn't do what it was told** — nothing more. It runs as a single
container, has no web UI, and makes no changes to your Home Assistant.

## What it does

- **🔍 Real-time monitoring** — one WebSocket connection for instant state updates.
- **🎯 Auto-discovery** — automatically scopes monitoring to the entities referenced
  in your automations/scenes/scripts (refreshes on reload and on a timer).
- **📣 Monitor-and-notify** — alerts when a monitored entity goes `unavailable`/
  `unknown` or stops updating (stale), after a grace period. Sends a Home Assistant
  persistent notification and, optionally, a mobile push.
- **☁️ Cloud-aware** — internet-dependent integrations (manifest `iot_class` of
  `cloud_polling`/`cloud_push`, e.g. PlayStation Network, Plex, Life360) get a
  longer grace and no mobile push, so external blips don't page you.
- **🔌 Expected-unavailable** — entities that report `unavailable` when simply off
  (e.g. a TV) can be marked so they aren't flagged (`monitoring.unavailable_ok`).
- **✅ Action verification** — optionally warns if a commanded entity (turn on/off,
  cover, lock…) doesn't reach the intended state within a grace window.
- **🗂️ Out-of-scope audit** — optional periodic digest of unavailable entities that
  aren't used by any automation/scene/script.
- **🐳 Docker-first** — single container, SQLite, process-based healthcheck.

> HA Boss is intentionally read-only: it does **not** auto-heal, reload
> integrations, or modify your Home Assistant config.

## Quick start (Docker)

```bash
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss
cp .env.example .env          # set HA_URL and HA_TOKEN
mkdir -p data config
sudo chown -R 1000:1000 data

# Build + run locally
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker-compose logs -f haboss
```

## Local development

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
haboss init && haboss start --foreground
```

## CLI

```bash
haboss start --foreground   # run the service
haboss status               # show service + monitoring status
haboss config validate      # validate configuration
haboss db cleanup           # prune old data
```

## Configuration

See [`config/config.yaml.example`](config/config.yaml.example). The essentials:

```yaml
home_assistant:
  url: "${HA_URL}"
  token: "${HA_TOKEN}"

monitoring:
  grace_period_seconds: 300
  unavailable_ok: []          # entities where 'unavailable' is normal (e.g. a TV)
  cloud_handling:
    enabled: true             # gentler handling for cloud integrations
  action_verification:
    enabled: false
  out_of_scope_audit:
    enabled: false

notifications:
  on_issue_detected: true     # send alerts in monitor-and-notify mode
  mobile_push_services: []    # e.g. ["notify.jasons_iphone"]
```

## Architecture

```
WebSocket events ─▶ StateTracker (scoped by auto-discovery)
                       │
                       ▼
                  HealthMonitor ─▶ NotificationEscalator ─▶ HA persistent + mobile push
                       ▲
            IntegrationClassifier (cloud vs local, via HA manifests)
```

Packages: `monitoring/` (state tracking, health, websocket, action verification,
out-of-scope audit), `discovery/` (auto-discovery + cloud classification),
`notifications/`, `core/` (config, db, HA client), `service/` (orchestration),
`cli/`.

## License

[MIT](LICENSE) — made for the Home Assistant community.
