"""Redact secrets from structured log event dicts."""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "model_api_key",
    "bearer",
    "credentials",
    "private_key",
}


def _is_sensitive(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SENSITIVE_KEYS:
        return True
    return any(s in lowered for s in ("password", "secret", "token", "api_key"))


def redact_value(key: str, value: Any) -> Any:
    if _is_sensitive(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_event_dict(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor — strip secrets before JSON render."""
    return {k: redact_value(k, v) for k, v in event_dict.items()}
