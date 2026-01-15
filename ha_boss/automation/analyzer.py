"""Automation analyzer for Home Assistant automations."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import func, select

from ha_boss.core.config import Config
from ha_boss.core.database import AutomationExecution, AutomationServiceCall, Database
from ha_boss.core.ha_client import HomeAssistantClient
from ha_boss.intelligence.llm_router import LLMRouter, TaskComplexity

logger = logging.getLogger(__name__)


class SuggestionSeverity(Enum):
    """Severity levels for optimization suggestions."""

    INFO = "info"  # Good practices, minor improvements
    WARNING = "warning"  # Potential issues, inefficiencies
    ERROR = "error"  # Anti-patterns, likely bugs


@dataclass
class Suggestion:
    """An optimization suggestion for an automation."""

    title: str
    description: str
    severity: SuggestionSeverity
    category: str  # e.g., "triggers", "conditions", "actions", "structure"


@dataclass
class UsageStatistics:
    """Usage statistics for an automation."""

    execution_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float | None = None
    service_call_count: int = 0
    most_common_trigger: str | None = None
    last_executed: datetime | None = None


@dataclass
class AnalysisResult:
    """Result of analyzing an automation."""

    automation_id: str
    friendly_name: str
    state: str
    trigger_count: int
    condition_count: int
    action_count: int
    suggestions: list[Suggestion] = field(default_factory=list)
    ai_analysis: str | None = None
    raw_attributes: dict[str, Any] = field(default_factory=dict)
    usage_stats: UsageStatistics | None = None

    @property
    def has_issues(self) -> bool:
        """Check if any warnings or errors exist."""
        return any(
            s.severity in (SuggestionSeverity.WARNING, SuggestionSeverity.ERROR)
            for s in self.suggestions
        )


class AutomationAnalyzer:
    """Analyzes Home Assistant automations for optimization opportunities.

    This class fetches automations from Home Assistant, parses their structure,
    identifies common anti-patterns, and uses AI to generate improvement suggestions.
    """

    def __init__(
        self,
        ha_client: HomeAssistantClient,
        config: Config,
        instance_id: str,
        database: Database | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        """Initialize automation analyzer.

        Args:
            ha_client: Home Assistant API client
            config: HA Boss configuration
            instance_id: Home Assistant instance identifier
            database: Optional database for usage tracking
            llm_router: Optional LLM router for AI-powered suggestions
        """
        self.ha_client = ha_client
        self.config = config
        self.instance_id = instance_id
        self.database = database
        self.llm_router = llm_router

    async def get_automations(self) -> list[dict[str, Any]]:
        """Fetch all automations from Home Assistant.

        Returns:
            List of automation entity states
        """
        states = await self.ha_client.get_states()
        automations = [
            state for state in states if state.get("entity_id", "").startswith("automation.")
        ]
        logger.debug(f"Found {len(automations)} automations")
        return automations

    async def analyze_automation(
        self,
        automation_id: str,
        include_ai: bool = True,
    ) -> AnalysisResult | None:
        """Analyze a single automation for improvements.

        Args:
            automation_id: Entity ID of the automation (e.g., "automation.bedroom_lights")
            include_ai: Whether to include AI-powered analysis

        Returns:
            Analysis result with suggestions, or None if automation not found
        """
        # Ensure proper entity ID format
        if not automation_id.startswith("automation."):
            automation_id = f"automation.{automation_id}"

        try:
            state = await self.ha_client.get_state(automation_id)
        except Exception as e:
            logger.error(f"Failed to fetch automation {automation_id}: {e}")
            return None

        return await self.analyze_automation_state(state, include_ai)

    async def analyze_all(
        self,
        include_ai: bool = True,
    ) -> list[AnalysisResult]:
        """Analyze all automations.

        When AI analysis is disabled, automations are analyzed concurrently
        for better performance.

        Args:
            include_ai: Whether to include AI-powered analysis

        Returns:
            List of analysis results
        """
        import asyncio

        automations = await self.get_automations()

        if not include_ai:
            # Analyze concurrently when AI is disabled (no LLM rate limiting concerns)
            tasks = [
                self.analyze_automation_state(automation, include_ai=False)
                for automation in automations
            ]
            results = await asyncio.gather(*tasks)
            return [r for r in results if r is not None]
        else:
            # Analyze sequentially when AI is enabled to avoid overwhelming LLM
            results = []
            for automation in automations:
                result = await self.analyze_automation_state(automation, include_ai)
                if result:
                    results.append(result)
            return results

    async def analyze_automation_state(
        self,
        state: dict[str, Any],
        include_ai: bool = True,
    ) -> AnalysisResult:
        """Analyze an automation state object.

        This method is useful when you already have the automation state
        (e.g., from get_automations) and want to avoid an additional API call.

        Args:
            state: Automation entity state from HA API
            include_ai: Whether to include AI analysis

        Returns:
            Analysis result
        """
        entity_id = state.get("entity_id", "unknown")
        attributes = state.get("attributes", {})
        automation_state = state.get("state", "unknown")

        # Extract automation structure
        friendly_name = attributes.get("friendly_name", entity_id)
        triggers = self._extract_triggers(attributes)
        conditions = self._extract_conditions(attributes)
        actions = self._extract_actions(attributes)

        # Create result
        result = AnalysisResult(
            automation_id=entity_id,
            friendly_name=friendly_name,
            state=automation_state,
            trigger_count=len(triggers),
            condition_count=len(conditions),
            action_count=len(actions),
            raw_attributes=attributes,
        )

        # Run static analysis
        suggestions = self._static_analysis(
            triggers=triggers,
            conditions=conditions,
            actions=actions,
            attributes=attributes,
        )
        result.suggestions.extend(suggestions)

        # Add AI analysis if enabled and LLM available
        if include_ai and self.llm_router:
            ai_analysis = await self._generate_ai_analysis(
                friendly_name=friendly_name,
                triggers=triggers,
                conditions=conditions,
                actions=actions,
                static_suggestions=suggestions,
            )
            result.ai_analysis = ai_analysis

        return result

    def _extract_triggers(self, attributes: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract triggers from automation attributes.

        Args:
            attributes: Automation attributes

        Returns:
            List of trigger dictionaries
        """
        # HA stores triggers in 'last_triggered' attribute context
        # But the actual trigger definitions may be in 'trigger' attribute
        triggers = attributes.get("trigger", [])
        if isinstance(triggers, dict):
            triggers = [triggers]
        elif not isinstance(triggers, list):
            triggers = []
        return triggers

    def _extract_conditions(self, attributes: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract conditions from automation attributes.

        Args:
            attributes: Automation attributes

        Returns:
            List of condition dictionaries
        """
        conditions = attributes.get("condition", [])
        if isinstance(conditions, dict):
            conditions = [conditions]
        elif not isinstance(conditions, list):
            conditions = []
        return conditions

    def _extract_actions(self, attributes: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract actions from automation attributes.

        Args:
            attributes: Automation attributes

        Returns:
            List of action dictionaries
        """
        actions = attributes.get("action", [])
        if isinstance(actions, dict):
            actions = [actions]
        elif not isinstance(actions, list):
            actions = []
        return actions

    def _static_analysis(
        self,
        triggers: list[dict[str, Any]],
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        attributes: dict[str, Any],
    ) -> list[Suggestion]:
        """Perform static analysis on automation structure.

        Args:
            triggers: List of triggers
            conditions: List of conditions
            actions: List of actions
            attributes: Full automation attributes

        Returns:
            List of suggestions from static analysis
        """
        suggestions: list[Suggestion] = []

        # Check for common anti-patterns

        # 1. No triggers
        if not triggers:
            suggestions.append(
                Suggestion(
                    title="No triggers defined",
                    description=(
                        "This automation has no triggers. It can only be started manually "
                        "or by other automations."
                    ),
                    severity=SuggestionSeverity.INFO,
                    category="triggers",
                )
            )

        # 2. Multiple similar triggers that could be combined
        if len(triggers) > 1:
            trigger_platforms = [t.get("platform") for t in triggers]
            if trigger_platforms.count("state") > 1:
                # Check if they're for similar entities
                state_triggers = [t for t in triggers if t.get("platform") == "state"]
                entity_ids = [t.get("entity_id") for t in state_triggers]

                # If multiple state triggers with same conditions
                if len(set(entity_ids)) > 1 and len(entity_ids) == len(state_triggers):
                    suggestions.append(
                        Suggestion(
                            title="Multiple state triggers could be combined",
                            description=(
                                "Multiple state triggers for different entities could be "
                                "combined into a single trigger with entity_id list."
                            ),
                            severity=SuggestionSeverity.WARNING,
                            category="triggers",
                        )
                    )

        # 3. Duplicate entity checks in conditions
        if len(conditions) > 1:
            entity_refs = []
            for condition in conditions:
                entity_id = condition.get("entity_id")
                if entity_id:
                    entity_refs.append(entity_id)

            # Check for duplicates
            seen = set()
            duplicates = set()
            for entity in entity_refs:
                if entity in seen:
                    duplicates.add(entity)
                seen.add(entity)

            if duplicates:
                suggestions.append(
                    Suggestion(
                        title="Redundant entity checks in conditions",
                        description=(
                            f"Entity {', '.join(duplicates)} is checked multiple times. "
                            "Consider combining conditions."
                        ),
                        severity=SuggestionSeverity.WARNING,
                        category="conditions",
                    )
                )

        # 4. No actions
        if not actions:
            suggestions.append(
                Suggestion(
                    title="No actions defined",
                    description="This automation has no actions and does nothing when triggered.",
                    severity=SuggestionSeverity.ERROR,
                    category="actions",
                )
            )

        # 5. Very long action sequences
        if len(actions) > 10:
            suggestions.append(
                Suggestion(
                    title="Complex action sequence",
                    description=(
                        f"This automation has {len(actions)} actions. Consider breaking "
                        "it into multiple automations or using scripts for reusability."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="actions",
                )
            )

        # 6. Hardcoded delays
        delay_count = sum(1 for a in actions if a.get("delay") is not None)
        if delay_count > 2:
            suggestions.append(
                Suggestion(
                    title="Multiple hardcoded delays",
                    description=(
                        f"This automation has {delay_count} delays. Consider using "
                        "wait_for_trigger or time patterns for better reliability."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="actions",
                )
            )

        # 7. Check for deprecated or risky patterns
        for action in actions:
            service = action.get("service", "")
            if service == "homeassistant.restart":
                suggestions.append(
                    Suggestion(
                        title="Home Assistant restart in automation",
                        description=(
                            "This automation restarts Home Assistant. This should be "
                            "used with extreme caution and proper safeguards."
                        ),
                        severity=SuggestionSeverity.ERROR,
                        category="actions",
                    )
                )

        # 8. Check mode
        mode = attributes.get("mode", "single")
        if mode == "parallel" and len(actions) > 5:
            suggestions.append(
                Suggestion(
                    title="Parallel mode with many actions",
                    description=(
                        "This automation runs in parallel mode with many actions. "
                        "This could cause race conditions. Consider 'queued' mode."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="structure",
                )
            )

        # 9. Good practices (positive feedback)
        if attributes.get("mode") == "queued":
            suggestions.append(
                Suggestion(
                    title="Uses queued mode",
                    description="Good practice: Queued mode prevents overlapping runs.",
                    severity=SuggestionSeverity.INFO,
                    category="structure",
                )
            )

        # Check for use of choose (conditional logic)
        has_choose = any(a.get("choose") is not None for a in actions)
        if has_choose:
            suggestions.append(
                Suggestion(
                    title="Uses choose for conditional logic",
                    description="Good practice: Using choose for conditional actions.",
                    severity=SuggestionSeverity.INFO,
                    category="actions",
                )
            )

        return suggestions

    async def _generate_ai_analysis(
        self,
        friendly_name: str,
        triggers: list[dict[str, Any]],
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        static_suggestions: list[Suggestion],
    ) -> str | None:
        """Generate AI-powered analysis using LLM.

        Args:
            friendly_name: Automation friendly name
            triggers: List of triggers
            conditions: List of conditions
            actions: List of actions
            static_suggestions: Already identified suggestions

        Returns:
            AI-generated analysis text, or None if unavailable
        """
        if not self.llm_router:
            return None

        # Build prompt
        prompt = self._build_analysis_prompt(
            friendly_name=friendly_name,
            triggers=triggers,
            conditions=conditions,
            actions=actions,
            static_suggestions=static_suggestions,
        )

        system_prompt = (
            "You are a Home Assistant automation expert. Analyze the automation "
            "and provide specific, actionable suggestions. Focus on efficiency, "
            "reliability, and best practices. Be concise but helpful."
        )

        try:
            result = await self.llm_router.generate(
                prompt=prompt,
                complexity=TaskComplexity.MODERATE,
                max_tokens=500,
                temperature=0.3,  # Lower temperature for more focused analysis
                system_prompt=system_prompt,
            )
            return result
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return None

    def _build_analysis_prompt(
        self,
        friendly_name: str,
        triggers: list[dict[str, Any]],
        conditions: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        static_suggestions: list[Suggestion],
    ) -> str:
        """Build prompt for AI analysis.

        Args:
            friendly_name: Automation name
            triggers: Triggers list
            conditions: Conditions list
            actions: Actions list
            static_suggestions: Already identified issues

        Returns:
            Formatted prompt string
        """
        # Summarize existing issues
        issues_text = ""
        if static_suggestions:
            warning_errors = [
                s
                for s in static_suggestions
                if s.severity in (SuggestionSeverity.WARNING, SuggestionSeverity.ERROR)
            ]
            if warning_errors:
                issues_text = "\n\nAlready identified issues:\n"
                for s in warning_errors:
                    issues_text += f"- {s.title}\n"

        prompt = f"""Analyze this Home Assistant automation and suggest improvements:

Automation: {friendly_name}

Triggers ({len(triggers)}):
{self._format_items(triggers)}

Conditions ({len(conditions)}):
{self._format_items(conditions)}

Actions ({len(actions)}):
{self._format_items(actions)}
{issues_text}

Provide 1-3 specific optimization suggestions not already mentioned. Focus on:
1. Performance improvements
2. Reliability enhancements
3. Code simplification
4. Best practices

Be concise. Each suggestion should be 1-2 sentences."""

        return prompt

    def _format_items(self, items: list[dict[str, Any]]) -> str:
        """Format list items for prompt.

        Args:
            items: List of dictionaries

        Returns:
            Formatted string
        """
        if not items:
            return "  (none)"

        result = []
        for i, item in enumerate(items[:5], 1):  # Limit to 5 items
            # Extract key identifying info
            if "platform" in item:
                result.append(f"  {i}. Platform: {item['platform']}")
            elif "service" in item:
                result.append(f"  {i}. Service: {item['service']}")
            elif "condition" in item:
                result.append(f"  {i}. Condition: {item['condition']}")
            else:
                # Use first key-value pair
                if item:
                    key, value = next(iter(item.items()))
                    if isinstance(value, (str, int, float, bool)):
                        result.append(f"  {i}. {key}: {value}")
                    else:
                        result.append(f"  {i}. {key}: (complex)")
                else:
                    result.append(f"  {i}. (empty)")

        if len(items) > 5:
            result.append(f"  ... and {len(items) - 5} more")

        return "\n".join(result)

    async def suggest_optimizations(
        self,
        automation_id: str,
    ) -> list[Suggestion]:
        """Get optimization suggestions for an automation.

        Convenience method that returns just the suggestions from analysis.

        Args:
            automation_id: Entity ID of the automation

        Returns:
            List of suggestions
        """
        result = await self.analyze_automation(automation_id)
        if result:
            return result.suggestions
        return []

    async def get_usage_statistics(
        self, automation_id: str, days: int = 30
    ) -> UsageStatistics | None:
        """Get usage statistics for an automation.

        Args:
            automation_id: Automation entity ID
            days: Number of days to look back (default: 30)

        Returns:
            Usage statistics or None if database unavailable
        """
        if not self.database:
            return None

        # Calculate time window
        since = datetime.now(UTC) - timedelta(days=days)

        try:
            async with self.database.async_session() as session:
                # Query execution stats
                exec_result = await session.execute(
                    select(
                        func.count(AutomationExecution.id).label("count"),
                        func.sum(
                            func.cast(AutomationExecution.success == False, int)  # noqa: E712
                        ).label("failures"),
                        func.avg(AutomationExecution.duration_ms).label("avg_duration"),
                        func.max(AutomationExecution.executed_at).label("last_executed"),
                    ).where(
                        AutomationExecution.instance_id == self.instance_id,
                        AutomationExecution.automation_id == automation_id,
                        AutomationExecution.executed_at >= since,
                    )
                )
                exec_stats = exec_result.one()

                # Query most common trigger type
                trigger_result = await session.execute(
                    select(
                        AutomationExecution.trigger_type,
                        func.count(AutomationExecution.id).label("count"),
                    )
                    .where(
                        AutomationExecution.instance_id == self.instance_id,
                        AutomationExecution.automation_id == automation_id,
                        AutomationExecution.executed_at >= since,
                    )
                    .group_by(AutomationExecution.trigger_type)
                    .order_by(func.count(AutomationExecution.id).desc())
                    .limit(1)
                )
                trigger_row = trigger_result.first()

                # Query service call count
                service_result = await session.execute(
                    select(func.count(AutomationServiceCall.id)).where(
                        AutomationServiceCall.instance_id == self.instance_id,
                        AutomationServiceCall.automation_id == automation_id,
                        AutomationServiceCall.called_at >= since,
                    )
                )
                service_count = service_result.scalar() or 0

                return UsageStatistics(
                    execution_count=exec_stats.count or 0,
                    failure_count=exec_stats.failures or 0,
                    avg_duration_ms=exec_stats.avg_duration,
                    service_call_count=service_count,
                    most_common_trigger=trigger_row[0] if trigger_row else None,
                    last_executed=exec_stats.last_executed,
                )

        except Exception as e:
            logger.error(f"Failed to query usage statistics for {automation_id}: {e}")
            return None

    async def analyze_with_usage(
        self,
        automation_id: str,
        include_ai: bool = True,
        days: int = 30,
    ) -> AnalysisResult | None:
        """Analyze automation with usage-based recommendations.

        Args:
            automation_id: Automation entity ID
            include_ai: Whether to include AI analysis
            days: Number of days for usage statistics

        Returns:
            Analysis result with usage-based suggestions
        """
        # Get base analysis
        result = await self.analyze_automation(automation_id, include_ai=include_ai)
        if not result:
            return None

        # Add usage statistics if database available
        if self.database:
            usage_stats = await self.get_usage_statistics(automation_id, days=days)
            if usage_stats:
                result.usage_stats = usage_stats

                # Add usage-based suggestions
                usage_suggestions = self._usage_based_suggestions(usage_stats, result)
                result.suggestions.extend(usage_suggestions)

        return result

    def _usage_based_suggestions(
        self, usage: UsageStatistics, analysis: AnalysisResult
    ) -> list[Suggestion]:
        """Generate usage-based optimization suggestions.

        Args:
            usage: Usage statistics
            analysis: Base analysis result

        Returns:
            List of usage-based suggestions
        """
        suggestions: list[Suggestion] = []

        # 1. High execution frequency
        if usage.execution_count > 100:
            executions_per_day = usage.execution_count / 30  # Assuming 30 days
            if executions_per_day > 100:
                suggestions.append(
                    Suggestion(
                        title="Very high execution frequency",
                        description=(
                            f"This automation runs ~{int(executions_per_day)} times per day. "
                            "Consider adding rate limiting or consolidating triggers."
                        ),
                        severity=SuggestionSeverity.WARNING,
                        category="usage",
                    )
                )

        # 2. High failure rate
        if usage.execution_count > 0:
            failure_rate = (usage.failure_count / usage.execution_count) * 100
            if failure_rate > 10:
                suggestions.append(
                    Suggestion(
                        title="High failure rate",
                        description=(
                            f"This automation fails {failure_rate:.1f}% of the time "
                            f"({usage.failure_count}/{usage.execution_count} executions). "
                            "Review error handling and conditions."
                        ),
                        severity=SuggestionSeverity.ERROR,
                        category="usage",
                    )
                )

        # 3. Slow execution
        if usage.avg_duration_ms and usage.avg_duration_ms > 5000:
            suggestions.append(
                Suggestion(
                    title="Slow execution time",
                    description=(
                        f"Average execution time is {usage.avg_duration_ms/1000:.1f}s. "
                        "Consider optimizing delays, service calls, or conditions."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="usage",
                )
            )

        # 4. Many service calls
        if usage.execution_count > 0:
            calls_per_execution = usage.service_call_count / usage.execution_count
            if calls_per_execution > 5:
                suggestions.append(
                    Suggestion(
                        title="High service call volume",
                        description=(
                            f"Averages {calls_per_execution:.1f} service calls per execution. "
                            "Consider batching operations or using scenes/scripts."
                        ),
                        severity=SuggestionSeverity.INFO,
                        category="usage",
                    )
                )

        # 5. Inactive automation
        if usage.execution_count == 0:
            suggestions.append(
                Suggestion(
                    title="Automation never executed",
                    description=(
                        "This automation hasn't run in the past 30 days. "
                        "Verify triggers are working or consider disabling."
                    ),
                    severity=SuggestionSeverity.WARNING,
                    category="usage",
                )
            )
        elif usage.execution_count < 5:
            suggestions.append(
                Suggestion(
                    title="Rarely executed automation",
                    description=(
                        f"Only executed {usage.execution_count} times in 30 days. "
                        "Verify this matches expected behavior."
                    ),
                    severity=SuggestionSeverity.INFO,
                    category="usage",
                )
            )

        return suggestions
