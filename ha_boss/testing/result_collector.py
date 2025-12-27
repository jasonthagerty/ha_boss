"""Results aggregation and reporting for UAT."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ha_boss.testing.models import (
    APITestCase,
    CLITestCase,
    ExecutionResults,
    TestResult,
    TestStatus,
    UATReport,
)

logger = logging.getLogger(__name__)


class ResultCollector:
    """Collects and formats test results."""

    def __init__(self, project_root: str | Path):
        """Initialize result collector.

        Args:
            project_root: Path to project root
        """
        self.project_root = Path(project_root)

    def generate_report(self, results: ExecutionResults, issues_created: list[str]) -> UATReport:
        """Generate comprehensive test report.

        Args:
            results: Test execution results
            issues_created: List of created issue URLs

        Returns:
            UATReport with formatted results
        """
        summary = self._generate_summary(results, issues_created)
        cli_results = self._filter_by_type(results, CLITestCase)
        api_results = self._filter_by_type(results, APITestCase)
        failures = self._collect_failures(results)
        recommendations = self._generate_recommendations(results)

        # Update issue URLs in results
        for i, result in enumerate(failures):
            if i < len(issues_created):
                result.issue_url = issues_created[i]

        return UATReport(
            generated_at=datetime.now(),
            execution_time=results.execution_time,
            summary=summary,
            cli_results=cli_results,
            api_results=api_results,
            failures=failures,
            issues_created=issues_created,
            recommendations=recommendations,
        )

    def _generate_summary(
        self, results: ExecutionResults, issues_created: list[str]
    ) -> dict[str, str | int]:
        """Generate summary statistics.

        Args:
            results: Test execution results
            issues_created: Created issue URLs

        Returns:
            Summary dictionary
        """
        return {
            "total_tests": results.total,
            "passed": results.passed,
            "failed": results.failed,
            "skipped": results.skipped,
            "errors": results.errors,
            "pass_rate": f"{results.pass_rate:.1f}%",
            "execution_time": f"{results.execution_time:.2f}s",
            "issues_created": len(issues_created),
        }

    def _filter_by_type(self, results: ExecutionResults, test_type: type) -> list[TestResult]:
        """Filter results by test case type.

        Args:
            results: All test results
            test_type: Type to filter by

        Returns:
            Filtered test results
        """
        return [r for r in results.results if isinstance(r.test, test_type)]

    def _collect_failures(self, results: ExecutionResults) -> list[TestResult]:
        """Collect all failed and error test results.

        Args:
            results: All test results

        Returns:
            List of failed/error results
        """
        return [r for r in results.results if r.status in (TestStatus.FAILED, TestStatus.ERROR)]

    def _generate_recommendations(self, results: ExecutionResults) -> list[str]:
        """Generate recommendations based on results.

        Args:
            results: Test execution results

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # Check for API errors
        api_errors = [
            r
            for r in results.results
            if isinstance(r.test, APITestCase)
            and r.status == TestStatus.ERROR
            and "connect" in r.message.lower()
        ]
        if api_errors:
            recommendations.append(
                "API server not running - start service before running API tests"
            )

        # Check for CLI errors
        cli_errors = [
            r
            for r in results.results
            if isinstance(r.test, CLITestCase) and r.status == TestStatus.ERROR
        ]
        if cli_errors:
            recommendations.append("CLI not available - ensure ha_boss is installed in environment")

        # Check pass rate
        if results.pass_rate < 80:
            recommendations.append(
                f"Low pass rate ({results.pass_rate:.1f}%) - review failures for patterns"
            )

        # Check for skipped tests
        if results.skipped > 0:
            recommendations.append(
                f"{results.skipped} tests skipped - consider sandbox environment for destructive tests"
            )

        return recommendations

    def format_console_output(self, report: UATReport) -> str:
        """Format report for console display.

        Args:
            report: UAT report

        Returns:
            Formatted console output
        """
        output = []
        output.append("=" * 80)
        output.append("UAT REPORT")
        output.append("=" * 80)
        output.append("")

        # Summary section
        output.append("SUMMARY")
        output.append("-" * 80)
        for key, value in report.summary.items():
            output.append(f"  {key.replace('_', ' ').title()}: {value}")
        output.append("")

        # Failures section (if any)
        if report.failures:
            output.append("FAILURES")
            output.append("-" * 80)
            for i, failure in enumerate(report.failures, 1):
                output.append(f"\n{i}. {failure.test.name}")
                if isinstance(failure.test, CLITestCase):
                    output.append(f"   Command: {failure.test.command}")
                elif isinstance(failure.test, APITestCase):
                    output.append(f"   Endpoint: {failure.test.method} {failure.test.path}")
                output.append(f"   Error: {failure.message}")
                if failure.issue_url:
                    output.append(f"   Issue: {failure.issue_url}")
            output.append("")

        # CLI results section
        if report.cli_results:
            output.append(f"CLI TESTS ({len(report.cli_results)} total)")
            output.append("-" * 80)
            for result in report.cli_results:
                status_icon = "✓" if result.status == TestStatus.PASSED else "✗"
                output.append(f"  {status_icon} {result.test.name}")
            output.append("")

        # API results section
        if report.api_results:
            output.append(f"API TESTS ({len(report.api_results)} total)")
            output.append("-" * 80)
            for result in report.api_results:
                status_icon = "✓" if result.status == TestStatus.PASSED else "✗"
                if isinstance(result.test, APITestCase):
                    output.append(f"  {status_icon} {result.test.method} {result.test.path}")
            output.append("")

        # Recommendations
        if report.recommendations:
            output.append("RECOMMENDATIONS")
            output.append("-" * 80)
            for rec in report.recommendations:
                output.append(f"  • {rec}")
            output.append("")

        output.append("=" * 80)

        return "\n".join(output)

    def save_report_file(self, report: UATReport, output_path: Path) -> None:
        """Save detailed report to file (JSON format).

        Args:
            report: UAT report
            output_path: Path to save report
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report_data = {
            "generated_at": report.generated_at.isoformat(),
            "execution_time": report.execution_time,
            "summary": report.summary,
            "cli_results": [self._serialize_result(r) for r in report.cli_results],
            "api_results": [self._serialize_result(r) for r in report.api_results],
            "failures": [self._serialize_result(r) for r in report.failures],
            "issues_created": report.issues_created,
            "recommendations": report.recommendations,
        }

        with output_path.open("w") as f:
            json.dump(report_data, f, indent=2)

        logger.info(f"Report saved to {output_path}")

    def _serialize_result(self, result: TestResult) -> dict[str, str | int | None]:
        """Serialize test result to dictionary.

        Args:
            result: Test result

        Returns:
            Serialized result
        """
        data = {
            "test_name": result.test.name,
            "test_description": result.test.description,
            "status": result.status.value,
            "message": result.message,
            "execution_time": result.execution_time,
        }

        if isinstance(result.test, CLITestCase):
            data["test_type"] = "cli"
            data["command"] = result.test.command
            data["stdout"] = result.stdout[:500] if result.stdout else ""
            data["stderr"] = result.stderr[:500] if result.stderr else ""
        elif isinstance(result.test, APITestCase):
            data["test_type"] = "api"
            data["method"] = result.test.method
            data["path"] = result.test.path
            data["response_status"] = result.response_status
            data["response_body"] = result.response_body[:500] if result.response_body else ""

        if result.issue_url:
            data["issue_url"] = result.issue_url

        return data
