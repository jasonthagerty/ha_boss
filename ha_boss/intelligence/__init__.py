"""Intelligence layer for pattern collection and analysis."""

from ha_boss.intelligence.anomaly_detector import (
    Anomaly,
    AnomalyDetector,
    AnomalyType,
    create_anomaly_detector,
)
from ha_boss.intelligence.claude_client import ClaudeClient
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity
from ha_boss.intelligence.ollama_client import OllamaClient
from ha_boss.intelligence.pattern_collector import PatternCollector
from ha_boss.intelligence.reliability_analyzer import (
    FailureEvent,
    ReliabilityAnalyzer,
    ReliabilityMetric,
)
from ha_boss.intelligence.weekly_summary import (
    IntegrationTrend,
    WeeklySummary,
    WeeklySummaryGenerator,
)

__all__ = [
    # Anomaly Detection
    "Anomaly",
    "AnomalyDetector",
    "AnomalyType",
    "create_anomaly_detector",
    # LLM
    "ClaudeClient",
    "LLMRouter",
    "TaskComplexity",
    "OllamaClient",
    # Pattern Analysis
    "PatternCollector",
    "ReliabilityAnalyzer",
    "ReliabilityMetric",
    "FailureEvent",
    # Weekly Summary
    "IntegrationTrend",
    "WeeklySummary",
    "WeeklySummaryGenerator",
]
