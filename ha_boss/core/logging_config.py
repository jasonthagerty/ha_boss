"""Logging configuration for HA Boss."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ha_boss.core.config import Config


def setup_logging(config: Config) -> None:
    """Configure Python logging based on HA Boss configuration.

    Args:
        config: HA Boss configuration with logging settings
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.logging.level))

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Console handler (always enabled for Docker/foreground mode)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.logging.level))

    # Format based on config
    if config.logging.format == "json":
        # JSON format for structured logging
        formatter = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        # Text format (default)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional, if log file path is accessible)
    if config.logging.file:
        try:
            # Create log directory if needed
            log_file = Path(config.logging.file)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            # Rotating file handler
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=config.logging.max_size_mb * 1024 * 1024,
                backupCount=config.logging.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, config.logging.level))
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

            root_logger.debug(f"File logging enabled: {log_file}")

        except Exception as e:
            # If file logging fails, just log to console
            root_logger.warning(f"Failed to setup file logging: {e}")
            root_logger.info("Continuing with console-only logging")

    root_logger.info(
        f"Logging configured: level={config.logging.level}, "
        f"format={config.logging.format}, "
        f"handlers={len(root_logger.handlers)}"
    )

