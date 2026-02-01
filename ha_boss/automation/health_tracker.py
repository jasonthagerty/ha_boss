"""Automation health tracking for consecutive execution monitoring.

This module implements the AutomationHealthTracker service that tracks consecutive
successes and failures for automations to support validation gating in goal-oriented
healing. When an automation meets the consecutive success threshold, it becomes
"validated healthy" and eligible for reliability scoring.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ha_boss.core.database import AutomationHealthStatus, Database

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AutomationHealthTracker:
    """Track automation health via consecutive execution results.

    This tracker maintains per-automation counters for consecutive successes and
    failures, implementing validation gating for goal-oriented healing. When an
    automation achieves the configured threshold of consecutive successes, it is
    marked as "validated healthy" for reliability analysis.

    Attributes:
        database: Database instance for persistence
        consecutive_success_threshold: Number of consecutive successes required
                                       for validation gating
    """

    def __init__(
        self,
        database: Database,
        consecutive_success_threshold: int = 3,
    ) -> None:
        """Initialize AutomationHealthTracker.

        Args:
            database: Database instance for persistence
            consecutive_success_threshold: Number of consecutive successes required
                                           for validation (default: 3)

        Raises:
            ValueError: If consecutive_success_threshold < 1
        """
        if consecutive_success_threshold < 1:
            raise ValueError("consecutive_success_threshold must be >= 1")

        self.database = database
        self.consecutive_success_threshold = consecutive_success_threshold

        logger.info(
            f"Initialized AutomationHealthTracker with threshold={consecutive_success_threshold}"
        )

    async def record_execution_result(
        self,
        instance_id: str,
        automation_id: str,
        success: bool,
    ) -> AutomationHealthStatus:
        """Record execution result and update consecutive counts.

        This method updates the health status for an automation based on the
        execution result. Consecutive counters are incremented/reset appropriately,
        and validation gating is updated when thresholds are met.

        Logic:
        - If success:
          - Increment consecutive_successes, reset consecutive_failures
          - Increment total_successes and total_executions
          - If consecutive_successes >= threshold: mark is_validated_healthy=True
        - If failure:
          - Increment consecutive_failures, reset consecutive_successes
          - Increment total_failures and total_executions
          - Mark is_validated_healthy=False
        - Update updated_at timestamp

        Args:
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier (e.g., "automation.test")
            success: Whether the execution was successful

        Returns:
            Updated AutomationHealthStatus record

        Raises:
            ValueError: If instance_id or automation_id is empty
        """
        if not instance_id or not instance_id.strip():
            raise ValueError("instance_id cannot be empty")
        if not automation_id or not automation_id.strip():
            raise ValueError("automation_id cannot be empty")

        try:
            async with self.database.async_session() as session:
                # Get or create status record
                status = await self._get_or_create_status(session, instance_id, automation_id)

                # Update counters based on result
                if success:
                    status.consecutive_successes += 1
                    status.consecutive_failures = 0
                    status.total_successes += 1

                    # Check validation threshold
                    if status.consecutive_successes >= self.consecutive_success_threshold:
                        if not status.is_validated_healthy:
                            logger.info(
                                f"Automation {instance_id}:{automation_id} validated healthy "
                                f"({status.consecutive_successes} consecutive successes)"
                            )
                        status.is_validated_healthy = True
                        status.last_validation_at = datetime.now(UTC)
                else:
                    status.consecutive_failures += 1
                    status.consecutive_successes = 0
                    status.total_failures += 1

                    # Reset validation on any failure
                    if status.is_validated_healthy:
                        logger.info(
                            f"Automation {instance_id}:{automation_id} lost validated status "
                            f"(consecutive_failures={status.consecutive_failures})"
                        )
                    status.is_validated_healthy = False

                # Update totals and timestamp
                status.total_executions += 1
                status.updated_at = datetime.now(UTC)

                # Save and return
                await self._save_status(session, status)

                logger.debug(
                    f"Recorded {'success' if success else 'failure'} for "
                    f"{instance_id}:{automation_id} - "
                    f"consecutive_successes={status.consecutive_successes}, "
                    f"consecutive_failures={status.consecutive_failures}, "
                    f"validated={status.is_validated_healthy}"
                )

                return status
        except Exception as e:
            logger.error(
                f"Failed to record execution result for {instance_id}:{automation_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_reliability_score(
        self,
        instance_id: str,
        automation_id: str,
    ) -> float:
        """Calculate reliability score (0.0-1.0) for automation.

        The reliability score is calculated as total_successes / total_executions.
        This provides a simple percentage-based reliability metric.

        Args:
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier

        Returns:
            Reliability score from 0.0 (0%) to 1.0 (100%)
            Returns 0.0 if no executions or status not found

        Raises:
            ValueError: If instance_id or automation_id is empty
        """
        if not instance_id or not instance_id.strip():
            raise ValueError("instance_id cannot be empty")
        if not automation_id or not automation_id.strip():
            raise ValueError("automation_id cannot be empty")

        try:
            async with self.database.async_session() as session:
                status = await self._get_status(session, instance_id, automation_id)

                if not status or status.total_executions == 0:
                    return 0.0

                return status.total_successes / status.total_executions
        except Exception as e:
            logger.error(
                f"Failed to get reliability score for {instance_id}:{automation_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_health_status(
        self,
        instance_id: str,
        automation_id: str,
    ) -> AutomationHealthStatus | None:
        """Get current health status for automation.

        Args:
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier

        Returns:
            Current health status or None if not found

        Raises:
            ValueError: If instance_id or automation_id is empty
        """
        if not instance_id or not instance_id.strip():
            raise ValueError("instance_id cannot be empty")
        if not automation_id or not automation_id.strip():
            raise ValueError("automation_id cannot be empty")

        try:
            async with self.database.async_session() as session:
                return await self._get_status(session, instance_id, automation_id)
        except Exception as e:
            logger.error(
                f"Failed to get health status for {instance_id}:{automation_id}: {e}",
                exc_info=True,
            )
            raise

    async def reset_validation(
        self,
        instance_id: str,
        automation_id: str,
    ) -> None:
        """Reset validation status for automation.

        This method resets the validation status and consecutive counters,
        effectively requiring the automation to re-prove itself. This is
        useful for manual intervention or testing scenarios.

        Args:
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier

        Raises:
            ValueError: If instance_id or automation_id is empty
        """
        if not instance_id or not instance_id.strip():
            raise ValueError("instance_id cannot be empty")
        if not automation_id or not automation_id.strip():
            raise ValueError("automation_id cannot be empty")

        try:
            async with self.database.async_session() as session:
                status = await self._get_status(session, instance_id, automation_id)

                if status:
                    status.consecutive_successes = 0
                    status.consecutive_failures = 0
                    status.is_validated_healthy = False
                    status.last_validation_at = None
                    status.updated_at = datetime.now(UTC)

                    await self._save_status(session, status)

                    logger.info(
                        f"Reset validation for {instance_id}:{automation_id} "
                        f"(total_executions={status.total_executions} preserved)"
                    )
        except Exception as e:
            logger.error(
                f"Failed to reset validation for {instance_id}:{automation_id}: {e}",
                exc_info=True,
            )
            raise

    # Private helper methods

    async def _get_status(
        self,
        session: "AsyncSession",
        instance_id: str,
        automation_id: str,
    ) -> AutomationHealthStatus | None:
        """Get existing health status record.

        Args:
            session: Active database session
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier

        Returns:
            Existing status or None if not found
        """
        stmt = select(AutomationHealthStatus).where(
            AutomationHealthStatus.instance_id == instance_id,
            AutomationHealthStatus.automation_id == automation_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_status(
        self,
        session: "AsyncSession",
        instance_id: str,
        automation_id: str,
    ) -> AutomationHealthStatus:
        """Get existing or create new health status record.

        Handles concurrent requests by using session.flush() to detect unique
        constraint violations before commit. If another request creates the
        same record concurrently, we catch the IntegrityError and retry the get.

        Args:
            session: Active database session
            instance_id: Home Assistant instance identifier
            automation_id: Automation identifier

        Returns:
            Existing or newly created status record
        """
        status = await self._get_status(session, instance_id, automation_id)

        if not status:
            status = AutomationHealthStatus(
                instance_id=instance_id,
                automation_id=automation_id,
                consecutive_successes=0,
                consecutive_failures=0,
                is_validated_healthy=False,
                last_validation_at=None,
                total_executions=0,
                total_successes=0,
                total_failures=0,
                updated_at=datetime.now(UTC),
            )
            session.add(status)

            try:
                # Flush to detect unique constraint violations before commit
                await session.flush()
                logger.debug(f"Created new health status for {instance_id}:{automation_id}")
            except IntegrityError:
                # Another request created the same record concurrently
                # Rollback and retry the get operation
                await session.rollback()
                status = await self._get_status(session, instance_id, automation_id)
                if not status:
                    # This shouldn't happen, but handle gracefully
                    raise RuntimeError(
                        f"Failed to create or retrieve status for {instance_id}:{automation_id}"
                    ) from None
                logger.debug(
                    f"Concurrent creation detected for {instance_id}:{automation_id}, "
                    "using existing record"
                )

        return status

    async def _save_status(
        self,
        session: "AsyncSession",
        status: AutomationHealthStatus,
    ) -> None:
        """Save health status to database.

        Args:
            session: Active database session
            status: Status record to save
        """
        await session.commit()
        await session.refresh(status)
