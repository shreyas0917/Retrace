"""Structured logging for Retrace. Never log secrets or Authorization headers."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

from app.core.redaction import redact_event_dict


def configure_logging(log_level: str = "INFO", service: str = "retrace-backend") -> None:
    """Configure structlog + stdlib logging once at process start."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    environment = os.environ.get("ENVIRONMENT", "development")

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_service(service, environment),
            redact_event_dict,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_service(service: str, environment: str):
    def processor(
        logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("environment", environment)
        return event_dict

    return processor


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_correlation(**kwargs: Any) -> None:
    """Bind correlation fields into structlog contextvars (non-secret only)."""
    clean = {k: v for k, v in kwargs.items() if v is not None}
    if clean:
        structlog.contextvars.bind_contextvars(**clean)
