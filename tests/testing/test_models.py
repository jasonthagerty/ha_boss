"""Tests for UAT data models."""

from __future__ import annotations

from datetime import datetime

from ha_boss.testing.models import (
    APITestCase,
    CLITestCase,
    ExecutionResults,
    TestPlan,
    TestResult,
    TestScope,
    TestStatus,
)


def test_cli_test_case_creation() -> None:
    """Test CLI test case creation."""
    test_case = CLITestCase(
        name="test_example",
        description="Example test",
        command="haboss --help",
        expected_exit_code=0,
        expected_output_contains=["usage"],
    )

    assert test_case.name == "test_example"
    assert test_case.command == "haboss --help"
    assert test_case.expected_exit_code == 0
    assert "usage" in test_case.expected_output_contains


def test_api_test_case_creation() -> None:
    """Test API test case creation."""
    test_case = APITestCase(
        name="test_api_health",
        description="Test health endpoint",
        method="GET",
        path="/api/health",
        expected_status=200,
    )

    assert test_case.name == "test_api_health"
    assert test_case.method == "GET"
    assert test_case.path == "/api/health"
    assert test_case.expected_status == 200


def test_test_result_creation() -> None:
    """Test test result creation."""
    test_case = CLITestCase(
        name="test_example",
        description="Example test",
        command="haboss --help",
    )

    result = TestResult(
        test=test_case,
        status=TestStatus.PASSED,
        execution_time=1.5,
        stdout="usage information",
    )

    assert result.test == test_case
    assert result.status == TestStatus.PASSED
    assert result.execution_time == 1.5
    assert result.stdout == "usage information"


def test_test_plan_post_init() -> None:
    """Test test plan post_init updates total_count."""
    test_cases = [
        CLITestCase(name="test1", description="Test 1", command="cmd1"),
        CLITestCase(name="test2", description="Test 2", command="cmd2"),
    ]

    test_plan = TestPlan(
        generated_at=datetime.now(),
        scope=TestScope.CLI_ONLY,
        test_cases=test_cases,
        total_count=0,  # Should be overridden
    )

    assert test_plan.total_count == 2


def test_execution_results_pass_rate() -> None:
    """Test execution results pass rate calculation."""
    results = ExecutionResults(
        total=10,
        passed=8,
        failed=1,
        skipped=1,
        errors=0,
        results=[],
        execution_time=10.0,
    )

    assert results.pass_rate == 80.0


def test_execution_results_pass_rate_zero_tests() -> None:
    """Test execution results pass rate with zero tests."""
    results = ExecutionResults(
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        errors=0,
        results=[],
        execution_time=0.0,
    )

    assert results.pass_rate == 0.0
