"""Bearer API-key authentication (single-tenant env key for Phase 1)."""

from __future__ import annotations

import hmac
import secrets

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


def _constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    """Require Authorization: Bearer <API_KEY>. Raises 401 on failure."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Authorization Bearer token required")

    token = credentials.credentials
    if not token or not _constant_time_equals(token, settings.api_key):
        raise UnauthorizedError("Invalid API key")

    # Bind a non-secret marker for logs (never the raw key)
    request.state.api_key_ok = True
    return "authenticated"


def generate_dev_api_key() -> str:
    """Utility for scripts; not used by the API at runtime."""
    return secrets.token_urlsafe(32)
