# REST API

HA Boss provides a comprehensive REST API for monitoring, managing, and analyzing your Home Assistant instance. The API enables programmatic access to all HA Boss features and serves as the foundation for the CLI and future integrations.

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [Design](#design)
- [Development](#development)
- [API Reference](#api-reference)
- [Authentication](#authentication)
- [Examples](#examples)

---

## Overview

### What is the HA Boss API?

The HA Boss REST API is a FastAPI-based service that exposes all HA Boss functionality through HTTP endpoints. It provides:

- **Real-time monitoring** - Entity states, health checks, and service status
- **Pattern analysis** - Integration reliability and failure tracking
- **Automation management** - AI-powered analysis and generation
- **Manual healing** - On-demand integration reloads
- **Historical data** - Event timelines and healing history

### Key Features

- ✅ **13 Comprehensive Endpoints** - Full coverage of HA Boss functionality
- ✅ **OpenAPI Documentation** - Auto-generated interactive docs at `/docs`
- ✅ **Optional Authentication** - API key support with configurable security
- ✅ **CORS Support** - Configurable cross-origin resource sharing
- ✅ **Type Safety** - Pydantic models for request/response validation
- ✅ **Async Performance** - Built on FastAPI's async foundation

### Use Cases

**For Users:**
- Monitor HA Boss status from custom dashboards
- Integrate with home automation systems
- Build mobile apps or notifications
- Query historical reliability data

**For Developers:**
- CLI commands consume the API (future migration)
- MCP server integration for AI assistants
- Custom integrations and extensions
- Testing and validation

---

## Getting Started

### Prerequisites

- HA Boss installed and configured
- API enabled in configuration
- (Optional) API key configured for authentication

### Quick Start

**1. Enable the API**

Edit `config/config.yaml`:

```yaml
api:
  enabled: true
  host: "0.0.0.0"  # Listen on all interfaces
  port: 8000       # API port
```

**2. Start the API Server**

```bash
# Start in foreground
haboss server

# Or with Docker
docker-compose up
```

**3. Access the API**

- **Interactive Docs:** http://localhost:8000/docs (Swagger UI)
- **Alternative Docs:** http://localhost:8000/redoc (ReDoc)
- **OpenAPI Schema:** http://localhost:8000/openapi.json
- **Dashboard:** http://localhost:8000/dashboard

**4. Make Your First Request**

```bash
# Get service status
curl http://localhost:8000/api/status

# Health check
curl http://localhost:8000/api/health
```

---

## Design

### Architecture

```
┌─────────────────────────────────────────┐
│         HA Boss REST API                 │
├─────────────────────────────────────────┤
│                                          │
│  ┌──────────────────────────────────┐  │
│  │   FastAPI Application            │  │
│  │   - Route Registration           │  │
│  │   - Middleware (CORS, Auth)      │  │
│  │   - Exception Handling           │  │
│  └──────────────────────────────────┘  │
│                                          │
│  ┌──────────────────────────────────┐  │
│  │   API Routes (5 modules)         │  │
│  │   - status.py      (Status)      │  │
│  │   - monitoring.py  (Entities)    │  │
│  │   - patterns.py    (Analysis)    │  │
│  │   - automations.py (AI)          │  │
│  │   - healing.py     (Manual)      │  │
│  └──────────────────────────────────┘  │
│                                          │
│  ┌──────────────────────────────────┐  │
│  │   Pydantic Models                │  │
│  │   - Request validation           │  │
│  │   - Response serialization       │  │
│  │   - Type safety                  │  │
│  └──────────────────────────────────┘  │
│                                          │
│  ┌──────────────────────────────────┐  │
│  │   Dependencies                   │  │
│  │   - Service injection            │  │
│  │   - Authentication               │  │
│  │   - Error handling               │  │
│  └──────────────────────────────────┘  │
│                                          │
└─────────────────────────────────────────┘
              │
              │ Accesses
              ▼
    ┌──────────────────┐
    │  HABossService   │
    │  (Core Logic)    │
    └──────────────────┘
```

### Design Principles

**1. Separation of Concerns**
- Routes handle HTTP concerns (validation, serialization)
- Service layer handles business logic
- Clear boundaries between API and core functionality

**2. Type Safety**
- All endpoints use Pydantic models
- Request validation automatic
- Response serialization guaranteed

**3. Async-First**
- All endpoints are async
- Non-blocking I/O operations
- Concurrent request handling

**4. Self-Documenting**
- OpenAPI schema auto-generated
- Interactive documentation included
- Type hints provide IntelliSense

**5. Secure by Default**
- Optional authentication (disabled by default for ease of setup)
- Configurable CORS policies
- HTTPS support (via reverse proxy)

### Data Flow

```
HTTP Request
    │
    ▼
FastAPI (Middleware)
    │ - CORS headers
    │ - Authentication (if enabled)
    │ - Exception handling
    ▼
Route Handler
    │ - Request validation (Pydantic)
    │ - Parameter parsing
    ▼
Service Layer
    │ - Business logic
    │ - Database queries
    │ - HA API calls
    ▼
Response Model (Pydantic)
    │ - Data serialization
    │ - Type validation
    ▼
HTTP Response (JSON)
```

---

## Development

### Project Structure

```
ha_boss/api/
├── app.py              # Application factory
├── dependencies.py     # Dependency injection
├── models.py          # Pydantic models
├── routes/            # Endpoint modules
│   ├── status.py      # Status & health
│   ├── monitoring.py  # Entity monitoring
│   ├── patterns.py    # Pattern analysis
│   ├── automations.py # Automation management
│   └── healing.py     # Manual healing
└── static/            # Dashboard files
    ├── index.html
    ├── css/
    └── js/

tests/api/
├── test_api_status.py    # Status tests
├── test_api_auth.py      # Auth tests
└── test_dashboard.py     # Dashboard tests
```

### Adding a New Endpoint

**1. Define the Pydantic Models**

```python
# In ha_boss/api/models.py
from pydantic import BaseModel, Field

class MyRequest(BaseModel):
    """Request model for my endpoint."""
    param: str = Field(..., description="Parameter description")

class MyResponse(BaseModel):
    """Response model for my endpoint."""
    result: str
    timestamp: datetime
```

**2. Create the Route Handler**

```python
# In ha_boss/api/routes/my_module.py
from fastapi import APIRouter, HTTPException
from ha_boss.api.app import get_service
from ha_boss.api.models import MyRequest, MyResponse

router = APIRouter()

@router.post("/my-endpoint", response_model=MyResponse)
async def my_endpoint(request: MyRequest) -> MyResponse:
    """Endpoint description for OpenAPI docs."""
    try:
        service = get_service()

        # Your logic here
        result = await service.do_something(request.param)

        return MyResponse(
            result=result,
            timestamp=datetime.now(UTC)
        )
    except Exception as e:
        logger.error(f"Error in my endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**3. Register the Router**

```python
# In ha_boss/api/app.py
from ha_boss.api.routes import my_module

app.include_router(
    my_module.router,
    prefix="/api",
    tags=["My Feature"],
    dependencies=dependencies
)
```

**4. Write Tests**

```python
# In tests/api/test_my_endpoint.py
import pytest
from fastapi.testclient import TestClient

def test_my_endpoint(client):
    """Test my new endpoint."""
    response = client.post(
        "/api/my-endpoint",
        json={"param": "value"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
```

### Best Practices

**Error Handling:**
```python
# Specific exceptions
try:
    result = await service.operation()
except SpecificError as e:
    raise HTTPException(status_code=400, detail=str(e))
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error")
```

**Type Hints:**
```python
# Always use complete type hints
async def endpoint(
    entity_id: str,
    limit: int = 100
) -> MyResponse:
    ...
```

**Validation:**
```python
# Use Pydantic Field for validation
class MyRequest(BaseModel):
    limit: int = Field(50, ge=1, le=500, description="Max items")
    hours: int = Field(24, ge=1, le=168, description="Time range")
```

**Documentation:**
```python
# Comprehensive docstrings
@router.get("/endpoint", response_model=Response)
async def endpoint(param: str) -> Response:
    """Short description.

    Detailed explanation of what this endpoint does,
    when to use it, and any important notes.

    Args:
        param: Description of parameter

    Returns:
        Description of response

    Raises:
        HTTPException: When and why
    """
```

### Testing Guidelines

**Unit Tests:**
- Test each endpoint with valid inputs
- Test error conditions (404, 500, etc.)
- Test authentication (if enabled)
- Test validation (invalid inputs)

**Integration Tests:**
- Test endpoint with mocked service
- Verify response structure
- Check status codes
- Validate JSON schema

**Example Test:**
```python
@pytest.mark.asyncio
async def test_endpoint_success(client, mock_service):
    """Test endpoint returns correct data."""
    # Setup mock
    mock_service.method.return_value = expected_data

    # Make request
    response = client.get("/api/endpoint")

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["field"] == expected_value
```

---

## API Reference

### Base URL

```
http://localhost:8000/api
```

### Endpoints Overview

| Category | Endpoints | Description |
|----------|-----------|-------------|
| **Status** | 2 endpoints | Service status and health checks |
| **Monitoring** | 3 endpoints | Entity states and history |
| **Patterns** | 3 endpoints | Reliability and failure analysis |
| **Automations** | 3 endpoints | AI-powered automation management |
| **Healing** | 2 endpoints | Manual healing and history |

### Status & Health

#### GET /api/status

Get current service status and statistics.

**Response:**
```json
{
  "state": "running",
  "uptime_seconds": 86400.5,
  "start_time": "2025-01-20T10:00:00Z",
  "health_checks_performed": 1000,
  "healings_attempted": 50,
  "healings_succeeded": 45,
  "healings_failed": 5,
  "monitored_entities": 100
}
```

#### GET /api/health

Health check for monitoring and load balancers.

**Response:**
```json
{
  "status": "healthy",
  "service_running": true,
  "ha_connected": true,
  "websocket_connected": true,
  "database_accessible": true,
  "timestamp": "2025-01-20T12:00:00Z"
}
```

**Status Values:**
- `healthy` - All components operational
- `degraded` - Service running but some components down
- `unhealthy` - Service not running or critical failure

### Monitoring

#### GET /api/entities

List all monitored entities with pagination.

**Parameters:**
- `limit` (int, 1-1000, default: 100) - Max entities to return
- `offset` (int, ≥0, default: 0) - Pagination offset

**Response:**
```json
[
  {
    "entity_id": "sensor.temperature",
    "state": "72.5",
    "attributes": {"unit_of_measurement": "°F"},
    "last_changed": "2025-01-20T11:00:00Z",
    "last_updated": "2025-01-20T12:00:00Z",
    "monitored": true
  }
]
```

#### GET /api/entities/{entity_id}

Get current state of a specific entity.

**Response:** Same as entity object above.

**Status Codes:**
- `200` - Success
- `404` - Entity not found

#### GET /api/entities/{entity_id}/history

Get state history for an entity.

**Parameters:**
- `hours` (int, 1-168, default: 24) - Hours of history

**Response:**
```json
{
  "entity_id": "sensor.temperature",
  "history": [
    {"timestamp": "2025-01-20T11:00:00Z", "state": "71.0"},
    {"timestamp": "2025-01-20T12:00:00Z", "state": "72.5"}
  ],
  "count": 2
}
```

### Pattern Analysis

#### GET /api/patterns/reliability

Get integration reliability statistics.

**Response:**
```json
[
  {
    "integration": "mqtt",
    "total_entities": 50,
    "unavailable_count": 2,
    "failure_count": 10,
    "success_count": 90,
    "reliability_percent": 90.0,
    "last_failure": "2025-01-20T10:00:00Z"
  }
]
```

#### GET /api/patterns/failures

Get failure event timeline.

**Parameters:**
- `limit` (int, 1-500, default: 50) - Max failures to return
- `hours` (int, 1-168, default: 24) - Hours of history

**Response:**
```json
[
  {
    "id": 1,
    "entity_id": "sensor.example",
    "integration": "mqtt",
    "state": "unavailable",
    "timestamp": "2025-01-20T11:00:00Z",
    "resolved": true,
    "resolution_time": "2025-01-20T11:05:00Z"
  }
]
```

#### GET /api/patterns/summary

Get weekly summary statistics.

**Parameters:**
- `days` (int, 1-30, default: 7) - Days to summarize
- `ai` (bool, default: false) - Include AI insights

**Response:**
```json
{
  "start_date": "2025-01-13T00:00:00Z",
  "end_date": "2025-01-20T00:00:00Z",
  "total_health_checks": 10000,
  "total_failures": 50,
  "total_healings": 45,
  "success_rate": 90.0,
  "top_failing_integrations": ["mqtt", "zwave"],
  "ai_insights": "Your MQTT integration..."
}
```

### Automation Management

#### POST /api/automations/analyze

Analyze an automation with AI.

**Request:**
```json
{
  "automation_id": "automation.lights_on"
}
```

**Response:**
```json
{
  "automation_id": "automation.lights_on",
  "alias": "Lights On at Sunset",
  "analysis": "This automation turns on lights...",
  "suggestions": [
    "Consider adding a condition...",
    "Use sun elevation instead..."
  ],
  "complexity_score": 3
}
```

**Status Codes:**
- `200` - Success
- `404` - Automation not found
- `503` - AI not configured

#### POST /api/automations/generate

Generate automation from natural language.

**Request:**
```json
{
  "description": "Turn on lights when motion detected after sunset",
  "mode": "single"
}
```

**Response:**
```json
{
  "automation_id": "automation.generated_12345",
  "alias": "Motion Lights After Sunset",
  "description": "Turn on lights when motion detected after sunset",
  "yaml_content": "alias: Motion Lights...",
  "validation_errors": null,
  "is_valid": true
}
```

#### POST /api/automations/create

Create automation in Home Assistant.

**Request:**
```json
{
  "automation_yaml": "alias: My Automation\n..."
}
```

**Response:**
```json
{
  "success": true,
  "automation_id": "automation.my_automation",
  "message": "Automation created successfully"
}
```

### Healing

#### POST /api/healing/{entity_id}

Manually trigger healing for an entity.

**Response:**
```json
{
  "entity_id": "sensor.example",
  "integration": "mqtt",
  "action_type": "integration_reload",
  "success": true,
  "timestamp": "2025-01-20T12:00:00Z",
  "message": "Healing successful"
}
```

#### GET /api/healing/history

Get healing action history.

**Parameters:**
- `limit` (int, 1-500, default: 50) - Max actions to return
- `hours` (int, 1-168, default: 24) - Hours of history

**Response:**
```json
{
  "actions": [
    {
      "entity_id": "sensor.example",
      "integration": "mqtt",
      "action_type": "integration_reload",
      "success": true,
      "timestamp": "2025-01-20T12:00:00Z",
      "message": "Success"
    }
  ],
  "total_count": 1,
  "success_count": 1,
  "failure_count": 0
}
```

---

## Authentication

### Overview

API key authentication is optional and disabled by default for ease of setup. Enable it for production deployments or when exposing the API externally.

### Configuration

**Enable Authentication:**

```yaml
# config/config.yaml
api:
  auth_enabled: true
  api_keys:
    - "your-secure-api-key-here"
    - "another-key-for-different-client"
  require_https: true  # Recommended for production
```

### Using API Keys

**HTTP Header:**
```bash
curl -H "X-API-Key: your-secure-api-key-here" \
     http://localhost:8000/api/status
```

**Python:**
```python
import requests

headers = {"X-API-Key": "your-secure-api-key-here"}
response = requests.get(
    "http://localhost:8000/api/status",
    headers=headers
)
```

**JavaScript:**
```javascript
fetch('http://localhost:8000/api/status', {
  headers: {
    'X-API-Key': 'your-secure-api-key-here'
  }
})
```

### Security Best Practices

1. **Use HTTPS** - Always use HTTPS in production
2. **Strong Keys** - Generate long, random API keys
3. **Rotate Keys** - Periodically rotate API keys
4. **Restrict CORS** - Limit allowed origins in production
5. **Monitor Access** - Log API key usage
6. **Separate Keys** - Use different keys for different clients

**Generate Secure API Key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Examples

### Python Client

```python
import requests
from typing import Optional

class HABossClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key

    def get_status(self):
        """Get service status."""
        response = requests.get(
            f"{self.base_url}/api/status",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def trigger_healing(self, entity_id: str):
        """Trigger manual healing."""
        response = requests.post(
            f"{self.base_url}/api/healing/{entity_id}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

# Usage
client = HABossClient("http://localhost:8000")
status = client.get_status()
print(f"HA Boss is {status['state']}")
```

### Node.js Client

```javascript
class HABossClient {
  constructor(baseURL, apiKey = null) {
    this.baseURL = baseURL;
    this.headers = {};
    if (apiKey) {
      this.headers['X-API-Key'] = apiKey;
    }
  }

  async getStatus() {
    const response = await fetch(
      `${this.baseURL}/api/status`,
      { headers: this.headers }
    );
    return response.json();
  }

  async getReliability() {
    const response = await fetch(
      `${this.baseURL}/api/patterns/reliability`,
      { headers: this.headers }
    );
    return response.json();
  }
}

// Usage
const client = new HABossClient('http://localhost:8000');
const status = await client.getStatus();
console.log(`HA Boss is ${status.state}`);
```

### Home Assistant Integration

Create a custom sensor in Home Assistant:

```yaml
# configuration.yaml
sensor:
  - platform: rest
    name: HA Boss Status
    resource: http://haboss:8000/api/status
    headers:
      X-API-Key: "your-key-here"
    value_template: "{{ value_json.state }}"
    json_attributes:
      - uptime_seconds
      - healings_succeeded
      - healings_failed
    scan_interval: 60
```

### Prometheus Metrics

Example Prometheus exporter:

```python
from prometheus_client import Gauge, start_http_server
import requests
import time

# Define metrics
uptime = Gauge('haboss_uptime_seconds', 'HA Boss uptime')
healings_success = Gauge('haboss_healings_succeeded', 'Successful healings')
healings_failed = Gauge('haboss_healings_failed', 'Failed healings')

def collect_metrics():
    """Collect metrics from HA Boss API."""
    response = requests.get('http://localhost:8000/api/status')
    data = response.json()

    uptime.set(data['uptime_seconds'])
    healings_success.set(data['healings_succeeded'])
    healings_failed.set(data['healings_failed'])

if __name__ == '__main__':
    start_http_server(9090)
    while True:
        collect_metrics()
        time.sleep(60)
```

---

**Back to:** [Wiki Home](Home) | [Dashboard Documentation](Dashboard) | [CLI Commands](CLI-Commands)
