"""Tests for dashboard static file serving and endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ha_boss.api.app import create_app


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock()
    config.api.auth_enabled = False
    config.api.cors_enabled = True
    config.api.cors_origins = ["*"]
    return config


@pytest.fixture
def client(mock_config):
    """Create test client with mocked config."""
    with patch("ha_boss.api.app.load_config", return_value=mock_config):
        app = create_app()
        return TestClient(app)


def test_static_files_mounted(client):
    """Test that static files are mounted and accessible."""
    # Test CSS file
    response = client.get("/static/css/dashboard.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "").lower()

    # Test JavaScript files
    js_files = [
        "/static/js/api-client.js",
        "/static/js/components.js",
        "/static/js/charts.js",
        "/static/js/dashboard.js",
    ]

    for js_file in js_files:
        response = client.get(js_file)
        assert response.status_code == 200, f"Failed to load {js_file}"
        assert any(
            ct in response.headers.get("content-type", "").lower()
            for ct in ["javascript", "ecmascript", "text/plain"]
        )


def test_dashboard_endpoint_serves_html(client):
    """Test that /dashboard endpoint serves the HTML file."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "").lower()

    # Check for key HTML elements
    html = response.text
    assert "HA Boss Dashboard" in html
    assert "Overview" in html
    assert "Monitoring" in html
    assert "Analysis" in html
    assert "Automations" in html
    assert "Healing" in html


def test_dashboard_contains_required_scripts(client):
    """Test that dashboard HTML includes required script tags."""
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text

    # Check for CDN scripts
    assert "tailwindcss" in html or "tailwind" in html
    assert "chart.js" in html.lower() or "chart.umd" in html.lower()
    assert "dayjs" in html.lower()

    # Check for custom scripts
    assert "/static/js/api-client.js" in html
    assert "/static/js/components.js" in html
    assert "/static/js/charts.js" in html
    assert "/static/js/dashboard.js" in html

    # Check for custom CSS
    assert "/static/css/dashboard.css" in html


def test_root_endpoint_includes_dashboard_link(client):
    """Test that root endpoint includes dashboard link."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "dashboard" in data
    assert data["dashboard"] == "/dashboard"


def test_root_endpoint_structure(client):
    """Test that root endpoint has expected structure."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()

    # Check all expected keys
    assert "message" in data
    assert "docs" in data
    assert "redoc" in data
    assert "openapi" in data
    assert "dashboard" in data

    # Check values
    assert data["message"] == "HA Boss API"
    assert data["docs"] == "/docs"
    assert data["redoc"] == "/redoc"
    assert data["openapi"] == "/openapi.json"
    assert data["dashboard"] == "/dashboard"


def test_nonexistent_static_file_returns_404(client):
    """Test that requesting nonexistent static file returns 404."""
    response = client.get("/static/nonexistent.js")
    assert response.status_code == 404


def test_index_html_accessible_directly(client):
    """Test that index.html can be accessed directly via static mount."""
    response = client.get("/static/index.html")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "").lower()


def test_dashboard_has_required_elements(client):
    """Test that dashboard has all required UI elements."""
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text

    # Check for header elements
    assert 'id="statusIndicator"' in html
    assert 'id="settingsBtn"' in html

    # Check for tab navigation
    assert 'data-tab="overview"' in html
    assert 'data-tab="monitoring"' in html
    assert 'data-tab="analysis"' in html
    assert 'data-tab="automations"' in html
    assert 'data-tab="healing"' in html

    # Check for tab content containers
    assert 'id="overviewTab"' in html
    assert 'id="monitoringTab"' in html
    assert 'id="analysisTab"' in html
    assert 'id="automationsTab"' in html
    assert 'id="healingTab"' in html

    # Check for modals
    assert 'id="settingsModal"' in html
    assert 'id="entityModal"' in html

    # Check for charts
    assert 'id="statusChart"' in html
    assert 'id="failureChart"' in html
    assert 'id="topFailingChart"' in html
    assert 'id="successRateChart"' in html


def test_dashboard_has_forms(client):
    """Test that dashboard has all required forms."""
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text

    # Check for automation forms
    assert 'id="analyzeForm"' in html
    assert 'id="generateForm"' in html

    # Check for healing form
    assert 'id="healingForm"' in html

    # Check for input fields
    assert 'id="automationId"' in html
    assert 'id="automationDescription"' in html
    assert 'id="entityId"' in html
    assert 'id="apiKeyInput"' in html


def test_css_file_has_animations(client):
    """Test that custom CSS file includes animations."""
    response = client.get("/static/css/dashboard.css")
    assert response.status_code == 200

    css = response.text

    # Check for keyframe animations
    assert "@keyframes" in css
    assert "fadeIn" in css
    assert "pulse" in css

    # Check for custom styles
    assert ".status-pulse" in css
    assert ".chart-container" in css


def test_api_client_exports_class(client):
    """Test that api-client.js exports APIClient class."""
    response = client.get("/static/js/api-client.js")
    assert response.status_code == 200

    js = response.text

    # Check for class export
    assert "export class APIClient" in js

    # Check for key methods
    assert "getStatus" in js
    assert "getHealth" in js
    assert "getEntities" in js
    assert "triggerHealing" in js


def test_components_exports_object(client):
    """Test that components.js exports Components object."""
    response = client.get("/static/js/components.js")
    assert response.status_code == 200

    js = response.text

    # Check for export
    assert "export const Components" in js

    # Check for key methods
    assert "statusBadge" in js
    assert "table" in js
    assert "pagination" in js
    assert "toast" in js


def test_charts_exports_class(client):
    """Test that charts.js exports ChartManager class."""
    response = client.get("/static/js/charts.js")
    assert response.status_code == 200

    js = response.text

    # Check for class export
    assert "export class ChartManager" in js

    # Check for chart creation methods
    assert "createStatusChart" in js
    assert "createReliabilityChart" in js
    assert "createSuccessRateGauge" in js


def test_dashboard_module_type(client):
    """Test that dashboard scripts are loaded as modules."""
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text

    # Check that scripts are loaded as ES modules
    assert 'type="module"' in html
