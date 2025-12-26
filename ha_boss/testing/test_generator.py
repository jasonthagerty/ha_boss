"""Test case generation from documentation and source code."""

from __future__ import annotations

import ast
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ha_boss.testing.models import (
    APITestCase,
    CLITestCase,
    TestPlan,
    TestScope,
    TestStatus,
)

logger = logging.getLogger(__name__)


class TestGenerator:
    """Generates test cases from documentation and source code."""

    def __init__(self, project_root: str | Path):
        """Initialize test generator.

        Args:
            project_root: Path to project root directory
        """
        self.project_root = Path(project_root)
        self.docs_sources = [
            self.project_root / "README.md",
            self.project_root / "SETUP_GUIDE.md",
            self.project_root / "docs" / "wiki",
            self.project_root / "ha_boss" / "cli" / "commands.py",
            self.project_root / ".claude" / "commands",
        ]

    async def generate_test_plan(self, scope: TestScope) -> TestPlan:
        """Generate complete test plan from documentation.

        Args:
            scope: Scope of testing (CLI, API, or both)

        Returns:
            TestPlan with generated test cases
        """
        test_cases: list[CLITestCase | APITestCase] = []

        if scope in (TestScope.CLI_ONLY, TestScope.FULL):
            cli_tests = await self.generate_cli_tests()
            test_cases.extend(cli_tests)
            logger.info(f"Generated {len(cli_tests)} CLI test cases")

        if scope in (TestScope.API_ONLY, TestScope.FULL):
            api_tests = await self.generate_api_tests()
            test_cases.extend(api_tests)
            logger.info(f"Generated {len(api_tests)} API test cases")

        return TestPlan(
            generated_at=datetime.now(),
            scope=scope,
            test_cases=test_cases,
            total_count=len(test_cases),
        )

    async def generate_cli_tests(self) -> list[CLITestCase]:
        """Parse CLI documentation and generate test cases.

        Returns:
            List of CLI test cases
        """
        test_cases: list[CLITestCase] = []

        # Parse CLI source code to get command definitions
        cli_commands = await self._parse_cli_source()

        for cmd in cli_commands:
            # Generate test for basic invocation
            test_cases.append(
                CLITestCase(
                    name=f"test_haboss_{cmd['name']}_basic",
                    description=f"Test basic invocation of {cmd['name']} command",
                    command=f"haboss {cmd['name']}",
                    expected_exit_code=0 if not cmd.get("requires_args") else 1,
                    expected_output_contains=cmd.get("expected_keywords", []),
                    destructive=cmd.get("destructive", False),
                )
            )

            # Generate test for --help flag
            test_cases.append(
                CLITestCase(
                    name=f"test_haboss_{cmd['name']}_help",
                    description=f"Test --help flag for {cmd['name']} command",
                    command=f"haboss {cmd['name']} --help",
                    expected_exit_code=0,
                    expected_output_contains=["usage", "options"],
                    destructive=False,
                )
            )

        # Add global help tests
        test_cases.extend(
            [
                CLITestCase(
                    name="test_haboss_help",
                    description="Test haboss --help",
                    command="haboss --help",
                    expected_exit_code=0,
                    expected_output_contains=["usage", "commands"],
                    destructive=False,
                ),
                CLITestCase(
                    name="test_haboss_version",
                    description="Test haboss --version",
                    command="haboss --version",
                    expected_exit_code=0,
                    expected_output_contains=[],
                    destructive=False,
                ),
            ]
        )

        return test_cases

    async def _parse_cli_source(self) -> list[dict[str, Any]]:
        """Extract CLI commands from commands.py source code.

        Returns:
            List of command definitions
        """
        commands_file = self.project_root / "ha_boss" / "cli" / "commands.py"

        if not commands_file.exists():
            logger.warning(f"CLI commands file not found: {commands_file}")
            return []

        source = commands_file.read_text()
        commands = []

        try:
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check for @app.command decorator
                    for decorator in node.decorator_list:
                        if self._is_typer_command(decorator):
                            cmd = self._extract_command_info(node, decorator)
                            commands.append(cmd)

        except SyntaxError as e:
            logger.error(f"Failed to parse CLI source: {e}")

        return commands

    def _is_typer_command(self, decorator: ast.expr) -> bool:
        """Check if decorator is @app.command().

        Args:
            decorator: AST decorator node

        Returns:
            True if Typer command decorator
        """
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr == "command"
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr == "command"
        return False

    def _extract_command_info(
        self, func_node: ast.FunctionDef, decorator: ast.expr
    ) -> dict[str, Any]:
        """Extract command information from AST nodes.

        Args:
            func_node: Function definition node
            decorator: Command decorator node

        Returns:
            Command info dictionary
        """
        # Default command name is function name with underscores replaced by hyphens
        cmd_name = func_node.name.replace("_", "-")

        # Check if decorator specifies custom name
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    cmd_name = keyword.value.value

        # Determine if command requires arguments
        required_args = any(
            arg.arg not in ("self", "config_dir", "data_dir", "force", "foreground")
            and not any(isinstance(d, ast.Name) and d.id == "Option" for d in [])
            for arg in func_node.args.args
        )

        # Map command names to their properties
        command_properties = {
            "init": {"destructive": True, "expected_keywords": ["Initialization"]},
            "start": {"destructive": True, "expected_keywords": ["Starting", "service"]},
            "stop": {"destructive": True, "expected_keywords": ["Stopping"]},
            "status": {"destructive": False, "expected_keywords": ["Status"]},
            "config": {"destructive": False, "expected_keywords": []},
            "heal": {"destructive": True, "expected_keywords": ["Healing"]},
            "patterns": {"destructive": False, "expected_keywords": []},
            "automation": {"destructive": False, "expected_keywords": []},
        }

        props = command_properties.get(cmd_name, {})

        return {
            "name": cmd_name,
            "requires_args": required_args,
            "destructive": props.get("destructive", False),
            "expected_keywords": props.get("expected_keywords", []),
        }

    async def generate_api_tests(self) -> list[APITestCase]:
        """Parse API documentation and generate endpoint tests.

        Returns:
            List of API test cases
        """
        test_cases: list[APITestCase] = []

        # Parse API routes from source code
        api_routes = await self._parse_api_routes()

        for route in api_routes:
            # Only generate tests for GET endpoints (non-destructive)
            if route["method"] == "GET":
                test_cases.append(
                    APITestCase(
                        name=f"test_api{route['path'].replace('/', '_')}",
                        description=f"Test {route['method']} {route['path']} endpoint",
                        method=route["method"],
                        path=route["path"],
                        expected_status=200,
                        destructive=False,
                    )
                )
            else:
                # Mark destructive operations as skipped
                test_case = APITestCase(
                    name=f"test_api{route['path'].replace('/', '_')}_{route['method'].lower()}",
                    description=f"Test {route['method']} {route['path']} endpoint",
                    method=route["method"],
                    path=route["path"],
                    expected_status=200,
                    destructive=True,
                )
                test_case.status = TestStatus.SKIPPED
                test_case.skip_reason = "Destructive operation - deferred to sandbox phase"
                test_cases.append(test_case)

        return test_cases

    async def _parse_api_routes(self) -> list[dict[str, Any]]:
        """Extract API routes from FastAPI source code.

        Returns:
            List of route definitions
        """
        routes = []
        api_dir = self.project_root / "ha_boss" / "api"

        if not api_dir.exists():
            logger.warning(f"API directory not found: {api_dir}")
            return routes

        # Find all Python files in API directory
        api_files = list(api_dir.glob("**/*.py"))

        for file_path in api_files:
            if file_path.name.startswith("__"):
                continue

            source = file_path.read_text()

            # Pattern: @router.get("/path")
            route_patterns = re.finditer(
                r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']',
                source,
                re.MULTILINE,
            )

            for match in route_patterns:
                method, path = match.groups()
                routes.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "source_file": str(file_path),
                    }
                )

        # Try to get routes from running server's OpenAPI spec
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://localhost:8000/openapi.json")
                if response.status_code == 200:
                    openapi = response.json()
                    routes = self._merge_with_openapi(routes, openapi)
        except Exception:
            # Server not running - rely on source parsing only
            pass

        return routes

    def _merge_with_openapi(
        self, routes: list[dict[str, Any]], openapi: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Merge parsed routes with OpenAPI specification.

        Args:
            routes: Routes from source code parsing
            openapi: OpenAPI specification from server

        Returns:
            Merged and deduplicated routes
        """
        # Extract paths from OpenAPI spec
        openapi_routes = []
        for path, methods in openapi.get("paths", {}).items():
            for method in methods.keys():
                if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    openapi_routes.append({"method": method.upper(), "path": path})

        # Merge routes, preferring source code routes
        route_set = {(r["method"], r["path"]) for r in routes}

        for openapi_route in openapi_routes:
            key = (openapi_route["method"], openapi_route["path"])
            if key not in route_set:
                routes.append(openapi_route)
                route_set.add(key)

        return routes
