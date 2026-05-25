"""
logger.py — Structured logging configuration for the OCP monitoring agent.

Uses structlog for consistent, machine-parseable JSON logs in production
and a pretty console renderer for local development.

All modules should import get_logger from here:

    from agent.logger import get_logger
    log = get_logger(__name__)
    log.info("cycle_started", cluster=cfg.cluster_name, timestamp=ts)
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache

import structlog


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure structlog + stdlib logging.

    Call this ONCE at application startup (in scheduler.py or main entry point).

    Args:
        log_level:  One of DEBUG / INFO / WARNING / ERROR / CRITICAL
        log_format: 'json' for structured JSON output (production / log aggregators)
                    'console' for human-readable coloured output (local dev)
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # ── Shared processors (run on every log event) ──────────────────────────
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,          # thread-local context
        structlog.stdlib.add_logger_name,                 # adds 'logger' key
        structlog.stdlib.add_log_level,                   # adds 'level' key
        structlog.processors.TimeStamper(fmt="iso"),      # ISO-8601 timestamp
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,             # pretty exception info
    ]

    if log_format == "json":
        # Production: one JSON object per line — ingest into ELK/Splunk/CloudWatch
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: coloured, human-readable output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    # Silence noisy third-party loggers
    for noisy in ("kubernetes", "urllib3", "httpx", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@lru_cache(maxsize=None)
def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a module-level structlog logger.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        A structlog BoundLogger. Use keyword arguments for structured context:
            log.info("node_collected", node_name="worker-01", status="Ready")
            log.error("tool_failed", tool="get_etcd_health", error=str(e))
    """
    return structlog.get_logger(name)
