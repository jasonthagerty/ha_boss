"""Automation analysis and optimization module."""

from ha_boss.automation.analyzer import (
    AnalysisResult,
    AutomationAnalyzer,
    Suggestion,
    SuggestionSeverity,
)
from ha_boss.automation.generator import AutomationGenerator, GeneratedAutomation

__all__ = [
    "AnalysisResult",
    "AutomationAnalyzer",
    "AutomationGenerator",
    "GeneratedAutomation",
    "Suggestion",
    "SuggestionSeverity",
]
