"""Data models for User Acceptance Testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TestStatus(Enum):
    """Test execution status."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class TestScope(Enum):
    """Scope of testing."""

    CLI_ONLY = "cli"
    API_ONLY = "api"
    FULL = "full"


@dataclass
class TestCase:
    """Base class for test cases."""

    name: str
    description: str
    destructive: bool = False
    status: TestStatus = TestStatus.PENDING
    skip_reason: str | None = None


@dataclass
class CLITestCase(TestCase):
    """CLI command test case."""

    command: str = ""
    expected_exit_code: int = 0
    expected_output_contains: list[str] = field(default_factory=list)
    expected_error_contains: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0


@dataclass
class APITestCase(TestCase):
    """API endpoint test case."""

    method: str = "GET"
    path: str = ""
    expected_status: int = 200
    expected_schema: type | None = None
    expected_response_contains: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None


@dataclass
class TestResult:
    """Result of test execution."""

    test: TestCase
    status: TestStatus
    message: str = ""
    execution_time: float = 0.0
    stdout: str = ""
    stderr: str = ""
    response_body: str = ""
    response_status: int | None = None
    exception: Exception | None = None
    issue_url: str | None = None


@dataclass
class TestPlan:
    """Complete test plan."""

    generated_at: datetime
    scope: TestScope
    test_cases: list[TestCase]
    total_count: int

    def __post_init__(self) -> None:
        """Ensure total_count matches actual test cases."""
        self.total_count = len(self.test_cases)


@dataclass
class ExecutionResults:
    """Aggregated test execution results."""

    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    results: list[TestResult]
    execution_time: float
    issues_created: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate percentage."""
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100


@dataclass
class UATReport:
    """Final UAT report."""

    generated_at: datetime
    execution_time: float
    summary: dict[str, Any]
    cli_results: list[TestResult]
    api_results: list[TestResult]
    failures: list[TestResult]
    issues_created: list[str]
    recommendations: list[str]


@dataclass
class PrerequisiteStatus:
    """Status of prerequisite checks."""

    cli_available: bool = False
    api_available: bool = False
    github_available: bool = False


@dataclass
class ValidationResult:
    """Result of test case validation."""

    valid: bool
    reason: str = ""
    suggestion: str = ""
