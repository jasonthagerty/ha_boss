"""Automation management endpoints."""

import logging

from fastapi import APIRouter, HTTPException

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
from ha_boss.intelligence.llm_router import LLMRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/automations/analyze", response_model=AutomationAnalysisResponse)
async def analyze_automation(request: AutomationAnalysisRequest) -> AutomationAnalysisResponse:
    """Analyze an existing Home Assistant automation.

    Uses AI to analyze an automation and provide:
    - Detailed analysis of the automation's purpose and logic
    - Optimization suggestions
    - Complexity assessment

    Args:
        request: Automation analysis request with automation ID

    Returns:
        Analysis result with suggestions

    Raises:
        HTTPException: Service error (500) or automation not found (404)
    """
    try:
        service = get_service()

        if not service.ha_client:
            raise HTTPException(status_code=500, detail="Home Assistant client not initialized") from None

        # Check if LLM router is configured
        if not hasattr(service.config, "ai") or not service.config.ai:
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Set up Ollama or Claude API in configuration.",
            )

        # Create LLM router and analyzer
        llm_router = LLMRouter(service.config)
        analyzer = AutomationAnalyzer(
            ha_client=service.ha_client,
            config=service.config,
            llm_router=llm_router,
        )

        # Analyze automation
        analysis = await analyzer.analyze_automation(request.automation_id)

        if not analysis:
            raise HTTPException(
                status_code=404,
                detail=f"Automation '{request.automation_id}' not found or analysis failed",
            )

        return AutomationAnalysisResponse(
            automation_id=analysis.automation_id,
            alias=analysis.alias,
            analysis=analysis.analysis,
            suggestions=analysis.suggestions,
            complexity_score=analysis.complexity_score,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error analyzing automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze automation") from None


@router.post("/automations/generate", response_model=AutomationGenerateResponse)
async def generate_automation(request: AutomationGenerateRequest) -> AutomationGenerateResponse:
    """Generate a new automation from natural language description.

    Uses AI to generate a complete Home Assistant automation YAML from
    a natural language description. The generated automation is validated
    but not created in Home Assistant - use the create endpoint for that.

    Args:
        request: Automation generation request with description and mode

    Returns:
        Generated automation with YAML and validation results

    Raises:
        HTTPException: Service error (500) or generation failed (400)
    """
    try:
        service = get_service()

        if not service.ha_client:
            raise HTTPException(status_code=500, detail="Home Assistant client not initialized") from None

        # Check if LLM router is configured
        if not hasattr(service.config, "ai") or not service.config.ai:
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Set up Ollama or Claude API in configuration.",
            )

        # Create LLM router and generator
        llm_router = LLMRouter(service.config)
        generator = AutomationGenerator(
            ha_client=service.ha_client,
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
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error generating automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate automation") from None


@router.post("/automations/create", response_model=AutomationCreateResponse)
async def create_automation(request: AutomationCreateRequest) -> AutomationCreateResponse:
    """Create an automation in Home Assistant.

    Takes a validated automation YAML and creates it in Home Assistant
    via the REST API.

    Args:
        request: Automation creation request with YAML content

    Returns:
        Creation result with automation ID if successful

    Raises:
        HTTPException: Service error (500) or creation failed (400)
    """
    try:
        service = get_service()

        if not service.ha_client:
            raise HTTPException(status_code=500, detail="Home Assistant client not initialized") from None

        # Parse and create automation
        import yaml

        try:
            automation_dict = yaml.safe_load(request.automation_yaml)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e

        # Create automation in HA
        result = await service.ha_client.create_automation(automation_dict)

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
        logger.error(f"Service not initialized: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Error creating automation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create automation") from None
