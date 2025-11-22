"""Tests for WeeklySummaryGenerator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ha_boss.core.config import Config, IntelligenceConfig, NotificationsConfig
from ha_boss.core.database import IntegrationReliability, PatternInsight, init_database
from ha_boss.intelligence.llm_router import LLMRouter
from ha_boss.intelligence.weekly_summary import (
    IntegrationTrend,
    WeeklySummary,
    WeeklySummaryGenerator,
)
from ha_boss.notifications.manager import NotificationManager


@pytest.fixture
async def test_database(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test_weekly.db"
    db = await init_database(db_path)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def test_config(tmp_path):
    """Create test configuration."""
    return Config(
        home_assistant={
            "url": "http://localhost:8123",
            "token": "test_token",
        },
        notifications=NotificationsConfig(
            weekly_summary=True,
            ai_enhanced=True,
        ),
        intelligence=IntelligenceConfig(
            ollama_enabled=True,
            ollama_url="http://localhost:11434",
            ollama_model="llama3.1:8b",
        ),
        database={
            "path": tmp_path / "ha_boss.db",
        },
    )


@pytest.fixture
async def generator(test_database, test_config):
    """Create WeeklySummaryGenerator instance."""
    return WeeklySummaryGenerator(
        config=test_config,
        database=test_database,
    )


@pytest.fixture
async def sample_weekly_data(test_database):
    """Create sample reliability data for a full week."""
    now = datetime.now(UTC)

    async with test_database.async_session() as session:
        # MQTT: High reliability (95%) - 19 successes, 1 failure
        for i in range(19):
            event = IntegrationReliability(
                integration_id="mqtt_101",
                integration_domain="mqtt",
                timestamp=now - timedelta(hours=i * 8),
                event_type="heal_success",
                entity_id=f"sensor.mqtt_{i}",
            )
            session.add(event)

        event = IntegrationReliability(
            integration_id="mqtt_101",
            integration_domain="mqtt",
            timestamp=now - timedelta(days=5),
            event_type="heal_failure",
        )
        session.add(event)

        # Hue: Good reliability (80%) - 8 successes, 2 failures
        for i in range(8):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=now - timedelta(hours=i * 12),
                event_type="heal_success",
                entity_id=f"light.hue_{i}",
            )
            session.add(event)

        for i in range(2):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=now - timedelta(days=3 + i),
                event_type="heal_failure",
            )
            session.add(event)

        # ZWave: Poor reliability (40%) - 2 successes, 3 failures
        for i in range(2):
            event = IntegrationReliability(
                integration_id="zwave_456",
                integration_domain="zwave",
                timestamp=now - timedelta(days=i),
                event_type="heal_success",
            )
            session.add(event)

        for i in range(3):
            event = IntegrationReliability(
                integration_id="zwave_456",
                integration_domain="zwave",
                timestamp=now - timedelta(days=2 + i),
                event_type="heal_failure",
            )
            session.add(event)

        # ESPHome: Some unavailable events (no healing)
        for i in range(3):
            event = IntegrationReliability(
                integration_id="esphome_789",
                integration_domain="esphome",
                timestamp=now - timedelta(hours=i * 24),
                event_type="unavailable",
            )
            session.add(event)

        await session.commit()


@pytest.fixture
async def previous_week_data(test_database):
    """Create sample data from previous week for trend comparison."""
    now = datetime.now(UTC)
    prev_start = now - timedelta(days=14)

    async with test_database.async_session() as session:
        # MQTT previous week: 90% (9 successes, 1 failure)
        for i in range(9):
            event = IntegrationReliability(
                integration_id="mqtt_101",
                integration_domain="mqtt",
                timestamp=prev_start + timedelta(hours=i * 12),
                event_type="heal_success",
            )
            session.add(event)

        event = IntegrationReliability(
            integration_id="mqtt_101",
            integration_domain="mqtt",
            timestamp=prev_start + timedelta(days=5),
            event_type="heal_failure",
        )
        session.add(event)

        # Hue previous week: 70% (7 successes, 3 failures)
        for i in range(7):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=prev_start + timedelta(hours=i * 12),
                event_type="heal_success",
            )
            session.add(event)

        for i in range(3):
            event = IntegrationReliability(
                integration_id="hue_123",
                integration_domain="hue",
                timestamp=prev_start + timedelta(days=4 + i),
                event_type="heal_failure",
            )
            session.add(event)

        # ZWave previous week: 60% (3 successes, 2 failures)
        for i in range(3):
            event = IntegrationReliability(
                integration_id="zwave_456",
                integration_domain="zwave",
                timestamp=prev_start + timedelta(days=i),
                event_type="heal_success",
            )
            session.add(event)

        for i in range(2):
            event = IntegrationReliability(
                integration_id="zwave_456",
                integration_domain="zwave",
                timestamp=prev_start + timedelta(days=4 + i),
                event_type="heal_failure",
            )
            session.add(event)

        await session.commit()


# Test WeeklySummary dataclass
class TestWeeklySummary:
    """Tests for WeeklySummary dataclass."""

    def test_summary_creation(self):
        """Test creating WeeklySummary with basic data."""
        now = datetime.now(UTC)
        summary = WeeklySummary(
            period_start=now - timedelta(days=7),
            period_end=now,
            total_integrations=5,
            total_healing_attempts=30,
            successful_healings=25,
            failed_healings=5,
            overall_success_rate=0.833,
        )

        assert summary.total_integrations == 5
        assert summary.total_healing_attempts == 30
        assert summary.successful_healings == 25
        assert summary.failed_healings == 5
        assert summary.overall_success_rate == pytest.approx(0.833, rel=0.001)

    def test_summary_with_trends(self):
        """Test WeeklySummary with trend data."""
        now = datetime.now(UTC)
        summary = WeeklySummary(
            period_start=now - timedelta(days=7),
            period_end=now,
            total_integrations=3,
            total_healing_attempts=20,
            successful_healings=16,
            failed_healings=4,
            overall_success_rate=0.8,
            improved_count=2,
            degraded_count=1,
            stable_count=0,
        )

        assert summary.improved_count == 2
        assert summary.degraded_count == 1
        assert summary.stable_count == 0


# Test IntegrationTrend dataclass
class TestIntegrationTrend:
    """Tests for IntegrationTrend dataclass."""

    def test_improved_trend(self):
        """Test improved trend detection."""
        trend = IntegrationTrend(
            domain="hue",
            current_rate=0.85,
            previous_rate=0.70,
            trend="improved",
            change_percent=15.0,
        )

        assert trend.domain == "hue"
        assert trend.trend == "improved"
        assert trend.change_percent == 15.0

    def test_degraded_trend(self):
        """Test degraded trend detection."""
        trend = IntegrationTrend(
            domain="zwave",
            current_rate=0.40,
            previous_rate=0.60,
            trend="degraded",
            change_percent=-20.0,
        )

        assert trend.trend == "degraded"
        assert trend.change_percent == -20.0

    def test_new_integration(self):
        """Test trend for new integration."""
        trend = IntegrationTrend(
            domain="esphome",
            current_rate=0.90,
            previous_rate=None,
            trend="new",
            change_percent=None,
        )

        assert trend.trend == "new"
        assert trend.previous_rate is None


# Test WeeklySummaryGenerator
class TestWeeklySummaryGenerator:
    """Tests for WeeklySummaryGenerator class."""

    @pytest.mark.asyncio
    async def test_generator_initialization(self, test_database, test_config):
        """Test generator initialization."""
        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
        )

        assert generator.config == test_config
        assert generator.database == test_database
        assert generator.llm_router is None
        assert generator.notification_manager is None

    @pytest.mark.asyncio
    async def test_generate_summary_empty_database(self, generator):
        """Test generating summary with no data."""
        summary = await generator.generate_summary()

        assert summary.total_integrations == 0
        assert summary.total_healing_attempts == 0
        assert summary.successful_healings == 0
        assert summary.failed_healings == 0
        assert summary.overall_success_rate == 1.0  # No failures
        assert len(summary.top_performers) == 0
        assert len(summary.needs_attention) == 0

    @pytest.mark.asyncio
    async def test_generate_summary_with_data(self, generator, sample_weekly_data):
        """Test generating summary with sample data."""
        summary = await generator.generate_summary()

        assert summary.total_integrations == 4  # mqtt, hue, zwave, esphome
        assert summary.total_healing_attempts == 35  # 20 + 10 + 5
        assert summary.successful_healings == 29  # 19 + 8 + 2
        assert summary.failed_healings == 6  # 1 + 2 + 3
        assert summary.overall_success_rate == pytest.approx(0.829, rel=0.01)

    @pytest.mark.asyncio
    async def test_top_performers(self, generator, sample_weekly_data):
        """Test top performers are correctly identified."""
        summary = await generator.generate_summary()

        # Top performers should be sorted by best success rate
        assert len(summary.top_performers) <= 3
        if len(summary.top_performers) > 0:
            # First should be mqtt (95%)
            assert summary.top_performers[0].integration_domain == "mqtt"
            assert summary.top_performers[0].success_rate == pytest.approx(0.95, rel=0.01)

    @pytest.mark.asyncio
    async def test_needs_attention(self, generator, sample_weekly_data):
        """Test integrations needing attention are identified."""
        summary = await generator.generate_summary()

        # Needs attention should include poor performers
        domains = [m.integration_domain for m in summary.needs_attention]
        assert "zwave" in domains  # 40% success rate

    @pytest.mark.asyncio
    async def test_trend_calculation(self, generator, sample_weekly_data, previous_week_data):
        """Test trend calculation between weeks."""
        summary = await generator.generate_summary()

        assert len(summary.trends) > 0

        # Find specific trends
        hue_trend = next((t for t in summary.trends if t.domain == "hue"), None)
        zwave_trend = next((t for t in summary.trends if t.domain == "zwave"), None)

        # Hue should be improved (70% -> 80%)
        if hue_trend:
            assert hue_trend.trend == "improved"
            assert hue_trend.change_percent is not None
            assert hue_trend.change_percent > 0

        # ZWave should be degraded (60% -> 40%)
        if zwave_trend:
            assert zwave_trend.trend == "degraded"
            assert zwave_trend.change_percent is not None
            assert zwave_trend.change_percent < 0

    @pytest.mark.asyncio
    async def test_success_rate_change(self, generator, sample_weekly_data, previous_week_data):
        """Test success rate change calculation."""
        summary = await generator.generate_summary()

        # Should have comparison data
        assert summary.previous_success_rate is not None
        assert summary.success_rate_change is not None

    @pytest.mark.asyncio
    async def test_store_in_database(self, generator, sample_weekly_data):
        """Test storing summary in pattern_insights table."""
        summary = await generator.generate_summary()
        await generator.store_in_database(summary)

        # Verify it was stored
        async with generator.database.async_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(PatternInsight).where(PatternInsight.insight_type == "weekly_summary")
            )
            insight = result.scalar_one()

            assert insight is not None
            assert insight.period == "weekly"
            assert insight.data["total_integrations"] == summary.total_integrations
            assert insight.data["overall_success_rate"] == summary.overall_success_rate

    @pytest.mark.asyncio
    async def test_format_report(self, generator, sample_weekly_data):
        """Test report formatting."""
        summary = await generator.generate_summary()
        report = generator.format_report(summary)

        assert "Weekly Health Summary" in report
        assert "Overview:" in report
        assert str(summary.total_integrations) in report
        assert f"{summary.overall_success_rate:.0%}" in report

    @pytest.mark.asyncio
    async def test_format_report_with_trends(
        self, generator, sample_weekly_data, previous_week_data
    ):
        """Test report formatting includes trend information."""
        summary = await generator.generate_summary()
        report = generator.format_report(summary)

        assert "Trends:" in report
        assert "improved" in report or "degraded" in report or "stable" in report


# Test AI generation
class TestAIGeneration:
    """Tests for AI summary generation."""

    @pytest.mark.asyncio
    async def test_generate_summary_without_llm(self, generator, sample_weekly_data):
        """Test generating summary without LLM router."""
        summary = await generator.generate_summary()

        # Should work but without AI content
        assert summary.ai_summary is None
        assert summary.ai_recommendations is None

    @pytest.mark.asyncio
    async def test_generate_summary_with_llm(self, test_database, test_config, sample_weekly_data):
        """Test generating summary with mocked LLM router."""
        # Create mock LLM router
        mock_router = AsyncMock(spec=LLMRouter)
        mock_router.generate.return_value = "Test AI summary"

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
            llm_router=mock_router,
        )

        summary = await generator.generate_summary()

        # Should have AI content
        assert summary.ai_summary == "Test AI summary"
        assert mock_router.generate.called

    @pytest.mark.asyncio
    async def test_ai_generation_failure(self, test_database, test_config, sample_weekly_data):
        """Test graceful handling of AI generation failure."""
        # Create mock LLM router that fails
        mock_router = AsyncMock(spec=LLMRouter)
        mock_router.generate.side_effect = Exception("LLM error")

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
            llm_router=mock_router,
        )

        # Should not raise, just return None for AI content
        summary = await generator.generate_summary()

        assert summary.ai_summary is None


# Test notifications
class TestNotifications:
    """Tests for notification sending."""

    @pytest.mark.asyncio
    async def test_send_notification(self, test_database, test_config, sample_weekly_data):
        """Test sending notification with mocked manager."""
        # Create mock notification manager
        mock_manager = AsyncMock(spec=NotificationManager)

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
            notification_manager=mock_manager,
        )

        summary = await generator.generate_summary()
        await generator.send_notification(summary)

        # Should have called notify
        assert mock_manager.notify.called
        call_args = mock_manager.notify.call_args
        context = call_args[0][0]

        assert context.notification_type.value == "weekly_summary"
        assert context.stats["total_attempts"] == summary.total_healing_attempts

    @pytest.mark.asyncio
    async def test_send_notification_without_manager(self, generator, sample_weekly_data):
        """Test sending notification without manager."""
        summary = await generator.generate_summary()

        # Should not raise
        await generator.send_notification(summary)


# Test edge cases
class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_all_successes(self, test_database, test_config):
        """Test summary when all healing attempts are successful."""
        now = datetime.now(UTC)

        async with test_database.async_session() as session:
            for i in range(10):
                event = IntegrationReliability(
                    integration_id="perfect_001",
                    integration_domain="perfect",
                    timestamp=now - timedelta(hours=i),
                    event_type="heal_success",
                )
                session.add(event)
            await session.commit()

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
        )

        summary = await generator.generate_summary()

        assert summary.overall_success_rate == 1.0
        assert summary.failed_healings == 0

    @pytest.mark.asyncio
    async def test_all_failures(self, test_database, test_config):
        """Test summary when all healing attempts fail."""
        now = datetime.now(UTC)

        async with test_database.async_session() as session:
            for i in range(10):
                event = IntegrationReliability(
                    integration_id="broken_001",
                    integration_domain="broken",
                    timestamp=now - timedelta(hours=i),
                    event_type="heal_failure",
                )
                session.add(event)
            await session.commit()

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
        )

        summary = await generator.generate_summary()

        assert summary.overall_success_rate == 0.0
        assert summary.successful_healings == 0

    @pytest.mark.asyncio
    async def test_only_unavailable_events(self, test_database, test_config):
        """Test summary with only unavailable events (no healing)."""
        now = datetime.now(UTC)

        async with test_database.async_session() as session:
            for i in range(10):
                event = IntegrationReliability(
                    integration_id="offline_001",
                    integration_domain="offline",
                    timestamp=now - timedelta(hours=i),
                    event_type="unavailable",
                )
                session.add(event)
            await session.commit()

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
        )

        summary = await generator.generate_summary()

        # No healing attempts means 100% success (no failures)
        assert summary.overall_success_rate == 1.0
        assert summary.total_healing_attempts == 0

    @pytest.mark.asyncio
    async def test_generate_and_send(self, test_database, test_config, sample_weekly_data):
        """Test generate_and_send convenience method."""
        # Create mock notification manager
        mock_manager = AsyncMock(spec=NotificationManager)

        generator = WeeklySummaryGenerator(
            config=test_config,
            database=test_database,
            notification_manager=mock_manager,
        )

        summary = await generator.generate_and_send()

        # Should have generated and stored
        assert summary is not None
        assert summary.total_integrations > 0

        # Should have sent notification
        assert mock_manager.notify.called

        # Should have stored in database
        async with test_database.async_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(PatternInsight).where(PatternInsight.insight_type == "weekly_summary")
            )
            assert result.scalar_one() is not None


# Test prompt building
class TestPromptBuilding:
    """Tests for AI prompt construction."""

    @pytest.mark.asyncio
    async def test_build_summary_prompt(self, generator, sample_weekly_data):
        """Test summary prompt construction."""
        summary = await generator.generate_summary()
        prompt = generator._build_summary_prompt(summary)

        assert "weekly health report" in prompt.lower()
        assert str(summary.total_integrations) in prompt
        assert f"{summary.overall_success_rate:.1%}" in prompt

    @pytest.mark.asyncio
    async def test_build_recommendations_prompt(self, generator, sample_weekly_data):
        """Test recommendations prompt construction."""
        summary = await generator.generate_summary()
        prompt = generator._build_recommendations_prompt(summary)

        if summary.needs_attention:
            assert "recommendations" in prompt.lower()
            # Should include problematic integrations
            for metric in summary.needs_attention:
                assert metric.integration_domain in prompt
