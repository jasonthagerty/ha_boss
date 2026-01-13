"""Automation management endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    AutomationAnalysisRequest,
    AutomationAnalysisResponse,
    AutomationCreateRequest,
    AutomationCreateResponse,
    AutomationGenerateRequest,
    AutomationGenerateResponse,
)
from ha_boss.automation.analyzer import AutomationAnalyzer
from ha_boss.automation.generator import AutomationGenerator
from ha_boss.intelligence.claude_client import ClaudeClient
from ha_boss.intelligence.llm_router import LLMRouter
from ha_boss.intelligence.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/automations/analyze", response_model=AutomationAnalysisResponse)
async def analyze_automation(
    request: AutomationAnalysisRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> AutomationAnalysisResponse:
    """Analyze an existing Home Assistant automation for a specific instance.

    Uses AI to analyze an automation and provide:
    - Detailed analysis of the automation's purpose and logic
    - Optimization suggestions
    - Complexity assessment

    Args:
        request: Automation analysis request with automation ID
        instance_id: Instance identifier (default: "default")

    Returns:
        Analysis result with suggestions

    Raises:
        HTTPException: Instance not found (404), automation not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists and get HA client
        ha_client = service.ha_clients.get(instance_id)
        if not ha_client:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Check if LLM features are configured
        if not hasattr(service.config, "intelligence"):
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Set up Ollama or Claude API in configuration.",
            ) from None

        # Create LLM clients
        ollama_client = None
        claude_client = None

        if service.config.intelligence.ollama_enabled:
            ollama_client = OllamaClient(
                url=service.config.intelligence.ollama_url,
                model=service.config.intelligence.ollama_model,
                timeout=service.config.intelligence.ollama_timeout_seconds,
            )

        if (
            service.config.intelligence.claude_enabled
            and service.config.intelligence.claude_api_key
        ):
            claude_client = ClaudeClient(
                api_key=service.config.intelligence.claude_api_key,
                model=service.config.intelligence.claude_model,
            )

        # Create LLM router
        llm_router = LLMRouter(
            ollama_client=ollama_client,
            claude_client=claude_client,
            local_only=not service.config.intelligence.claude_enabled,
        )

        # Create analyzer
        analyzer = AutomationAnalyzer(
            ha_client=ha_client,
            config=service.config,
            llm_router=llm_router,
        )

        # Analyze automation
        analysis = await analyzer.analyze_automation(request.automation_id)

        if not analysis:
            raise HTTPException(
                status_code=404,
                detail=f"Automation '{request.automation_id}' not found or analysis failed",
            ) from None

        # Convert suggestions to strings for API response
        suggestion_strings = [
            f"{s.severity.value.upper()}: {s.title} - {s.description}" for s in analysis.suggestions
        ]

        return AutomationAnalysisResponse(
            automation_id=analysis.automation_id,
            alias=analysis.friendly_name,
            analysis=analysis.ai_analysis or "No AI analysis available",
            suggestions=suggestion_strings,
            complexity_score=None,  # Not available in AnalysisResult
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error analyzing automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze automation") from None


@router.post("/automations/generate", response_model=AutomationGenerateResponse)
async def generate_automation(
    request: AutomationGenerateRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> AutomationGenerateResponse:
    """Generate a new automation from natural language description for a specific instance.

    Uses AI to generate a complete Home Assistant automation YAML from
    a natural language description. The generated automation is validated
    but not created in Home Assistant - use the create endpoint for that.

    Args:
        request: Automation generation request with description and mode
        instance_id: Instance identifier (default: "default")

    Returns:
        Generated automation with YAML and validation results

    Raises:
        HTTPException: Instance not found (404) or generation failed (400)
    """
    try:
        service = get_service()

        # Validate instance exists and get HA client
        ha_client = service.ha_clients.get(instance_id)
        if not ha_client:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Check if LLM features are configured
        if not hasattr(service.config, "intelligence"):
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Set up Ollama or Claude API in configuration.",
            ) from None

        # Create LLM clients
        ollama_client = None
        claude_client = None

        if service.config.intelligence.ollama_enabled:
            ollama_client = OllamaClient(
                url=service.config.intelligence.ollama_url,
                model=service.config.intelligence.ollama_model,
                timeout=service.config.intelligence.ollama_timeout_seconds,
            )

        if (
            service.config.intelligence.claude_enabled
            and service.config.intelligence.claude_api_key
        ):
            claude_client = ClaudeClient(
                api_key=service.config.intelligence.claude_api_key,
                model=service.config.intelligence.claude_model,
            )

        # Create LLM router
        llm_router = LLMRouter(
            ollama_client=ollama_client,
            claude_client=claude_client,
            local_only=not service.config.intelligence.claude_enabled,
        )

        # Create generator
        generator = AutomationGenerator(
            ha_client=ha_client,
            config=service.config,
            llm_router=llm_router,
        )

        # Generate automation
        generated = await generator.generate_from_prompt(
            prompt=request.description,
            mode=request.mode,
        )

        if not generated:
            raise HTTPException(
                status_code=400,
                detail="Failed to generate automation. Check the description and try again.",
            )

        return AutomationGenerateResponse(
            automation_id=generated.automation_id,
            alias=generated.alias,
            description=generated.description,
            yaml_content=generated.raw_yaml,
            validation_errors=generated.validation_errors,
            is_valid=generated.is_valid,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error generating automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate automation") from None


@router.post("/automations/create", response_model=AutomationCreateResponse)
async def create_automation(
    request: AutomationCreateRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> AutomationCreateResponse:
    """Create an automation in Home Assistant for a specific instance.

    Takes a validated automation YAML and creates it in Home Assistant
    via the REST API.

    Args:
        request: Automation creation request with YAML content
        instance_id: Instance identifier (default: "default")

    Returns:
        Creation result with automation ID if successful

    Raises:
        HTTPException: Instance not found (404) or creation failed (400)
    """
    try:
        service = get_service()

        # Validate instance exists and get HA client
        ha_client = service.ha_clients.get(instance_id)
        if not ha_client:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Parse and create automation
        import yaml

        try:
            automation_dict = yaml.safe_load(request.automation_yaml)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e

        # Create automation in HA
        result = await ha_client.create_automation(automation_dict)

        if result.get("success"):
            return AutomationCreateResponse(
                success=True,
                automation_id=result.get("id"),
                message="Automation created successfully",
            )
        else:
            return AutomationCreateResponse(
                success=False,
                automation_id=None,
                message=result.get("error", "Failed to create automation"),
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(f"[{instance_id}] Error creating automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create automation") from None
