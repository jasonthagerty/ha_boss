# HA Boss

[![CI Status](https://github.com/jasonthagerty/ha_boss/workflows/CI/badge.svg)](https://github.com/jasonthagerty/ha_boss/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-81%25-brightgreen)](https://github.com/jasonthagerty/ha_boss)

A standalone Python service that monitors Home Assistant instances, automatically heals integration failures, and provides AI-powered automation management. HA Boss acts as an intelligent watchdog for your smart home, detecting issues before they become problems and fixing them automatically.

## ✨ Key Features

- **🔍 Real-time Monitoring** - WebSocket connection for instant state updates
- **🔧 Auto-Healing** - Automatically reloads failed integrations with circuit breakers and cooldowns
- **🛡️ Safety First** - Dry-run mode, graceful degradation, automatic reconnection
- **📊 Pattern Analysis** - Tracks reliability metrics and failure patterns
- **🤖 AI Intelligence** - Local LLM (Ollama) + optional Claude API for automation analysis and generation
- **📈 Weekly Reports** - AI-generated health summaries delivered as notifications
- **🐳 Docker-First** - Production-ready with multi-stage builds and health checks
- **💻 Rich CLI** - Beautiful terminal UI for management and analysis

## 🚀 Quick Start

### Docker (Recommended)

```bash
# 1. Clone and configure
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss
cp .env.example .env

# 2. Edit .env with your Home Assistant URL and token
#    HOME_ASSISTANT__URL=http://homeassistant.local:8123
#    HOME_ASSISTANT__TOKEN=your_long_lived_token_here

# 3. Start the service
docker-compose up -d

# 4. Check status
docker-compose exec haboss haboss status
```

### Local Development

```bash
# Install with uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

# Initialize and run
haboss init
haboss start --foreground
```

## 📚 Documentation

Comprehensive documentation is available in the [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki):

- **[Installation Guide](https://github.com/jasonthagerty/ha_boss/wiki/Installation)** - Docker, local, and configuration setup
- **[CLI Reference](https://github.com/jasonthagerty/ha_boss/wiki/CLI-Commands)** - Complete command documentation
- **[Configuration Guide](https://github.com/jasonthagerty/ha_boss/wiki/Configuration)** - All configuration options explained
- **[Architecture](https://github.com/jasonthagerty/ha_boss/wiki/Architecture)** - Technical design and component overview
- **[AI Features](https://github.com/jasonthagerty/ha_boss/wiki/AI-Features)** - LLM integration and capabilities
- **[Development](https://github.com/jasonthagerty/ha_boss/wiki/Development)** - Contributing, testing, and code quality
- **[Troubleshooting](https://github.com/jasonthagerty/ha_boss/wiki/Troubleshooting)** - Common issues and solutions

## 🎮 Common Commands

```bash
# Monitor and heal
haboss start --foreground          # Run service in foreground
haboss status                      # Show health status
haboss heal sensor.temperature     # Manually heal specific entity

# Pattern analysis
haboss patterns reliability        # Show integration reliability
haboss patterns failures           # View failure timeline
haboss patterns weekly-summary     # Generate AI weekly report

# Automation management
haboss automation analyze bedroom_lights    # Analyze existing automation
haboss automation generate "Turn on lights when motion detected"
```

## 🎯 Project Status

**All phases complete and production-ready!**

- ✅ **Phase 1 (MVP)** - Real-time monitoring, auto-healing, Docker deployment
- ✅ **Phase 2 (Pattern Analysis)** - Reliability tracking, CLI reports, database schema
- ✅ **Phase 3 (AI Intelligence)** - Local LLM, Claude integration, automation generation

**Test Coverage:** 81% (528 tests passing)

## 🔐 Security

- Tokens stored securely in `.env` (never committed)
- Non-root Docker user
- No external API calls required (works fully offline with local LLM)
- Optional Claude API for advanced features only

## 🏗️ Architecture Overview

```
┌──────────────────────────────────────┐
│      HA Boss Service                 │
├──────────────────────────────────────┤
│  WebSocket Monitor ──▶ State Tracker│
│  Health Monitor ──▶ Healing Manager  │
│  Pattern Collector ──▶ AI Analyzer   │
│  Notification Manager ◀── Escalation │
└──────────────────────────────────────┘
         │                    │
         │ REST + WebSocket   │ SQLite
         ▼                    ▼
   ┌─────────────┐      ┌──────────┐
   │ Home        │      │ Pattern  │
   │ Assistant   │      │ Database │
   └─────────────┘      └──────────┘
```

See [Architecture Wiki](https://github.com/jasonthagerty/ha_boss/wiki/Architecture) for detailed component interactions.

## 🤝 Contributing

Contributions welcome! Please see:
- [Contributing Guide](CONTRIBUTING.md) - Guidelines and workflow
- [Development Wiki](https://github.com/jasonthagerty/ha_boss/wiki/Development) - Setup and testing

## 📝 Example Use Cases

**Monitor critical sensors:**
```yaml
monitoring:
  include:
    - "sensor.temperature_*"
    - "binary_sensor.door_*"
```

**Conservative healing with long grace periods:**
```yaml
monitoring:
  grace_period_seconds: 600  # 10 minutes
healing:
  max_attempts: 2
  cooldown_seconds: 600
```

**Weekly AI reports:**
```bash
haboss patterns weekly-summary --ai
```

## 📜 License

[MIT License](LICENSE) - See LICENSE file for details

## 📞 Support

- **Issues:** [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- **Discussions:** [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)
- **Documentation:** [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki)

---

**Made with ❤️ for the Home Assistant community**
