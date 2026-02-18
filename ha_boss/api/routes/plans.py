"""Healing plan management API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ha_boss.api.app import get_service
from ha_boss.api.models import (
    HealingPlanExecutionResponse,
    HealingPlanListResponse,
    HealingPlanMatchCriteria,
    HealingPlanMatchTestRequest,
    HealingPlanMatchTestResponse,
    HealingPlanResponse,
    HealingPlanStepResponse,
    HealingPlanValidateRequest,
    HealingPlanValidationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_plan_components(instance_id: str = "default") -> tuple[Any, Any]:
    """Get plan matcher and executor from the cascade orchestrator.

    Returns:
        Tuple of (plan_matcher, plan_executor)

    Raises:
        HTTPException: If plan framework is not available
    """
    service = get_service()
    orchestrator = service.cascade_orchestrators.get(instance_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    plan_matcher = getattr(orchestrator, "plan_matcher", None)
    if not plan_matcher:
        raise HTTPException(
            status_code=503,
            detail="Healing plan framework not available. "
            "Ensure healing_plans_enabled is true in config.",
        )
    plan_executor = getattr(orchestrator, "plan_executor", None)
    return plan_matcher, plan_executor


def _plan_to_response(plan: Any, source: str = "unknown") -> HealingPlanResponse:
    """Convert a plan definition to API response model."""
    match_criteria = HealingPlanMatchCriteria(
        entity_patterns=(
            getattr(plan.match, "entity_patterns", []) if hasattr(plan, "match") else []
        ),
        integration_domains=(
            getattr(plan.match, "integration_domains", []) if hasattr(plan, "match") else []
        ),
        failure_types=getattr(plan.match, "failure_types", []) if hasattr(plan, "match") else [],
    )
    steps = []
    for step in getattr(plan, "steps", []):
        steps.append(
            HealingPlanStepResponse(
                name=step.name,
                level=step.level,
                action=step.action,
                params=step.params if hasattr(step, "params") else {},
                timeout_seconds=step.timeout_seconds if hasattr(step, "timeout_seconds") else 30.0,
            )
        )
    return HealingPlanResponse(
        name=plan.name,
        description=getattr(plan, "description", ""),
        version=getattr(plan, "version", 1),
        enabled=getattr(plan, "enabled", True),
        priority=getattr(plan, "priority", 0),
        source=source,
        match_criteria=match_criteria,
        steps=steps,
        tags=getattr(plan, "tags", []),
    )


@router.get("/healing/plans", response_model=HealingPlanListResponse)
async def list_plans(
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    tag: str | None = Query(None, description="Filter by tag"),
) -> HealingPlanListResponse:
    """List all configured healing plans."""
    plan_matcher, _ = _get_plan_components()

    plans = []
    for plan in plan_matcher.plans:
        # Apply filters
        if enabled is not None and getattr(plan, "enabled", True) != enabled:
            continue
        if tag and tag not in getattr(plan, "tags", []):
            continue

        plans.append(_plan_to_response(plan, source="loaded"))

    return HealingPlanListResponse(plans=plans, total=len(plans))


@router.get("/healing/plans/{plan_name}", response_model=HealingPlanResponse)
async def get_plan(plan_name: str) -> HealingPlanResponse:
    """Get a specific healing plan by name."""
    plan_matcher, _ = _get_plan_components()

    for plan in plan_matcher.plans:
        if plan.name == plan_name:
            return _plan_to_response(plan, source="loaded")

    raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found")


@router.post("/healing/plans/{plan_name}/toggle")
async def toggle_plan(plan_name: str) -> dict[str, Any]:
    """Enable or disable a healing plan."""
    plan_matcher, _ = _get_plan_components()

    for plan in plan_matcher.plans:
        if plan.name == plan_name:
            current = getattr(plan, "enabled", True)
            plan.enabled = not current
            return {
                "plan_name": plan_name,
                "enabled": plan.enabled,
                "message": f"Plan '{plan_name}' {'enabled' if plan.enabled else 'disabled'}",
            }

    raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found")


@router.post("/healing/plans/validate", response_model=HealingPlanValidationResponse)
async def validate_plan(request: HealingPlanValidateRequest) -> HealingPlanValidationResponse:
    """Validate a YAML healing plan without saving it."""
    try:
        import yaml

        from ha_boss.healing.plan_models import HealingPlanDefinition

        data = yaml.safe_load(request.yaml_content)
        plan = HealingPlanDefinition(**data)
        return HealingPlanValidationResponse(
            valid=True,
            errors=[],
            plan=_plan_to_response(plan, source="validation"),
        )
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="Plan validation modules not available",
        ) from e
    except Exception as e:
        return HealingPlanValidationResponse(
            valid=False,
            errors=[str(e)],
            plan=None,
        )


@router.post("/healing/plans/match-test", response_model=HealingPlanMatchTestResponse)
async def match_test(request: HealingPlanMatchTestRequest) -> HealingPlanMatchTestResponse:
    """Test which plan would match a given failure scenario."""
    plan_matcher, _ = _get_plan_components(request.instance_id)

    try:
        from ha_boss.healing.cascade_orchestrator import HealingContext

        context = HealingContext(
            instance_id=request.instance_id,
            automation_id="match_test",
            execution_id=None,
            trigger_type="trigger_failure",
            failed_entities=request.entity_ids,
        )
        matched_plan = plan_matcher.find_matching_plan(context)

        if matched_plan:
            return HealingPlanMatchTestResponse(
                matched=True,
                plan_name=matched_plan.name,
                plan_priority=getattr(matched_plan, "priority", 0),
            )
        return HealingPlanMatchTestResponse(matched=False, plan_name=None, plan_priority=None)

    except Exception as e:
        logger.error(f"Match test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Match test failed: {e}") from e


@router.get(
    "/healing/plans/{plan_name}/executions",
    response_model=list[HealingPlanExecutionResponse],
)
async def get_plan_executions(
    plan_name: str,
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
) -> list[HealingPlanExecutionResponse]:
    """Get execution history for a healing plan."""
    service = get_service()
    if not service.database:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        from sqlalchemy import desc, select

        from ha_boss.core.database import HealingPlanExecution  # type: ignore[attr-defined]

        async with service.database.async_session() as session:
            stmt = (
                select(HealingPlanExecution)
                .where(HealingPlanExecution.plan_name == plan_name)
                .order_by(desc(HealingPlanExecution.created_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            executions = result.scalars().all()

            return [
                HealingPlanExecutionResponse(
                    id=exc.id,
                    plan_name=exc.plan_name,
                    success=exc.success or False,
                    steps_attempted=exc.steps_attempted or 0,
                    steps_succeeded=exc.steps_succeeded or 0,
                    total_duration_seconds=exc.total_duration_seconds or 0.0,
                    created_at=exc.created_at,
                    error_message=exc.error_message,
                )
                for exc in executions
            ]
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="Healing plan database models not available",
        ) from e
    except Exception as e:
        logger.error(f"Failed to fetch plan executions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch executions: {e}") from e
