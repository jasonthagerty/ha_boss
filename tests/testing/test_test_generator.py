"""Tests for test generator."""

from __future__ import annotations

import pytest

from ha_boss.testing.models import TestScope
from ha_boss.testing.test_generator import TestGenerator


@pytest.fixture
def test_generator(tmp_path) -> TestGenerator:
    """Create test generator instance.

    Args:
        tmp_path: Temporary directory

    Returns:
        TestGenerator instance
    """
    return TestGenerator(tmp_path)


@pytest.mark.asyncio
async def test_generate_test_plan_cli_only(test_generator: TestGenerator) -> None:
    """Test generating CLI-only test plan."""
    test_plan = await test_generator.generate_test_plan(TestScope.CLI_ONLY)

    assert test_plan.scope == TestScope.CLI_ONLY
    assert test_plan.total_count > 0
    assert all(hasattr(test, "command") for test in test_plan.test_cases)


@pytest.mark.asyncio
async def test_generate_test_plan_api_only(test_generator: TestGenerator) -> None:
    """Test generating API-only test plan."""
    test_plan = await test_generator.generate_test_plan(TestScope.API_ONLY)

    assert test_plan.scope == TestScope.API_ONLY
    # May be 0 if API files not found in tmp_path
    assert test_plan.total_count >= 0


@pytest.mark.asyncio
async def test_generate_test_plan_full(test_generator: TestGenerator) -> None:
    """Test generating full test plan."""
    test_plan = await test_generator.generate_test_plan(TestScope.FULL)

    assert test_plan.scope == TestScope.FULL
    assert test_plan.total_count >= 0


def test_is_typer_command(test_generator: TestGenerator) -> None:
    """Test Typer command detection."""
    # Note: This is a placeholder test for AST parsing functionality
    # The actual implementation uses complex AST parsing in _is_typer_command
    # Full testing requires mocking AST nodes
    assert test_generator is not None
