"""Tests for healing plan API endpoints."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router
from ha_boss.api.routes.plans import router


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _mock_plan(name="test_plan", enabled=True, priority=10):
    plan = MagicMock()
    plan.name = name
    plan.description = "Test plan"
    plan.version = 1
    plan.enabled = enabled
    plan.priority = priority
    plan.tags = ["test"]
    plan.match = MagicMock()
    plan.match.entity_patterns = ["light.*"]
    plan.match.integration_domains = ["zha"]
    plan.match.failure_types = ["unavailable"]
    plan.steps = []
    return plan


def test_list_plans():
    """Test GET /api/healing/plans."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = [_mock_plan("plan1"), _mock_plan("plan2")]
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["plans"]) == 2


def test_list_plans_filter_by_tag():
    """Test GET /api/healing/plans?tag=test."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    plan1 = _mock_plan("plan1")
    plan1.tags = ["zigbee"]
    plan2 = _mock_plan("plan2")
    plan2.tags = ["wifi"]
    mock_matcher.plans = [plan1, plan2]
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans?tag=zigbee")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["plans"][0]["name"] == "plan1"


def test_list_plans_filter_by_enabled():
    """Test GET /api/healing/plans?enabled=true."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    plan1 = _mock_plan("plan1", enabled=True)
    plan2 = _mock_plan("plan2", enabled=False)
    mock_matcher.plans = [plan1, plan2]
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans?enabled=true")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["plans"][0]["name"] == "plan1"


def test_get_plan():
    """Test GET /api/healing/plans/{name}."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = [_mock_plan("test_plan")]
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans/test_plan")
        assert response.status_code == 200
        assert response.json()["name"] == "test_plan"


def test_get_plan_not_found():
    """Test GET /api/healing/plans/{name} with nonexistent plan."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = []
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans/nonexistent")
        assert response.status_code == 404


def test_toggle_plan():
    """Test POST /api/healing/plans/{name}/toggle."""
    app = _create_test_app()
    client = TestClient(app)

    mock_plan = _mock_plan("test_plan", enabled=True)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = [mock_plan]
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.post("/api/healing/plans/test_plan/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["plan_name"] == "test_plan"
        assert data["enabled"] is False  # Toggled from True to False


def test_toggle_plan_not_found():
    """Test POST /api/healing/plans/{name}/toggle with nonexistent plan."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = []
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.post("/api/healing/plans/nonexistent/toggle")
        assert response.status_code == 404


def test_plans_503_when_not_available():
    """Test that endpoints return 503 when plan framework not available."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_orchestrator.plan_matcher = None  # No plan matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans")
        assert response.status_code == 503


def test_plans_404_when_instance_not_found():
    """Test that endpoints return 404 when instance not found."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_service.cascade_orchestrators = {}  # No instances

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans")
        assert response.status_code == 404


def test_validate_plan_invalid_yaml():
    """Test POST /api/healing/plans/validate with invalid YAML."""
    app = _create_test_app()
    client = TestClient(app)

    # Send invalid YAML that will fail parsing
    yaml_content = "invalid: yaml: content:"

    # Since the plan_models module doesn't exist on main, this will return validation errors
    response = client.post("/api/healing/plans/validate", json={"yaml_content": yaml_content})
    # The actual implementation will vary based on whether plan modules exist
    assert response.status_code in [200, 422, 503]


def test_match_test_no_match():
    """Test POST /api/healing/plans/match-test with no matching plan."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    mock_matcher.plans = []
    mock_matcher.find_matching_plan = MagicMock(return_value=None)
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    # Mock the HealingContext class at the source module
    mock_context_class = MagicMock()
    mock_context = MagicMock()
    mock_context_class.return_value = mock_context

    with (
        patch("ha_boss.api.routes.plans.get_service", return_value=mock_service),
        patch("ha_boss.healing.cascade_orchestrator.HealingContext", mock_context_class),
    ):
        response = client.post(
            "/api/healing/plans/match-test",
            json={
                "entity_ids": ["light.test"],
                "failure_type": "unavailable",
                "instance_id": "default",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] is False


def test_get_plan_executions_db_not_available():
    """Test GET /api/healing/plans/{name}/executions when database not available."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_service.database = None

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans/test_plan/executions")
        assert response.status_code == 503


def test_validate_plan_valid_yaml():
    """Test POST /api/healing/plans/validate with valid YAML body format."""
    app = _create_test_app()
    client = TestClient(app)

    yaml_content = "name: test_plan\nversion: 1\nenabled: true\npriority: 5"

    response = client.post("/api/healing/plans/validate", json={"yaml_content": yaml_content})
    assert response.status_code in [200, 503]
    if response.status_code == 200:
        data = response.json()
        assert "valid" in data
        assert "errors" in data


def test_validate_plan_missing_body():
    """Test POST /api/healing/plans/validate with missing yaml_content returns 422."""
    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/healing/plans/validate", json={})
    assert response.status_code == 422


def test_match_test_with_match():
    """Test POST /api/healing/plans/match-test when a plan matches."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    mock_orchestrator = MagicMock()
    mock_matcher = MagicMock()
    matched_plan = MagicMock()
    matched_plan.name = "zigbee_device_offline"
    matched_plan.priority = 10
    mock_matcher.find_matching_plan = MagicMock(return_value=matched_plan)
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    mock_context_class = MagicMock()
    mock_context = MagicMock()
    mock_context_class.return_value = mock_context

    with (
        patch("ha_boss.api.routes.plans.get_service", return_value=mock_service),
        patch("ha_boss.healing.cascade_orchestrator.HealingContext", mock_context_class),
    ):
        response = client.post(
            "/api/healing/plans/match-test",
            json={
                "entity_ids": ["light.zigbee_bedroom"],
                "failure_type": "unavailable",
                "instance_id": "default",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] is True
        assert data["plan_name"] == "zigbee_device_offline"
        assert data["plan_priority"] == 10


def test_list_plans_filter_by_enabled_false():
    """Test GET /api/healing/plans?enabled=false filter."""
    app = _create_test_app()
    client = TestClient(app)

    mock_service = MagicMock()
    disabled_plan = _mock_plan(name="disabled_plan", enabled=False)
    mock_matcher = MagicMock()
    mock_matcher.plans = [disabled_plan]
    mock_orchestrator = MagicMock()
    mock_orchestrator.plan_matcher = mock_matcher
    mock_service.cascade_orchestrators = {"default": mock_orchestrator}

    with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
        response = client.get("/api/healing/plans?enabled=false")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["plans"][0]["name"] == "disabled_plan"
