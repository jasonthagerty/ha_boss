"""User Acceptance Testing module for HA Boss.

This module provides automated UAT capabilities including:
- Test case generation from documentation
- Safe test execution (non-destructive by default)
- GitHub issue creation for failures
- Comprehensive reporting

Usage:
    Via slash command: /uat [--cli-only | --api-only | --full] [--dry-run]
"""

from ha_boss.testing.models import (
    APITestCase,
    CLITestCase,
    ExecutionResults,
    TestCase,
    TestPlan,
    TestResult,
    TestScope,
    TestStatus,
    UATReport,
)
from ha_boss.testing.uat_agent import UATAgent

__all__ = [
    "UATAgent",
    "TestCase",
    "CLITestCase",
    "APITestCase",
    "TestResult",
    "TestPlan",
    "ExecutionResults",
    "UATReport",
    "TestStatus",
    "TestScope",
]
