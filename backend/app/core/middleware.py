"""Request-ID middleware: correlation + request metrics."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.metrics import get_metrics
from app.core.telemetry import flush_telemetry, get_buffer

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            operation="http_request",
        )

        metrics = get_metrics()
        metrics.inc("http.requests_total")
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            status_code = getattr(response, "status_code", None)
            if response is not None:
                response.headers[REQUEST_ID_HEADER] = request_id
            if status_code is not None:
                if status_code >= 500:
                    metrics.inc("http.requests_5xx")
                    metrics.inc("http.requests_failed")
                elif status_code >= 400:
                    metrics.inc("http.requests_4xx")
                else:
                    metrics.inc("http.requests_success")
            metrics.observe("http.request", latency_ms)
            logger.info(
                "request_completed",
                endpoint=request.url.path,
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
                operation="http_request",
            )
            # Durable telemetry: one batched INSERT per request (off the event
            # loop). flush_telemetry() swallows DB errors and never raises.
            if len(get_buffer()) > 0:
                try:
                    await run_in_threadpool(flush_telemetry)
                except Exception as exc:  # noqa: BLE001 - never fail the request
                    logger.warning("telemetry_flush_error", error=str(exc)[:200])
