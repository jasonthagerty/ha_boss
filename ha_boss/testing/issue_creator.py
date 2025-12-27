"""GitHub issue creation for UAT failures."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from ha_boss.testing.models import APITestCase, CLITestCase, ExecutionResults, TestResult

logger = logging.getLogger(__name__)


class IssueCreator:
    """Creates GitHub issues for test failures."""

    def __init__(self, project_root: str | Path, repo: str = "jasonthagerty/ha_boss"):
        """Initialize issue creator.

        Args:
            project_root: Path to project root
            repo: GitHub repository in owner/repo format
        """
        self.project_root = Path(project_root)
        self.repo = repo
        self.created_issues: list[str] = []

    async def create_issues_for_failures(self, results: ExecutionResults) -> list[str]:
        """Create GitHub issues for all failures.

        Args:
            results: Test execution results

        Returns:
            List of created issue URLs
        """
        failed_results = [r for r in results.results if r.status.value in ("failed", "error")]

        if not failed_results:
            logger.info("No failures to report")
            return []

        logger.info(f"Creating issues for {len(failed_results)} failures...")

        # Create issues in batches of 5 to avoid rate limits
        batch_size = 5
        all_issue_urls = []

        for i in range(0, len(failed_results), batch_size):
            batch = failed_results[i : i + batch_size]

            issue_urls = await asyncio.gather(
                *[self.create_issue_for_failure(r) for r in batch],
                return_exceptions=True,
            )

            # Log results
            for result, url in zip(batch, issue_urls, strict=True):
                if isinstance(url, Exception):
                    logger.error(f"Failed to create issue for {result.test.name}: {url}")
                elif isinstance(url, str):
                    logger.info(f"Created issue: {url}")
                    all_issue_urls.append(url)
                else:
                    logger.info(f"Skipped duplicate for {result.test.name}")

        self.created_issues = all_issue_urls
        return all_issue_urls

    async def create_issue_for_failure(self, result: TestResult) -> str | None:
        """Create GitHub issue for a failed test.

        Args:
            result: Test result (failed or error)

        Returns:
            Issue URL if created, None if skipped
        """
        # Check for duplicates first
        if await self._is_duplicate(result):
            logger.info(f"Skipping duplicate issue for {result.test.name}")
            return None

        # Generate issue content
        issue_data = self._generate_issue_data(result)

        # Try creating via gh CLI
        try:
            issue_url = await self._create_via_gh_cli(issue_data)
            return issue_url
        except Exception as e:
            logger.error(f"Failed to create issue: {e}")
            return None

    def _generate_issue_data(self, result: TestResult) -> dict[str, str | list[str]]:
        """Generate structured issue data from test result.

        Args:
            result: Test result

        Returns:
            Issue data dictionary
        """
        test = result.test

        # Determine issue type
        if isinstance(test, CLITestCase):
            title = f"UAT: CLI command `{test.command}` failed"
            component_label = "CLI Commands"
        elif isinstance(test, APITestCase):
            title = f"UAT: API endpoint `{test.method} {test.path}` failed"
            component_label = "api"
        else:
            title = f"UAT: Test `{test.name}` failed"
            component_label = "uat"

        # Sanitize sensitive information
        stdout = self._sanitize_output(result.stdout)
        stderr = self._sanitize_output(result.stderr)
        response_body = self._sanitize_output(result.response_body)

        # Get git info
        branch = self._get_current_branch()
        commit = self._get_current_commit()

        # Generate issue body following bug_report template structure
        body = f"""## Description
UAT discovered a test failure for: `{test.name}`

**Test Type**: {"CLI Command" if isinstance(test, CLITestCase) else "API Endpoint"}
**Failure Category**: {result.status.value}

## Reproduction Steps

"""

        if isinstance(test, CLITestCase):
            body += f"""```bash
{test.command}
```

**Expected Exit Code**: {test.expected_exit_code}
"""
        elif isinstance(test, APITestCase):
            body += f"""```bash
curl -X {test.method} http://localhost:8000{test.path}
```

**Expected Status**: {test.expected_status}
"""

        body += f"""
## Expected Behavior

{self._describe_expected_behavior(test)}

## Actual Behavior

{result.message}
"""

        if stdout:
            body += f"""
## Command Output (stdout)

```
{stdout[:1000]}
```
"""

        if stderr:
            body += f"""
## Error Output (stderr)

```
{stderr[:1000]}
```
"""

        if response_body:
            body += f"""
## Response Body

```
{response_body[:1000]}
```
"""

        body += f"""
## Environment

- **Test Run**: {datetime.now().isoformat()}
- **Project**: ha_boss
- **Branch**: {branch}
- **Commit**: {commit}
- **Execution Time**: {result.execution_time:.2f}s

## Additional Context

This issue was automatically created by the UAT agent. The test was generated from project documentation and validates that the implementation matches documented behavior.

---
*Generated by UAT Agent - `/uat` command*
"""

        return {
            "title": title,
            "body": body,
            "labels": ["uat-discovered", "needs-triage", component_label, "bug"],
        }

    async def _create_via_gh_cli(self, issue_data: dict) -> str:
        """Create issue using gh CLI.

        Args:
            issue_data: Issue data dictionary

        Returns:
            Issue URL
        """
        # Write body to temp file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(issue_data["body"])
            body_file = f.name

        try:
            labels_arg = ",".join(issue_data["labels"])

            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "create",
                "--repo",
                self.repo,
                "--title",
                issue_data["title"],
                "--body-file",
                body_file,
                "--label",
                labels_arg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                # gh CLI returns issue URL on stdout
                return stdout.decode().strip()
            else:
                raise Exception(f"gh issue create failed: {stderr.decode()}")

        finally:
            os.unlink(body_file)

    async def _is_duplicate(self, result: TestResult) -> bool:
        """Check if similar issue already exists.

        Args:
            result: Test result

        Returns:
            True if duplicate exists
        """
        # Search for existing issues with same test name
        search_query = (
            f'repo:{self.repo} is:issue is:open label:uat-discovered "{result.test.name}"'
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "list",
                "--repo",
                self.repo,
                "--search",
                search_query,
                "--json",
                "number,title",
                "--limit",
                "5",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()

            if proc.returncode == 0:
                issues = json.loads(stdout.decode())
                # Consider it a duplicate if any open issue exists
                return len(issues) > 0

        except Exception as e:
            logger.warning(f"Duplicate check failed: {e}")

        # If search fails, err on side of creating issue
        return False

    def _sanitize_output(self, output: str) -> str:
        """Remove sensitive information from output.

        Args:
            output: Raw output string

        Returns:
            Sanitized output
        """
        if not output:
            return ""

        # Patterns to redact
        patterns = [
            (r"(HA_TOKEN[=:]\s*)[\w-]+", r"\1[REDACTED]"),
            (r"(GITHUB_TOKEN[=:]\s*)[\w-]+", r"\1[REDACTED]"),
            (r"(token[=:]\s*)[\w-]+", r"\1[REDACTED]"),
            (r"(password[=:]\s*)[\w-]+", r"\1[REDACTED]"),
            (r"(api_key[=:]\s*)[\w-]+", r"\1[REDACTED]"),
        ]

        sanitized = output
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        return sanitized

    def _describe_expected_behavior(self, test: CLITestCase | APITestCase) -> str:
        """Describe expected behavior for test.

        Args:
            test: Test case

        Returns:
            Expected behavior description
        """
        if isinstance(test, CLITestCase):
            expectations = []
            expectations.append(f"- Exit code: {test.expected_exit_code}")
            if test.expected_output_contains:
                expectations.append(
                    f"- Output contains: {', '.join(test.expected_output_contains)}"
                )
            return "\n".join(expectations)
        elif isinstance(test, APITestCase):
            expectations = []
            expectations.append(f"- HTTP status: {test.expected_status}")
            if test.expected_response_contains:
                expectations.append(
                    f"- Response contains: {', '.join(test.expected_response_contains)}"
                )
            return "\n".join(expectations)
        return "Test should pass without errors"

    def _get_current_branch(self) -> str:
        """Get current git branch.

        Returns:
            Branch name or 'unknown'
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _get_current_commit(self) -> str:
        """Get current git commit hash.

        Returns:
            Commit hash or 'unknown'
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"
