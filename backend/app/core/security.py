"""Authentication for the API.

Two credentials are accepted, and both resolve to the same single-tenant
operator identity:

* ``Authorization: Bearer <API_KEY>`` for the CLI, scripts and tests.
* A ``retrace_session`` cookie issued by ``POST /api/v1/auth/session`` for
  the browser console. The cookie carries a stateless, HMAC-SHA256-signed,
  short-lived token so the API key itself never reaches the browser bundle.

Cookie-authenticated state-changing requests must also carry
``X-Requested-With: retrace-console`` (CSRF guard).
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError

SESSION_COOKIE_NAME = "retrace_session"
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "retrace-console"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_bearer = HTTPBearer(auto_error=False)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _now() -> int:
    """Current unix time (seconds). Patched in tests to simulate expiry."""
    return int(time.time())


# --------------------------------------------------------------------------- #
# Session tokens
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SessionClaims:
    issued_at: int
    expires_at: int
    nonce: str


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()


def issue_session_token(settings: Settings, *, now: int | None = None) -> tuple[str, SessionClaims]:
    """Create a signed token valid for ``settings.session_ttl_minutes``."""
    issued = _now() if now is None else now
    claims = SessionClaims(
        issued_at=issued,
        expires_at=issued + max(1, settings.session_ttl_minutes) * 60,
        nonce=secrets.token_hex(16),
    )
    payload = json.dumps(
        {"iat": claims.issued_at, "exp": claims.expires_at, "nonce": claims.nonce},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = _sign(payload, settings.effective_session_secret)
    return f"{encoded}.{signature}", claims


def verify_session_token(token: str | None, settings: Settings) -> SessionClaims | None:
    """Return the claims for a valid, unexpired token; ``None`` otherwise."""
    if not token or token.count(".") != 1:
        return None
    encoded, signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded)
    except (ValueError, TypeError):
        return None
    expected = _sign(payload, settings.effective_session_secret)
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
        claims = SessionClaims(
            issued_at=int(data["iat"]),
            expires_at=int(data["exp"]),
            nonce=str(data["nonce"]),
        )
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    if claims.expires_at <= _now():
        return None
    return claims


# --------------------------------------------------------------------------- #
# Request authentication
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuthContext:
    method: str  # "bearer" | "session"
    expires_at: int | None = None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def resolve_auth(request: Request, settings: Settings) -> AuthContext | None:
    """Identify the caller without raising. Bearer wins over the cookie."""
    token = _bearer_token(request)
    if token is not None:
        if constant_time_equals(token, settings.api_key):
            return AuthContext(method="bearer")
        return None
    claims = verify_session_token(request.cookies.get(SESSION_COOKIE_NAME), settings)
    if claims is not None:
        return AuthContext(method="session", expires_at=claims.expires_at)
    return None


def _enforce_csrf(request: Request) -> None:
    if request.method.upper() in SAFE_METHODS:
        return
    header = request.headers.get(CSRF_HEADER_NAME, "")
    if header != CSRF_HEADER_VALUE:
        raise ForbiddenError(
            "Cookie-authenticated requests must send X-Requested-With: retrace-console",
            code="CSRF_REJECTED",
        )


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    """Require a Bearer API key or a valid session cookie. Raises 401/403."""
    if credentials is not None and credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Authorization Bearer token required")

    auth = resolve_auth(request, settings)
    if auth is None:
        if request.headers.get("authorization"):
            raise UnauthorizedError("Invalid API key")
        raise UnauthorizedError("Authorization Bearer token or session cookie required")

    if auth.method == "session":
        _enforce_csrf(request)

    # Bind non-secret markers for logs (never the raw key or token)
    request.state.api_key_ok = True
    request.state.auth_method = auth.method
    request.state.auth_expires_at = auth.expires_at
    return "authenticated"


# Backwards-compatible name used by all routers.
require_api_key = require_auth


def generate_dev_api_key() -> str:
    """Utility for scripts; not used by the API at runtime."""
    return secrets.token_urlsafe(32)
