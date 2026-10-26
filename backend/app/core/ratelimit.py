"""In-memory sliding-window rate limiting (single process).

Keyed by the hashed credential (API key or session cookie) when present,
otherwise by client IP. Documented limitation: state lives in this process
and resets on restart; a multi-replica deployment needs a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from hashlib import sha256
from typing import Any, Awaitable, Callable, MutableMapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logging import get_logger
from app.core.security import SESSION_COOKIE_NAME

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

logger = get_logger(__name__)

WINDOW_SECONDS = 60
AUTH_SESSION_PATH = "/api/v1/auth/session"
_EXEMPT_API_PATHS = frozenset({"/api/v1/health", "/api/v1/ready", "/api/v1/metrics"})
_EXEMPT_GET_PREFIXES = ("/api/v1/runbooks",)


class RateLimiter:
    """Thread-safe sliding window counter per key."""

    def __init__(
        self, per_minute: int = 120, auth_per_minute: int = 10, enabled: bool = True
    ) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self.per_minute = per_minute
        self.auth_per_minute = auth_per_minute
        self.enabled = enabled

    def configure(
        self,
        *,
        per_minute: int | None = None,
        auth_per_minute: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        with self._lock:
            if per_minute is not None:
                self.per_minute = per_minute
            if auth_per_minute is not None:
                self.auth_per_minute = auth_per_minute
            if enabled is not None:
                self.enabled = enabled

    def reset(self) -> None:
        """Test hook: forget all recorded hits."""
        with self._lock:
            self._hits.clear()

    def check(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """Record a hit for ``key``. Returns ``(allowed, retry_after_seconds)``."""
        if limit <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        cutoff = now - WINDOW_SECONDS
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + WINDOW_SECONDS - now) + 1)
                return False, retry_after
            bucket.append(now)
            if len(self._hits) > 10_000:
                self._evict_stale(cutoff)
        return True, 0

    def _evict_stale(self, cutoff: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or b[-1] <= cutoff]
        for k in stale:
            del self._hits[k]


_LIMITER = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _LIMITER


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


def client_key(request: Request) -> str:
    """Stable, non-secret bucket key for the caller."""
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return "key:" + _hash(token.strip())
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        return "session:" + _hash(cookie)
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return "ip:" + first
    host = request.client.host if request.client else "unknown"
    return "ip:" + host


def is_exempt(path: str, method: str) -> bool:
    if not path.startswith("/api/v1"):
        return True
    if path in _EXEMPT_API_PATHS:
        return True
    if method in {"GET", "HEAD"} and path.startswith(_EXEMPT_GET_PREFIXES):
        return True
    return False


class RateLimitMiddleware:
    """Pure ASGI middleware: 429 + Retry-After when a key exceeds its budget."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter | None = None) -> None:
        self.app = app
        self.limiter = limiter or get_rate_limiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.limiter.enabled:
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS" or is_exempt(path, method):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        key = client_key(request)
        if path == AUTH_SESSION_PATH:
            limit = self.limiter.auth_per_minute
            key = "auth:" + key
        else:
            limit = self.limiter.per_minute
        allowed, retry_after = self.limiter.check(key, limit)
        if allowed:
            await self.app(scope, receive, send)
            return

        request_id = scope.get("state", {}).get("request_id")
        logger.warning(
            "rate_limited",
            endpoint=path,
            method=method,
            key_kind=key.split(":", 1)[0],
            retry_after_seconds=retry_after,
        )
        response = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many requests",
                    "details": {
                        "retry_after_seconds": retry_after,
                        "limit_per_minute": limit,
                    },
                },
                "request_id": request_id,
            },
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
