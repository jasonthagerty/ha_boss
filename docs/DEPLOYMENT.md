# HA Boss Deployment Guide

This guide covers production deployment patterns for HA Boss, with focus on multi-instance and multi-tenant scenarios.

## Table of Contents

- [Quick Start](#quick-start)
- [Single-Instance Deployment](#single-instance-deployment)
- [Multi-Instance Deployment (Single Tenant)](#multi-instance-deployment-single-tenant)
- [Multi-Tenant Deployment](#multi-tenant-deployment)
- [Security Considerations](#security-considerations)
- [Production Best Practices](#production-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

**Simplest deployment** (single Home Assistant instance):

```bash
git clone https://github.com/jasonthagerty/ha_boss.git
cd ha_boss
cp .env.example .env

# Edit .env with your HA URL and token
nano .env

# Create data directory and start
mkdir -p data && sudo chown -R 1000:1000 data
docker-compose up -d
```

**Verify it's running:**
```bash
docker-compose exec haboss haboss status
curl http://localhost:8000/api/status
```

---

## Single-Instance Deployment

**Use Case**: Monitor one Home Assistant instance.

### Configuration

**Option 1: Environment Variables** (simplest)

```bash
# .env file
HA_URL=http://homeassistant.local:8123
HA_TOKEN=eyJ0eXAi...your-long-lived-token
API_ENABLED=true
API_AUTH_ENABLED=false  # No auth needed on private network
```

**Option 2: Config File** (more control)

```yaml
# config/config.yaml
home_assistant:
  instances:
    - instance_id: "default"
      url: "http://homeassistant.local:8123"
      token: "eyJ0eXAi...your-token"

api:
  enabled: true
  host: "0.0.0.0"
  port: 8000
  auth_enabled: false
```

### Docker Compose

```yaml
# docker-compose.yml
services:
  haboss:
    image: ghcr.io/jasonthagerty/ha-boss:latest
    container_name: ha-boss
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./.env:/app/.env
    environment:
      - HA_URL=${HA_URL}
      - HA_TOKEN=${HA_TOKEN}
    healthcheck:
      test: ["CMD", "haboss", "status"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Start:**
```bash
docker-compose up -d
```

---

## Multi-Instance Deployment (Single Tenant)

**Use Case**: Monitor multiple Home Assistant instances for one user/household (e.g., main home + vacation home).

### Architecture

```
┌─────────────────────────────────────┐
│        HA Boss (Single Container)    │
│                                      │
│  ┌────────────┐   ┌────────────┐   │
│  │ Instance:  │   │ Instance:  │   │
│  │   "home"   │   │  "cabin"   │   │
│  └────────────┘   └────────────┘   │
│        │                 │           │
└────────┼─────────────────┼───────────┘
         │                 │
         ▼                 ▼
   ┌──────────┐      ┌──────────┐
   │   Home   │      │  Cabin   │
   │ Assistant│      │ Assistant│
   └──────────┘      └──────────┘
```

### Configuration

```yaml
# config/config.yaml
home_assistant:
  instances:
    - instance_id: "home"
      url: "http://home.local:8123"
      token: "eyJ0eXAi...home-token"
      bridge_enabled: true  # Enable WebSocket monitoring

    - instance_id: "cabin"
      url: "http://cabin.external.example.com:8123"
      token: "eyJ0eXAi...cabin-token"
      bridge_enabled: true

api:
  enabled: true
  auth_enabled: true  # Enable auth for remote access
  api_keys:
    - "shared-family-api-key-abc123"  # All family members use same key
```

### API Usage

All API endpoints accept an `instance_id` query parameter:

```bash
# Check home instance status
curl -H "X-API-Key: shared-family-api-key-abc123" \
  http://localhost:8000/api/status?instance_id=home

# Check cabin instance status
curl -H "X-API-Key: shared-family-api-key-abc123" \
  http://localhost:8000/api/status?instance_id=cabin

# List all instances
curl -H "X-API-Key: shared-family-api-key-abc123" \
  http://localhost:8000/api/instances
```

### Dashboard Access

The web dashboard includes an instance selector dropdown:

```
http://localhost:8000/dashboard
```

Switch between instances using the selector in the top-right corner.

### Security Model

**Important**: In this configuration, **any valid API key grants access to ALL instances**.

- ✅ **Acceptable for**: Single household with shared access
- ❌ **Not suitable for**: Multi-tenant scenarios where instance isolation is required

For tenant isolation, see [Multi-Tenant Deployment](#multi-tenant-deployment).

---

## Multi-Tenant Deployment

**Use Case**: Managed service provider monitoring multiple customer homes with complete isolation.

### Architecture

```
┌──────────────────┐     ┌──────────────────┐
│  HA Boss Container │     │  HA Boss Container │
│   (Customer A)     │     │   (Customer B)     │
│                    │     │                    │
│  Instance: "home"  │     │  Instance: "home"  │
│  API Key: key-A    │     │  API Key: key-B    │
│  Port: 8001        │     │  Port: 8002        │
└─────────┼──────────┘     └─────────┼──────────┘
          │                          │
          ▼                          ▼
    ┌──────────┐               ┌──────────┐
    │ Customer A│               │ Customer B│
    │   HA     │               │    HA    │
    └──────────┘               └──────────┘
```

### Deployment: Separate Containers

**Why separate containers?**
- ✅ **Complete isolation** - Customer A cannot access Customer B's data
- ✅ **Independent API keys** - Each customer has their own authentication
- ✅ **Independent scaling** - Allocate resources per customer
- ✅ **Independent updates** - Update Customer A without affecting Customer B
- ✅ **Simple security model** - No complex authorization logic needed

### Example: Docker Compose (Multi-Tenant)

```yaml
# docker-compose.multi-tenant.yml
version: '3.8'

services:
  # Customer A
  haboss-customer-a:
    image: ghcr.io/jasonthagerty/ha-boss:latest
    container_name: ha-boss-customer-a
    restart: unless-stopped
    ports:
      - "8001:8000"  # Unique port per customer
    volumes:
      - ./data/customer-a:/app/data
      - ./config/customer-a:/app/config
    environment:
      - HA_URL=http://customer-a.local:8123
      - HA_TOKEN=${CUSTOMER_A_TOKEN}
      - API_ENABLED=true
      - API_AUTH_ENABLED=true
      - API_KEYS=customer-a-api-key-abc123
    healthcheck:
      test: ["CMD", "haboss", "status"]
      interval: 30s

  # Customer B
  haboss-customer-b:
    image: ghcr.io/jasonthagerty/ha-boss:latest
    container_name: ha-boss-customer-b
    restart: unless-stopped
    ports:
      - "8002:8000"  # Different port
    volumes:
      - ./data/customer-b:/app/data
      - ./config/customer-b:/app/config
    environment:
      - HA_URL=http://customer-b.local:8123
      - HA_TOKEN=${CUSTOMER_B_TOKEN}
      - API_ENABLED=true
      - API_AUTH_ENABLED=true
      - API_KEYS=customer-b-api-key-def456
    healthcheck:
      test: ["CMD", "haboss", "status"]
      interval: 30s

  # Customer C
  haboss-customer-c:
    image: ghcr.io/jasonthagerty/ha-boss:latest
    container_name: ha-boss-customer-c
    restart: unless-stopped
    ports:
      - "8003:8000"
    volumes:
      - ./data/customer-c:/app/data
      - ./config/customer-c:/app/config
    environment:
      - HA_URL=http://customer-c.local:8123
      - HA_TOKEN=${CUSTOMER_C_TOKEN}
      - API_ENABLED=true
      - API_AUTH_ENABLED=true
      - API_KEYS=customer-c-api-key-ghi789
    healthcheck:
      test: ["CMD", "haboss", "status"]
      interval: 30s
```

### Environment Variables

```bash
# .env
CUSTOMER_A_TOKEN=eyJ0eXAi...customer-a-token
CUSTOMER_B_TOKEN=eyJ0eXAi...customer-b-token
CUSTOMER_C_TOKEN=eyJ0eXAi...customer-c-token
```

### Starting Services

```bash
# Start all customers
docker-compose -f docker-compose.multi-tenant.yml up -d

# Start specific customer
docker-compose -f docker-compose.multi-tenant.yml up -d haboss-customer-a

# Check status
docker ps | grep ha-boss
```

### Customer Access

Each customer accesses their own instance:

```bash
# Customer A
curl -H "X-API-Key: customer-a-api-key-abc123" \
  http://your-server:8001/api/status

# Customer B
curl -H "X-API-Key: customer-b-api-key-def456" \
  http://your-server:8002/api/status
```

### Reverse Proxy Setup (Recommended)

Use nginx to provide HTTPS and custom domains:

```nginx
# /etc/nginx/sites-available/ha-boss-multi-tenant

# Customer A
server {
    listen 443 ssl http2;
    server_name ha-boss-customer-a.example.com;

    ssl_certificate /etc/letsencrypt/live/customer-a.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/customer-a.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Customer B
server {
    listen 443 ssl http2;
    server_name ha-boss-customer-b.example.com;

    ssl_certificate /etc/letsencrypt/live/customer-b.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/customer-b.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Customers access:**
- Customer A: `https://ha-boss-customer-a.example.com`
- Customer B: `https://ha-boss-customer-b.example.com`

---

## Security Considerations

### API Authentication

**Enable authentication for any deployment exposed beyond localhost:**

```yaml
api:
  auth_enabled: true
  api_keys:
    - "use-a-long-random-key-here-abc123def456"
  require_https: true  # Reject HTTP requests
```

**Generate secure API keys:**
```bash
# Generate a random 32-character key
openssl rand -base64 32
```

### HTTPS Requirements

**Never expose HA Boss over HTTP on public networks.** Use one of these approaches:

1. **Reverse Proxy** (nginx/Caddy) - Recommended
   ```nginx
   location / {
       proxy_pass http://localhost:8000;
   }
   ```

2. **HTTPS Requirement** (config)
   ```yaml
   api:
     require_https: true  # Reject all HTTP requests
   ```

3. **VPN/Tunnel** - WireGuard, Tailscale, CloudFlare Tunnel

### Home Assistant Token Security

**Long-lived access tokens grant full HA access.** Protect them carefully:

- ✅ Store in `.env` file (never commit to git)
- ✅ Use environment variables in production
- ✅ Rotate tokens periodically
- ✅ Consider creating a dedicated HA user for HA Boss with limited permissions (future HA feature)

### CORS Configuration

**Restrict origins to trusted domains:**

```yaml
api:
  cors_enabled: true
  cors_origins:
    - "https://your-dashboard.example.com"
    - "https://trusted-domain.com"
```

**Default** (`["*"]`) allows all origins - only use on private networks.

### Container Security

**HA Boss containers run as non-root users:**
- Main service: `haboss` (UID 1000)
- MCP server: `mcpuser` (UID 1001)

**Best practices:**
- Use read-only root filesystem when possible
- Limit container capabilities
- Keep images updated (automatically rebuilt on main branch)

---

## Production Best Practices

### 1. Resource Limits

Prevent resource exhaustion:

```yaml
# docker-compose.yml
services:
  haboss:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

### 2. Logging

**Structured logging with retention:**

```yaml
services:
  haboss:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**View logs:**
```bash
docker-compose logs -f haboss
docker-compose logs --tail=100 haboss
```

### 3. Health Checks

**Already included in official images:**

```yaml
healthcheck:
  test: ["CMD", "haboss", "status"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

**Check health:**
```bash
docker inspect ha-boss | jq '.[0].State.Health'
```

### 4. Backups

**Database and config backups:**

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups/ha-boss/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup database
docker-compose exec -T haboss sqlite3 /app/data/ha_boss.db ".backup /tmp/backup.db"
docker cp ha-boss:/tmp/backup.db "$BACKUP_DIR/ha_boss.db"

# Backup config
cp -r config "$BACKUP_DIR/"

# Keep last 7 days
find /backups/ha-boss -type d -mtime +7 -exec rm -rf {} +
```

**Restore:**
```bash
docker-compose down
cp backup/ha_boss.db data/ha_boss.db
docker-compose up -d
```

### 5. Monitoring

**Monitor container health:**

```bash
# Prometheus exporter (future)
# Grafana dashboard (future)

# Current: Use healthcheck endpoint
curl http://localhost:8000/api/status
```

### 6. Updates

**Stay current with latest releases:**

```bash
# Pull latest images
docker-compose pull

# Restart services
docker-compose down && docker-compose up -d

# Clean old images
docker image prune -a
```

### 7. Database Maintenance

**SQLite vacuum (reclaim space):**

```bash
docker-compose exec haboss sqlite3 /app/data/ha_boss.db "VACUUM;"
```

**Check database size:**
```bash
docker-compose exec haboss du -h /app/data/ha_boss.db
```

---

## Troubleshooting

### Container Won't Start

**Check logs:**
```bash
docker-compose logs haboss
```

**Common issues:**
- ❌ Invalid HA URL/token → Check `.env` file
- ❌ Permission denied on `/app/data` → Run `sudo chown -R 1000:1000 data`
- ❌ Port 8000 already in use → Change `ports` in docker-compose.yml

### API Returns 503

**Service not ready yet:**
```bash
# Wait for healthcheck to pass
docker-compose ps

# Check service status
curl http://localhost:8000/api/status
```

### WebSocket Connection Fails

**Check Home Assistant connectivity:**
```bash
docker-compose exec haboss haboss status
```

**Common causes:**
- Home Assistant URL incorrect
- Home Assistant token expired/invalid
- Network firewall blocking WebSocket connections
- Home Assistant not reachable from container

### Instance Not Found (404)

**Verify instance configuration:**
```bash
# List configured instances
curl http://localhost:8000/api/instances

# Check specific instance
curl http://localhost:8000/api/status?instance_id=YOUR_INSTANCE_ID
```

### High Memory Usage

**SQLite database growth:**
```bash
# Check database size
docker-compose exec haboss du -h /app/data/

# Configure retention period
# config/config.yaml
database:
  retention_days: 30  # Reduce from default
```

### Permission Denied Errors

**Data directory permissions:**
```bash
# Fix ownership
sudo chown -R 1000:1000 data config

# Verify
ls -la data config
```

---

## Support

- **Documentation**: [GitHub Wiki](https://github.com/jasonthagerty/ha_boss/wiki)
- **Issues**: [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- **Discussions**: [GitHub Discussions](https://github.com/jasonthagerty/ha_boss/discussions)

---

## Related Documentation

- [README.md](../README.md) - Project overview and quick start
- [CLAUDE.md](../CLAUDE.md) - Development guide for contributors
- [AI_FEATURES.md](AI_FEATURES.md) - AI capabilities and LLM setup
- [INSTANCE_AUTHORIZATION_ANALYSIS.md](INSTANCE_AUTHORIZATION_ANALYSIS.md) - Future authorization features
