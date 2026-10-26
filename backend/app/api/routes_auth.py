"""Console session authentication (v1.0).

The browser exchanges the operator API key once for a short-lived, signed,
HttpOnly session cookie. The key itself is never stored in the bundle or in
browser storage.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    SESSION_COOKIE_NAME,
    constant_time_equals,
    issue_session_token,
    resolve_auth,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SessionRequest(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=512)


class SessionResponse(BaseModel):
    authenticated: bool
    expires_at: str
    ttl_seconds: int


class AuthStateResponse(BaseModel):
    authenticated: bool
    method: str | None = None
    expires_at: str | None = None


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/session", response_model=SessionResponse)
def create_session(
    body: SessionRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    if not constant_time_equals(body.api_key, settings.api_key):
        logger.warning(
            "session_login_failed",
            client=request.client.host if request.client else None,
        )
        raise UnauthorizedError("Invalid API key")

    token, claims = issue_session_token(settings)
    ttl_seconds = claims.expires_at - claims.issued_at
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl_seconds,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    logger.info("session_login_succeeded", expires_at=_iso(claims.expires_at))
    return SessionResponse(
        authenticated=True,
        expires_at=_iso(claims.expires_at),
        ttl_seconds=ttl_seconds,
    )


@router.post("/logout", response_model=AuthStateResponse)
def logout(
    response: Response, settings: Settings = Depends(get_settings)
) -> AuthStateResponse:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return AuthStateResponse(authenticated=False, method=None, expires_at=None)


@router.get("/me", response_model=AuthStateResponse)
def me(request: Request, settings: Settings = Depends(get_settings)) -> AuthStateResponse:
    auth = resolve_auth(request, settings)
    if auth is None:
        return AuthStateResponse(authenticated=False)
    return AuthStateResponse(
        authenticated=True,
        method=auth.method,
        expires_at=_iso(auth.expires_at) if auth.expires_at else None,
    )
