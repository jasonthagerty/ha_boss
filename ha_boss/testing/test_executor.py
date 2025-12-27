"""Test execution engine for UAT."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ha_boss.testing.models import (
    APITestCase,
    CLITestCase,
    ExecutionResults,
    PrerequisiteStatus,
    TestCase,
    TestPlan,
    TestResult,
    TestStatus,
    ValidationResult,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SafetyEnforcer:
    """Enforces safety constraints on test execution."""

    # Whitelist of safe CLI patterns
    SAFE_CLI_PATTERNS = [
        r"^haboss\s+--help$",
        r"^haboss\s+--version$",
        r"^haboss\s+status",
        r"^haboss\s+config\s+validate",
        r"^haboss\s+patterns\s+(reliability|failures|weekly-summary)",
        r"^haboss\s+automation\s+analyze",
        r"^haboss\s+heal\s+.*--dry-run",  # Only dry-run healing
    ]

    # Blacklist of destructive CLI commands
    DESTRUCTIVE_CLI_PATTERNS = [
        r"^haboss\s+init",  # Creates files
        r"^haboss\s+start",  # Starts service
        r"^haboss\s+stop",  # Stops service
        r"^haboss\s+heal\s+(?!.*--dry-run)",  # No actual healing
        r"^haboss\s+automation\s+generate",  # Creates automations
    ]

    # Safe API methods (read-only)
    SAFE_API_METHODS = ["GET", "HEAD", "OPTIONS"]

    # Destructive API methods (deferred to sandbox)
    DESTRUCTIVE_API_METHODS = ["POST", "PUT", "DELETE", "PATCH"]

    def validate_test_case(self, test: TestCase) -> ValidationResult:
        """Validate that test case is safe to execute.

        Args:
            test: Test case to validate

        Returns:
            ValidationResult with validation outcome
        """
        if isinstance(test, CLITestCase):
            return self._validate_cli_test(test)
        elif isinstance(test, APITestCase):
            return self._validate_api_test(test)

        return ValidationResult(valid=False, reason="Unknown test type")

    def _validate_cli_test(self, test: CLITestCase) -> ValidationResult:
        """Validate CLI test safety.

        Args:
            test: CLI test case

        Returns:
            ValidationResult
        """
        # Check against destructive patterns first
        for pattern in self.DESTRUCTIVE_CLI_PATTERNS:
            if re.match(pattern, test.command):
                return ValidationResult(
                    valid=False,
                    reason=f"Destructive command blocked: {test.command}",
                    suggestion="Add --dry-run flag or defer to sandbox phase",
                )

        # Check against safe patterns
        for pattern in self.SAFE_CLI_PATTERNS:
            if re.match(pattern, test.command):
                return ValidationResult(valid=True)

        # If not explicitly safe, mark as requiring review
        return ValidationResult(
            valid=False,
            reason="Command not in safe patterns list",
            suggestion="Manually review and add to whitelist if safe",
        )

    def _validate_api_test(self, test: APITestCase) -> ValidationResult:
        """Validate API test safety.

        Args:
            test: API test case

        Returns:
            ValidationResult
        """
        if test.method in self.SAFE_API_METHODS:
            return ValidationResult(valid=True)

        if test.method in self.DESTRUCTIVE_API_METHODS:
            return ValidationResult(
                valid=False,
                reason=f"Destructive HTTP method: {test.method}",
                suggestion="Defer POST/PUT/DELETE tests to sandbox phase",
            )

        return ValidationResult(valid=False, reason="Unknown HTTP method")


class TestExecutor:
    """Executes test cases safely."""

    def __init__(self, project_root: str | Path, allow_destructive: bool = False):
        """Initialize test executor.

        Args:
            project_root: Path to project root
            allow_destructive: Whether to allow destructive tests (default: False)
        """
        self.project_root = Path(project_root)
        self.allow_destructive = allow_destructive
        self.safety_enforcer = SafetyEnforcer()
        self.api_base_url = "http://localhost:8000"

    async def execute_all(self, test_plan: TestPlan) -> ExecutionResults:
        """Execute all tests with parallel execution where safe.

        Args:
            test_plan: Test plan to execute

        Returns:
            ExecutionResults with all test results
        """
        start_time = time.time()

        # Separate tests by parallelization safety
        parallel_safe = []
        sequential_only = []

        for test in test_plan.test_cases:
            # Skip already marked as skipped
            if test.status == TestStatus.SKIPPED:
                continue

            if self._is_parallel_safe(test):
                parallel_safe.append(test)
            else:
                sequential_only.append(test)

        results: list[TestResult] = []

        # Execute parallel-safe tests concurrently (batches of 10)
        batch_size = 10
        for i in range(0, len(parallel_safe), batch_size):
            batch = parallel_safe[i : i + batch_size]
            batch_results = await asyncio.gather(
                *[self._execute_single(test) for test in batch],
                return_exceptions=True,
            )

            # Handle exceptions from gather
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Unexpected error in batch execution: {result}")
                else:
                    results.append(result)

        # Execute sequential tests one at a time
        for test in sequential_only:
            result = await self._execute_single(test)
            results.append(result)

        # Add skipped tests
        for test in test_plan.test_cases:
            if test.status == TestStatus.SKIPPED:
                results.append(
                    TestResult(
                        test=test,
                        status=TestStatus.SKIPPED,
                        message=test.skip_reason or "Test skipped",
                    )
                )

        execution_time = time.time() - start_time

        # Count results
        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)

        return ExecutionResults(
            total=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            results=results,
            execution_time=execution_time,
        )

    def _is_parallel_safe(self, test: TestCase) -> bool:
        """Determine if test can be run in parallel.

        Args:
            test: Test case to check

        Returns:
            True if safe for parallel execution
        """
        if isinstance(test, CLITestCase):
            # Safe: --help, --version, status, config validate (read-only)
            safe_commands = ["help", "version", "status", "validate", "patterns"]
            return any(cmd in test.command for cmd in safe_commands)

        elif isinstance(test, APITestCase):
            # Safe: All GET requests
            return test.method == "GET"

        return False

    async def _execute_single(self, test: TestCase) -> TestResult:
        """Execute a single test case.

        Args:
            test: Test case to execute

        Returns:
            TestResult
        """
        # Validate test safety
        validation = self.safety_enforcer.validate_test_case(test)
        if not validation.valid and not self.allow_destructive:
            return TestResult(
                test=test,
                status=TestStatus.SKIPPED,
                message=f"Safety check failed: {validation.reason}",
            )

        # Execute based on test type
        if isinstance(test, CLITestCase):
            return await self._execute_cli_test(test)
        elif isinstance(test, APITestCase):
            return await self._execute_api_test(test)

        return TestResult(test=test, status=TestStatus.ERROR, message="Unknown test type")

    async def _execute_cli_test(self, test: CLITestCase) -> TestResult:
        """Execute a CLI test case.

        Args:
            test: CLI test case

        Returns:
            TestResult
        """
        start_time = time.time()

        try:
            # Execute command with timeout
            result = await asyncio.wait_for(
                self._run_command(test.command), timeout=test.timeout_seconds
            )

            execution_time = time.time() - start_time

            # Validate exit code
            if result.returncode != test.expected_exit_code:
                return TestResult(
                    test=test,
                    status=TestStatus.FAILED,
                    message=f"Exit code mismatch: expected {test.expected_exit_code}, got {result.returncode}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                    execution_time=execution_time,
                )

            # Validate output content (case-insensitive)
            if test.expected_output_contains:
                stdout_lower = result.stdout.lower()
                for keyword in test.expected_output_contains:
                    if keyword.lower() not in stdout_lower:
                        return TestResult(
                            test=test,
                            status=TestStatus.FAILED,
                            message=f"Expected output to contain '{keyword}'",
                            stdout=result.stdout,
                            stderr=result.stderr,
                            execution_time=execution_time,
                        )

            # Validate error conditions
            if test.expected_error_contains:
                for keyword in test.expected_error_contains:
                    if keyword not in result.stderr:
                        return TestResult(
                            test=test,
                            status=TestStatus.FAILED,
                            message=f"Expected stderr to contain '{keyword}'",
                            stdout=result.stdout,
                            stderr=result.stderr,
                            execution_time=execution_time,
                        )

            return TestResult(
                test=test,
                status=TestStatus.PASSED,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time,
            )

        except TimeoutError:
            execution_time = time.time() - start_time
            return TestResult(
                test=test,
                status=TestStatus.FAILED,
                message=f"Command timed out after {test.timeout_seconds} seconds",
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return TestResult(
                test=test,
                status=TestStatus.ERROR,
                message=f"Unexpected error: {str(e)}",
                exception=e,
                execution_time=execution_time,
            )

    async def _run_command(self, command: str) -> subprocess.CompletedProcess:
        """Run command safely with proper environment.

        Args:
            command: Command to execute

        Returns:
            CompletedProcess result
        """
        # Build environment with venv bin in PATH if it exists
        env = {**os.environ, "PYTHONPATH": str(self.project_root)}

        venv_bin = self.project_root / ".venv" / "bin"
        if venv_bin.exists():
            # Prepend venv bin to PATH
            current_path = env.get("PATH", "")
            env["PATH"] = f"{venv_bin}:{current_path}"

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.project_root,
            env=env,
        )

        stdout, stderr = await proc.communicate()

        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode or 0,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

    async def _execute_api_test(self, test: APITestCase) -> TestResult:
        """Execute an API test case.

        Args:
            test: API test case

        Returns:
            TestResult
        """
        start_time = time.time()

        try:
            async with httpx.AsyncClient(base_url=self.api_base_url, timeout=30.0) as client:
                # Make HTTP request
                response = await client.request(
                    method=test.method,
                    url=test.path,
                    json=test.body if test.body else None,
                    headers=test.headers if test.headers else {},
                )

                execution_time = time.time() - start_time

                # Validate status code
                if response.status_code != test.expected_status:
                    return TestResult(
                        test=test,
                        status=TestStatus.FAILED,
                        message=f"Status code mismatch: expected {test.expected_status}, got {response.status_code}",
                        response_body=response.text,
                        response_status=response.status_code,
                        execution_time=execution_time,
                    )

                # Validate response content (if specified)
                if test.expected_response_contains:
                    response_text = response.text
                    for keyword in test.expected_response_contains:
                        if keyword not in response_text:
                            return TestResult(
                                test=test,
                                status=TestStatus.FAILED,
                                message=f"Expected response to contain '{keyword}'",
                                response_body=response_text,
                                response_status=response.status_code,
                                execution_time=execution_time,
                            )

                return TestResult(
                    test=test,
                    status=TestStatus.PASSED,
                    response_body=response.text[:500],  # Truncate to 500 chars
                    response_status=response.status_code,
                    execution_time=execution_time,
                )

        except httpx.ConnectError:
            execution_time = time.time() - start_time
            return TestResult(
                test=test,
                status=TestStatus.ERROR,
                message="Could not connect to API server - ensure service is running",
                execution_time=execution_time,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return TestResult(
                test=test,
                status=TestStatus.ERROR,
                message=f"Unexpected error: {str(e)}",
                exception=e,
                execution_time=execution_time,
            )

    async def check_prerequisites(self) -> PrerequisiteStatus:
        """Check what components are available.

        Returns:
            PrerequisiteStatus with component availability
        """
        status = PrerequisiteStatus()

        # Check CLI availability (try venv first, then system)
        try:
            venv_haboss = self.project_root / ".venv" / "bin" / "haboss"
            if venv_haboss.exists():
                # Try running help instead of --version (which isn't implemented)
                proc = await asyncio.create_subprocess_exec(
                    str(venv_haboss),
                    "--help",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                status.cli_available = proc.returncode == 0
            else:
                # Fall back to system haboss
                proc = await asyncio.create_subprocess_exec(
                    "haboss",
                    "--help",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                status.cli_available = proc.returncode == 0
        except FileNotFoundError:
            status.cli_available = False

        # Check API server availability
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_base_url}/api/health")
                status.api_available = response.status_code == 200
        except Exception:
            status.api_available = False

        # Check GitHub CLI availability
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "auth",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            status.github_available = proc.returncode == 0
        except FileNotFoundError:
            status.github_available = False

        return status
