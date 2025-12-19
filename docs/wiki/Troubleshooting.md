# Troubleshooting Guide

Comprehensive troubleshooting guide for HA Boss covering common issues, diagnostic commands, and solutions.

## Table of Contents

- [Quick Diagnostics](#quick-diagnostics)
- [Connection Issues](#connection-issues)
  - [Home Assistant Not Reachable](#home-assistant-not-reachable)
  - [WebSocket Connection Problems](#websocket-connection-problems)
  - [Frequent Disconnections](#frequent-disconnections)
- [Authentication Errors](#authentication-errors)
  - [401 Unauthorized](#401-unauthorized)
  - [Token Expired or Invalid](#token-expired-or-invalid)
- [Performance Issues](#performance-issues)
  - [High Memory Usage](#high-memory-usage)
  - [High CPU Usage](#high-cpu-usage)
  - [Slow Response Times](#slow-response-times)
- [Healing Issues](#healing-issues)
  - [Entities Not Being Healed](#entities-not-being-healed)
  - [Healing Attempts Failing](#healing-attempts-failing)
  - [Healing Loops](#healing-loops)
  - [Circuit Breaker Tripped](#circuit-breaker-tripped)
- [AI/LLM Issues](#aillm-issues)
  - [Ollama Not Available](#ollama-not-available)
  - [Slow LLM Responses](#slow-llm-responses)
  - [Claude API Errors](#claude-api-errors)
  - [AI Features Not Working](#ai-features-not-working)
- [Docker Issues](#docker-issues)
  - [Container Won't Start](#container-wont-start)
  - [Container Keeps Restarting](#container-keeps-restarting)
  - [Permission Denied Errors](#permission-denied-errors)
  - [Networking Problems](#networking-problems)
- [Database Issues](#database-issues)
  - [Database Corruption](#database-corruption)
  - [Database Growing Too Large](#database-growing-too-large)
  - [Migration Errors](#migration-errors)
- [Configuration Issues](#configuration-issues)
  - [Configuration Not Loading](#configuration-not-loading)
  - [Validation Errors](#validation-errors)
  - [Environment Variables Not Working](#environment-variables-not-working)
- [Log Analysis Tips](#log-analysis-tips)
- [Getting Help](#getting-help)

---

## Quick Diagnostics

Run these commands first to gather system information:

```bash
# Check HA Boss status
docker-compose exec haboss haboss status

# Validate configuration
docker-compose exec haboss haboss config validate

# View recent logs
docker-compose logs --tail=100 haboss

# Check resource usage
docker stats haboss

# Check Home Assistant connectivity
docker-compose exec haboss curl http://your-ha-url:8123/api/

# Database information
docker-compose exec haboss haboss db info

# Check running containers
docker-compose ps
```

**Local development** (replace `docker-compose exec haboss` with direct commands):
```bash
haboss status
haboss config validate
LOG_LEVEL=DEBUG haboss start --foreground
```

---

## Connection Issues

### Home Assistant Not Reachable

**Symptoms**:
- `Connection refused` errors
- `Connection timeout` errors
- `Failed to connect to Home Assistant` messages
- Container health check failing

**Common Causes**:
1. Wrong Home Assistant URL
2. Home Assistant not running
3. Network/firewall blocking connection
4. Docker networking issues

**Solutions**:

#### 1. Verify Home Assistant URL

```bash
# Check configured URL
docker-compose exec haboss haboss config show | grep url

# Test connectivity from host
curl http://homeassistant.local:8123/api/
# Should return: {"message": "API running."}

# Test from HA Boss container
docker-compose exec haboss curl http://homeassistant.local:8123/api/
```

**Expected response**:
```json
{"message": "API running."}
```

If this fails, check:
- Is the URL correct in `.env` or `config.yaml`?
- Is Home Assistant actually running? (`docker ps | grep homeassistant`)
- Can you reach it from a web browser?

#### 2. Fix Docker Networking

**macOS/Windows Docker Desktop**:
Use `host.docker.internal` instead of `localhost`:

```bash
# Edit .env
HA_URL=http://host.docker.internal:8123

# Restart
docker-compose restart haboss
```

**Linux Docker**:
Use the host's actual IP address (not `localhost` or `127.0.0.1`):

```bash
# Find host IP
ip addr show | grep inet

# Edit .env
HA_URL=http://192.168.1.100:8123  # Replace with your IP

# Restart
docker-compose restart haboss
```

**Docker Compose same network**:
If Home Assistant runs in Docker, ensure both containers are on the same network:

```yaml
# docker-compose.yml
services:
  haboss:
    networks:
      - homeassistant-network

  homeassistant:
    networks:
      - homeassistant-network

networks:
  homeassistant-network:
    external: true
```

Then use service name: `HA_URL=http://homeassistant:8123`

#### 3. Check Firewall

```bash
# Test port accessibility
nc -zv homeassistant.local 8123

# Or
telnet homeassistant.local 8123
```

If connection refused:
- Check Home Assistant firewall rules
- Verify Docker host firewall allows outbound connections
- Check router/network ACLs

#### 4. Verify Home Assistant Configuration

Ensure Home Assistant allows API access from HA Boss:

```yaml
# configuration.yaml (Home Assistant)
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.16.0.0/12  # Docker network range
    - 192.168.0.0/16  # Local network range
```

**Prevention**:
- Use static IP for Home Assistant (avoid DHCP changes)
- Configure DNS entry or use IP address directly
- Test connectivity before deploying HA Boss

---

### WebSocket Connection Problems

**Symptoms**:
- `WebSocket connection failed` errors
- `WebSocket closed unexpectedly` messages
- No state updates received
- Constant reconnection attempts

**Common Causes**:
1. WebSocket endpoint not accessible
2. Authentication timeout
3. Home Assistant rate limiting
4. Proxy/reverse proxy blocking WebSockets

**Diagnostic Commands**:

```bash
# Check WebSocket status in logs
docker-compose logs haboss | grep -i websocket

# Look for connection patterns
docker-compose logs haboss | grep -E "Connected|Disconnected|WebSocket"

# Check reconnection attempts
docker-compose logs haboss | grep "Reconnecting"
```

**Solutions**:

#### 1. Increase WebSocket Timeout

Edit `config/config.yaml`:

```yaml
websocket:
  timeout_seconds: 15  # Increase from default 10
  heartbeat_interval_seconds: 30
  reconnect_delay_seconds: 5
```

#### 2. Fix Proxy Configuration

If using reverse proxy (Nginx, Caddy, etc.) in front of Home Assistant:

**Nginx**:
```nginx
location /api/websocket {
    proxy_pass http://homeassistant:8123;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
}
```

**Caddy**:
```
reverse_proxy /api/websocket homeassistant:8123 {
    header_up Upgrade websocket
    header_up Connection Upgrade
}
```

#### 3. Check Home Assistant Logs

```bash
# Check HA logs for WebSocket issues
docker logs homeassistant | grep -i websocket

# Look for rate limiting
docker logs homeassistant | grep -i "rate limit"
```

#### 4. Verify Authentication

WebSocket uses same token as REST API:

```bash
# Test token with REST API first
curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://homeassistant.local:8123/api/

# If this fails, WebSocket will also fail
```

**Prevention**:
- Use stable network connection
- Avoid rate limiting (don't run multiple HA Boss instances)
- Keep Home Assistant updated

---

### Frequent Disconnections

**Symptoms**:
- WebSocket reconnecting every few minutes
- "Connection lost" messages in logs
- Missed state updates

**Common Causes**:
1. Unreliable network
2. Home Assistant restarting
3. Proxy timeout too short
4. Insufficient resources

**Solutions**:

#### 1. Optimize Reconnection Settings

For unreliable networks:

```yaml
websocket:
  reconnect_delay_seconds: 3  # Faster reconnection
  heartbeat_interval_seconds: 15  # More frequent heartbeat
  timeout_seconds: 15  # Longer timeout
```

For stable networks:

```yaml
websocket:
  reconnect_delay_seconds: 10  # Slower reconnection
  heartbeat_interval_seconds: 60  # Less frequent heartbeat
  timeout_seconds: 10  # Standard timeout
```

#### 2. Check Network Quality

```bash
# Test latency to Home Assistant
ping -c 10 homeassistant.local

# Check for packet loss
mtr homeassistant.local

# Monitor network interface
ifconfig  # or ip link
```

#### 3. Check Home Assistant Stability

```bash
# Check HA uptime
docker exec homeassistant uptime

# Check HA resource usage
docker stats homeassistant

# Review HA logs for crashes
docker logs homeassistant | grep -E "error|crash|restart"
```

#### 4. Increase Proxy Timeouts

If using reverse proxy, increase timeouts:

**Nginx**:
```nginx
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

**Prevention**:
- Use wired connection instead of WiFi
- Monitor network quality
- Keep Home Assistant stable
- Use appropriate timeout values

---

## Authentication Errors

### 401 Unauthorized

**Symptoms**:
- `401 Unauthorized` HTTP errors
- `Authentication failed` messages
- `Invalid token` errors
- HA Boss cannot start

**Common Causes**:
1. Wrong token
2. Token expired (unlikely, default 10 years)
3. Token deleted in Home Assistant
4. Token not properly set in environment

**Diagnostic Commands**:

```bash
# Check if token is set
docker-compose exec haboss env | grep HA_TOKEN

# Check token in config
docker-compose exec haboss haboss config show | grep token

# Test token manually
curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://homeassistant.local:8123/api/states
```

**Solutions**:

#### 1. Regenerate Long-Lived Token

1. Open Home Assistant web interface
2. Go to Profile (bottom left)
3. Scroll to "Long-Lived Access Tokens"
4. Delete old "HA Boss" token (if exists)
5. Click "Create Token"
6. Enter name: `HA Boss`
7. Copy token immediately
8. Update `.env` file:

```bash
# .env
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

9. Restart HA Boss:
```bash
docker-compose restart haboss
```

#### 2. Verify Environment Variable Loading

```bash
# Check .env file exists
ls -la .env

# Verify syntax (no spaces around =)
cat .env | grep HA_TOKEN

# Check variable loaded in container
docker-compose exec haboss env | grep HA_TOKEN

# If empty, check docker-compose.yml
cat docker-compose.yml | grep -A5 environment
```

#### 3. Check Token Format

Token should:
- Start with `eyJ`
- Be very long (hundreds of characters)
- Not contain spaces or line breaks
- Not be wrapped in quotes in `.env`

**Correct**:
```bash
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Incorrect**:
```bash
HA_TOKEN="eyJ..."  # Don't use quotes
HA_TOKEN=eyJ...    # Don't split across lines
  rest_of_token
```

**Prevention**:
- Store token securely (password manager)
- Don't commit `.env` to git (add to `.gitignore`)
- Rotate tokens periodically
- Use separate token for HA Boss (easier to revoke)

---

### Token Expired or Invalid

**Symptoms**:
- Previously working setup now fails with 401
- Token worked before but stopped
- "Token has expired" messages

**Solutions**:

#### 1. Check Token Status in Home Assistant

1. Open Home Assistant → Profile
2. Scroll to "Long-Lived Access Tokens"
3. Check if "HA Boss" token still listed
4. If missing, someone deleted it - create new token
5. If present, token may be corrupted - delete and recreate

#### 2. Test Token Directly

```bash
# Save token to file temporarily
echo "YOUR_TOKEN" > /tmp/token.txt

# Test with curl
curl -H "Authorization: Bearer $(cat /tmp/token.txt)" \
     http://homeassistant.local:8123/api/states

# Clean up
rm /tmp/token.txt
```

Expected response: JSON array of entity states

If this fails:
- Token is invalid
- Token was deleted
- Home Assistant authentication system has issues

#### 3. Create Fresh Token

Always the safest solution when in doubt:

1. Delete old token in HA
2. Create new token
3. Update `.env`
4. Restart HA Boss
5. Verify connection

**Prevention**:
- Document token creation date
- Set calendar reminder to rotate tokens annually
- Keep backup token in secure location
- Monitor Home Assistant for token deletions

---

## Performance Issues

### High Memory Usage

**Symptoms**:
- HA Boss container using excessive RAM (>500MB)
- Out of memory errors
- System becoming slow
- Container killed by OOM

**Diagnostic Commands**:

```bash
# Check container memory usage
docker stats haboss

# Check database size
docker exec haboss ls -lh /data/ha_boss.db

# Check number of monitored entities
docker-compose exec haboss haboss status | grep "Monitoring"

# Check pattern data size
docker-compose exec haboss sqlite3 /data/ha_boss.db "SELECT COUNT(*) FROM health_events;"
```

**Common Causes**:
1. Monitoring too many entities (thousands)
2. Large database (old records not cleaned)
3. Ollama model loaded in memory
4. Memory leak (rare)

**Solutions**:

#### 1. Reduce Monitored Entities

Edit `config/config.yaml`:

```yaml
monitoring:
  # Exclude non-critical entities
  exclude:
    - "sensor.*"  # Exclude all sensors
    - "device_tracker.*"
    - "person.*"

  # Then include only critical ones
  include:
    - "sensor.temperature_*"
    - "sensor.critical_*"
```

Check reduction:
```bash
docker-compose restart haboss
docker-compose exec haboss haboss status
# Should show fewer monitored entities
```

#### 2. Clean Up Database

```bash
# Check current database size
docker exec haboss ls -lh /data/ha_boss.db

# Clean records older than 30 days
docker-compose exec haboss haboss db cleanup --older-than 30

# Vacuum database to reclaim space
docker-compose exec haboss sqlite3 /data/ha_boss.db "VACUUM;"

# Verify size reduction
docker exec haboss ls -lh /data/ha_boss.db
```

#### 3. Reduce Retention Period

Edit `config/config.yaml`:

```yaml
database:
  retention_days: 14  # Reduce from 30 to 14
```

This automatically purges old records daily.

#### 4. Optimize Ollama Usage

If using Ollama LLM:

```bash
# Check Ollama memory usage
docker stats haboss_ollama

# Use smaller model
# Edit config/config.yaml
intelligence:
  ollama_model: "llama3.1:3b"  # Smaller than 8b (uses ~4GB vs 8GB)
```

Or disable Ollama if not needed:

```yaml
intelligence:
  ollama_enabled: false
```

#### 5. Increase Docker Memory Limit

**Docker Desktop**:
1. Open Docker Desktop
2. Settings → Resources → Memory
3. Increase to 8GB+ (was likely 2-4GB)
4. Apply & Restart

**Docker Engine** (Linux):
```bash
# Check current limits
docker info | grep -i memory

# No hard limit by default on Linux
# If using systemd, check unit file:
cat /etc/systemd/system/docker.service.d/override.conf
```

**Prevention**:
- Start with targeted monitoring (`include` specific patterns)
- Set reasonable `retention_days` (14-30 days)
- Run database cleanup weekly
- Monitor memory trends

---

### High CPU Usage

**Symptoms**:
- HA Boss using >50% CPU constantly
- System fan running loudly
- Other services slowing down
- High load average

**Diagnostic Commands**:

```bash
# Check CPU usage
docker stats haboss

# Check what's using CPU inside container
docker exec haboss top

# Check for reconnection loops
docker-compose logs haboss | grep -c "Reconnecting"

# Check health check frequency
docker-compose exec haboss haboss config show | grep interval
```

**Common Causes**:
1. Monitoring too many entities
2. Ollama inference running continuously
3. WebSocket reconnection loop
4. Health check interval too short
5. Database operations

**Solutions**:

#### 1. Reduce Monitored Entities

Same as memory optimization above - use `include`/`exclude` patterns.

#### 2. Check for Reconnection Loop

```bash
# Count reconnections in last hour
docker-compose logs --since 1h haboss | grep -c "WebSocket.*reconnect"

# If > 10, investigate why disconnecting
docker-compose logs haboss | grep -E "disconnect|error|timeout"
```

Fix underlying connection issue (see [WebSocket Connection Problems](#websocket-connection-problems)).

#### 3. Adjust Health Check Interval

Edit `config/config.yaml`:

```yaml
monitoring:
  health_check_interval_seconds: 120  # Increase from 60 to 120
  snapshot_interval_seconds: 600  # Increase from 300 to 600
```

Less frequent checks = lower CPU usage.

#### 4. Check Ollama Usage

```bash
# Is Ollama constantly running inference?
docker stats haboss_ollama

# Check logs for excessive LLM calls
docker-compose logs haboss | grep -i "ollama\|llm"
```

If Ollama running constantly:
- Bug causing infinite LLM loop
- Check GitHub issues
- Disable temporarily: `ollama_enabled: false`

#### 5. Database Optimization

```bash
# Check for slow queries
# Enable query logging temporarily
docker-compose exec haboss haboss config show | grep echo

# Edit config/config.yaml
database:
  echo: true  # Enable SQL logging

# Restart and check logs
docker-compose restart haboss
docker-compose logs haboss | grep SELECT

# Disable after investigation
database:
  echo: false
```

**Prevention**:
- Monitor resource usage trends
- Set appropriate check intervals
- Use targeted entity monitoring
- Keep database clean

---

### Slow Response Times

**Symptoms**:
- Slow CLI commands
- Delayed healing actions
- Notifications arrive late
- Dashboard updates slowly

**Diagnostic Commands**:

```bash
# Test response time
time docker-compose exec haboss haboss status

# Check database response
time docker-compose exec haboss sqlite3 /data/ha_boss.db "SELECT COUNT(*) FROM entities;"

# Check Home Assistant response
time curl http://homeassistant.local:8123/api/states

# Check disk I/O
docker exec haboss df -h
docker exec haboss iostat  # If available
```

**Common Causes**:
1. Large database
2. Slow disk I/O
3. Home Assistant slow to respond
4. Network latency
5. Resource contention

**Solutions**:

#### 1. Optimize Database

```bash
# Vacuum database
docker-compose exec haboss sqlite3 /data/ha_boss.db "VACUUM;"

# Analyze tables
docker-compose exec haboss sqlite3 /data/ha_boss.db "ANALYZE;"

# Check database size
docker exec haboss ls -lh /data/ha_boss.db

# If very large (>100MB), reduce retention
```

#### 2. Move to Faster Storage

If using HDD, move to SSD:

```bash
# Stop HA Boss
docker-compose down

# Move data directory to SSD
mv ./data /mnt/ssd/ha_boss_data

# Update volume mount in docker-compose.yml
volumes:
  - /mnt/ssd/ha_boss_data:/data

# Start HA Boss
docker-compose up -d
```

#### 3. Check Network Latency

```bash
# Test latency to Home Assistant
ping -c 10 homeassistant.local

# If high latency (>100ms), investigate network
# - Check WiFi signal strength
# - Use wired connection
# - Check router performance
```

#### 4. Increase Timeout Values

If operations timing out:

```yaml
rest:
  timeout_seconds: 30  # Increase from 10
  retry_attempts: 5

websocket:
  timeout_seconds: 20  # Increase from 10
```

**Prevention**:
- Use SSD storage for database
- Keep database size reasonable
- Monitor performance trends
- Use wired network connection

---

## Healing Issues

### Entities Not Being Healed

**Symptoms**:
- Unavailable entities remain unavailable
- No healing attempts logged
- Entities detected but not healed
- Silent failures

**Diagnostic Commands**:

```bash
# Check healing status
docker-compose exec haboss haboss status

# Check recent healing actions
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT * FROM healing_actions ORDER BY attempted_at DESC LIMIT 10;"

# Check if healing enabled
docker-compose exec haboss haboss config show | grep -A5 healing

# Check circuit breaker status
docker-compose logs haboss | grep -i "circuit breaker"

# Check cooldown status
docker-compose logs haboss | grep -i "cooldown"
```

**Common Causes**:
1. Healing disabled in config
2. Circuit breaker tripped
3. Cooldown period active
4. Entity excluded from monitoring
5. Dry-run mode enabled

**Solutions**:

#### 1. Verify Healing Enabled

```bash
# Check config
docker-compose exec haboss haboss config show | grep enabled

# Should show:
# healing:
#   enabled: true
```

If disabled, edit `config/config.yaml`:

```yaml
healing:
  enabled: true
```

Restart:
```bash
docker-compose restart haboss
```

#### 2. Check Circuit Breaker

```bash
# Check logs for circuit breaker messages
docker-compose logs haboss | grep -i "circuit breaker"

# Example: "Circuit breaker tripped after 10 failures"
```

Reset by restarting:
```bash
docker-compose restart haboss
```

Or adjust threshold in `config/config.yaml`:
```yaml
healing:
  circuit_breaker_threshold: 20  # Increase from 10
  circuit_breaker_reset_seconds: 1800  # Reset after 30 min
```

#### 3. Check Cooldown Period

```bash
# Check logs
docker-compose logs haboss | grep -i cooldown

# Example: "Integration 'esphome' in cooldown period"
```

Wait for cooldown to expire, or reduce in config:

```yaml
healing:
  cooldown_seconds: 180  # Reduce from 300 (5 min → 3 min)
```

#### 4. Verify Entity Monitored

```bash
# Check if entity is monitored
docker-compose exec haboss haboss status

# List monitored entities
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT entity_id FROM entities ORDER BY entity_id;"

# Check if entity excluded
docker-compose exec haboss haboss config show | grep -A10 exclude
```

If entity excluded, remove from `exclude` list or add to `include` list.

#### 5. Check Operational Mode

```bash
# Check mode
docker-compose exec haboss haboss config show | grep mode
```

If `mode: "dry_run"`, healing is simulated but not executed.

Change to production:
```yaml
mode: "production"
```

**Prevention**:
- Monitor healing success rates
- Review circuit breaker thresholds
- Check logs regularly
- Use appropriate cooldown periods

---

### Healing Attempts Failing

**Symptoms**:
- Healing attempted but fails
- "Integration reload failed" messages
- Entities remain unavailable after healing
- Error messages in logs

**Diagnostic Commands**:

```bash
# Check recent healing failures
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT * FROM healing_actions WHERE success = 0 ORDER BY attempted_at DESC LIMIT 10;"

# Check specific error messages
docker-compose logs haboss | grep -A5 "healing.*fail"

# Test manual healing
docker-compose exec haboss haboss heal sensor.test_entity --dry-run

# Check Home Assistant logs
docker logs homeassistant | grep -i reload
```

**Common Causes**:
1. Integration doesn't support reload
2. Home Assistant service call failing
3. Permissions issue
4. Integration in bad state
5. Network issues during reload

**Solutions**:

#### 1. Check Integration Compatibility

Not all integrations support reload. Check Home Assistant documentation:

```bash
# Check if integration supports reload
# Look in Home Assistant logs
docker logs homeassistant | grep "reload"

# Some integrations require full restart instead
```

If integration doesn't support reload:
- Exclude entities from that integration
- Manually restart Home Assistant when needed

#### 2. Verify Service Call Permissions

HA Boss needs permission to call `homeassistant.reload_config_entry`:

```bash
# Test service call manually in HA Developer Tools
# Services → homeassistant.reload_config_entry
# This should work with your token
```

If fails with permission error:
- Token might have limited permissions
- Check Home Assistant user account settings

#### 3. Check Integration State

```bash
# View integration status in Home Assistant
# Settings → Devices & Services → Integrations

# Check if integration shows errors
# If yes, fix root cause first before healing can work
```

Common issues:
- API key expired
- Device offline
- Configuration error

#### 4. Increase Retry Attempts

Some integrations need multiple reload attempts:

```yaml
healing:
  max_attempts: 5  # Increase from 3
  retry_base_delay_seconds: 2.0  # Longer delays
```

#### 5. Check Service Call Logs

```bash
# Enable debug logging
# Edit config/config.yaml
logging:
  level: "DEBUG"

# Restart and watch logs
docker-compose restart haboss
docker-compose logs -f haboss | grep -i "service call"
```

**Prevention**:
- Test healing manually before relying on automation
- Monitor healing success rates
- Keep integrations healthy
- Review HA Boss and Home Assistant logs

---

### Healing Loops

**Symptoms**:
- Same entity healed repeatedly
- Integration reloaded every few minutes
- High healing attempt count
- Circuit breaker tripping frequently

**Diagnostic Commands**:

```bash
# Check healing frequency
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT entity_id, COUNT(*) as attempts FROM healing_actions GROUP BY entity_id ORDER BY attempts DESC;"

# Check time between healing attempts
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT entity_id, attempted_at FROM healing_actions ORDER BY attempted_at DESC LIMIT 20;"

# Check logs for pattern
docker-compose logs haboss | grep -E "Healing|unavailable" | tail -50
```

**Common Causes**:
1. Underlying issue not fixed by reload
2. Entity becomes unavailable immediately after heal
3. Grace period too short
4. Cooldown too short
5. Integration fundamentally broken

**Solutions**:

#### 1. Increase Grace Period

Give entity more time before marking unavailable:

```yaml
monitoring:
  grace_period_seconds: 600  # Increase from 300 (5 min → 10 min)
```

#### 2. Increase Cooldown

Prevent rapid retry attempts:

```yaml
healing:
  cooldown_seconds: 600  # Increase from 300 (5 min → 10 min)
```

#### 3. Reduce Max Attempts

Limit healing attempts per integration:

```yaml
healing:
  max_attempts: 2  # Reduce from 3
```

#### 4. Exclude Problematic Entity

If specific entity causes loops:

```yaml
monitoring:
  exclude:
    - "sensor.problematic_entity"
    - "binary_sensor.broken_*"
```

#### 5. Fix Root Cause

Healing loop indicates underlying issue:

```bash
# Check entity/integration in Home Assistant
# Settings → Devices & Services → Integrations

# Common issues:
# - Device offline permanently
# - API credentials expired
# - Integration misconfigured
# - Network unreachable
```

Fix the root cause, then re-enable monitoring.

**Prevention**:
- Start with conservative settings (long grace, cooldown)
- Monitor healing patterns
- Fix integration issues promptly
- Exclude broken integrations

---

### Circuit Breaker Tripped

**Symptoms**:
- "Circuit breaker tripped" in logs
- Healing stops completely
- High failure count
- No healing attempts after threshold

**Diagnostic Commands**:

```bash
# Check circuit breaker status
docker-compose logs haboss | grep -i "circuit breaker"

# Check failure count
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT COUNT(*) FROM healing_actions WHERE success = 0;"

# Check when last failure occurred
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT MAX(attempted_at) FROM healing_actions WHERE success = 0;"
```

**Solutions**:

#### 1. Reset Circuit Breaker

Restart HA Boss to reset:

```bash
docker-compose restart haboss
```

Circuit breaker resets on restart.

#### 2. Wait for Automatic Reset

Circuit breaker automatically resets after `circuit_breaker_reset_seconds`:

```bash
# Check reset time
docker-compose exec haboss haboss config show | grep circuit_breaker_reset

# Default: 3600 seconds (1 hour)
```

#### 3. Increase Threshold

If hitting limit too easily:

```yaml
healing:
  circuit_breaker_threshold: 20  # Increase from 10
  circuit_breaker_reset_seconds: 1800  # Reset after 30 min
```

#### 4. Investigate Root Cause

Circuit breaker tripping indicates systemic issues:

```bash
# Check which integrations failing
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT entity_id, COUNT(*) as failures FROM healing_actions WHERE success = 0 GROUP BY entity_id;"

# Check error patterns
docker-compose logs haboss | grep -i error | tail -50
```

Fix underlying issues before increasing threshold.

**Prevention**:
- Monitor failure trends
- Fix integration issues promptly
- Set appropriate threshold
- Review logs regularly

---

## AI/LLM Issues

### Ollama Not Available

**Symptoms**:
- "Ollama not available" in logs
- AI features disabled
- Notifications without AI insights
- LLM router shows no available LLMs

**Diagnostic Commands**:

```bash
# Check if Ollama container running
docker ps | grep ollama

# Check Ollama logs
docker logs haboss_ollama

# Test Ollama API from host
curl http://localhost:11434/api/tags

# Test from HA Boss container
docker-compose exec haboss curl http://ollama:11434/api/tags

# Check Ollama models
docker exec haboss_ollama ollama list

# Verify HA Boss configuration
docker-compose exec haboss haboss config show | grep -A5 ollama
```

**Common Causes**:
1. Ollama container not running
2. Model not downloaded
3. Wrong Ollama URL in config
4. Network connectivity between containers
5. Ollama startup failure

**Solutions**:

#### 1. Start Ollama Container

```bash
# Check if Ollama service defined
cat docker-compose.yml | grep -A10 ollama

# Start Ollama
docker-compose up -d ollama

# Check status
docker ps | grep ollama
```

#### 2. Download Model

```bash
# Pull recommended model
docker exec haboss_ollama ollama pull llama3.1:8b

# Verify download
docker exec haboss_ollama ollama list

# Should show:
# NAME              ID              SIZE
# llama3.1:8b       abc123          4.6 GB
```

#### 3. Fix Ollama URL

**Docker Compose** - use service name:

```yaml
# config/config.yaml
intelligence:
  ollama_url: "http://ollama:11434"  # NOT localhost
```

**Local Ollama** - use localhost:

```yaml
intelligence:
  ollama_url: "http://localhost:11434"
```

Restart after config change:
```bash
docker-compose restart haboss
```

#### 4. Check Network Connectivity

```bash
# From HA Boss container, test Ollama
docker-compose exec haboss curl http://ollama:11434/api/tags

# Should return JSON with model list
```

If fails, check network:

```bash
# Verify both on same network
docker network inspect haboss_default | grep -A5 ollama
docker network inspect haboss_default | grep -A5 haboss

# Ensure depends_on in docker-compose.yml
cat docker-compose.yml | grep -B5 -A2 depends_on
```

#### 5. Check Ollama Startup

```bash
# Check Ollama logs for errors
docker logs haboss_ollama | grep -i error

# Common issues:
# - Port 11434 already in use
# - Insufficient disk space
# - Permissions issues
```

**Prevention**:
- Use `depends_on: ollama` in docker-compose.yml
- Pull models after first setup
- Verify network configuration
- Monitor Ollama health

---

### Slow LLM Responses

**Symptoms**:
- AI operations take >30 seconds
- Timeouts waiting for LLM
- "LLM request timed out" errors
- Notifications delayed

**Diagnostic Commands**:

```bash
# Check Ollama resource usage
docker stats haboss_ollama

# Check CPU/GPU usage
docker exec haboss_ollama nvidia-smi  # If GPU available

# Test Ollama response time
time docker exec haboss_ollama ollama run llama3.1:8b "Hello"

# Check HA Boss LLM timeout setting
docker-compose exec haboss haboss config show | grep timeout
```

**Common Causes**:
1. CPU-only inference (no GPU)
2. Model too large for hardware
3. Insufficient RAM
4. CPU throttling
5. Other processes competing

**Expected Performance** (CPU mode):
- Short responses (150 tokens): 11-15 seconds
- Medium responses (300 tokens): 20-30 seconds
- Long responses (600 tokens): 50-70 seconds

**Solutions**:

#### 1. Use Smaller/Faster Model

```yaml
# config/config.yaml
intelligence:
  ollama_model: "mistral:7b"  # Faster than llama3.1:8b
  # or
  ollama_model: "llama3.1:3b"  # Even faster, lower quality
```

Download new model:
```bash
docker exec haboss_ollama ollama pull mistral:7b
docker-compose restart haboss
```

#### 2. Increase Timeout

If responses just need more time:

```yaml
intelligence:
  ollama_timeout_seconds: 60  # Increase from 30
```

#### 3. Enable GPU Acceleration

See [Issue #52](https://github.com/jasonthagerty/ha_boss/issues/52) for GPU setup.

For Intel ARC GPU:

```yaml
# docker-compose.yml
services:
  ollama:
    devices:
      - /dev/dri:/dev/dri  # Intel GPU
    environment:
      - OLLAMA_GPU=1
```

#### 4. Reduce LLM Usage

```yaml
notifications:
  ai_enhanced: false  # Disable AI in notifications
```

Or use LLM selectively:
- Keep enabled for weekly summaries (background task)
- Disable for real-time notifications

#### 5. Check Resource Availability

```bash
# Check RAM usage
free -h

# Check CPU load
uptime

# Check if other processes competing
top

# Check disk I/O wait
iostat
```

Close unnecessary processes or upgrade hardware.

**Prevention**:
- Use appropriate model size for hardware
- Monitor LLM performance trends
- Consider GPU if frequent LLM usage
- Set realistic timeout values

---

### Claude API Errors

**Symptoms**:
- "Claude API authentication failed"
- "Rate limit exceeded"
- "Claude API error" messages
- Automation generation fails

**Diagnostic Commands**:

```bash
# Check if Claude API key set
docker-compose exec haboss env | grep CLAUDE

# Check Claude configuration
docker-compose exec haboss haboss config show | grep -A5 claude

# Check logs for Claude errors
docker-compose logs haboss | grep -i claude

# Verify API key valid (from host)
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-5-sonnet-20241022","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
```

**Common Causes**:
1. Invalid or missing API key
2. API key expired
3. Rate limit exceeded
4. Billing issue
5. Network connectivity to Anthropic

**Solutions**:

#### 1. Verify API Key

Check key is set correctly:

```bash
# View .env (be careful - contains secrets)
cat .env | grep CLAUDE

# Should show:
# CLAUDE_API_KEY=sk-ant-...
```

If missing or wrong:

1. Go to https://console.anthropic.com
2. API Keys → Create Key
3. Copy key (starts with `sk-ant-`)
4. Update `.env`:

```bash
CLAUDE_API_KEY=sk-ant-api03-your-new-key
```

5. Restart:
```bash
docker-compose restart haboss
```

#### 2. Check API Key Permissions

1. Go to https://console.anthropic.com/settings/keys
2. Verify key has necessary permissions:
   - Read access
   - Write access
3. Check expiration date (if set)

#### 3. Check Rate Limits

1. Go to https://console.anthropic.com/settings/limits
2. Check current usage vs. limits
3. If exceeded, wait for reset or upgrade plan

Rate limits vary by plan:
- Free tier: Very limited
- Pay-as-you-go: Higher limits

#### 4. Check Billing Status

1. Go to https://console.anthropic.com/settings/billing
2. Verify credit card on file
3. Check for payment failures
4. Ensure credits available (if prepaid)

#### 5. Disable Claude if Not Needed

If Claude causing issues and not critical:

```yaml
intelligence:
  claude_enabled: false  # Disable Claude
```

You'll lose automation generation but keep local Ollama features.

**Prevention**:
- Set billing alerts at console.anthropic.com
- Monitor usage regularly
- Keep API key secure
- Rotate keys periodically

---

### AI Features Not Working

**Symptoms**:
- Notifications missing AI insights
- No AI enhancements visible
- Weekly summaries plain text only
- LLM router shows "NO available LLMs"

**Diagnostic Commands**:

```bash
# Check AI configuration
docker-compose exec haboss haboss config show | grep -A20 intelligence

# Check LLM router status in logs
docker-compose logs haboss | grep -i "LLM Router"

# Check if any LLM available
docker-compose logs haboss | grep -E "Ollama.*initialized|Claude.*initialized"

# Test Ollama
curl http://localhost:11434/api/tags

# Test Claude
docker-compose exec haboss env | grep CLAUDE
```

**Checklist**:

```bash
# 1. Is ai_enhanced enabled?
docker-compose exec haboss haboss config show | grep ai_enhanced
# Should show: ai_enhanced: true

# 2. Is at least one LLM enabled?
docker-compose exec haboss haboss config show | grep -E "ollama_enabled|claude_enabled"
# At least one should be: true

# 3. Is LLM service running?
docker ps | grep ollama  # If using Ollama
docker-compose exec haboss env | grep CLAUDE_API_KEY  # If using Claude

# 4. Are models available?
docker exec haboss_ollama ollama list  # If using Ollama

# 5. Any errors in logs?
docker-compose logs haboss | grep -i error
```

**Solutions**:

#### 1. Enable AI Features

Edit `config/config.yaml`:

```yaml
notifications:
  ai_enhanced: true  # Enable AI in notifications

intelligence:
  ollama_enabled: true  # Enable Ollama
  ollama_url: "http://ollama:11434"
  ollama_model: "llama3.1:8b"
```

#### 2. Verify LLM Service

For Ollama:
```bash
# Start Ollama
docker-compose up -d ollama

# Pull model
docker exec haboss_ollama ollama pull llama3.1:8b

# Verify
docker exec haboss_ollama ollama list
```

For Claude:
```bash
# Set API key in .env
echo "CLAUDE_API_KEY=sk-ant-your-key" >> .env

# Enable in config
# intelligence:
#   claude_enabled: true

# Restart
docker-compose restart haboss
```

#### 3. Check Graceful Degradation

If LLM unavailable, HA Boss falls back to simple notifications:

```bash
# Check logs
docker-compose logs haboss | grep -i "fallback\|degraded"

# You'll see:
# "LLM not available, using fallback notification"
```

This is expected if:
- Ollama not running
- Model not downloaded
- Claude API key missing

#### 4. Test LLM Manually

```bash
# Test Ollama
docker exec haboss_ollama ollama run llama3.1:8b "Say hello"

# Should get response in 5-15 seconds
```

If this works, HA Boss should be able to use it.

**Prevention**:
- Verify LLM setup during initial deployment
- Monitor LLM availability
- Check logs after configuration changes
- Test features manually

---

## Docker Issues

### Container Won't Start

**Symptoms**:
- `docker-compose up` fails immediately
- Container exits with error code
- "Cannot start container" errors
- Health check never passes

**Diagnostic Commands**:

```bash
# Check container status
docker-compose ps

# View startup logs
docker-compose logs haboss

# Check exit code
docker inspect haboss | grep -A5 State

# View last container logs (even if stopped)
docker logs haboss

# Check docker-compose config
docker-compose config
```

**Common Causes**:
1. Configuration error
2. Missing environment variables
3. Port conflict
4. Volume mount issues
5. Image pull failure

**Solutions**:

#### 1. Check Configuration Errors

```bash
# Validate config first
docker-compose exec haboss haboss config validate

# Or check logs for validation errors
docker-compose logs haboss | grep -i "error\|failed"
```

Common errors:
- `HA_TOKEN not set`
- `Invalid URL format`
- `Field required`

Fix in `.env` or `config.yaml`, then:
```bash
docker-compose restart haboss
```

#### 2. Verify Environment Variables

```bash
# Check .env file exists
ls -la .env

# Verify required variables
cat .env | grep -E "HA_URL|HA_TOKEN"

# Check variables loaded
docker-compose config | grep -A5 environment
```

#### 3. Check Port Conflicts

```bash
# Check if port in use
sudo lsof -i :8080  # Or whatever port HA Boss uses

# Or
sudo netstat -tulpn | grep 8080
```

If port in use, change in docker-compose.yml:
```yaml
services:
  haboss:
    ports:
      - "8081:8080"  # Use 8081 instead
```

#### 4. Fix Volume Mount Issues

```bash
# Check data directory exists and is writable
ls -la ./data

# If missing, create it
mkdir -p ./data ./config

# Check ownership
ls -la ./data

# Fix permissions
chmod 755 ./data
# Container runs as UID 1000 by default
chown 1000:1000 ./data
```

#### 5. Pull Latest Image

```bash
# Update image
docker-compose pull haboss

# Rebuild if using local Dockerfile
docker-compose build --no-cache haboss

# Start fresh
docker-compose up -d haboss
```

**Prevention**:
- Validate configuration before deploying
- Check logs during startup
- Use `docker-compose config` to verify syntax
- Test with minimal configuration first

---

### Container Keeps Restarting

**Symptoms**:
- Container starts, then exits repeatedly
- Restart loop every few seconds
- Status shows "Restarting (1) X seconds ago"
- Health check failing

**Diagnostic Commands**:

```bash
# Watch restart loop
watch docker-compose ps

# Check restart count
docker inspect haboss | grep -A5 RestartCount

# View logs for crash pattern
docker-compose logs --tail=200 haboss

# Check for specific error patterns
docker-compose logs haboss | grep -E "Error|Exception|Traceback"
```

**Common Causes**:
1. Cannot connect to Home Assistant
2. Invalid token
3. Database corruption
4. Python exception/crash
5. Memory limit exceeded

**Solutions**:

#### 1. Check Logs for Root Cause

```bash
# View full logs
docker-compose logs haboss

# Look for error before restart:
# Common patterns:
# - "Connection refused" → HA URL wrong
# - "401 Unauthorized" → Token invalid
# - "Database locked" → Database issue
# - "Traceback" → Python error
```

#### 2. Fix Home Assistant Connection

```bash
# Test connectivity
docker-compose exec haboss curl http://your-ha-url:8123/api/

# If fails, fix HA_URL in .env
# macOS/Windows: http://host.docker.internal:8123
# Linux: http://192.168.x.x:8123
```

#### 3. Regenerate Token

See [Authentication Errors](#authentication-errors) section.

#### 4. Reset Database

If database corrupt:

```bash
# Stop container
docker-compose down

# Backup current database
docker cp haboss:/data/ha_boss.db ./backup_ha_boss.db

# Remove corrupt database
docker volume rm haboss_data
# Or: rm ./data/ha_boss.db

# Start fresh
docker-compose up -d haboss

# Database will be recreated
```

#### 5. Check Memory Limits

```bash
# Check if OOM killed
docker inspect haboss | grep -i oom

# Increase memory limit in docker-compose.yml
services:
  haboss:
    mem_limit: 1g  # Increase if needed
```

#### 6. Temporary Disable Auto-Restart

For troubleshooting, change restart policy:

```yaml
services:
  haboss:
    restart: "no"  # Temporarily disable restart
```

Container will stay stopped after crash, allowing investigation:

```bash
docker logs haboss  # View crash logs
```

**Prevention**:
- Monitor logs for patterns
- Ensure stable HA connection
- Test configuration in dry-run mode
- Keep database healthy

---

### Permission Denied Errors

**Symptoms**:
- "Permission denied" when accessing database
- "Cannot create file" errors
- "Operation not permitted"
- Container exits with permission error

**Diagnostic Commands**:

```bash
# Check data directory permissions
ls -la ./data

# Check ownership
stat ./data/ha_boss.db

# Check container user
docker exec haboss id

# Check file permissions in container
docker exec haboss ls -la /data
```

**Common Causes**:
1. Data directory owned by root
2. Wrong UID/GID in container
3. Volume mount permissions
4. SELinux/AppArmor restrictions

**Solutions**:

#### 1. Fix Data Directory Ownership

HA Boss container runs as UID 1000, GID 1000:

```bash
# Stop container
docker-compose down

# Fix ownership
sudo chown -R 1000:1000 ./data ./config

# Verify
ls -la ./data

# Should show:
# drwxr-xr-x 1000 1000 data/

# Start container
docker-compose up -d
```

#### 2. Fix Permissions

```bash
# Make data directory writable
chmod 755 ./data

# Make database writable
chmod 644 ./data/ha_boss.db
```

#### 3. Check Volume Mount

If using named volume:

```bash
# Inspect volume
docker volume inspect haboss_data

# Check volume mountpoint permissions
ls -la $(docker volume inspect haboss_data -f '{{.Mountpoint}}')

# Fix if needed
sudo chown -R 1000:1000 $(docker volume inspect haboss_data -f '{{.Mountpoint}}')
```

#### 4. SELinux Context (Linux only)

If using SELinux:

```bash
# Check SELinux status
getenforce

# Add proper context to data directory
sudo chcon -R -t svirt_sandbox_file_t ./data

# Or disable SELinux temporarily for testing
sudo setenforce 0
```

#### 5. Use Docker Volume Instead

Instead of bind mount, use named volume:

```yaml
# docker-compose.yml
services:
  haboss:
    volumes:
      - haboss_data:/data  # Named volume instead of ./data

volumes:
  haboss_data:  # Docker manages permissions
```

**Prevention**:
- Use consistent UID/GID
- Set proper permissions initially
- Use named volumes for production
- Document permission requirements

---

### Networking Problems

**Symptoms**:
- Cannot reach Home Assistant from container
- Cannot reach Ollama from HA Boss
- DNS resolution failures
- "Network unreachable" errors

**Diagnostic Commands**:

```bash
# Check networks
docker network ls

# Inspect HA Boss network
docker network inspect haboss_default

# Test DNS resolution
docker-compose exec haboss nslookup homeassistant.local

# Test connectivity
docker-compose exec haboss ping -c 3 homeassistant.local

# Test HTTP connectivity
docker-compose exec haboss curl -v http://homeassistant.local:8123/api/

# Check routing
docker-compose exec haboss ip route
```

**Common Causes**:
1. Containers on different networks
2. DNS resolution failing
3. Firewall blocking
4. Docker networking issues
5. Wrong host.docker.internal usage

**Solutions**:

#### 1. Ensure Same Network

Check docker-compose.yml:

```yaml
services:
  haboss:
    networks:
      - haboss-network

  ollama:
    networks:
      - haboss-network

  homeassistant:  # If in same compose
    networks:
      - haboss-network

networks:
  haboss-network:
    driver: bridge
```

#### 2. Use Service Names

In Docker Compose, use service names instead of localhost:

```yaml
# config/config.yaml
intelligence:
  ollama_url: "http://ollama:11434"  # NOT localhost
```

```bash
# .env
HA_URL=http://homeassistant:8123  # If in same compose
```

#### 3. Use host.docker.internal (Mac/Windows)

For services on host machine:

```bash
# .env
HA_URL=http://host.docker.internal:8123
OLLAMA_URL=http://host.docker.internal:11434
```

Note: `host.docker.internal` only works on Docker Desktop (Mac/Windows).

#### 4. Use Host IP (Linux)

On Linux, use actual host IP:

```bash
# Find host IP
ip addr show docker0 | grep inet

# .env
HA_URL=http://172.17.0.1:8123  # Docker bridge IP
# or
HA_URL=http://192.168.1.100:8123  # Host LAN IP
```

#### 5. Join External Network

If Home Assistant in separate compose:

```yaml
# docker-compose.yml
services:
  haboss:
    networks:
      - homeassistant-network

networks:
  homeassistant-network:
    external: true  # Already exists
```

```bash
# Use HA service name
HA_URL=http://homeassistant:8123
```

#### 6. Check DNS

If DNS failing:

```yaml
# docker-compose.yml
services:
  haboss:
    dns:
      - 8.8.8.8  # Google DNS
      - 8.8.4.4
```

Or use IP address instead of hostname.

**Prevention**:
- Use consistent network configuration
- Document network topology
- Test connectivity before deployment
- Use service names in Docker Compose

---

## Database Issues

### Database Corruption

**Symptoms**:
- "Database disk image is malformed"
- "Database is locked"
- SQLite errors in logs
- Container crashes with database error

**Diagnostic Commands**:

```bash
# Check database integrity
docker-compose exec haboss sqlite3 /data/ha_boss.db "PRAGMA integrity_check;"

# Should return: ok

# Check database info
docker-compose exec haboss sqlite3 /data/ha_boss.db ".dbinfo"

# Attempt recovery
docker-compose exec haboss sqlite3 /data/ha_boss.db ".recover" > recovered.sql
```

**Solutions**:

#### 1. Run Integrity Check

```bash
docker-compose exec haboss sqlite3 /data/ha_boss.db "PRAGMA integrity_check;"
```

If returns errors:
- Database is corrupt
- Needs recovery

#### 2. Backup Current Database

```bash
# Stop container
docker-compose down

# Backup database
docker cp haboss:/data/ha_boss.db ./backup_ha_boss_corrupt.db
# Or: cp ./data/ha_boss.db ./backup_ha_boss_corrupt.db
```

#### 3. Attempt Recovery

```bash
# Try to dump database
docker-compose exec haboss sqlite3 /data/ha_boss.db ".dump" > recovery.sql

# Create new database from dump
docker-compose exec haboss sqlite3 /data/ha_boss_new.db < recovery.sql

# Replace old database
docker-compose down
mv ./data/ha_boss.db ./data/ha_boss_old.db
mv ./data/ha_boss_new.db ./data/ha_boss.db

# Start container
docker-compose up -d
```

#### 4. Start Fresh Database

If recovery fails:

```bash
# Stop container
docker-compose down

# Move corrupt database
mv ./data/ha_boss.db ./data/ha_boss_corrupt_$(date +%Y%m%d).db

# Start container (creates new DB)
docker-compose up -d

# Database will be empty but functional
```

You'll lose historical data but HA Boss will function.

#### 5. Restore from Backup

If you have backups:

```bash
# Stop container
docker-compose down

# Restore backup
cp ./backup/ha_boss_YYYYMMDD.db ./data/ha_boss.db

# Fix permissions
chown 1000:1000 ./data/ha_boss.db

# Start container
docker-compose up -d
```

**Prevention**:
- Regular database backups (weekly)
- Graceful container shutdown (`docker-compose down` not `kill`)
- Monitor disk health
- Avoid force-killing container

**Backup Script**:

```bash
#!/bin/bash
# backup_haboss.sh

BACKUP_DIR="./backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

docker exec haboss sqlite3 /data/ha_boss.db ".backup /data/backup.db"
docker cp haboss:/data/backup.db "$BACKUP_DIR/ha_boss_$DATE.db"
docker exec haboss rm /data/backup.db

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/ha_boss_*.db | tail -n +8 | xargs rm -f

echo "Backup created: $BACKUP_DIR/ha_boss_$DATE.db"
```

Run weekly via cron:
```bash
# crontab -e
0 2 * * 0 /path/to/backup_haboss.sh
```

---

### Database Growing Too Large

**Symptoms**:
- Database file >100MB
- Slow queries
- High disk I/O
- Disk space warnings

**Diagnostic Commands**:

```bash
# Check database size
docker exec haboss ls -lh /data/ha_boss.db

# Check record counts
docker-compose exec haboss sqlite3 /data/ha_boss.db <<EOF
SELECT 'health_events', COUNT(*) FROM health_events
UNION ALL
SELECT 'healing_actions', COUNT(*) FROM healing_actions
UNION ALL
SELECT 'entities', COUNT(*) FROM entities;
EOF

# Check oldest records
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT MIN(detected_at) FROM health_events;"

# Check retention setting
docker-compose exec haboss haboss config show | grep retention
```

**Expected Sizes**:
- Fresh database: <1MB
- After 1 week: 5-20MB
- After 1 month: 10-50MB
- After 3 months: 30-150MB

If significantly larger, investigate.

**Solutions**:

#### 1. Run Database Cleanup

```bash
# Clean records older than 30 days
docker-compose exec haboss haboss db cleanup --older-than 30

# Vacuum database to reclaim space
docker-compose exec haboss sqlite3 /data/ha_boss.db "VACUUM;"

# Check new size
docker exec haboss ls -lh /data/ha_boss.db
```

#### 2. Reduce Retention Period

Edit `config/config.yaml`:

```yaml
database:
  retention_days: 14  # Reduce from 30 to 14
```

Cleanup runs automatically daily at 02:00.

#### 3. Reduce Monitored Entities

Fewer entities = fewer records:

```yaml
monitoring:
  include:
    - "light.*"  # Only monitor specific domains
    - "switch.*"
  exclude:
    - "sensor.*"  # Exclude noisy domains
```

#### 4. Aggressive Cleanup

For very large databases:

```bash
# Clean all but last 7 days
docker-compose exec haboss haboss db cleanup --older-than 7

# Vacuum
docker-compose exec haboss sqlite3 /data/ha_boss.db "VACUUM;"

# Analyze for query optimization
docker-compose exec haboss sqlite3 /data/ha_boss.db "ANALYZE;"
```

#### 5. Archive and Reset

For databases >500MB:

```bash
# Stop container
docker-compose down

# Archive old database
tar -czf ha_boss_archive_$(date +%Y%m%d).tar.gz ./data/ha_boss.db

# Start fresh
rm ./data/ha_boss.db

# Start container
docker-compose up -d
```

**Prevention**:
- Set reasonable retention (14-30 days)
- Use targeted entity monitoring
- Run regular cleanups
- Monitor database size trends

**Monitoring Script**:

```bash
#!/bin/bash
# check_db_size.sh

SIZE=$(docker exec haboss stat -f%z /data/ha_boss.db 2>/dev/null || \
       docker exec haboss stat -c%s /data/ha_boss.db)
SIZE_MB=$((SIZE / 1024 / 1024))

echo "Database size: ${SIZE_MB}MB"

if [ "$SIZE_MB" -gt 200 ]; then
    echo "WARNING: Database exceeds 200MB, consider cleanup"
fi
```

---

### Migration Errors

**Symptoms**:
- "Migration failed" errors on startup
- "Database schema version mismatch"
- Container fails to start after update
- Table/column doesn't exist errors

**Note**: HA Boss currently uses automatic schema creation (no formal migrations). Future versions may include Alembic migrations.

**Diagnostic Commands**:

```bash
# Check database schema
docker-compose exec haboss sqlite3 /data/ha_boss.db ".schema"

# Check tables
docker-compose exec haboss sqlite3 /data/ha_boss.db ".tables"

# Check for migration table (future)
docker-compose exec haboss sqlite3 /data/ha_boss.db \
  "SELECT * FROM alembic_version;" 2>/dev/null
```

**Solutions**:

#### 1. Backup Database

Always backup before fixing:

```bash
docker cp haboss:/data/ha_boss.db ./backup_before_fix.db
```

#### 2. Check HA Boss Version

```bash
# Check image version
docker inspect haboss | grep -i version

# Pull latest version
docker-compose pull haboss

# Restart
docker-compose up -d
```

#### 3. Manual Schema Update

If specific table missing:

```bash
# Add table manually
docker-compose exec haboss sqlite3 /data/ha_boss.db <<EOF
CREATE TABLE IF NOT EXISTS new_table (
    id INTEGER PRIMARY KEY,
    field TEXT
);
EOF
```

Contact project maintainers for correct schema.

#### 4. Start Fresh Database

Last resort:

```bash
# Stop container
docker-compose down

# Rename old database
mv ./data/ha_boss.db ./data/ha_boss_old.db

# Start container (creates new DB with current schema)
docker-compose up -d
```

**Prevention**:
- Follow upgrade guides
- Backup before updates
- Test updates in staging environment
- Monitor GitHub releases for breaking changes

---

## Configuration Issues

### Configuration Not Loading

**Symptoms**:
- Changes to config.yaml not taking effect
- Settings reverting to defaults
- Wrong values displayed in `haboss config show`

**Diagnostic Commands**:

```bash
# Check config file location
docker exec haboss ls -la /config/

# Verify config file content
docker exec haboss cat /config/config.yaml

# Check environment variables
docker-compose exec haboss env | grep -E "HA_|LOG_|MODE"

# Validate configuration
docker-compose exec haboss haboss config validate

# Show loaded configuration
docker-compose exec haboss haboss config show
```

**Solutions**:

#### 1. Restart Container

Configuration loaded at startup:

```bash
docker-compose restart haboss
```

#### 2. Check Volume Mount

Ensure config directory mounted:

```yaml
# docker-compose.yml
services:
  haboss:
    volumes:
      - ./config:/config:ro  # :ro = read-only (recommended)
```

Verify mount:
```bash
docker inspect haboss | grep -A10 Mounts
```

#### 3. Check File Permissions

```bash
# Config should be readable
ls -la ./config/config.yaml

# Should show: -rw-r--r-- or similar

# Fix if needed
chmod 644 ./config/config.yaml
```

#### 4. Validate YAML Syntax

```bash
# Check for YAML syntax errors
docker-compose exec haboss python3 -c "
import yaml
with open('/config/config.yaml') as f:
    yaml.safe_load(f)
print('YAML syntax valid')
"
```

Common YAML errors:
- Wrong indentation (use spaces, not tabs)
- Missing quotes for special characters
- Unbalanced brackets/quotes

#### 5. Check Configuration Hierarchy

Settings loaded in order (later overrides earlier):
1. Defaults in code
2. config.yaml
3. Environment variables

Environment variables override config file:

```bash
# Check what's overriding
docker-compose exec haboss env | grep -E "HA_|MONITORING_|HEALING_"
```

**Prevention**:
- Use `haboss config validate` before deployment
- Check logs after config changes
- Use version control for config files
- Document configuration changes

---

### Validation Errors

**Symptoms**:
- Container fails to start with validation error
- "ConfigurationError" in logs
- "Field required" errors
- "Invalid value" errors

**Common Validation Errors**:

#### 1. Missing Required Fields

```
ConfigurationError: Field required: home_assistant.token
```

**Solution**: Set in `.env`:
```bash
HA_TOKEN=your_token_here
```

#### 2. Invalid Type

```
ConfigurationError: Input should be a valid integer
```

**Solution**: Fix field type in config.yaml:
```yaml
# Wrong:
grace_period_seconds: "300"

# Right:
grace_period_seconds: 300
```

#### 3. Out of Range

```
ConfigurationError: Input should be greater than or equal to 1
```

**Solution**: Adjust value:
```yaml
# Wrong:
max_attempts: 0

# Right:
max_attempts: 3
```

#### 4. Invalid URL

```
ConfigurationError: Invalid URL format
```

**Solution**: Add protocol:
```bash
# Wrong:
HA_URL=homeassistant.local:8123

# Right:
HA_URL=http://homeassistant.local:8123
```

#### 5. Invalid Token Format

```
ConfigurationError: HA_TOKEN environment variable is not set
```

**Solution**: Verify token set:
```bash
# Check .env
cat .env | grep HA_TOKEN

# Verify loaded
docker-compose exec haboss env | grep HA_TOKEN
```

**Validation Commands**:

```bash
# Validate before starting
docker-compose run --rm haboss haboss config validate

# Show validation errors with details
docker-compose logs haboss | grep -A10 "ConfigurationError"
```

**Prevention**:
- Always run `config validate` before deployment
- Use example config as template
- Check types match (string, integer, boolean)
- Verify environment variables set

---

### Environment Variables Not Working

**Symptoms**:
- Settings in `.env` ignored
- Config file used instead of environment
- Variables not loaded in container

**Diagnostic Commands**:

```bash
# Check .env file
cat .env

# Check docker-compose loads .env
docker-compose config | grep -A5 environment

# Check variables in container
docker-compose exec haboss env | sort

# Test specific variable
docker-compose exec haboss env | grep HA_TOKEN
```

**Solutions**:

#### 1. Verify .env Location

`.env` must be in same directory as `docker-compose.yml`:

```bash
ls -la .env docker-compose.yml

# Should show both in same directory
```

#### 2. Check .env Syntax

```bash
# Correct format:
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_token

# Wrong formats:
HA_URL = http://...  # No spaces around =
HA_TOKEN="token"     # No quotes needed
export HA_TOKEN=...  # No export keyword
```

#### 3. Restart Docker Compose

Changes to `.env` require restart:

```bash
docker-compose down
docker-compose up -d
```

`docker-compose restart` doesn't reload `.env`!

#### 4. Use Nested Delimiter

For nested config fields, use `__`:

```bash
# Wrong:
MONITORING.GRACE_PERIOD_SECONDS=300

# Right:
MONITORING__GRACE_PERIOD_SECONDS=300
```

#### 5. Explicit Environment in docker-compose.yml

Force variable loading:

```yaml
# docker-compose.yml
services:
  haboss:
    environment:
      - HA_URL=${HA_URL}
      - HA_TOKEN=${HA_TOKEN}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}  # With default
```

#### 6. Check Variable Substitution in Config

In config.yaml:
```yaml
home_assistant:
  token: "${HA_TOKEN}"  # Uses environment variable
  # or
  token: "literal_value"  # Literal value
```

**Prevention**:
- Keep .env in same directory as docker-compose.yml
- Use consistent naming (uppercase with underscores)
- No spaces around `=`
- Restart after .env changes (`down` then `up`)

---

## Log Analysis Tips

### Viewing Logs

```bash
# Real-time logs
docker-compose logs -f haboss

# Last 100 lines
docker-compose logs --tail=100 haboss

# Logs since specific time
docker-compose logs --since 30m haboss  # Last 30 minutes
docker-compose logs --since 2024-01-01T00:00:00 haboss

# Search logs
docker-compose logs haboss | grep -i error
docker-compose logs haboss | grep -E "heal|unavailable"
```

### Log Levels

```bash
# Show only errors and above
docker-compose logs haboss | grep -E "ERROR|CRITICAL"

# Show warnings and above
docker-compose logs haboss | grep -E "WARNING|ERROR|CRITICAL"

# Debug logging (enable first in config)
# config/config.yaml:
# logging:
#   level: "DEBUG"
docker-compose restart haboss
docker-compose logs -f haboss
```

### Common Log Patterns

**Successful Startup**:
```
INFO: Connected to Home Assistant 2024.11.1
INFO: Monitoring 150 entities
INFO: Auto-healing enabled
INFO: WebSocket connection established
```

**Connection Issues**:
```
ERROR: Failed to connect to Home Assistant
ERROR: Connection refused
ERROR: Connection timeout
```

**Authentication Errors**:
```
ERROR: Authentication failed
ERROR: 401 Unauthorized
ERROR: Invalid token
```

**Healing Activity**:
```
INFO: Entity sensor.temp became unavailable
INFO: Attempting to heal integration 'esphome' (attempt 1/3)
INFO: Successfully healed integration 'esphome'
# or
WARNING: Healing failed for integration 'esphome' (attempt 1/3)
```

**WebSocket Activity**:
```
INFO: WebSocket connection established
INFO: Subscribed to state_changed events
WARNING: WebSocket connection lost, reconnecting...
INFO: WebSocket reconnected
```

**Circuit Breaker**:
```
WARNING: Circuit breaker tripped after 10 failures
INFO: Circuit breaker reset
```

### Analyzing JSON Logs

If using JSON format:

```bash
# View formatted JSON
docker-compose logs haboss | jq '.'

# Filter by level
docker-compose logs haboss | jq 'select(.level=="ERROR")'

# Count errors
docker-compose logs haboss | jq 'select(.level=="ERROR")' | wc -l

# Extract specific field
docker-compose logs haboss | jq -r '.message'
```

### Log File Access

```bash
# View log file (inside container)
docker exec haboss tail -f /data/ha_boss.log

# Copy log file to host
docker cp haboss:/data/ha_boss.log ./ha_boss.log

# View all log files (with rotation)
docker exec haboss ls -lh /data/*.log*
```

### Troubleshooting with Logs

**Problem**: Why entity not being healed?

```bash
# Search for entity mentions
docker-compose logs haboss | grep "sensor.temp_bedroom"

# Look for:
# - Entity detected as unavailable?
# - Healing attempted?
# - Cooldown active?
# - Circuit breaker?
```

**Problem**: Why high CPU usage?

```bash
# Look for reconnection loops
docker-compose logs haboss | grep -c "reconnect"

# Check health check frequency
docker-compose logs haboss | grep "health check" | tail -20

# Look for errors causing retries
docker-compose logs haboss | grep -i error
```

**Problem**: LLM not working?

```bash
# Check LLM initialization
docker-compose logs haboss | grep -i "LLM Router"

# Look for Ollama errors
docker-compose logs haboss | grep -i ollama

# Check for timeout errors
docker-compose logs haboss | grep -i timeout
```

### Log Rotation

Check log rotation settings:

```bash
# View current logs
docker exec haboss ls -lh /data/*.log*

# Shows:
# ha_boss.log      (current)
# ha_boss.log.1    (previous)
# ha_boss.log.2
# ...
# ha_boss.log.5    (oldest)

# Configure in config.yaml:
logging:
  max_size_mb: 10      # Rotate at 10MB
  backup_count: 5      # Keep 5 old files
```

---

## Getting Help

### Before Asking for Help

Gather this information:

1. **System Information**:
   ```bash
   # HA Boss version
   docker inspect haboss | grep -i version

   # Home Assistant version
   # (from HA web UI or logs)

   # Docker version
   docker --version
   docker-compose --version

   # OS
   uname -a
   ```

2. **Configuration** (sanitized):
   ```bash
   # Remove secrets first!
   docker-compose exec haboss haboss config show | sed 's/eyJ.*/[REDACTED]/'
   ```

3. **Recent Logs**:
   ```bash
   docker-compose logs --tail=200 haboss > haboss_logs.txt
   ```

4. **Error Messages**: Copy full error text including traceback

5. **Steps to Reproduce**: What were you doing when issue occurred?

### Support Channels

1. **GitHub Issues** (bugs and feature requests):
   - https://github.com/jasonthagerty/ha_boss/issues
   - Search existing issues first
   - Use issue templates
   - Provide all information above

2. **GitHub Discussions** (questions and help):
   - https://github.com/jasonthagerty/ha_boss/discussions
   - Community support
   - Search before asking

3. **Documentation**:
   - [Wiki](https://github.com/jasonthagerty/ha_boss/wiki)
   - [README](https://github.com/jasonthagerty/ha_boss/blob/main/README.md)
   - [Setup Guide](https://github.com/jasonthagerty/ha_boss/blob/main/SETUP_GUIDE.md)

4. **Home Assistant Community**:
   - https://community.home-assistant.io/
   - Search for HA Boss or integration issues

### Diagnostic Bundle

Create a diagnostic bundle to share:

```bash
#!/bin/bash
# create_diagnostic_bundle.sh

BUNDLE_DIR="ha_boss_diagnostics_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BUNDLE_DIR"

# System info
docker --version > "$BUNDLE_DIR/docker_version.txt"
docker-compose --version >> "$BUNDLE_DIR/docker_version.txt"
uname -a > "$BUNDLE_DIR/system_info.txt"

# HA Boss info
docker inspect haboss > "$BUNDLE_DIR/container_inspect.json"
docker-compose ps > "$BUNDLE_DIR/container_status.txt"
docker stats haboss --no-stream > "$BUNDLE_DIR/resource_usage.txt"

# Configuration (sanitized)
docker-compose exec haboss haboss config show | \
  sed 's/eyJ.*/[REDACTED]/' | \
  sed 's/sk-ant-.*/[REDACTED]/' \
  > "$BUNDLE_DIR/config_sanitized.txt"

# Logs
docker-compose logs --tail=500 haboss > "$BUNDLE_DIR/logs.txt"

# Database info
docker-compose exec haboss haboss db info > "$BUNDLE_DIR/database_info.txt"

# Network info
docker network inspect haboss_default > "$BUNDLE_DIR/network_info.json"

# Create archive
tar -czf "$BUNDLE_DIR.tar.gz" "$BUNDLE_DIR"
rm -rf "$BUNDLE_DIR"

echo "Diagnostic bundle created: $BUNDLE_DIR.tar.gz"
echo "Review file to ensure no secrets before sharing!"
```

Run and share resulting `.tar.gz` file with support.

### Security Note

**Never share**:
- Long-lived access tokens
- API keys
- Passwords
- Database files (may contain sensitive data)

**Always redact**:
- `HA_TOKEN` values
- `CLAUDE_API_KEY` values
- Any `password` fields
- Personal information

---

**Last Updated**: 2024-12-19
**HA Boss Version**: Phase 3 (Complete)
**Document Version**: 1.0
