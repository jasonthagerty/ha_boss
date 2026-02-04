"""Automation management endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    AIFailureAnalysis,
    AutomationAnalysisRequest,
    AutomationAnalysisResponse,
    DesiredStateCreateRequest,
    DesiredStateResponse,
    DesiredStateUpdateRequest,
    EntityFailureDetail,
    FailureReportRequest,
    FailureReportResponse,
    InferenceMethod,
    InferredStateResponse,
)
from ha_boss.automation.analyzer import AutomationAnalyzer
from ha_boss.core.exceptions import HomeAssistantError
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
            instance_id=instance_id,
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


# Desired States Endpoints


@router.get(
    "/automations/{automation_id}/desired-states",
    response_model=list[DesiredStateResponse],
)
async def get_desired_states(
    automation_id: str,
    instance_id: str = Query("default", description="Instance identifier"),
) -> list[DesiredStateResponse]:
    """Get desired states for an automation.

    Returns all desired entity states for the specified automation,
    sorted by confidence (highest first).

    Args:
        automation_id: Automation entity ID
        instance_id: Instance identifier (default: "default")

    Returns:
        List of desired states

    Raises:
        HTTPException: Instance not found (404) or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Query database for desired states
        async with service.database.async_session() as session:
            from sqlalchemy import select

            from ha_boss.core.database import AutomationDesiredState

            stmt = (
                select(AutomationDesiredState)
                .where(
                    AutomationDesiredState.instance_id == instance_id,
                    AutomationDesiredState.automation_id == automation_id,
                )
                .order_by(AutomationDesiredState.confidence.desc())
            )

            result = await session.execute(stmt)
            states = result.scalars().all()

        return [
            DesiredStateResponse(
                entity_id=state.entity_id,
                desired_state=state.desired_state,
                desired_attributes=state.desired_attributes,
                confidence=state.confidence,
                inference_method=state.inference_method,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
            for state in states
        ]

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error fetching desired states for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch desired states") from None


@router.post(
    "/automations/{automation_id}/desired-states",
    response_model=DesiredStateResponse,
    status_code=201,
)
async def create_desired_state(
    automation_id: str,
    request: DesiredStateCreateRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> DesiredStateResponse:
    """Create or update a user-annotated desired state.

    Allows users to manually specify the expected outcome for an automation.
    Sets inference_method="user_annotated" and confidence=1.0.

    Args:
        automation_id: Automation entity ID
        request: Desired state to create
        instance_id: Instance identifier (default: "default")

    Returns:
        Created desired state

    Raises:
        HTTPException: Instance not found (404), entity not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        ha_client = service.ha_clients.get(instance_id)
        if not ha_client:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Validate entity exists in HA (optional but recommended)
        try:
            await ha_client.get_state(request.entity_id)
        except HomeAssistantError:
            # Expected - entity might not exist yet or be temporarily unavailable
            logger.debug(
                f"[{instance_id}] Entity {request.entity_id} not found in HA - will create desired state anyway"
            )
        except Exception as e:
            # Unexpected error (connection, auth, etc.) - log but don't block
            logger.error(
                f"[{instance_id}] Unexpected error validating {request.entity_id}: {e}",
                exc_info=True,
            )

        # Create or update desired state in database
        from datetime import UTC, datetime

        from ha_boss.core.database import AutomationDesiredState

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Check if state already exists
            stmt = select(AutomationDesiredState).where(
                AutomationDesiredState.instance_id == instance_id,
                AutomationDesiredState.automation_id == automation_id,
                AutomationDesiredState.entity_id == request.entity_id,
            )
            result = await session.execute(stmt)
            existing_state = result.scalar_one_or_none()

            if existing_state:
                # Update existing
                existing_state.desired_state = request.desired_state
                existing_state.desired_attributes = request.desired_attributes
                existing_state.confidence = 1.0
                existing_state.inference_method = InferenceMethod.USER_ANNOTATED.value
                existing_state.updated_at = datetime.now(UTC)
                state = existing_state
            else:
                # Create new
                state = AutomationDesiredState(
                    instance_id=instance_id,
                    automation_id=automation_id,
                    entity_id=request.entity_id,
                    desired_state=request.desired_state,
                    desired_attributes=request.desired_attributes,
                    confidence=1.0,
                    inference_method=InferenceMethod.USER_ANNOTATED.value,
                )
                session.add(state)

            await session.commit()
            await session.refresh(state)

            return DesiredStateResponse(
                entity_id=state.entity_id,
                desired_state=state.desired_state,
                desired_attributes=state.desired_attributes,
                confidence=state.confidence,
                inference_method=state.inference_method,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error creating desired state for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to create desired state") from None


@router.put(
    "/automations/{automation_id}/desired-states/{entity_id}",
    response_model=DesiredStateResponse,
)
async def update_desired_state(
    automation_id: str,
    entity_id: str,
    request: DesiredStateUpdateRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> DesiredStateResponse:
    """Update an existing desired state.

    Allows editing state, attributes, or confidence score.

    Args:
        automation_id: Automation entity ID
        entity_id: Target entity ID
        request: Fields to update
        instance_id: Instance identifier (default: "default")

    Returns:
        Updated desired state

    Raises:
        HTTPException: Instance not found (404), desired state not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        from datetime import UTC, datetime

        from ha_boss.core.database import AutomationDesiredState

        async with service.database.async_session() as session:
            from sqlalchemy import select

            # Find existing state
            stmt = select(AutomationDesiredState).where(
                AutomationDesiredState.instance_id == instance_id,
                AutomationDesiredState.automation_id == automation_id,
                AutomationDesiredState.entity_id == entity_id,
            )
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if not state:
                raise HTTPException(
                    status_code=404,
                    detail=f"Desired state not found for automation '{automation_id}' and entity '{entity_id}'",
                ) from None

            # Update fields
            if request.desired_state is not None:
                state.desired_state = request.desired_state
            if request.desired_attributes is not None:
                state.desired_attributes = request.desired_attributes
            if request.confidence is not None:
                state.confidence = request.confidence

            state.updated_at = datetime.now(UTC)

            await session.commit()
            await session.refresh(state)

            return DesiredStateResponse(
                entity_id=state.entity_id,
                desired_state=state.desired_state,
                desired_attributes=state.desired_attributes,
                confidence=state.confidence,
                inference_method=state.inference_method,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error updating desired state for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update desired state") from None


@router.delete(
    "/automations/{automation_id}/desired-states/{entity_id}",
    status_code=204,
)
async def delete_desired_state(
    automation_id: str,
    entity_id: str,
    instance_id: str = Query("default", description="Instance identifier"),
) -> None:
    """Delete a desired state entry.

    Args:
        automation_id: Automation entity ID
        entity_id: Target entity ID
        instance_id: Instance identifier (default: "default")

    Raises:
        HTTPException: Instance not found (404), desired state not found (404), or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        if instance_id not in service.ha_clients:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        from ha_boss.core.database import AutomationDesiredState

        async with service.database.async_session() as session:
            from sqlalchemy import delete

            # Delete state
            stmt = delete(AutomationDesiredState).where(
                AutomationDesiredState.instance_id == instance_id,
                AutomationDesiredState.automation_id == automation_id,
                AutomationDesiredState.entity_id == entity_id,
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Desired state not found for automation '{automation_id}' and entity '{entity_id}'",
                ) from None

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error deleting desired state for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to delete desired state") from None


@router.post(
    "/automations/{automation_id}/infer-states",
    response_model=list[InferredStateResponse],
)
async def infer_desired_states(
    automation_id: str,
    instance_id: str = Query("default", description="Instance identifier"),
    save: bool = Query(False, description="Save inferred states to database (default: false)"),
) -> list[InferredStateResponse]:
    """Trigger AI inference for automation desired states.

    Uses the DesiredStateInference service to analyze the automation
    and infer what entity states it's trying to achieve.

    By default, inference is read-only (save=false). Set save=true to
    persist inferred states to the database for use in outcome validation.

    Args:
        automation_id: Automation entity ID
        instance_id: Instance identifier (default: "default")
        save: Whether to save inferred states to database (default: False)

    Returns:
        List of inferred states

    Raises:
        HTTPException: Instance not found (404), automation not found (404),
                      AI not configured (503), or service error (500)
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

        # Check if AI features are configured
        if not hasattr(service.config, "intelligence"):
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Set up Ollama or Claude API in configuration.",
            ) from None

        # Get automation configuration
        try:
            automation_state = await ha_client.get_state(automation_id)
            automation_config = automation_state.get("attributes", {})

            if not automation_config or "action" not in automation_config:
                raise HTTPException(
                    status_code=404,
                    detail=f"Automation '{automation_id}' not found or has no actions",
                ) from None
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"[{instance_id}] Error fetching automation {automation_id}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=404,
                detail=f"Automation '{automation_id}' not found or inaccessible",
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

        # Validate that at least one LLM is available
        if not ollama_client and not claude_client:
            raise HTTPException(
                status_code=503,
                detail="AI features not configured. Enable Ollama or Claude in configuration.",
            ) from None

        # Create LLM router
        llm_router = LLMRouter(
            ollama_client=ollama_client,
            claude_client=claude_client,
            local_only=not service.config.intelligence.claude_enabled,
        )

        # Create inference service
        from ha_boss.automation.desired_state_inference import DesiredStateInference

        inference = DesiredStateInference(
            llm_router=llm_router,
            database=service.database if save else None,
            instance_id=instance_id,
        )

        # Infer states
        inferred_states = await inference.infer_from_automation(
            automation_id=automation_id,
            automation_config=automation_config,
            use_cache=False,  # Always re-infer for API calls
        )

        return [
            InferredStateResponse(
                entity_id=state.entity_id,
                desired_state=state.desired_state,
                desired_attributes=state.desired_attributes,
                confidence=state.confidence,
            )
            for state in inferred_states
        ]

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error inferring desired states for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to infer desired states") from None


@router.post(
    "/automations/{automation_id}/report-failure",
    response_model=FailureReportResponse,
)
async def report_automation_failure(
    automation_id: str,
    request: FailureReportRequest,
    instance_id: str = Query("default", description="Instance identifier"),
) -> FailureReportResponse:
    """Report automation failure and get AI analysis.

    Triggers retroactive outcome validation and optional AI analysis
    of the automation failure. If no execution_id is provided, validates
    the most recent execution.

    Args:
        automation_id: Automation entity ID
        request: Failure report details
        instance_id: Instance identifier (default: "default")

    Returns:
        Validation results and AI analysis

    Raises:
        HTTPException: Instance not found (404), no execution found (404),
                      or service error (500)
    """
    try:
        service = get_service()

        # Validate instance exists
        ha_client = service.ha_clients.get(instance_id)
        if not ha_client:
            raise HTTPException(
                status_code=404,
                detail=f"Instance '{instance_id}' not found. Available instances: {list(service.ha_clients.keys())}",
            ) from None

        # Find execution_id if not provided
        execution_id = request.execution_id
        if not execution_id:
            # Query for most recent execution
            from sqlalchemy import select

            from ha_boss.core.database import AutomationExecution

            async with service.database.async_session() as session:
                result = await session.execute(
                    select(AutomationExecution.id)
                    .where(
                        AutomationExecution.instance_id == instance_id,
                        AutomationExecution.automation_id == automation_id,
                        AutomationExecution.success == True,  # noqa: E712
                    )
                    .order_by(AutomationExecution.executed_at.desc())
                    .limit(1)
                )
                execution_id = result.scalar_one_or_none()

            if not execution_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"No successful execution found for {automation_id}",
                ) from None

        # Create LLM router if AI analysis is enabled
        llm_router = None
        if service.config.outcome_validation.analyze_failures:
            if (
                service.config.intelligence.ollama_enabled
                or service.config.intelligence.claude_enabled
            ):
                from ha_boss.intelligence.llm_router import LLMRouter
                from ha_boss.intelligence.ollama_client import OllamaClient

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
                    from ha_boss.intelligence.claude_client import ClaudeClient

                    claude_client = ClaudeClient(
                        api_key=service.config.intelligence.claude_api_key,
                        model=service.config.intelligence.claude_model,
                    )

                llm_router = LLMRouter(
                    ollama_client=ollama_client,
                    claude_client=claude_client,
                    local_only=not service.config.intelligence.claude_enabled,
                )

        # Trigger outcome validation
        from ha_boss.automation.outcome_validator import OutcomeValidator

        validator = OutcomeValidator(
            database=service.database,
            ha_client=ha_client,
            instance_id=instance_id,
            llm_router=llm_router,
            config=service.config,
        )

        validation_result = await validator.validate_execution(
            execution_id=execution_id,
            validation_window_seconds=service.config.outcome_validation.validation_delay_seconds,
        )

        # Build failed entities list
        failed_entities = [
            EntityFailureDetail(
                entity_id=entity_id,
                desired_state=entity_result.desired_state,
                actual_state=entity_result.actual_state,
                root_cause=None,  # Will be populated by AI analysis
            )
            for entity_id, entity_result in validation_result.entity_results.items()
            if not entity_result.achieved
        ]

        # Perform AI analysis if enabled and LLM router is available
        ai_analysis = None
        if service.config.outcome_validation.analyze_failures and llm_router is not None:
            # Get automation config if possible
            automation_config = None
            try:
                automation_state = await ha_client.get_state(automation_id)
                automation_config = automation_state.get("attributes", {})
            except Exception as e:
                logger.warning(f"[{instance_id}] Could not fetch automation config: {e}")

            # Run AI analysis
            try:
                analysis_result = await validator.analyze_failure(
                    automation_id=automation_id,
                    validation_result=validation_result,
                    automation_config=automation_config,
                    user_description=request.user_description,
                )

                ai_analysis = AIFailureAnalysis(
                    root_cause=analysis_result["root_cause"],
                    suggested_healing=analysis_result["suggested_healing"],
                    healing_level=analysis_result["healing_level"],
                )

            except Exception as e:
                logger.error(
                    f"[{instance_id}] Error running AI analysis: {e}",
                    exc_info=True,
                )
        elif service.config.outcome_validation.analyze_failures:
            logger.warning(f"[{instance_id}] AI analysis requested but no LLM configured")

        return FailureReportResponse(
            execution_id=execution_id,
            automation_id=automation_id,
            overall_success=validation_result.overall_success,
            failed_entities=failed_entities,
            ai_analysis=ai_analysis,
            user_description=request.user_description,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[{instance_id}] Service not initialized: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from None
    except Exception as e:
        logger.error(
            f"[{instance_id}] Error reporting failure for {automation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to process failure report") from None
