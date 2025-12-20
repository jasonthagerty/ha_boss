# HA Boss Wiki

Welcome to the HA Boss documentation! This wiki provides comprehensive guides for installation, configuration, and usage of HA Boss.

## ✨ What's New

**Recent Updates:**

- **REST API & Dashboard** - Full REST API with interactive web dashboard
  - 13 endpoints covering all HA Boss features (status, entities, patterns, healing, automations)
  - Real-time dashboard with charts, monitoring, and API testing
  - See [REST API](REST-API) and [Dashboard](Dashboard) for complete documentation

- **Automation Creation** - Generate and create automations directly in Home Assistant via API
  - Preview-first workflow: review generated YAML before creating
  - Use `haboss automation generate "description" --create` to create in HA
  - See [AI Features - Automation Generation](AI-Features#automation-generation) for details

- **Enhanced CLI** - Improved automation commands with safer defaults
  - Preview by default, opt-in creation with `--create` flag
  - Rich terminal UI with formatted output
  - See [CLI Commands - Automation Commands](CLI-Commands#automation-commands) for full reference

- **Comprehensive Test Suite** - 528 tests with 81% coverage
  - Full test coverage for core monitoring and healing features
  - Pattern analysis and AI features thoroughly tested
  - See [Development - Testing](Development#testing) for contribution guidelines

## 📖 Documentation Sections

### Getting Started
- **[Installation](Installation)** - Docker and local installation guide with full setup instructions
- **[Configuration](Configuration)** - Complete configuration reference for all options
- **[Quick Start](Installation#quick-start)** - Get up and running in 5 minutes

### Usage & Features
- **[CLI Commands](CLI-Commands)** - Complete command-line interface reference
- **[AI Features](AI-Features)** - LLM integration, automation generation, and intelligent analysis
- **[Pattern Analysis](CLI-Commands#pattern-analysis-commands)** - Reliability tracking and failure analysis

### API & Dashboard
- **[REST API](REST-API)** - Complete REST API reference with all endpoints and client examples
- **[Dashboard](Dashboard)** - Interactive web dashboard for monitoring, analysis, and control

### Technical Documentation
- **[Architecture](Architecture)** - System design, components, and data flow
- **[Development](Development)** - Contributing, testing, and code quality standards
- **[Troubleshooting](Troubleshooting)** - Common issues and solutions

## 🎯 Quick Links

| I want to... | Go to... |
|-------------|----------|
| Install HA Boss with Docker | [Docker Installation](Installation#docker-installation) |
| Set up local development | [Local Development](Installation#local-development) |
| Access the web dashboard | [Dashboard Guide](Dashboard#getting-started) |
| Use the REST API | [API Reference](REST-API#api-reference) |
| Configure monitoring options | [Monitoring Configuration](Configuration#monitoring-configuration) |
| Use the CLI commands | [CLI Reference](CLI-Commands) |
| Set up AI features | [AI Features Setup](AI-Features) |
| Understand the architecture | [Architecture Overview](Architecture) |
| Contribute to the project | [Development Guide](Development) |
| Fix connection issues | [Troubleshooting](Troubleshooting) |

## 🔍 Search Tips

Use the search bar at the top of the wiki to quickly find what you're looking for. Try searching for:
- Specific commands (e.g., "haboss status", "patterns reliability")
- Configuration options (e.g., "grace_period", "healing")
- Error messages or issues you're encountering

## 💡 Need Help?

- **Common Issues:** Check the [Troubleshooting](Troubleshooting) page first
- **Questions:** Use [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)
- **Bugs:** Report on [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- **Examples:** See [Example Use Cases](Installation#example-configurations)

## 📋 Project Status

HA Boss is production-ready with all three development phases complete:

- ✅ **Phase 1 (MVP)** - Monitoring, auto-healing, Docker deployment
- ✅ **Phase 2 (Pattern Analysis)** - Reliability tracking, database schema
- ✅ **Phase 3 (AI Intelligence)** - Local LLM, Claude integration, automation generation

**Test Coverage:** 81% (528 tests passing)

---

**Back to:** [Repository](https://github.com/jasonthagerty/ha_boss) | [Main README](https://github.com/jasonthagerty/ha_boss/blob/main/README.md)
