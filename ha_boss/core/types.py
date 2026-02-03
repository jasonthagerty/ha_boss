"""Shared type definitions for HA Boss.

This module contains common data types used across multiple components
to avoid circular dependencies.
"""

from datetime import datetime
from typing import Any


class HealthIssue:
    """Represents a detected health issue with an entity.

    Args:
        entity_id: The entity that has the issue
        issue_type: Type of issue (e.g., "unavailable", "stale", "unknown")
        detected_at: When the issue was first detected
        details: Optional additional context about the issue
    """

    def __init__(
        self,
        entity_id: str,
        issue_type: str,
        detected_at: datetime,
        details: dict[str, Any] | None = None,
    ):
        self.entity_id = entity_id
        self.issue_type = issue_type
        self.detected_at = detected_at
        self.details = details or {}

    def __repr__(self) -> str:
        return (
            f"HealthIssue(entity_id={self.entity_id!r}, "
            f"issue_type={self.issue_type!r}, "
            f"detected_at={self.detected_at!r})"
        )
