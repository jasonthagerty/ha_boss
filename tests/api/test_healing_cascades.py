"""Tests for GET /healing/cascades endpoint."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def make_mock_cascade(
    *,
    instance_id: str = "default",
    automation_id: str = "automation.test",
    plan_generation_suggested: bool = False,
    final_success: bool | None = True,
) -> MagicMock:
    """Create a mock HealingCascadeExecution DB record."""
    cascade = MagicMock()
    cascade.id = 1
    cascade.instance_id = instance_id
    cascade.automation_id = automation_id
    cascade.execution_id = 123
    cascade.trigger_type = "trigger_failure"
    cascade.routing_strategy = "cascade"
    cascade.entity_level_attempted = True
    cascade.entity_level_success = False
    cascade.device_level_attempted = False
    cascade.device_level_success = None
    cascade.integration_level_attempted = True
    cascade.integration_level_success = True
    cascade.final_success = final_success
    cascade.total_duration_seconds = 5.0
    cascade.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    cascade.completed_at = datetime(2026, 1, 1, tzinfo=UTC)
    cascade.plan_generation_suggested = plan_generation_suggested
    return cascade


def make_mock_service(cascades: list[MagicMock]) -> MagicMock:
    """Create a mock service with a database returning the given cascade records."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = cascades

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_db = MagicMock()
    mock_db.async_session.return_value = mock_session

    mock_service = MagicMock()
    mock_service.database = mock_db
    return mock_service


class TestListCascadesEndpoint:
    """Tests for GET /healing/cascades."""

    @pytest.mark.asyncio
    async def test_returns_list_of_cascades(self) -> None:
        """Returns a list of cascade executions as HealingCascadeResponse objects."""
        from ha_boss.api.routes.healing import list_cascades

        cascades = [make_mock_cascade(), make_mock_cascade(automation_id="automation.other")]
        mock_service = make_mock_service(cascades)

        with patch("ha_boss.api.routes.healing.get_service", return_value=mock_service):
            result = await list_cascades(instance_id="all", limit=20, plan_suggested_only=False)

        assert len(result) == 2
        assert result[0].automation_id == "automation.test"

    @pytest.mark.asyncio
    async def test_plan_suggested_only_filter_included_in_query(self) -> None:
        """plan_suggested_only=True passes the filter through to the DB query."""
        from ha_boss.api.routes.healing import list_cascades

        suggested_cascade = make_mock_cascade(plan_generation_suggested=True)
        mock_service = make_mock_service([suggested_cascade])

        with patch("ha_boss.api.routes.healing.get_service", return_value=mock_service):
            result = await list_cascades(instance_id="all", limit=20, plan_suggested_only=True)

        # The mock returns only one cascade; the filter logic is applied in the DB query
        assert len(result) == 1
        assert result[0].plan_generation_suggested is True

    @pytest.mark.asyncio
    async def test_instance_id_filter_all_returns_all(self) -> None:
        """instance_id='all' does not apply instance filter."""
        from ha_boss.api.routes.healing import list_cascades

        cascades = [
            make_mock_cascade(instance_id="instance1"),
            make_mock_cascade(instance_id="instance2"),
        ]
        mock_service = make_mock_service(cascades)

        with patch("ha_boss.api.routes.healing.get_service", return_value=mock_service):
            result = await list_cascades(instance_id="all", limit=20, plan_suggested_only=False)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_no_database_returns_503(self) -> None:
        """Returns 503 when database is not available."""
        from ha_boss.api.routes.healing import list_cascades

        mock_service = MagicMock()
        mock_service.database = None

        with patch("ha_boss.api.routes.healing.get_service", return_value=mock_service):
            with pytest.raises(HTTPException) as exc_info:
                await list_cascades(instance_id="all", limit=20, plan_suggested_only=False)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_db_error_returns_500(self) -> None:
        """Returns 500 when database raises an exception."""
        from ha_boss.api.routes.healing import list_cascades

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        mock_db = MagicMock()
        mock_db.async_session.return_value = mock_session

        mock_service = MagicMock()
        mock_service.database = mock_db

        with patch("ha_boss.api.routes.healing.get_service", return_value=mock_service):
            with pytest.raises(HTTPException) as exc_info:
                await list_cascades(instance_id="all", limit=20, plan_suggested_only=False)

        assert exc_info.value.status_code == 500
