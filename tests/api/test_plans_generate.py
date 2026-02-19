"""Tests for plan generation, anonymization, and community URL API endpoints."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import HTTPException

from ha_boss.api.models import (
    AnonymizePlanResponse,
    CommunityUrlResponse,
)
from ha_boss.healing.plan_models import (
    HealingPlanDefinition,
    HealingStep,
    MatchCriteria,
)

VALID_YAML = """
name: test_zha_recovery
description: Recover ZHA entities
priority: 50
match:
  entity_patterns: ["light.bedroom"]
  integration_domains: ["zha"]
  failure_types: ["unavailable"]
steps:
  - name: reload_integration
    level: integration
    action: reload_integration
    timeout_seconds: 30
tags: ["zha"]
"""


def make_plan() -> HealingPlanDefinition:
    """Create a test healing plan definition."""
    return HealingPlanDefinition(
        name="test_zha_recovery",
        description="Recover ZHA entities",
        priority=50,
        match=MatchCriteria(
            entity_patterns=["light.bedroom"],
            integration_domains=["zha"],
            failure_types=["unavailable"],
        ),
        steps=[
            HealingStep(
                name="reload_integration",
                level="integration",
                action="reload_integration",
                timeout_seconds=30.0,
            )
        ],
        tags=["zha"],
    )


class TestGeneratePlanEndpoint:
    """Tests for POST /healing/plans/generate."""

    def test_generate_success(self) -> None:
        """Test successful plan generation returns YAML and plan details."""
        from ha_boss.healing.plan_generator import PlanGenerator

        mock_service = MagicMock()
        mock_service.config.intelligence.ollama_enabled = True
        mock_service.config.intelligence.ollama_url = "http://localhost:11434"
        mock_service.config.intelligence.ollama_model = "llama3.1"
        mock_service.config.intelligence.ollama_timeout_seconds = 30
        mock_service.config.intelligence.claude_enabled = False
        mock_service.config.intelligence.claude_api_key = None

        mock_plan = make_plan()

        with (
            patch("ha_boss.api.routes.plans.get_service", return_value=mock_service),
            patch.object(PlanGenerator, "generate_plan", new=AsyncMock(return_value=mock_plan)),
        ):
            from ha_boss.api.routes.plans import generate_plan

            request = MagicMock()
            request.entity_ids = ["light.bedroom"]
            request.failure_type = "unavailable"
            request.integration_domain = "zha"
            request.instance_id = "default"

            result = asyncio.get_event_loop().run_until_complete(generate_plan(request))

        assert result.generated is True
        assert result.yaml_content is not None
        assert result.plan is not None
        assert result.plan.name == "test_zha_recovery"
        assert result.error is None

    def test_generate_when_llm_unavailable_returns_generated_false(self) -> None:
        """When LLM has no clients, returns generated=False with error message."""
        mock_service = MagicMock()
        mock_service.config.intelligence.ollama_enabled = False
        mock_service.config.intelligence.claude_enabled = False
        mock_service.config.intelligence.claude_api_key = None

        with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
            from ha_boss.api.routes.plans import generate_plan

            request = MagicMock()
            request.entity_ids = ["light.bedroom"]
            request.failure_type = "unavailable"
            request.integration_domain = None
            request.instance_id = "default"

            result = asyncio.get_event_loop().run_until_complete(generate_plan(request))

        assert result.generated is False
        assert result.error is not None
        assert "LLM" in result.error or "configured" in result.error.lower()

    def test_generate_when_no_intelligence_config(self) -> None:
        """When intelligence config is absent (no config.intelligence attr), returns generated=False."""
        mock_config = MagicMock(spec=[])  # config has no attributes
        mock_service = MagicMock()
        mock_service.config = mock_config

        with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
            from ha_boss.api.routes.plans import generate_plan

            request = MagicMock()
            request.entity_ids = ["light.bedroom"]
            request.failure_type = "unavailable"
            request.integration_domain = None
            request.instance_id = "default"

            result = asyncio.get_event_loop().run_until_complete(generate_plan(request))

        assert result.generated is False


class TestAnonymizePlanEndpoint:
    """Tests for POST /healing/plans/anonymize."""

    def test_anonymize_rewrites_specific_entity_patterns(self) -> None:
        """Specific entity IDs in patterns are replaced with domain globs."""
        from ha_boss.api.routes.plans import anonymize_plan

        request = MagicMock()
        request.yaml_content = VALID_YAML

        result = asyncio.get_event_loop().run_until_complete(anonymize_plan(request))

        assert isinstance(result, AnonymizePlanResponse)
        assert result.yaml_content is not None
        # The specific 'light.bedroom' should become 'light.*'
        anon_data = yaml.safe_load(result.yaml_content)
        patterns = anon_data["match"]["entity_patterns"]
        assert all("bedroom" not in p for p in patterns)
        assert any(p.endswith(".*") or "*" in p for p in patterns)

    def test_anonymize_invalid_yaml_returns_422(self) -> None:
        """Invalid YAML returns 422 error."""
        from ha_boss.api.routes.plans import anonymize_plan

        request = MagicMock()
        request.yaml_content = "invalid: yaml: {"

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(anonymize_plan(request))

        assert exc_info.value.status_code == 422


class TestCommunityUrlEndpoint:
    """Tests for POST /healing/plans/community-url."""

    def test_community_url_returns_valid_github_url(self) -> None:
        """Returns a GitHub new-issue URL with plan name and YAML encoded."""
        mock_service = MagicMock()
        mock_service.config.healing.community_plans_repo = "jasonthagerty/ha-boss-community-plans"

        with patch("ha_boss.api.routes.plans.get_service", return_value=mock_service):
            from ha_boss.api.routes.plans import get_community_url

            request = MagicMock()
            request.yaml_content = VALID_YAML

            result = asyncio.get_event_loop().run_until_complete(get_community_url(request))

        assert isinstance(result, CommunityUrlResponse)
        assert result.url.startswith(
            "https://github.com/jasonthagerty/ha-boss-community-plans/issues/new"
        )
        assert "test_zha_recovery" in result.url or "Healing" in result.url
        assert result.repo == "jasonthagerty/ha-boss-community-plans"
