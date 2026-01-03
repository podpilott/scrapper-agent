"""Logging setup using structlog."""

import sys
from pathlib import Path

import structlog


def setup_logging(log_dir: Path | None = None, run_id: str | None = None) -> None:
    """Configure structured logging.

    Args:
        log_dir: Directory for log files. If None, logs only to console.
        run_id: Unique run identifier for log file naming.
    """
    processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add console renderer for development
    processors.append(
        structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name for context.

    Returns:
        Configured logger instance.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(component=name)
    return logger
