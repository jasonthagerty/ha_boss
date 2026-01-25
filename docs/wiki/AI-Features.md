# AI Features Guide

This guide covers HA Boss Phase 3 AI-powered intelligence features, including setup, configuration, and usage.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Features](#features)
  - [AI-Enhanced Notifications](#ai-enhanced-notifications)
  - [Anomaly Detection](#anomaly-detection)
  - [Weekly Summary Reports](#weekly-summary-reports)
  - [Automation Analysis](#automation-analysis)
  - [Automation Usage Tracking](#automation-usage-tracking)
- [Setup](#setup)
  - [Ollama Setup (Local LLM)](#ollama-setup-local-llm)
  - [Claude API Setup (Optional)](#claude-api-setup-optional)
- [Configuration](#configuration)
- [Privacy & Security](#privacy--security)
- [Performance](#performance)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

## Overview

HA Boss Phase 3 introduces AI-powered intelligence features using a **hybrid LLM architecture**:

- **Local LLM (Ollama)**: Privacy-first AI running on your hardware
- **Claude API (Optional)**: Cloud AI for complex reasoning tasks
- **Smart Routing**: Automatically selects the best LLM for each task

### AI Features at a Glance

| Feature | Description | LLM Used | Response Time |
|---------|-------------|----------|---------------|
| Enhanced Notifications | Natural language failure explanations | Ollama | < 3s |
| Anomaly Detection | Identifies unusual failure patterns | Ollama | < 5s |
| Weekly Summaries | AI-analyzed health reports | Ollama | < 15s |
| Automation Analysis | Suggests improvements | Ollama | < 5s |
| Automation Usage Tracking | Real-time execution and service call tracking | N/A | Real-time |

### Key Benefits

✅ **Privacy First**: Fully functional with local LLM only (no cloud required)
✅ **Graceful Degradation**: All features work without AI (fallback to simple text)
✅ **Cost Effective**: Minimal Claude API usage (only for complex tasks)
✅ **Performance Validated**: All operations meet < 15s response times
✅ **Easy Setup**: Docker-based deployment, minimal configuration

## Quick Start

### Minimal Setup (Local LLM Only)

```bash
# 1. Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull the recommended model
ollama pull llama3.1:8b

# 3. Configure HA Boss (config/config.yaml)
intelligence:
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"

notifications:
  ai_enhanced: true  # Enable AI features

# 4. Restart HA Boss
docker-compose restart haboss
```

### With Claude API (Optional)

```bash
# 1. Get Claude API key from https://console.anthropic.com

# 2. Add to .env file
echo "CLAUDE_API_KEY=sk-ant-..." >> .env

# 3. Configure HA Boss (config/config.yaml)
intelligence:
  claude_api_key: "${CLAUDE_API_KEY}"
  claude_model: "claude-3-5-sonnet-20241022"

# 4. Restart HA Boss
docker-compose restart haboss
```

## Features

### AI-Enhanced Notifications

**What it does**: Adds natural language explanations to failure notifications

**Example**:

**Before (without AI)**:
```
HA Boss Alert
Entity: sensor.outdoor_temperature
Status: unavailable
Integration: met
```

**After (with AI)**:
```
HA Boss Alert
Entity: sensor.outdoor_temperature
Status: unavailable
Integration: met

AI Insight:
The Met.no weather integration failed because the API rate limit
was exceeded. This typically happens when multiple automations poll
weather data too frequently. Consider increasing the update interval
to 10+ minutes or reducing the number of entities monitoring weather.
```

**Configuration**:
```yaml
notifications:
  ai_enhanced: true
```

**How it works**:
1. HA Boss detects integration failure
2. Gathers context (failure history, integration type, recent events)
3. Sends to local LLM (Ollama) for analysis
4. LLM generates natural language explanation
5. Delivers enhanced notification to Home Assistant

**Performance**: < 3s response time (Ollama)

---

### Anomaly Detection

**What it does**: Automatically identifies unusual failure patterns and alerts you

**Example**:

```
HA Boss Anomaly Detected

Pattern: Unusual Failure Rate
Integration: hue
Severity: High

Details:
The Hue integration has failed 12 times in the last hour
(normal: 0-1 per day). This spike started at 14:30 UTC.

AI Analysis:
This pattern suggests a network connectivity issue between
Home Assistant and the Hue Bridge. Check:
1. Hue Bridge network connection
2. Router/switch health
3. IP address assignment (DHCP vs static)
4. Network traffic/congestion

Historical Context:
Similar spike occurred 2 weeks ago during router firmware update.
```

**Configuration**:
```yaml
intelligence:
  anomaly_detection_enabled: true
```

**Detection Types**:
- **Unusual Failure Rate**: Integration fails more than normal
- **Time Correlation**: Failures cluster at specific times
- **Integration Correlation**: Multiple integrations fail together

**How it works**:
1. Continuously analyzes pattern data (Phase 2)
2. Compares current behavior to historical baselines
3. Detects statistical anomalies (> 2 standard deviations)
4. LLM generates explanation and recommendations
5. Sends notification if severity threshold exceeded

**Performance**: < 5s for 30-day scan

---

### Weekly Summary Reports

**What it does**: Generates AI-analyzed weekly health reports

**Example**:

```
HA Boss Weekly Summary
Period: Nov 18-25, 2024

Overview:
This week, HA Boss monitored 150 entities across 12 integrations,
performing 23 healing attempts with an 87% success rate.

Top Performers (Excellent Reliability):
• MQTT: 100% success rate (5 heals)
• Hue: 95% success rate (20 heals)
• ESPHome: 92% success rate (8 heals)

Needs Attention:
• ZWave: 75% reliability - Consider network health check
• Met.no: 45% reliability - Reduce polling frequency

Key Insights:
- Integration reliability improved 12% from last week
- Most failures occurred between 02:00-04:00 (network maintenance window)
- No critical anomalies detected

Recommendations:
1. Review ZWave network coverage in bedroom area
2. Increase Met.no update interval to 15 minutes
3. Consider static IP for Hue Bridge (3 DHCP changes this week)
```

**Configuration**:
```yaml
notifications:
  weekly_summary: true  # Enable weekly summary reports
```

**Delivery**: Sent to Home Assistant as persistent notification every Monday at 09:00

**How it works**:
1. Aggregates pattern data for past 7 days
2. Calculates reliability metrics per integration
3. Identifies trends (improving/degrading)
4. LLM analyzes data and generates summary
5. Delivers via Home Assistant notification service

**Performance**: < 15s generation time

---

### Automation Analysis

**What it does**: Analyzes existing Home Assistant automations and suggests improvements

**Example**:

```bash
# Analyze a specific automation
$ haboss automation analyze automation.bedroom_lights

Automation Analysis: Bedroom Lights
Status: On
Triggers: 2 | Conditions: 1 | Actions: 3

Suggestions:

⚠️  WARNING: Inefficient trigger pattern
Your automation triggers on every state change of binary_sensor.motion_bedroom.
Consider adding condition: to: 'on' to reduce unnecessary triggers.

ℹ️  INFO: Combine related actions
Actions 1 and 2 both call light.turn_on. These could be combined into a
single service call with multiple targets for better performance.

ℹ️  INFO: Missing timeout
No timeout condition for the motion sensor. Consider adding a wait action
to turn off lights after 5 minutes of no motion.

AI Analysis:
This automation could be simplified by using the wait_template action
with a timeout instead of separate on/off automations. This would
reduce automation count and improve reliability.
```

**CLI Commands**:
```bash
# Analyze specific automation
haboss automation analyze automation.bedroom_lights

# Analyze all automations
haboss automation analyze --all

# Get recommendations only (no full analysis)
haboss automation recommend automation.bedroom_lights
```

**Analysis Categories**:
- **Structure**: Trigger/condition/action organization
- **Performance**: Inefficiencies and optimization opportunities
- **Best Practices**: HA automation patterns and anti-patterns
- **Reliability**: Potential failure points and edge cases

**Performance**: < 5s per automation

---

### Automation Usage Tracking

**What it does**: Tracks automation executions and service calls in real-time for analysis and optimization

**Example**:

```bash
# View execution history for an automation
$ haboss automation executions automation.bedroom_lights --days 7

Automation Executions: automation.bedroom_lights
Period: Last 7 days

╭──────────────────────────────────────────────────────────────────╮
│ Executed At           │ Trigger    │ Duration │ Status          │
├───────────────────────┼────────────┼──────────┼─────────────────┤
│ 2024-12-20 08:30:15   │ state      │ 45ms     │ ✓ Success       │
│ 2024-12-20 07:15:22   │ state      │ 38ms     │ ✓ Success       │
│ 2024-12-19 22:45:10   │ time       │ 52ms     │ ✓ Success       │
│ 2024-12-19 18:30:05   │ state      │ 41ms     │ ✗ Failed        │
╰──────────────────────────────────────────────────────────────────╯

Total: 156 executions | 98.7% success rate | Avg: 44ms

# View usage statistics
$ haboss automation stats automation.bedroom_lights

Usage Statistics: automation.bedroom_lights
Period: Last 30 days

Execution Count: 458
Failure Count: 6
Success Rate: 98.7%
Avg Duration: 44ms
Service Calls: 912
Most Common Trigger: state
Last Executed: 2024-12-20 08:30:15
```

**Features**:
- **Real-time Tracking**: Captures every automation execution via WebSocket events
- **Service Call Tracking**: Records all service calls made by automations
- **Usage Statistics**: Aggregates execution counts, failure rates, and performance metrics
- **MCP Integration**: Exposes data via 5 MCP tools for AI-assisted analysis

**CLI Commands**:
```bash
# View execution history
haboss automation executions [automation_id] --days 7

# View service calls
haboss automation service-calls [automation_id] --days 7

# Get usage statistics
haboss automation stats automation.bedroom_lights --days 30

# List all automations with status
haboss automation list
```

**MCP Tools**:
- `get_automation_executions` - Query execution history
- `get_automation_service_calls` - Query service call history
- `get_automation_usage_stats` - Get aggregated statistics
- `list_automations` - List all automations
- `analyze_automation` - AI-powered analysis with usage data

**Data Stored**:
- Execution timestamp and duration
- Trigger type (state, time, event, etc.)
- Success/failure status with error messages
- Service calls with target entities and response times

**Known Limitations**:
> **Note**: Automation ID detection depends on Home Assistant including `context.parent_id`
> in events. Some trigger types may not provide this context, resulting in `unknown`
> automation attribution. This is a Home Assistant WebSocket API limitation.

---

## Setup

### Ollama Setup (Local LLM)

#### Option 1: Native Installation

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull recommended model
ollama pull llama3.1:8b

# Verify installation
ollama list
ollama run llama3.1:8b "Say hello"

# Ollama runs on http://localhost:11434 by default
```

#### Option 2: Docker (Recommended for HA Boss)

Add to your `docker-compose.yml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: haboss_ollama
    restart: unless-stopped
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    networks:
      - haboss-network

  haboss:
    # ... existing configuration ...
    depends_on:
      - ollama
    environment:
      - OLLAMA_URL=http://ollama:11434  # Use service name in Docker

volumes:
  ollama_data:

networks:
  haboss-network:
    driver: bridge
```

Then pull the model:

```bash
# Pull model into Docker container
docker-compose exec ollama ollama pull llama3.1:8b

# Verify
docker-compose exec ollama ollama list
```

#### Model Selection

**Recommended Models**:

| Model | Size | RAM | Speed | Use Case |
|-------|------|-----|-------|----------|
| llama3.1:8b | 4.6GB | 8GB | Fast | Recommended for HA Boss |
| mistral:7b | 4.1GB | 8GB | Very Fast | Alternative, good quality |
| llama3.1:70b | 40GB | 64GB | Slow | High quality (overkill) |

**For HA Boss, use `llama3.1:8b`** - best balance of quality and performance.

---

### Claude API Setup (Optional)

Claude API is **optional** and provides enhanced automation analysis. All other features work with Ollama alone.

#### 1. Get API Key

1. Go to https://console.anthropic.com
2. Sign up or log in
3. Navigate to "API Keys"
4. Create new key
5. Copy key immediately (starts with `sk-ant-`)

#### 2. Configure HA Boss

Add to `.env` file:
```bash
CLAUDE_API_KEY=sk-ant-api03-...
```

Update `config/config.yaml`:
```yaml
intelligence:
  claude_api_key: "${CLAUDE_API_KEY}"
  claude_model: "claude-3-5-sonnet-20241022"
```

#### 3. Verify

```bash
# Check logs for Claude initialization
docker-compose logs haboss | grep -i claude

# Should see: "LLM Router initialized with: Ollama, Claude"
```

#### Cost Considerations

Claude API charges per token:
- **Input**: ~$3 per million tokens
- **Output**: ~$15 per million tokens

**HA Boss Usage**:
- Automation analysis: ~500-1000 tokens per request
- Estimated cost: < $0.01 per analysis
- Monthly cost (10 analyses): < $0.10

**Cost Control**:
- Only used for complex automation analysis (not notifications)
- Keep `claude_enabled: false` to disable Claude completely
- Monitor usage at https://console.anthropic.com

---

## Configuration

### Complete AI Configuration Example

```yaml
# config/config.yaml

intelligence:
  # Pattern collection (Phase 2)
  pattern_collection_enabled: true

  # Anomaly detection
  anomaly_detection_enabled: true
  anomaly_sensitivity_threshold: 2.0
  anomaly_scan_hours: 24

  # Local LLM (Ollama)
  ollama_enabled: true
  ollama_url: "http://localhost:11434"  # Or http://ollama:11434 in Docker
  ollama_model: "llama3.1:8b"
  ollama_timeout_seconds: 30

  # Cloud LLM (Claude) - Optional
  claude_enabled: false  # Enable when you have an API key
  claude_api_key: "${CLAUDE_API_KEY}"
  claude_model: "claude-3-5-sonnet-20241022"

notifications:
  on_healing_failure: true
  weekly_summary: true  # Enable weekly summary reports
  ha_service: "persistent_notification.create"
  ai_enhanced: true  # Enable AI-enhanced notifications
```

### Configuration Options Explained

**`ollama_url`**: Ollama API endpoint
- Default: `http://localhost:11434`
- Docker: `http://ollama:11434` (use service name)

**`ollama_model`**: Model to use
- Recommended: `llama3.1:8b` (best balance)
- Alternative: `mistral:7b` (faster, slightly lower quality)

**`ollama_timeout_seconds`**: Max time to wait for Ollama
- Default: 30s
- Increase if using slower hardware or larger models

**`claude_api_key`**: Anthropic API key (optional)
- Provides enhanced analysis capabilities (not required for basic features)
- Set in .env file for security

**`notifications.ai_enhanced`**: Enable AI explanations in notifications
- Requires Ollama configured (with `ollama_enabled: true`)
- Falls back to simple text if LLM unavailable

**`notifications.weekly_summary`**: Enable weekly summary reports
- Sent every Monday at 09:00 as persistent notification

---

## Privacy & Security

### Data Privacy

**Local LLM (Ollama)**:
✅ All data stays on your hardware
✅ No internet connection required for inference
✅ Complete privacy and control
✅ Recommended for privacy-conscious users

**Claude API** (optional):
⚠️  Data sent to Anthropic servers
⚠️  Subject to Anthropic's privacy policy
ℹ️  Only minimal context sent (no sensitive data)
ℹ️  Used for complex automation analysis when enabled

### Security Best Practices

1. **API Keys**: Store Claude API key in `.env` file (not in config.yaml)
2. **Local-Only Mode**: Keep `claude_enabled: false` for maximum privacy
3. **Network Isolation**: Run Ollama on isolated network if desired
4. **Minimal Context**: HA Boss only sends necessary context to LLMs
5. **No Sensitive Data**: Entity IDs and states only (no passwords, tokens, etc.)

### What Data is Sent to LLMs?

**Enhanced Notifications**:
- Integration name (e.g., "hue")
- Entity ID (e.g., "light.bedroom")
- Failure count and timing
- Recent event history (non-sensitive)

**NOT sent**:
- Home Assistant tokens
- User passwords
- Location data
- Personal information
- Camera/media content

---

## Performance

### Performance Benchmarks

Validated on Intel CPU with Ollama (Llama 3.1 8B):

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Enhanced notification | < 3s | 1-2s | ✅ |
| Anomaly detection | < 5s | 3-4s | ✅ |
| Weekly summary | < 15s | 10-12s | ✅ |
| Automation analysis | < 5s | 3-4s | ✅ |
| Automation tracking (DB write) | < 100ms | 10-50ms | ✅ |

See `tests/performance/test_ai_performance.py` for detailed benchmarks.

### Performance Tips

1. **Use Q4 quantized models** (e.g., `llama3.1:8b`, not `llama3.1:70b`)
2. **Enable GPU acceleration** if available (see Issue #52)
3. **Adjust timeouts** if using slower hardware
4. **Monitor resource usage** with `docker stats`

### Resource Requirements

**Ollama (llama3.1:8b)**:
- **RAM**: 6-8GB during inference
- **Disk**: 5GB for model storage
- **CPU**: 4+ cores recommended
- **GPU**: Optional (2-5x speedup)

**HA Boss (with AI features)**:
- **RAM**: +50MB overhead
- **CPU**: Minimal (waits for LLM)
- **Disk**: +10MB for pattern data

---

## Troubleshooting

### Ollama Not Available

**Symptom**: Logs show "Ollama not available" or "AI features disabled"

**Solutions**:
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Verify model is downloaded
ollama list

# Pull model if missing
ollama pull llama3.1:8b

# Check Docker networking (if using Docker)
docker-compose exec haboss curl http://ollama:11434/api/tags

# Verify configuration
haboss config validate
```

### Slow LLM Response Times

**Symptom**: AI operations take > 15s

**Solutions**:
1. **Check CPU usage**: LLM inference is CPU-intensive
2. **Use smaller model**: Try `mistral:7b` instead of `llama3.1:8b`
3. **Enable GPU**: See Issue #52 for GPU acceleration
4. **Increase timeout**: Adjust `ollama_timeout_seconds` in config

### Claude API Errors

**Symptom**: "Claude API authentication failed" or "Rate limit exceeded"

**Solutions**:
```bash
# Verify API key is set
echo $CLAUDE_API_KEY

# Check API key is valid at https://console.anthropic.com

# Verify key is loaded in HA Boss
docker-compose logs haboss | grep -i claude

# Check rate limits/billing
# Visit https://console.anthropic.com/settings/limits
```

### AI Features Not Working

**Symptom**: Notifications don't include AI insights

**Checklist**:
- [ ] `ai_enhanced: true` in `notifications` section
- [ ] Ollama or Claude configured in `intelligence` section
- [ ] LLM service is running and accessible
- [ ] Model is downloaded (`ollama list`)
- [ ] No errors in logs (`docker-compose logs haboss`)

**Graceful Degradation**:
If LLM is unavailable, HA Boss automatically falls back to simple notifications. Check logs for:
```
INFO: LLM Router initialized with NO available LLMs
INFO: AI features disabled - using fallback notifications
```

---

## Best Practices

### 1. Start with Local LLM Only

Begin with Ollama-only setup (no Claude) to validate AI features work:
```yaml
intelligence:
  ollama_enabled: true
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b"
  claude_enabled: false  # Privacy mode - local LLM only
```

### 2. Monitor LLM Usage

Check resource usage and response times:
```bash
# Monitor Ollama container
docker stats haboss_ollama

# Check HA Boss logs for LLM timing
docker-compose logs haboss | grep -i "llm\|ollama"

# View performance metrics
haboss status --detailed
```

### 3. Tune for Your Hardware

Adjust configuration based on your server:

**Low-end hardware (< 8GB RAM)**:
```yaml
intelligence:
  ollama_model: "mistral:7b"  # Smaller, faster
  ollama_timeout_seconds: 45  # More time
```

**High-end hardware (GPU available)**:
```yaml
intelligence:
  ollama_model: "llama3.1:8b"
  ollama_timeout_seconds: 15  # Faster with GPU
```

### 4. Review Weekly Summaries

Use weekly summaries to identify issues:
- Check for degrading integrations
- Review recommendations
- Monitor reliability trends
- Act on AI suggestions

### 5. Use Automation Tracking for Optimization

Use execution history and statistics to optimize automations:
```bash
# Check for high-failure automations
haboss automation stats automation.bedroom_lights

# View execution patterns to identify issues
haboss automation executions automation.bedroom_lights --days 30

# Analyze with usage data for AI recommendations
haboss automation analyze automation.bedroom_lights --include-usage
```

### 6. Cost Control for Claude API

Minimize Claude costs:
- Only enable Claude when needed for complex analysis
- Set monthly budget alerts at https://console.anthropic.com
- Monitor usage regularly
- Keep `claude_enabled: false` for local-only mode if cost is a concern

---

## Additional Resources

- **LLM Setup Guide**: `docs/LLM_SETUP.md` - Detailed Ollama configuration
- **Performance Benchmarks**: `tests/performance/README.md` - Test methodology
- **Configuration Reference**: `config/config.yaml.example` - All options
- **CLAUDE.md**: Developer guide and architecture

## Support

- **Issues**: https://github.com/jasonthagerty/ha_boss/issues
- **Discussions**: https://github.com/jasonthagerty/ha_boss/discussions
- **Documentation**: https://github.com/jasonthagerty/ha_boss

---

**Last Updated**: 2025-01-20
**Phase**: 3 (AI-Powered Intelligence Layer)
**Status**: Complete ✅
