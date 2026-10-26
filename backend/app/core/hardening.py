"""Request hardening: body size limit and security response headers."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from starlette.responses import JSONResponse

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
NO_STORE_PREFIX = "/api/v1"


def _too_large_body(scope: Scope, max_bytes: int) -> bytes:
    payload = {
        "error": {
            "code": "PAYLOAD_TOO_LARGE",
            "message": "Request body too large",
            "details": {"max_request_bytes": max_bytes},
        },
        "request_id": scope.get("state", {}).get("request_id"),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class _RequestGuard:
    """Per-request state shared by the receive and send wrappers."""

    __slots__ = ("seen", "over_budget", "override_started")

    def __init__(self) -> None:
        self.seen = 0
        self.over_budget = False
        self.override_started = False


class RequestHardeningMiddleware:
    """Reject oversized bodies (413) and attach security headers to every response.

    Bodies with a ``Content-Length`` over the limit are rejected before the
    application runs. Streamed/chunked bodies are counted as they arrive; once
    the budget is exceeded the stream is cut and whatever error response the
    application produces is replaced by the 413 envelope.
    """

    def __init__(self, app: ASGIApp, max_request_bytes: int = 1_048_576) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        guard = _RequestGuard()
        send = self._hardened_send(send, scope, path, guard)

        declared = self._declared_length(scope)
        if declared is not None and declared > self.max_request_bytes:
            response = JSONResponse(
                status_code=413, content=json.loads(_too_large_body(scope, self.max_request_bytes))
            )
            await response(scope, receive, send)
            return

        await self.app(scope, self._guarded_receive(receive, guard), send)

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value.decode("latin-1"))
                except ValueError:
                    return None
        return None

    def _guarded_receive(self, receive: Receive, guard: _RequestGuard) -> Receive:
        max_bytes = self.max_request_bytes

        async def wrapped() -> Message:
            message = await receive()
            if message.get("type") == "http.request":
                guard.seen += len(message.get("body", b""))
                if guard.seen > max_bytes:
                    guard.over_budget = True
                    # Stop feeding the application; it will fail to parse the
                    # body and the send wrapper swaps its error for a 413.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        return wrapped

    def _hardened_send(
        self, send: Send, scope: Scope, path: str, guard: _RequestGuard
    ) -> Send:
        max_bytes = self.max_request_bytes

        async def wrapped(message: Message) -> None:
            kind = message.get("type")
            if guard.over_budget:
                if kind == "http.response.start":
                    body = _too_large_body(scope, max_bytes)
                    guard.override_started = True
                    message = {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": _merge_headers(
                            [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("latin-1")),
                            ],
                            path,
                            _passthrough(message.get("headers", [])),
                        ),
                    }
                    await send(message)
                    await send({"type": "http.response.body", "body": body, "more_body": False})
                    return
                if kind == "http.response.body" and guard.override_started:
                    return  # already sent the replacement body
            if kind == "http.response.start":
                message["headers"] = _merge_headers(list(message.get("headers", [])), path, [])
            await send(message)

        return wrapped


_PASSTHROUGH = {b"x-request-id", b"access-control-allow-origin", b"access-control-allow-credentials"}


def _passthrough(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    return [(n, v) for n, v in headers if n.lower() in _PASSTHROUGH]


def _merge_headers(
    headers: list[tuple[bytes, bytes]], path: str, extra: list[tuple[bytes, bytes]]
) -> list[tuple[bytes, bytes]]:
    headers = headers + extra
    present = {name.lower() for name, _ in headers}
    for name, value in SECURITY_HEADERS.items():
        if name.encode("latin-1") not in present:
            headers.append((name.encode("latin-1"), value.encode("latin-1")))
    if path.startswith(NO_STORE_PREFIX) and b"cache-control" not in present:
        headers.append((b"cache-control", b"no-store"))
    return headers
