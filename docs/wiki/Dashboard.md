# Dashboard

The HA Boss Dashboard is a full-featured web interface for monitoring and managing your Home Assistant instance through the HA Boss API. Built with vanilla JavaScript and modern web technologies, it provides real-time updates, interactive visualizations, and comprehensive control over all HA Boss features.

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [Design](#design)
- [Development](#development)
- [Usage Guide](#usage-guide)
- [Features](#features)
- [Troubleshooting](#troubleshooting)

---

## Overview

### What is the Dashboard?

The HA Boss Dashboard is a single-page web application that provides a visual interface to:

- **Monitor** service status, health, and statistics in real-time
- **Visualize** reliability data and failure patterns with interactive charts
- **Manage** automations with AI-powered analysis and generation
- **Trigger** manual healing actions on demand
- **Analyze** integration performance and historical trends

### Key Features

- ✅ **Real-Time Updates** - Auto-refreshing data every 10-60 seconds
- ✅ **Interactive Charts** - 6 Chart.js visualizations for data insights
- ✅ **Responsive Design** - Works on mobile, tablet, and desktop
- ✅ **API Key Authentication** - Secure access with optional authentication
- ✅ **Tab-Based Navigation** - Organized interface across 5 main sections
- ✅ **No Build Required** - Vanilla JavaScript, runs directly in browser

### Technology Stack

**Frontend:**
- HTML5 with semantic markup
- Tailwind CSS via CDN for styling
- Vanilla JavaScript (ES6 modules)
- Chart.js for data visualization
- DayJS for date/time formatting

**Backend:**
- FastAPI for static file serving
- RESTful API endpoints

---

## Getting Started

### Prerequisites

- HA Boss installed and running
- API server enabled
- Modern web browser (Chrome, Firefox, Safari, Edge)

### Quick Start

**1. Enable the API**

Ensure the API is enabled in `config/config.yaml`:

```yaml
api:
  enabled: true
  host: "0.0.0.0"
  port: 8000
```

**2. Start HA Boss**

```bash
# Option 1: CLI
haboss server

# Option 2: Docker
docker-compose up
```

**3. Access the Dashboard**

Open your browser and navigate to:

```
http://localhost:8000/dashboard
```

**4. (Optional) Configure API Key**

If authentication is enabled:

1. Click the settings gear icon (⚙️)
2. Enter your API key
3. Click "Test Connection"
4. Click "Save" if successful

The API key is stored in your browser's localStorage and will persist across sessions.

### First-Time Setup

**Recommended Workflow:**

1. **Overview Tab** - Verify HA Boss is running and connected
2. **Settings** - Configure API key if authentication is enabled
3. **Monitoring Tab** - Check that entities are being tracked
4. **Analysis Tab** - Review integration reliability
5. **Healing Tab** - Check healing history and success rate

---

## Design

### Architecture

```
┌─────────────────────────────────────────┐
│         Dashboard (Browser)              │
├─────────────────────────────────────────┤
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   HTML Structure (index.html)     │ │
│  │   - Header with status indicator  │ │
│  │   - Tab navigation (5 tabs)       │ │
│  │   - Tab content containers        │ │
│  │   - Modals (Settings, Entity)     │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   JavaScript Modules               │ │
│  │                                    │ │
│  │   dashboard.js                     │ │
│  │   ├─ Application orchestration    │ │
│  │   ├─ Tab management               │ │
│  │   ├─ Polling logic                │ │
│  │   └─ Event handling               │ │
│  │                                    │ │
│  │   api-client.js                    │ │
│  │   ├─ HTTP requests                │ │
│  │   ├─ Authentication               │ │
│  │   └─ Error handling               │ │
│  │                                    │ │
│  │   charts.js                        │ │
│  │   ├─ Chart creation               │ │
│  │   ├─ Data updates                 │ │
│  │   └─ Chart destruction            │ │
│  │                                    │ │
│  │   components.js                    │ │
│  │   └─ Reusable UI elements         │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   Styling (CSS)                    │ │
│  │   - Tailwind utilities (CDN)      │ │
│  │   - Custom animations             │ │
│  │   - Responsive breakpoints        │ │
│  └────────────────────────────────────┘ │
│                                          │
└─────────────────────────────────────────┘
              │
              │ HTTP/REST API
              ▼
    ┌──────────────────┐
    │  HA Boss API     │
    │  (FastAPI)       │
    └──────────────────┘
```

### Module Responsibilities

**dashboard.js** (Main Application)
- Initializes the application
- Manages tab switching
- Coordinates polling intervals
- Handles user interactions
- Orchestrates other modules

**api-client.js** (API Communication)
- Makes HTTP requests to API endpoints
- Manages API key authentication
- Handles connection errors
- Provides typed method for each endpoint

**charts.js** (Visualizations)
- Creates Chart.js instances
- Updates charts with new data
- Destroys charts when not needed
- Manages chart lifecycle

**components.js** (UI Components)
- Generates HTML for common elements
- Provides reusable UI patterns
- Formats data for display
- Handles date/time formatting

### Design Patterns

**1. Module Pattern**
- Each JS file is an ES6 module
- Clear separation of concerns
- Explicit imports/exports

**2. Service Injection**
- API client injected into dashboard
- Chart manager injected into dashboard
- Components available globally

**3. Observer Pattern**
- Polling intervals for real-time updates
- Event listeners for user actions
- Reactive UI updates

**4. Factory Pattern**
- Component generators (badges, tables, etc.)
- Chart creation methods
- Modal constructors

### Data Flow

```
User Action
    │
    ▼
Event Listener (dashboard.js)
    │
    ▼
API Call (api-client.js)
    │
    ▼
HTTP Request to API
    │
    ▼
API Response (JSON)
    │
    ▼
Update UI
    │ - Update HTML content
    │ - Update charts (charts.js)
    │ - Show notifications
    ▼
User sees updated data
```

**Real-Time Updates:**
```
Polling Timer (setInterval)
    │
    ▼
API Call (api-client.js)
    │
    ▼
Fetch Latest Data
    │
    ▼
Check if Tab is Active
    │
    ├─ Yes: Update UI
    │
    └─ No: Skip update (save resources)
```

---

## Development

### Project Structure

```
ha_boss/api/static/
├── index.html           # Main dashboard HTML (584 lines)
├── css/
│   └── dashboard.css    # Custom styles (248 lines)
└── js/
    ├── api-client.js    # API communication (235 lines)
    ├── components.js    # UI components (256 lines)
    ├── charts.js        # Chart.js manager (368 lines)
    └── dashboard.js     # Main app logic (699 lines)

tests/api/
└── test_dashboard.py    # Dashboard tests (186 lines)
```

### Development Setup

**1. Install Dependencies**

No build step required! All dependencies loaded via CDN:
- Tailwind CSS
- Chart.js
- DayJS

**2. Start Development Server**

```bash
# Start HA Boss API server
haboss server

# Dashboard available at:
# http://localhost:8000/dashboard
```

**3. Make Changes**

Edit files in `ha_boss/api/static/`:
- HTML: `index.html`
- CSS: `css/dashboard.css`
- JavaScript: `js/*.js`

**4. Test Changes**

Simply refresh the browser - no build step needed!

**5. Run Tests**

```bash
pytest tests/api/test_dashboard.py -v
```

### Adding a New Feature

**Example: Add a new chart**

**1. Update HTML**

```html
<!-- In index.html, add canvas element -->
<div class="bg-white rounded-lg shadow p-6">
    <h2 class="text-lg font-semibold mb-4">My New Chart</h2>
    <div class="chart-container" style="position: relative; height: 300px;">
        <canvas id="myNewChart"></canvas>
    </div>
</div>
```

**2. Create Chart Method**

```javascript
// In charts.js
createMyNewChart(canvasId, data) {
    this.destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    this.charts[canvasId] = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'My Data',
                data: data.values,
                backgroundColor: 'rgba(59, 130, 246, 0.8)'
            }]
        },
        options: this.defaultOptions
    });

    return this.charts[canvasId];
}
```

**3. Call from Dashboard**

```javascript
// In dashboard.js
async loadMyNewData() {
    try {
        const data = await this.api.getMyData();
        this.charts.createMyNewChart('myNewChart', data);
    } catch (error) {
        console.error('Error loading chart:', error);
    }
}
```

**4. Add to Tab Load**

```javascript
// In appropriate tab load function
await this.loadMyNewData();
```

### Best Practices

**JavaScript:**

```javascript
// Use async/await for API calls
async function loadData() {
    try {
        const data = await api.getData();
        updateUI(data);
    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

// Use template literals for HTML
const html = `
    <div class="card">
        <h3>${title}</h3>
        <p>${description}</p>
    </div>
`;

// Destructure for cleaner code
const { entity_id, state, attributes } = entity;
```

**Error Handling:**

```javascript
// Always catch errors
try {
    await api.operation();
} catch (error) {
    // Log for debugging
    console.error('Operation failed:', error);

    // Show user-friendly message
    this.showToast('Operation failed. Please try again.', 'error');
}
```

**Performance:**

```javascript
// Destroy charts when switching tabs
stopTabPolling() {
    // Clear intervals
    if (this.pollingIntervals.tab) {
        clearInterval(this.pollingIntervals.tab);
    }

    // Destroy charts to free memory
    this.charts.destroyAll();
}

// Debounce user input
let debounceTimer;
input.addEventListener('input', (e) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        handleInput(e.target.value);
    }, 300);
});
```

**Accessibility:**

```html
<!-- Use semantic HTML -->
<button aria-label="Open settings">
    <svg>...</svg>
</button>

<!-- Add ARIA attributes -->
<div role="tabpanel" aria-labelledby="overview-tab">
    <!-- Content -->
</div>

<!-- Keyboard navigation -->
<button onclick="handleAction()" onkeypress="handleAction()">
    Action
</button>
```

### Testing

**Test Structure:**

```python
def test_feature(client):
    """Test description."""
    # Arrange
    expected_value = "test"

    # Act
    response = client.get("/dashboard")

    # Assert
    assert response.status_code == 200
    assert expected_value in response.text
```

**Running Tests:**

```bash
# Run all dashboard tests
pytest tests/api/test_dashboard.py -v

# Run specific test
pytest tests/api/test_dashboard.py::test_specific_feature -v

# Run with coverage
pytest tests/api/test_dashboard.py --cov=ha_boss/api --cov-report=html
```

---

## Usage Guide

### Overview Tab

**Purpose:** Monitor service status and healing statistics in real-time.

**Features:**
- **Service Status Card**
  - Current state (running/stopped)
  - Uptime duration
  - Health checks performed
  - Monitored entity count

- **Health Check Card**
  - Overall health status (healthy/degraded/unhealthy)
  - Component status (HA, WebSocket, Database)
  - Color-coded indicators

- **Healing Statistics**
  - Attempted healings count
  - Successful healings count
  - Failed healings count

- **Activity Chart**
  - Line chart showing healing trends
  - Auto-updates every 10 seconds
  - Last 20 data points displayed

**Usage Tips:**
- Check this tab first after starting HA Boss
- Green status indicator = everything working
- Yellow/Red indicator = check health details
- Watch the activity chart for healing patterns

### Monitoring Tab

**Purpose:** View and search monitored entities.

**Features:**
- **Entity List Table**
  - Entity ID
  - Current state
  - Last updated time (relative)
  - Paginated display

- **Refresh Button**
  - Manually refresh entity list
  - Auto-refreshes every 60 seconds when tab is active

**Usage Tips:**
- Use browser search (Ctrl+F) to find specific entities
- Click refresh for immediate update
- Check "Last Updated" to see if entity is stale
- Table auto-refreshes while tab is active

**Future Enhancement:**
- Click entity row to view detailed modal with:
  - Full attributes
  - State history chart (24 hours)
  - Quick heal button

### Analysis Tab

**Purpose:** Analyze integration reliability and failure patterns.

**Features:**
- **Reliability Table**
  - Integration name
  - Reliability percentage
  - Failure count
  - Last failure timestamp

- **Failure Timeline Chart**
  - Scatter plot of failures over time
  - Green dots = resolved failures
  - Red dots = unresolved failures
  - Y-axis = integration names

- **Top Failing Integrations**
  - Pie chart of most problematic integrations
  - Top 5 integrations shown
  - Percentage breakdown

- **Weekly Summary**
  - Configurable time range (1-30 days)
  - Total failures and healings
  - Success rate percentage
  - Top failing integrations list
  - Optional AI insights (if enabled)

**Usage Tips:**
- Check reliability table to identify problem integrations
- Use failure timeline to spot patterns (time-based failures)
- Enable AI insights for recommendations
- Adjust summary time range for different perspectives

### Automations Tab

**Purpose:** Manage automations with AI assistance.

**Features:**
- **Automation Analyzer**
  - Input: Automation ID
  - Output: AI analysis and suggestions
  - Complexity score
  - Best practice recommendations

- **Automation Generator**
  - Input: Natural language description
  - Output: Generated YAML automation
  - Validation status
  - Mode selection (single/restart/queued/parallel)

**Usage Tips:**
- **Analyzing:**
  - Enter full automation ID (e.g., `automation.lights_on`)
  - Review suggestions for improvements
  - Copy suggestions to implement in HA

- **Generating:**
  - Be specific in your description
  - Include trigger, condition, and action details
  - Review generated YAML before using
  - Copy YAML to Home Assistant

**Example Descriptions:**
```
Good: "Turn on living room lights when motion is detected
       between sunset and 11 PM, only if someone is home"

Bad: "Motion lights"
```

### Healing Tab

**Purpose:** Manually trigger healing and view healing history.

**Features:**
- **Manual Healing Form**
  - Input: Entity ID
  - Triggers integration reload
  - Shows success/failure result
  - Bypasses grace periods

- **Success Rate Gauge**
  - Doughnut chart showing healing effectiveness
  - Percentage in center
  - Green = success, Red = failure
  - Based on last 7 days

- **Healing History Table**
  - Recent healing actions
  - Entity ID and integration
  - Success/failure status
  - Timestamp (relative)
  - Auto-refreshes every 30 seconds

**Usage Tips:**
- Use manual healing for stuck entities
- Enter exact entity ID (copy from Monitoring tab)
- Check history to see if entity has been healed before
- Low success rate? Check HA logs for root cause

### Settings Modal

**Purpose:** Configure API key authentication.

**Features:**
- API key input (password field)
- Test connection button
- Save/Clear buttons
- Connection status indicator

**Usage Tips:**
1. Click settings gear icon (⚙️)
2. Enter API key from config
3. Click "Test Connection" (don't save yet)
4. If green checkmark appears, click "Save"
5. If error appears, verify key is correct
6. API key stored in browser localStorage
7. Click "Clear Key" to remove

**Security Notes:**
- API key stored in browser only (not server)
- Key sent with every request (if saved)
- Clear key if using shared computer
- Key not visible in settings (password field)

---

## Features

### Real-Time Updates

The dashboard automatically polls the API for updates:

**High Priority (10 seconds):**
- Service status
- Health check

**Medium Priority (30 seconds):**
- Failure events (Analysis tab)
- Healing history (Healing tab)

**Low Priority (60 seconds):**
- Entity list (Monitoring tab)
- Reliability data (Analysis tab)

**Smart Polling:**
- Only polls active tab's data
- Pauses when browser tab is hidden
- Resumes when tab becomes visible
- Reduces server load

### Interactive Charts

**Status Timeline (Line Chart)**
- Shows healing activity over time
- 3 lines: Attempted, Succeeded, Failed
- Updates in real-time (every 10s)
- Last 20 data points displayed

**Reliability Chart (Horizontal Bar)**
- Integration reliability percentages
- Color-coded: Green (>90%), Yellow (70-90%), Red (<70%)
- Sorted by reliability (worst first)
- Top 10 integrations shown

**Failure Timeline (Scatter)**
- Failures plotted over time
- Y-axis: Integration names
- X-axis: Time
- Colors: Green (resolved), Red (unresolved)

**Top Failing Pie Chart**
- Top 5 failing integrations
- Percentage breakdown
- Color-coded segments
- Click for details (future)

**Entity History (Line Chart)**
- Shows state changes over time
- Only for numeric states
- 24-hour default range
- Shown in entity modal (future)

**Success Rate Gauge (Doughnut)**
- Healing success percentage
- Large number in center
- Green/red color coding
- Last 7 days of data

### Responsive Design

**Mobile (< 640px):**
- Single column layout
- Hamburger menu (planned)
- Touch-friendly buttons
- Simplified charts
- Vertical card stacking

**Tablet (640px - 1024px):**
- Two column layout
- Collapsible navigation
- Full chart features
- Comfortable spacing

**Desktop (> 1024px):**
- Three column layout
- Persistent navigation
- All features visible
- Optimal chart sizes

### Keyboard Navigation

- **Tab**: Navigate through interactive elements
- **Enter**: Activate buttons and submit forms
- **Escape**: Close modals
- **Arrow Keys**: Navigate tables (future)

### Accessibility

- **ARIA Labels**: All interactive elements labeled
- **Screen Reader**: Status announcements
- **High Contrast**: Supports high contrast mode
- **Reduced Motion**: Respects prefers-reduced-motion
- **Focus Indicators**: Visible keyboard focus

---

## Troubleshooting

### Dashboard Won't Load

**Problem:** Blank page or "404 Not Found"

**Solutions:**
```bash
# 1. Verify API is running
curl http://localhost:8000/

# 2. Check static files exist
ls -la ha_boss/api/static/

# 3. Check API logs
tail -f /data/ha_boss.log

# 4. Verify configuration
cat config/config.yaml | grep -A5 "api:"

# 5. Restart service
docker-compose restart
```

### Connection Errors

**Problem:** "Unable to connect to API"

**Solutions:**
1. Check API server is running: `docker ps`
2. Verify port 8000 is accessible
3. Check firewall rules
4. Try: `curl http://localhost:8000/api/health`
5. Check browser console for errors (F12)

### Authentication Failures

**Problem:** "Authentication failed" or 401 errors

**Solutions:**
1. Verify API key in config matches dashboard
2. Check `config.yaml`: `auth_enabled: true`
3. Confirm API key is in `api_keys` list
4. Try clearing and re-entering API key
5. Check browser console for exact error
6. Test with curl:
```bash
curl -H "X-API-Key: your-key" \
     http://localhost:8000/api/health
```

### Charts Not Displaying

**Problem:** Empty chart areas or errors

**Solutions:**
1. Check browser console (F12) for JavaScript errors
2. Verify Chart.js CDN is accessible
3. Check network tab for failed CDN requests
4. Try hard refresh: Ctrl+Shift+R (Cmd+Shift+R on Mac)
5. Disable browser extensions (especially ad blockers)
6. Test in incognito/private window

### Data Not Updating

**Problem:** Dashboard shows stale data

**Solutions:**
1. Check connection status indicator (top right)
2. Verify polling is active (check browser console)
3. Manually refresh tab (click refresh button)
4. Check if browser tab is hidden (polling pauses)
5. Verify API endpoints returning data:
```bash
curl http://localhost:8000/api/status
```

### Slow Performance

**Problem:** Dashboard feels sluggish

**Solutions:**
1. Close unused browser tabs
2. Check browser DevTools > Performance tab
3. Reduce polling frequency (future config option)
4. Disable charts temporarily
5. Check if API server is overloaded
6. Verify database isn't too large

### Browser Compatibility

**Supported Browsers:**
- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ❌ Internet Explorer (not supported)

**Check Browser Version:**
1. Help > About (Chrome/Firefox)
2. Update if version is old
3. Try different browser if issues persist

### API Key Not Saving

**Problem:** Dashboard asks for API key every time

**Solutions:**
1. Check browser allows localStorage
2. Disable "Clear cookies on exit" setting
3. Check browser privacy settings
4. Try different browser
5. Check browser console for storage errors

### Getting Help

**Before Asking:**
1. Check browser console (F12) for errors
2. Check API logs: `tail -f /data/ha_boss.log`
3. Verify API is responding: `curl http://localhost:8000/api/health`
4. Try in incognito/private window
5. Test with different browser

**Report Issue:**
Include:
- Browser version
- Operating system
- Error messages (console and logs)
- Steps to reproduce
- Screenshots if applicable

**Resources:**
- [GitHub Issues](https://github.com/jasonthagerty/ha_boss/issues)
- [Troubleshooting Guide](Troubleshooting)
- [REST API Docs](REST-API)

---

**Back to:** [Wiki Home](Home) | [REST API](REST-API) | [Installation](Installation)
