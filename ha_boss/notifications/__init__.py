"""Notification system for alerts and escalations."""

from ha_boss.notifications.manager import (
    NotificationChannel,
    NotificationManager,
    create_notification_manager,
)
from ha_boss.notifications.templates import (
    NotificationContext,
    NotificationSeverity,
    NotificationType,
    TemplateRegistry,
)

__all__ = [
    # Manager
    "NotificationManager",
    "NotificationChannel",
    "create_notification_manager",
    # Templates
    "NotificationContext",
    "NotificationType",
    "NotificationSeverity",
    "TemplateRegistry",
]
