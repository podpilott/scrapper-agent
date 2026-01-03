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

    # Determine renderer based on format
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Processors that prepare event dict for stdlib
    structlog_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    # Configure structlog to use stdlib
    structlog.configure(
        processors=structlog_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Create formatter with our renderer
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Configure root logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Silence noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name for context.

    Returns:
        Configured logger instance.
    """
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()


# Auto-initialize logging on import
setup_logging()
