from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO", log_format: str = "console") -> None:
    """
    Configure structlog for the entire application.

    Args:
        log_level: Minimum log level — DEBUG, INFO, WARNING, ERROR, CRITICAL.
        log_format: Output format — 'console' for development, 'json' for production.
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_logger_name,
    ]

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Gunakan stdlib BoundLogger
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    for noisy in ("httpx", "telegram", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
