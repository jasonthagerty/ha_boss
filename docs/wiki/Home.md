# HA Boss Wiki

Welcome to the HA Boss documentation! This wiki provides comprehensive guides for installation, configuration, and usage of HA Boss.

## ✨ What's New

**Recent Updates:**

- **Multi-Instance Support with Aggregate Mode** - Monitor multiple Home Assistant instances
  - Connect to multiple HA instances simultaneously
  - "All Instances" aggregate view shows combined data across all instances
  - Per-instance filtering via `instance_id` parameter
  - See [Multi-Instance](Multi-Instance) for complete documentation

- **REST API & Dashboard** - Full REST API with interactive web dashboard
  - 15+ endpoints covering all HA Boss features (status, entities, patterns, healing, automations)
  - Real-time dashboard with charts, monitoring, and instance selector
  - See [REST API](REST-API) and [Dashboard](Dashboard) for complete documentation

- **Automation Analysis & Tracking** - Usage-based optimization recommendations
  - Track automation executions with trigger types, durations, and success rates
  - Monitor service calls made by automations with response times
  - AI-powered analysis suggests optimizations based on real usage patterns
  - Access via CLI (`haboss automation stats`) or MCP tools
  - See [AI Features - Automation Analysis](AI-Features#automation-analysis) for details

- **Comprehensive Test Suite** - 740+ tests with robust coverage
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
- **[AI Features](AI-Features)** - LLM integration, automation analysis, and intelligent insights
- **[Multi-Instance](Multi-Instance)** - Managing multiple Home Assistant instances
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
| Monitor multiple HA instances | [Multi-Instance Setup](Multi-Instance) |
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
- ✅ **Phase 3 (AI Intelligence)** - Local LLM, Claude integration, automation analysis and tracking
- ✅ **Multi-Instance Support** - Monitor multiple HA instances with aggregate views

**Test Coverage:** 740+ tests passing

---

**Back to:** [Repository](https://github.com/jasonthagerty/ha_boss) | [Main README](https://github.com/jasonthagerty/ha_boss/blob/main/README.md)
