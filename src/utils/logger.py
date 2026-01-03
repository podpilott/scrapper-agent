"""Logging setup using structlog with level-based filtering."""

import logging
import sys

import structlog

from config.settings import settings

# Map string log levels to logging constants
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def setup_logging() -> None:
    """Configure structured logging with level-based filtering.

    Reads LOG_LEVEL and LOG_FORMAT from settings:
    - LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
    - LOG_FORMAT: console (colored dev output) or json (production) (default: console)
    """
    log_level = LOG_LEVEL_MAP.get(settings.log_level, logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    # Shared processors for all formats
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,  # Filter based on log level
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        # Production: JSON output for log aggregation (ELK, CloudWatch, etc.)
        processors = shared_processors + [
            structlog.processors.JSONRenderer()
        ]
        logger_factory = structlog.PrintLoggerFactory(file=sys.stderr)
    else:
        # Development: Colored console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
        logger_factory = structlog.PrintLoggerFactory(file=sys.stderr)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )

    # Set log level for common noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name for context.

    Returns:
        Configured logger instance.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return logger


# Auto-initialize logging on import
setup_logging()
