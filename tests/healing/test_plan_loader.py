"""Tests for healing plan YAML loader."""

import pytest
import yaml

from ha_boss.core.database import HealingPlan, init_database
from ha_boss.core.exceptions import HealingPlanNotFoundError, HealingPlanValidationError
from ha_boss.healing.plan_loader import PlanLoader


@pytest.fixture
async def database(tmp_path):
    """Create a test database."""
    db = await init_database(str(tmp_path / "test.db"))
    yield db
    await db.engine.dispose()


@pytest.fixture
def sample_plan_yaml(tmp_path):
    """Create a sample YAML plan file."""
    plan_data = {
        "name": "test_zigbee",
        "version": 1,
        "description": "Test zigbee plan",
        "enabled": True,
        "priority": 10,
        "match": {
            "entity_patterns": ["light.zigbee_*"],
            "integration_domains": ["zha"],
            "failure_types": ["unavailable"],
        },
        "steps": [
            {
                "name": "retry",
                "level": "entity",
                "action": "retry_service_call",
                "timeout_seconds": 15,
            },
            {
                "name": "reconnect",
                "level": "device",
                "action": "reconnect",
                "timeout_seconds": 20,
            },
        ],
        "on_failure": {"escalate": True, "cooldown_seconds": 600},
        "tags": ["zigbee", "connectivity"],
    }

    plan_file = tmp_path / "test_zigbee.yaml"
    with open(plan_file, "w") as f:
        yaml.dump(plan_data, f)

    return plan_file


@pytest.fixture
def plans_directory(tmp_path, sample_plan_yaml):
    """Create a directory with plan files."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()

    # Copy sample plan to plans directory
    import shutil

    shutil.copy(sample_plan_yaml, plans_dir / "test_zigbee.yaml")

    # Add a second plan
    plan2 = {
        "name": "test_wifi",
        "version": 1,
        "match": {
            "integration_domains": ["tuya"],
            "failure_types": ["unavailable"],
        },
        "steps": [
            {
                "name": "reload",
                "level": "integration",
                "action": "reload_integration",
                "timeout_seconds": 30,
            },
        ],
    }
    with open(plans_dir / "test_wifi.yaml", "w") as f:
        yaml.dump(plan2, f)

    return plans_dir


class TestPlanLoaderFile:
    """Test loading plans from files."""

    def test_load_plan_from_file(self, sample_plan_yaml):
        """Test loading a single plan from YAML file."""
        plan = PlanLoader.load_plan_from_file(sample_plan_yaml)
        assert plan.name == "test_zigbee"
        assert plan.priority == 10
        assert len(plan.steps) == 2
        assert plan.tags == ["zigbee", "connectivity"]

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml")
        with pytest.raises(HealingPlanValidationError, match="Invalid YAML"):
            PlanLoader.load_plan_from_file(bad_file)

    def test_load_non_dict_yaml(self, tmp_path):
        """Test loading non-dict YAML raises error."""
        bad_file = tmp_path / "list.yaml"
        bad_file.write_text("- item1\n- item2\n")
        with pytest.raises(HealingPlanValidationError, match="must contain a YAML mapping"):
            PlanLoader.load_plan_from_file(bad_file)

    def test_load_missing_required_fields(self, tmp_path):
        """Test loading plan with missing fields raises error."""
        bad_file = tmp_path / "incomplete.yaml"
        with open(bad_file, "w") as f:
            yaml.dump({"name": "incomplete"}, f)
        with pytest.raises(HealingPlanValidationError, match="validation failed"):
            PlanLoader.load_plan_from_file(bad_file)


class TestPlanLoaderValidation:
    """Test plan data validation."""

    def test_validate_valid_data(self):
        data = {
            "name": "test",
            "match": {"failure_types": ["unavailable"]},
            "steps": [{"name": "retry", "level": "entity", "action": "retry"}],
        }
        plan = PlanLoader.validate_plan_data(data)
        assert plan.name == "test"

    def test_validate_invalid_data(self):
        with pytest.raises(HealingPlanValidationError):
            PlanLoader.validate_plan_data({"name": "bad"})


class TestPlanLoaderDatabase:
    """Test plan loading with database sync."""

    @pytest.mark.asyncio
    async def test_load_from_directory(self, database, plans_directory):
        """Test loading plans from a directory and syncing to DB."""
        loader = PlanLoader(
            database=database,
            user_plans_directory=str(plans_directory),
            use_builtin=False,
        )
        plans = await loader.load_all_plans()
        assert len(plans) >= 2

        # Check they're synced to database
        async with database.async_session() as session:
            result = await session.execute(__import__("sqlalchemy").select(HealingPlan))
            db_plans = result.scalars().all()
            assert len(db_plans) >= 2

    @pytest.mark.asyncio
    async def test_get_plan(self, database, plans_directory):
        """Test getting a loaded plan by name."""
        loader = PlanLoader(
            database=database,
            user_plans_directory=str(plans_directory),
            use_builtin=False,
        )
        await loader.load_all_plans()
        plan = await loader.get_plan("test_zigbee")
        assert plan.name == "test_zigbee"

    @pytest.mark.asyncio
    async def test_get_plan_not_found(self, database):
        """Test getting a non-existent plan raises error."""
        loader = PlanLoader(database=database, use_builtin=False)
        with pytest.raises(HealingPlanNotFoundError):
            await loader.get_plan("nonexistent")

    @pytest.mark.asyncio
    async def test_get_all_enabled_plans(self, database, plans_directory):
        """Test getting all enabled plans sorted by priority."""
        loader = PlanLoader(
            database=database,
            user_plans_directory=str(plans_directory),
            use_builtin=False,
        )
        await loader.load_all_plans()
        enabled = await loader.get_all_enabled_plans()
        assert len(enabled) >= 2
        # Should be sorted by priority descending
        if len(enabled) >= 2:
            assert enabled[0].priority >= enabled[1].priority

    @pytest.mark.asyncio
    async def test_sync_preserves_enabled_state(self, database, plans_directory):
        """Test that re-syncing plans preserves enabled/disabled state."""
        loader = PlanLoader(
            database=database,
            user_plans_directory=str(plans_directory),
            use_builtin=False,
        )
        await loader.load_all_plans()

        # Disable a plan in the DB
        async with database.async_session() as session:
            result = await session.execute(
                __import__("sqlalchemy")
                .select(HealingPlan)
                .where(HealingPlan.name == "test_zigbee")
            )
            plan = result.scalar_one()
            plan.enabled = False
            await session.commit()

        # Reload plans
        await loader.load_all_plans()

        # Check enabled state was preserved
        async with database.async_session() as session:
            result = await session.execute(
                __import__("sqlalchemy")
                .select(HealingPlan)
                .where(HealingPlan.name == "test_zigbee")
            )
            plan = result.scalar_one()
            assert plan.enabled is False
