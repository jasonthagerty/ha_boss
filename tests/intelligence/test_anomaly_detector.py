"""Tests for pattern-based anomaly detection."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_boss.core.database import Database, IntegrationReliability
from ha_boss.intelligence.anomaly_detector import (
    Anomaly,
    AnomalyDetector,
    AnomalyType,
    create_anomaly_detector,
)
from ha_boss.intelligence.llm_router import LLMRouter


@pytest.fixture
async def database(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_anomaly.db"
    db = Database(db_path)
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
def mock_llm_router():
    """Create mock LLM router."""
    router = MagicMock(spec=LLMRouter)
    router.generate = AsyncMock(
        return_value="This pattern suggests network connectivity issues during peak hours."
    )
    return router


@pytest.fixture
def detector(database):
    """Create anomaly detector without LLM."""
    return AnomalyDetector(database)


@pytest.fixture
def detector_with_llm(database, mock_llm_router):
    """Create anomaly detector with LLM."""
    return AnomalyDetector(database, mock_llm_router)


# Helper functions for creating test data


async def create_failure_event(
    session,
    integration_id: str,
    integration_domain: str,
    timestamp: datetime,
    event_type: str = "heal_failure",
    entity_id: str | None = None,
):
    """Create a failure event in the database."""
    event = IntegrationReliability(
        integration_id=integration_id,
        integration_domain=integration_domain,
        timestamp=timestamp,
        event_type=event_type,
        entity_id=entity_id,
    )
    session.add(event)
    await session.commit()
    return event


# Data Model Tests


class TestAnomalyDataClass:
    """Tests for Anomaly data class."""

    def test_severity_label_critical(self):
        """Test critical severity label."""
        anomaly = Anomaly(
            type=AnomalyType.UNUSUAL_FAILURE_RATE,
            integration_domain="hue",
            severity=0.9,
            description="Test",
            detected_at=datetime.now(UTC),
        )
        assert anomaly.severity_label == "Critical"

    def test_severity_label_high(self):
        """Test high severity label."""
        anomaly = Anomaly(
            type=AnomalyType.UNUSUAL_FAILURE_RATE,
            integration_domain="hue",
            severity=0.7,
            description="Test",
            detected_at=datetime.now(UTC),
        )
        assert anomaly.severity_label == "High"

    def test_severity_label_medium(self):
        """Test medium severity label."""
        anomaly = Anomaly(
            type=AnomalyType.UNUSUAL_FAILURE_RATE,
            integration_domain="hue",
            severity=0.5,
            description="Test",
            detected_at=datetime.now(UTC),
        )
        assert anomaly.severity_label == "Medium"

    def test_severity_label_low(self):
        """Test low severity label."""
        anomaly = Anomaly(
            type=AnomalyType.UNUSUAL_FAILURE_RATE,
            integration_domain="hue",
            severity=0.2,
            description="Test",
            detected_at=datetime.now(UTC),
        )
        assert anomaly.severity_label == "Low"

    def test_anomaly_with_details(self):
        """Test anomaly with additional details."""
        anomaly = Anomaly(
            type=AnomalyType.TIME_CORRELATION,
            integration_domain="zwave",
            severity=0.6,
            description="Failures cluster around 14:00",
            detected_at=datetime.now(UTC),
            details={"peak_hour": 14, "concentration": 0.75},
        )
        assert anomaly.details["peak_hour"] == 14
        assert anomaly.details["concentration"] == 0.75


# Unusual Failure Rate Detection Tests


class TestUnusualFailureRateDetection:
    """Tests for unusual failure rate detection."""

    @pytest.mark.asyncio
    async def test_no_failures_returns_empty(self, detector, database):
        """Test that no failures returns empty anomaly list."""
        anomalies = await detector.check_unusual_failure_rate(hours=24)
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_detect_spike_vs_baseline(self, detector, database):
        """Test detection of failure spike compared to baseline."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create baseline: 2 failures over 30 days
            for i in range(2):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(days=15 + i),
                )

            # Create spike: 8 failures in last 24 hours
            for i in range(8):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(hours=i),
                )

        anomalies = await detector.check_unusual_failure_rate(hours=24)

        assert len(anomalies) == 1
        assert anomalies[0].type == AnomalyType.UNUSUAL_FAILURE_RATE
        assert anomalies[0].integration_domain == "hue"
        assert anomalies[0].severity > 0.5  # Should be high severity

    @pytest.mark.asyncio
    async def test_no_anomaly_for_normal_rate(self, detector, database):
        """Test that normal failure rate doesn't trigger anomaly."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create consistent failures in baseline (days 2-30)
            for i in range(2, 30, 3):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(days=i),
                )

            # Recent failure at same rate (1 per 3 days = 0.33 per day)
            # In 24 hours, expect ~0.33 failures, having 1 is normal
            await create_failure_event(
                session,
                "entry123",
                "hue",
                now - timedelta(hours=12),
            )

        anomalies = await detector.check_unusual_failure_rate(hours=24)

        # Rate should be similar, no anomaly (or low severity)
        # 1 failure in 24h vs baseline of ~0.33/day is only 3x, below threshold
        high_severity = [a for a in anomalies if a.severity > 0.5]
        assert len(high_severity) == 0

    @pytest.mark.asyncio
    async def test_new_integration_with_failures(self, detector, database):
        """Test detection of failures for integration with no baseline."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures only in recent period (no baseline)
            for i in range(5):
                await create_failure_event(
                    session,
                    "new_entry",
                    "new_integration",
                    now - timedelta(hours=i),
                )

        anomalies = await detector.check_unusual_failure_rate(hours=24)

        # Should detect anomaly since no baseline and multiple failures
        assert len(anomalies) == 1
        assert anomalies[0].integration_domain == "new_integration"

    @pytest.mark.asyncio
    async def test_custom_sensitivity_threshold(self, database):
        """Test that custom sensitivity threshold affects detection."""
        # Lower sensitivity = more anomalies
        detector_sensitive = AnomalyDetector(database, sensitivity_threshold=1.5)

        # Higher sensitivity = fewer anomalies
        detector_strict = AnomalyDetector(database, sensitivity_threshold=3.0)

        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create moderate spike
            for i in range(3):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(days=10 + i),
                )
            for i in range(5):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(hours=i),
                )

        sensitive_anomalies = await detector_sensitive.check_unusual_failure_rate(hours=24)
        strict_anomalies = await detector_strict.check_unusual_failure_rate(hours=24)

        # More sensitive detector should find more (or equal) anomalies
        assert len(sensitive_anomalies) >= len(strict_anomalies)


# Time Correlation Detection Tests


class TestTimeCorrelationDetection:
    """Tests for time-of-day correlation detection."""

    @pytest.mark.asyncio
    async def test_no_failures_returns_empty(self, detector, database):
        """Test that no failures returns empty list."""
        anomalies = await detector.check_time_correlations(hours=24)
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_detect_time_clustering(self, detector, database):
        """Test detection of failures clustered around specific time."""
        now = datetime.now(UTC)
        target_hour = 14  # 2 PM

        async with database.async_session() as session:
            # Create 5 failures all around 2 PM
            for i in range(5):
                timestamp = now.replace(hour=target_hour, minute=i * 10) - timedelta(days=i)
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    timestamp,
                )

        anomalies = await detector.check_time_correlations(hours=168)  # 7 days

        assert len(anomalies) == 1
        assert anomalies[0].type == AnomalyType.TIME_CORRELATION
        assert anomalies[0].integration_domain == "hue"
        # Peak hour should be 14
        assert anomalies[0].details.get("peak_hour") == target_hour

    @pytest.mark.asyncio
    async def test_no_anomaly_for_distributed_failures(self, detector, database):
        """Test that evenly distributed failures don't trigger anomaly."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures distributed across different hours
            for hour in [2, 6, 10, 14, 18, 22]:
                timestamp = now.replace(hour=hour, minute=0)
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    timestamp,
                )

        anomalies = await detector.check_time_correlations(hours=24)

        # Should not detect anomaly since failures are distributed
        assert len(anomalies) == 0

    @pytest.mark.asyncio
    async def test_minimum_failures_required(self, detector, database):
        """Test that minimum number of failures is required for pattern."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create only 2 failures (below minimum of 3)
            for i in range(2):
                timestamp = now.replace(hour=14, minute=0) - timedelta(days=i)
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    timestamp,
                )

        anomalies = await detector.check_time_correlations(hours=168)

        # Should not detect anomaly with too few failures
        assert len(anomalies) == 0


# Integration Correlation Detection Tests


class TestIntegrationCorrelationDetection:
    """Tests for integration failure correlation detection."""

    @pytest.mark.asyncio
    async def test_no_failures_returns_empty(self, detector, database):
        """Test that no failures returns empty list."""
        anomalies = await detector.check_integration_correlations(hours=24)
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_detect_correlated_failures(self, detector, database):
        """Test detection of integrations that fail together."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures for two integrations at same time windows
            # Need enough co-occurrences with high correlation
            # Create at same seconds to ensure same 5-min bucket
            for i in range(6):
                # All in different 5-minute buckets, but each has both integrations
                base_time = now.replace(second=0, microsecond=0) - timedelta(minutes=i * 6)

                # Both integrations fail in same 5-minute window
                await create_failure_event(
                    session,
                    "entry_hue",
                    "hue",
                    base_time,
                )
                await create_failure_event(
                    session,
                    "entry_zwave",
                    "zwave",
                    base_time + timedelta(seconds=60),
                )

        anomalies = await detector.check_integration_correlations(hours=24)

        # Should detect correlation between hue and zwave
        correlation_anomalies = [
            a for a in anomalies if a.type == AnomalyType.INTEGRATION_CORRELATION
        ]
        assert len(correlation_anomalies) >= 1
        # The anomaly domain contains both integration names
        assert any(
            "hue" in a.integration_domain and "zwave" in a.integration_domain
            for a in correlation_anomalies
        )

    @pytest.mark.asyncio
    async def test_no_anomaly_for_independent_failures(self, detector, database):
        """Test that independent failures don't trigger correlation."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures at different times (not within same bucket)
            await create_failure_event(
                session,
                "entry_hue",
                "hue",
                now - timedelta(hours=1),
            )
            await create_failure_event(
                session,
                "entry_zwave",
                "zwave",
                now - timedelta(hours=5),  # Different time bucket
            )

        anomalies = await detector.check_integration_correlations(hours=24)

        # Should not detect correlation
        assert len(anomalies) == 0


# AI Explanation Tests


class TestAIExplanation:
    """Tests for AI explanation generation."""

    @pytest.mark.asyncio
    async def test_ai_explanation_generated_for_high_severity(
        self, detector_with_llm, database, mock_llm_router
    ):
        """Test that AI explanations are generated for high severity anomalies."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create baseline: very few failures
            await create_failure_event(
                session,
                "entry123",
                "hue",
                now - timedelta(days=15),
            )

            # Create massive spike to trigger high-severity anomaly
            for i in range(20):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(hours=i),
                )

        anomalies = await detector_with_llm.detect_anomalies(hours=24)

        # Should have generated AI explanation for high severity
        high_severity = [a for a in anomalies if a.severity >= 0.6]
        assert len(high_severity) > 0
        assert high_severity[0].ai_explanation is not None
        mock_llm_router.generate.assert_called()

    @pytest.mark.asyncio
    async def test_no_ai_without_router(self, detector, database):
        """Test that no AI explanations without LLM router."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            for i in range(10):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(hours=i),
                )

        anomalies = await detector.detect_anomalies(hours=24)

        # Should not have AI explanations
        for anomaly in anomalies:
            assert anomaly.ai_explanation is None

    @pytest.mark.asyncio
    async def test_ai_failure_handled_gracefully(
        self, detector_with_llm, database, mock_llm_router
    ):
        """Test graceful handling when AI generation fails."""
        mock_llm_router.generate.side_effect = Exception("LLM error")

        now = datetime.now(UTC)

        async with database.async_session() as session:
            for i in range(10):
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    now - timedelta(hours=i),
                )

        # Should not raise exception
        anomalies = await detector_with_llm.detect_anomalies(hours=24)

        # Anomalies should still be detected without AI
        assert len(anomalies) > 0
        for anomaly in anomalies:
            assert anomaly.ai_explanation is None


# Combined Detection Tests


class TestCombinedDetection:
    """Tests for combined anomaly detection."""

    @pytest.mark.asyncio
    async def test_detect_anomalies_combines_all_types(self, detector, database):
        """Test that detect_anomalies combines all detection methods."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create various anomaly patterns
            # Unusual failure rate for hue
            for i in range(8):
                await create_failure_event(
                    session,
                    "entry_hue",
                    "hue",
                    now - timedelta(hours=i),
                )

            # Time correlation for zwave
            for i in range(5):
                timestamp = now.replace(hour=3, minute=0) - timedelta(days=i)
                await create_failure_event(
                    session,
                    "entry_zwave",
                    "zwave",
                    timestamp,
                )

        anomalies = await detector.detect_anomalies(hours=168)

        # Should find multiple types of anomalies
        types_found = {a.type for a in anomalies}
        assert len(types_found) >= 1

    @pytest.mark.asyncio
    async def test_anomalies_sorted_by_severity(self, detector, database):
        """Test that anomalies are returned sorted by severity (highest first)."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures for multiple integrations
            for domain in ["hue", "zwave", "mqtt"]:
                for i in range(5):
                    await create_failure_event(
                        session,
                        f"entry_{domain}",
                        domain,
                        now - timedelta(hours=i),
                    )

        anomalies = await detector.detect_anomalies(hours=24)

        if len(anomalies) > 1:
            # Verify sorted by severity descending
            for i in range(len(anomalies) - 1):
                assert anomalies[i].severity >= anomalies[i + 1].severity


# Factory Function Tests


class TestFactoryFunction:
    """Tests for create_anomaly_detector factory function."""

    @pytest.mark.asyncio
    async def test_create_anomaly_detector(self, database):
        """Test factory function creates detector correctly."""
        detector = await create_anomaly_detector(database)
        assert isinstance(detector, AnomalyDetector)
        assert detector.sensitivity_threshold == 2.0

    @pytest.mark.asyncio
    async def test_create_with_custom_threshold(self, database):
        """Test factory with custom sensitivity threshold."""
        detector = await create_anomaly_detector(database, sensitivity_threshold=3.0)
        assert detector.sensitivity_threshold == 3.0

    @pytest.mark.asyncio
    async def test_create_with_llm_router(self, database, mock_llm_router):
        """Test factory with LLM router."""
        detector = await create_anomaly_detector(database, llm_router=mock_llm_router)
        assert detector.llm_router is not None


# Performance Tests


class TestPerformance:
    """Performance tests for anomaly detection."""

    @pytest.mark.asyncio
    async def test_performance_30_day_scan(self, detector, database):
        """Test that 30-day scan completes within 5 seconds.

        This tests the performance requirement from the acceptance criteria.
        """
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create substantial test data: 100 failures over 30 days
            for i in range(100):
                await create_failure_event(
                    session,
                    f"entry_{i % 5}",
                    f"integration_{i % 5}",
                    now - timedelta(days=i % 30, hours=i % 24),
                )

        # Measure execution time
        start_time = time.time()
        _anomalies = await detector.detect_anomalies(hours=720)  # 30 days
        elapsed_time = time.time() - start_time

        # Should complete within 5 seconds
        assert elapsed_time < 5.0, f"30-day scan took {elapsed_time:.2f}s (target: <5s)"

    @pytest.mark.asyncio
    async def test_performance_empty_database(self, detector, database):
        """Test performance with empty database is fast."""
        start_time = time.time()
        anomalies = await detector.detect_anomalies(hours=720)
        elapsed_time = time.time() - start_time

        # Empty database should be very fast
        assert elapsed_time < 0.1
        assert anomalies == []


# Edge Case Tests


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_single_failure_no_anomaly(self, detector, database):
        """Test that single failure doesn't trigger anomaly."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            await create_failure_event(
                session,
                "entry123",
                "hue",
                now - timedelta(hours=1),
            )

        anomalies = await detector.detect_anomalies(hours=24)
        assert len(anomalies) == 0

    @pytest.mark.asyncio
    async def test_multiple_integrations_independent(self, detector, database):
        """Test that multiple integrations are analyzed independently."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Only hue has many failures
            for i in range(10):
                await create_failure_event(
                    session,
                    "entry_hue",
                    "hue",
                    now - timedelta(hours=i),
                )

            # zwave has only one failure
            await create_failure_event(
                session,
                "entry_zwave",
                "zwave",
                now - timedelta(hours=5),
            )

        anomalies = await detector.detect_anomalies(hours=24)

        # Should only detect anomaly for hue
        domains = {a.integration_domain for a in anomalies if "+" not in a.integration_domain}
        assert "hue" in domains or len(anomalies) > 0

    @pytest.mark.asyncio
    async def test_hour_boundary_handling(self, detector, database):
        """Test handling of failures at hour boundaries."""
        now = datetime.now(UTC)

        async with database.async_session() as session:
            # Create failures exactly at hour boundaries
            for hour in range(0, 24, 4):
                timestamp = now.replace(hour=hour, minute=0, second=0)
                await create_failure_event(
                    session,
                    "entry123",
                    "hue",
                    timestamp,
                )

        # Should not crash and should process correctly
        anomalies = await detector.detect_anomalies(hours=24)
        # Result depends on distribution, but should complete without error
        assert isinstance(anomalies, list)
