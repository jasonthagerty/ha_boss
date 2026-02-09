"""Load and validate YAML healing plans from filesystem and database.

Plans are loaded from two sources:
1. Built-in plans from ha_boss/healing/plans/ (source='builtin')
2. User plans from the configured plans directory (source='user')
3. Plans stored in the database via the API

Plans are validated against the Pydantic schema and stored in the
database for API access and execution stats tracking.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select

from ha_boss.core.database import Database, HealingPlan
from ha_boss.core.exceptions import HealingPlanNotFoundError, HealingPlanValidationError
from ha_boss.healing.plan_models import HealingPlanDefinition

logger = logging.getLogger(__name__)

# Built-in plans directory
BUILTIN_PLANS_DIR = Path(__file__).parent / "plans"


class PlanLoader:
    """Load and manage healing plans from YAML files and database.

    Plans are loaded from the filesystem on startup and synced to the
    database. The database copy is the runtime source of truth for
    enabled/disabled state and execution statistics.
    """

    def __init__(
        self,
        database: Database,
        user_plans_directory: str | None = None,
        use_builtin: bool = True,
    ) -> None:
        """Initialize plan loader.

        Args:
            database: Database for storing/querying plans
            user_plans_directory: Optional path to user-defined plans
            use_builtin: Whether to load built-in plans (default: True)
        """
        self.database = database
        self.user_plans_dir = Path(user_plans_directory) if user_plans_directory else None
        self.use_builtin = use_builtin
        self._plans: dict[str, HealingPlanDefinition] = {}

    async def load_all_plans(self) -> list[HealingPlanDefinition]:
        """Load all plans from filesystem and sync to database.

        Returns:
            List of validated plan definitions
        """
        plans: list[HealingPlanDefinition] = []
        builtin_names: set[str] = set()

        # Load built-in plans
        if self.use_builtin and BUILTIN_PLANS_DIR.exists():
            builtin_plans = self._load_plans_from_directory(BUILTIN_PLANS_DIR, source="builtin")
            plans.extend(builtin_plans)
            builtin_names = {p.name for p in builtin_plans}
            logger.info(f"Loaded {len(builtin_plans)} built-in plans")

        # Load user plans
        if self.user_plans_dir and self.user_plans_dir.exists():
            user_plans = self._load_plans_from_directory(self.user_plans_dir, source="user")
            plans.extend(user_plans)
            logger.info(f"Loaded {len(user_plans)} user plans")

        # Sync to database
        for plan in plans:
            source = "builtin" if plan.name in builtin_names else "user"
            await self._sync_plan_to_db(plan, source)

        # Cache plans
        self._plans = {plan.name: plan for plan in plans}

        logger.info(f"Total plans loaded: {len(plans)}")
        return plans

    def _load_plans_from_directory(
        self, directory: Path, source: str
    ) -> list[HealingPlanDefinition]:
        """Load and validate all YAML plans from a directory.

        Args:
            directory: Directory containing .yaml plan files
            source: Plan source ('builtin' or 'user')

        Returns:
            List of validated plan definitions
        """
        plans: list[HealingPlanDefinition] = []

        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                plan = self.load_plan_from_file(yaml_file)
                plans.append(plan)
                logger.debug(f"Loaded plan '{plan.name}' from {yaml_file} (source={source})")
            except (HealingPlanValidationError, yaml.YAMLError) as e:
                logger.error(f"Failed to load plan from {yaml_file}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error loading {yaml_file}: {e}", exc_info=True)

        return plans

    @staticmethod
    def load_plan_from_file(file_path: Path) -> HealingPlanDefinition:
        """Load and validate a single YAML plan file.

        Args:
            file_path: Path to the YAML file

        Returns:
            Validated plan definition

        Raises:
            HealingPlanValidationError: If plan fails validation
        """
        try:
            with open(file_path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise HealingPlanValidationError(f"Invalid YAML in {file_path}: {e}") from e

        if not isinstance(data, dict):
            raise HealingPlanValidationError(f"Plan file {file_path} must contain a YAML mapping")

        return PlanLoader.validate_plan_data(data)

    @staticmethod
    def validate_plan_data(data: dict[str, Any]) -> HealingPlanDefinition:
        """Validate plan data against the Pydantic schema.

        Args:
            data: Raw plan data dict

        Returns:
            Validated plan definition

        Raises:
            HealingPlanValidationError: If validation fails
        """
        try:
            return HealingPlanDefinition(**data)
        except ValidationError as e:
            raise HealingPlanValidationError(f"Plan validation failed: {e}") from e

    async def _sync_plan_to_db(self, plan: HealingPlanDefinition, source: str) -> None:
        """Sync a plan definition to the database.

        Creates or updates the plan record. Preserves execution stats
        and enabled/disabled state for existing plans.

        Args:
            plan: Validated plan definition
            source: Plan source ('builtin' or 'user')
        """
        try:
            async with self.database.async_session() as session:
                result = await session.execute(
                    select(HealingPlan).where(HealingPlan.name == plan.name)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update definition but preserve runtime state
                    existing.version = plan.version
                    existing.description = plan.description
                    existing.priority = plan.priority
                    existing.match_criteria = plan.match.model_dump()
                    existing.steps = [s.model_dump() for s in plan.steps]
                    existing.on_failure = plan.on_failure.model_dump()
                    existing.tags = plan.tags
                    existing.updated_at = datetime.now(UTC)
                    # Don't overwrite enabled or execution stats
                else:
                    db_plan = HealingPlan(
                        name=plan.name,
                        version=plan.version,
                        description=plan.description,
                        enabled=plan.enabled,
                        priority=plan.priority,
                        source=source,
                        match_criteria=plan.match.model_dump(),
                        steps=[s.model_dump() for s in plan.steps],
                        on_failure=plan.on_failure.model_dump(),
                        tags=plan.tags,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    session.add(db_plan)

                await session.commit()

        except Exception as e:
            logger.error(f"Failed to sync plan '{plan.name}' to database: {e}", exc_info=True)

    async def get_plan(self, name: str) -> HealingPlanDefinition:
        """Get a plan by name.

        Args:
            name: Plan name

        Returns:
            Plan definition

        Raises:
            HealingPlanNotFoundError: If plan not found
        """
        if name in self._plans:
            return self._plans[name]

        raise HealingPlanNotFoundError(f"Plan '{name}' not found")

    async def get_all_enabled_plans(self) -> list[HealingPlanDefinition]:
        """Get all enabled plans sorted by priority (highest first).

        Returns:
            List of enabled plan definitions sorted by priority
        """
        try:
            async with self.database.async_session() as session:
                result = await session.execute(
                    select(HealingPlan)
                    .where(HealingPlan.enabled == True)  # noqa: E712
                    .order_by(HealingPlan.priority.desc())
                )
                db_plans = result.scalars().all()

                plans = []
                for db_plan in db_plans:
                    try:
                        plan = HealingPlanDefinition(
                            name=db_plan.name,
                            version=db_plan.version,
                            description=db_plan.description or "",
                            enabled=db_plan.enabled,
                            priority=db_plan.priority,
                            match=db_plan.match_criteria or {},
                            steps=db_plan.steps or [],
                            on_failure=db_plan.on_failure or {},
                            tags=db_plan.tags or [],
                        )
                        plans.append(plan)
                    except ValidationError as e:
                        logger.error(
                            f"Invalid plan '{db_plan.name}' in database: {e}",
                            exc_info=True,
                        )

                return plans

        except Exception as e:
            logger.error(f"Failed to load enabled plans from database: {e}", exc_info=True)
            return []
