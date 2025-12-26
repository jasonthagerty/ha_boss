"""Main UAT agent orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from ha_boss.testing.issue_creator import IssueCreator
from ha_boss.testing.models import TestScope
from ha_boss.testing.result_collector import ResultCollector
from ha_boss.testing.test_executor import TestExecutor
from ha_boss.testing.test_generator import TestGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class UATAgent:
    """Autonomous agent for UAT execution."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        scope: TestScope = TestScope.FULL,
        dry_run: bool = False,
    ):
        """Initialize UAT agent.

        Args:
            project_root: Path to project root (default: current directory)
            scope: Scope of testing (CLI, API, or FULL)
            dry_run: If True, generate plan without execution
        """
        self.project_root = Path(project_root or Path.cwd())
        self.scope = scope
        self.dry_run = dry_run

        # Initialize components
        self.test_generator = TestGenerator(self.project_root)
        self.test_executor = TestExecutor(self.project_root)
        self.issue_creator = IssueCreator(self.project_root)
        self.result_collector = ResultCollector(self.project_root)

    async def run(self) -> int:
        """Run UAT workflow.

        Returns:
            Exit code (0 for success, 1 for failures)
        """
        logger.info("=" * 80)
        logger.info("UAT Agent Starting")
        logger.info("=" * 80)
        logger.info(f"Project Root: {self.project_root}")
        logger.info(f"Scope: {self.scope.value}")
        logger.info(f"Dry Run: {self.dry_run}")
        logger.info("")

        try:
            # Phase 1: Test Generation
            logger.info("Phase 1: Generating test plan...")
            test_plan = await self.test_generator.generate_test_plan(self.scope)
            logger.info(
                f"✓ Generated {test_plan.total_count} test cases "
                f"({len([t for t in test_plan.test_cases if hasattr(t, 'command')])} CLI, "
                f"{len([t for t in test_plan.test_cases if hasattr(t, 'path')])} API)"
            )
            logger.info("")

            # Dry run mode - just show test plan
            if self.dry_run:
                logger.info("DRY RUN MODE - Test plan generated")
                self._display_test_plan(test_plan)
                return 0

            # Phase 2: Prerequisites Check
            logger.info("Phase 2: Checking prerequisites...")
            prereq_status = await self.test_executor.check_prerequisites()
            logger.info(f"  CLI Available: {prereq_status.cli_available}")
            logger.info(f"  API Available: {prereq_status.api_available}")
            logger.info(f"  GitHub CLI Available: {prereq_status.github_available}")
            logger.info("")

            if not prereq_status.cli_available and self.scope in (
                TestScope.CLI_ONLY,
                TestScope.FULL,
            ):
                logger.warning("CLI not available - CLI tests will fail")

            if not prereq_status.api_available and self.scope in (
                TestScope.API_ONLY,
                TestScope.FULL,
            ):
                logger.warning("API not available - API tests will fail")

            # Phase 3: Test Execution
            logger.info("Phase 3: Executing tests...")
            results = await self.test_executor.execute_all(test_plan)
            logger.info(f"✓ Completed {results.total} tests in {results.execution_time:.2f}s")
            logger.info(
                f"  Passed: {results.passed}, Failed: {results.failed}, "
                f"Skipped: {results.skipped}, Errors: {results.errors}"
            )
            logger.info("")

            # Phase 4: Issue Creation
            issues_created: list[str] = []
            if results.failed > 0 or results.errors > 0:
                if prereq_status.github_available:
                    logger.info("Phase 4: Creating GitHub issues for failures...")
                    issues_created = await self.issue_creator.create_issues_for_failures(results)
                    logger.info(f"✓ Created {len(issues_created)} GitHub issues")
                    logger.info("")
                else:
                    logger.warning("GitHub CLI not available - skipping issue creation")
                    logger.info("")

            # Phase 5: Report Generation
            logger.info("Phase 5: Generating report...")
            report = self.result_collector.generate_report(results, issues_created)

            # Display console report
            print("\n")  # Blank line before report
            print(self.result_collector.format_console_output(report))

            # Save JSON report
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = self.project_root / "data" / "uat_reports" / f"report_{timestamp}.json"
            self.result_collector.save_report_file(report, report_path)
            logger.info(f"✓ Report saved to {report_path}")
            logger.info("")

            # Return exit code
            if results.failed > 0 or results.errors > 0:
                logger.error("UAT completed with failures")
                return 1
            else:
                logger.info("UAT completed successfully")
                return 0

        except Exception as e:
            logger.error(f"UAT failed with error: {e}", exc_info=True)
            return 1

    def _display_test_plan(self, test_plan) -> None:
        """Display test plan for dry-run mode.

        Args:
            test_plan: Test plan to display
        """
        print("\nTEST PLAN")
        print("=" * 80)

        # Group by type
        cli_tests = [t for t in test_plan.test_cases if hasattr(t, "command")]
        api_tests = [t for t in test_plan.test_cases if hasattr(t, "path")]

        if cli_tests:
            print(f"\nCLI TESTS ({len(cli_tests)} tests)")
            print("-" * 80)
            for test in cli_tests:
                print(f"  {test.name}")
                print(f"    Command: {test.command}")
                if test.destructive:
                    print("    [DESTRUCTIVE - Will be skipped]")

        if api_tests:
            print(f"\nAPI TESTS ({len(api_tests)} tests)")
            print("-" * 80)
            for test in api_tests:
                print(f"  {test.name}")
                print(f"    Endpoint: {test.method} {test.path}")
                if test.destructive:
                    print("    [DESTRUCTIVE - Will be skipped]")

        print("\n" + "=" * 80)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Arguments to parse (default: sys.argv)

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="HA Boss User Acceptance Testing Agent")

    parser.add_argument("--cli-only", action="store_true", help="Run CLI tests only")

    parser.add_argument("--api-only", action="store_true", help="Run API tests only")

    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full test suite (CLI + API) - default",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate test plan without execution",
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Path to project root (default: current directory)",
    )

    return parser.parse_args(args)


async def main_async(args: list[str] | None = None) -> int:
    """Main async entry point.

    Args:
        args: Command-line arguments

    Returns:
        Exit code
    """
    parsed_args = parse_args(args)

    # Determine scope
    if parsed_args.cli_only:
        scope = TestScope.CLI_ONLY
    elif parsed_args.api_only:
        scope = TestScope.API_ONLY
    else:
        scope = TestScope.FULL

    # Create and run agent
    agent = UATAgent(
        project_root=parsed_args.project_root,
        scope=scope,
        dry_run=parsed_args.dry_run,
    )

    return await agent.run()


def main() -> None:
    """Main entry point for command-line execution."""
    exit_code = asyncio.run(main_async())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
