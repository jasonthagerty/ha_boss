# HA Boss

[![CI Status](https://github.com/jasonthagerty/ha_boss/workflows/CI/badge.svg)](https://github.com/jasonthagerty/ha_boss/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-81%25-brightgreen)](https://github.com/jasonthagerty/ha_boss)

A standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and provides AI-powered automation management. HA Boss acts as an intelligent watchdog for your smart home, detecting issues before they become problems and fixing them automatically.

## ✨ Key Features

- **🔍 Real-time Monitoring** - WebSocket connection for instant state updates
- **🔧 Auto-Healing** - Automatically reloads failed integrations with circuit breakers
- **🛡️ Safety First** - Dry-run mode, graceful degradation, automatic reconnection
- **📊 Pattern Analysis** - Tracks reliability metrics and failure patterns
- **🤖 AI Intelligence** - Local LLM (Ollama) + Claude API for automation generation
- **🔌 MCP Server** - Exposes capabilities to AI agents via Model Context Protocol
- **🐳 Docker-First** - Production-ready with multi-stage builds and health checks
- **💻 Rich CLI** - Beautiful terminal UI for management and analysis

## 🚀 Quick Start

### Docker (Recommended - Production)

Uses pre-built images from GitHub Container Registry:

```bash
# Clone and configure
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss
cp .env.example .env

# Create data directory with correct permissions
mkdir -p data config
sudo chown -R 1000:1000 data

# Edit .env with your Home Assistant URL and token
# Then start the service (pulls latest images)
docker-compose up -d

# Check status
docker-compose exec haboss haboss status
```

### Docker (Local Development)

Build from source for development:

```bash
# Create data directory with correct permissions
mkdir -p data config
sudo chown -R 1000:1000 data

# Use dev overlay to build locally
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Or build specific service
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build haboss
```

### Local Development (Python)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
haboss init && haboss start --foreground
```

## 🔌 MCP Server (Model Context Protocol)

**NEW:** HA Boss includes an optional MCP server that exposes 12 tools to AI agents like Claude Desktop.

```bash
# Start with MCP server enabled
docker-compose --profile mcp up -d
```

**Available Tools:** Monitoring (4), Healing (3), Pattern Analysis (3), Service Management (2)

**Claude Desktop Integration:**
```json
{
  "mcpServers": {
    "ha-boss": {
      "command": "docker",
      "args": ["exec", "-i", "ha-boss-mcp", "python", "-m", "ha_boss_mcp.server"]
    }
  }
}
```

See [ha_boss_mcp/README.md](ha_boss_mcp/README.md) for complete documentation.

## 🎮 Common Commands

```bash
# Monitoring & Healing
haboss start --foreground          # Run service
haboss status                      # Health status
haboss heal sensor.temperature     # Manual heal

# Pattern Analysis
haboss patterns reliability        # Integration reliability
haboss patterns failures           # Failure timeline
haboss patterns weekly-summary     # AI weekly report

# Automation
haboss automation analyze bedroom_lights
haboss automation generate "Turn on lights when motion detected"
```

## 📚 Documentation

- **[Installation](https://github.com/jasonthagerty/ha_boss/wiki/Installation)** - Setup and configuration
- **[CLI Reference](https://github.com/jasonthagerty/ha_boss/wiki/CLI-Commands)** - All commands
- **[Configuration](https://github.com/jasonthagerty/ha_boss/wiki/Configuration)** - Settings explained
- **[Architecture](https://github.com/jasonthagerty/ha_boss/wiki/Architecture)** - Technical design
- **[AI Features](https://github.com/jasonthagerty/ha_boss/wiki/AI-Features)** - LLM integration
- **[MCP Server](https://github.com/jasonthagerty/ha_boss/wiki/MCP-Server)** - Model Context Protocol
- **[Development](https://github.com/jasonthagerty/ha_boss/wiki/Development)** - Contributing guide

## 🎯 Project Status

**All phases complete and production-ready!**

- ✅ **Phase 1** - Real-time monitoring, auto-healing, Docker deployment
- ✅ **Phase 2** - Reliability tracking, CLI reports, database schema
- ✅ **Phase 3** - Local LLM, Claude integration, automation generation
- ✅ **MCP Server** - Model Context Protocol interface for AI agents

**Test Coverage:** 81% (528 tests) | **Docker Images:** Multi-arch (amd64, arm64)

## 🏗️ Architecture

```
┌────────────────────────────────────┐
│      HA Boss Service + MCP         │
├────────────────────────────────────┤
│  WebSocket Monitor ──▶ State      │
│  Health Monitor ──▶ Healing Mgr    │
│  Pattern Collector ──▶ AI Analyzer │
│  MCP Server ──▶ 12 AI Agent Tools  │
└────────────────────────────────────┘
         │              │
         │ WebSocket    │ SQLite
         ▼              ▼
   ┌─────────┐    ┌──────────┐
   │  Home   │    │ Pattern  │
   │Assistant│    │ Database │
   └─────────┘    └──────────┘
```

## 🔐 Security

- Tokens stored in `.env` (never committed)
- Non-root Docker user (haboss:1000, mcpuser:1001)
- Works fully offline with local LLM
- Optional Claude API for advanced features

## 📦 Docker Images

Published to GitHub Container Registry with multi-arch support:
- `ghcr.io/jasonthagerty/ha-boss:latest` - Main service
- `ghcr.io/jasonthagerty/ha-boss-mcp:latest` - MCP server (optional)

**Supported Architectures:**
- `amd64` - Intel/AMD 64-bit (NUCs, x86_64 servers)
- `arm64` - ARM 64-bit (Raspberry Pi 4/5, Raspberry Pi 3 in 64-bit mode)

> **Note:** armv7 (32-bit ARM) is not supported due to dependency compilation issues. Raspberry Pi 3/4 users should use a 64-bit OS.

Images are automatically built and published on every push to main.

> **Future:** HA Boss will be available as a Home Assistant addon for one-click installation from the addon store.

## 📝 Example Configuration

**Monitor critical sensors:**
```yaml
monitoring:
  include:
    - "sensor.temperature_*"
    - "binary_sensor.door_*"
```

**Conservative healing:**
```yaml
monitoring:
  grace_period_seconds: 600
healing:
  max_attempts: 2
  cooldown_seconds: 600
```

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) and [Development Wiki](https://github.com/jasonthagerty/ha_boss/wiki/Development).

## 📜 License

[MIT License](LICENSE)

## 📞 Support

- **Issues:** [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- **Discussions:** [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)
- **Wiki:** [Documentation](https://github.com/jasonthagerty/ha_boss/wiki)

---

**Made with ❤️ for the Home Assistant community**
