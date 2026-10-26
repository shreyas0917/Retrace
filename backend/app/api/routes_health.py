"""Health, readiness, metrics, and operational signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.metrics import get_metrics
from app.core.security import require_api_key
from app.core.signals import evaluate_signals, load_observability_config
from app.core.telemetry import (
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
    durable_window_summary,
    try_durable_snapshot,
)
from app.db.session import check_database_connection
from app.schemas.common import DependencyStatus, HealthResponse, StatusResponse
from app.services.chroma import check_chroma_connection

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

WindowParam = Query(
    default=DEFAULT_WINDOW_MINUTES,
    ge=1,
    le=MAX_WINDOW_MINUTES,
    description="Trailing window for the durable (Postgres) aggregates, in minutes.",
)


def _dependency_status(settings: Settings) -> tuple[str, DependencyStatus]:
    details: dict[str, object] = {}
    pg_status: str = "ok"
    chroma_status: str = "ok"

    try:
        check_database_connection()
    except Exception as exc:  # noqa: BLE001
        pg_status = "error"
        details["postgres_error"] = str(exc)
        logger.error("postgres_check_failed", error=str(exc), operation="health")

    try:
        check_chroma_connection(settings)
    except Exception as exc:  # noqa: BLE001
        chroma_status = "error"
        details["chroma_error"] = str(exc)
        logger.error("chroma_check_failed", error=str(exc), operation="health")

    overall = "ok" if pg_status == "ok" and chroma_status == "ok" else "degraded"
    deps = DependencyStatus(
        postgres=pg_status,  # type: ignore[arg-type]
        chroma=chroma_status,  # type: ignore[arg-type]
        embedding_model=settings.embedding_model,
        details=details,
    )
    return overall, deps


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse)
def health_live() -> HealthResponse:
    """Liveness — process is up. No dependency checks."""
    return HealthResponse(status="ok")


@router.get("/health/ready")
@router.get("/api/v1/ready")
def health_ready(settings: Settings = Depends(get_settings)) -> dict:
    """Readiness — Postgres + Chroma available (no auth for probes)."""
    overall, deps = _dependency_status(settings)
    ready = overall == "ok"
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "service": "retrace-backend",
        "dependencies": deps.model_dump(),
    }


@router.get(
    "/api/v1/status",
    response_model=StatusResponse,
    dependencies=[Depends(require_api_key)],
)
def api_v1_status(settings: Settings = Depends(get_settings)) -> StatusResponse:
    """Authenticated readiness summary (legacy Phase 1 contract)."""
    overall, deps = _dependency_status(settings)
    return StatusResponse(
        status=overall,  # type: ignore[arg-type]
        dependencies=deps,
    )


@router.get("/metrics")
@router.get("/api/v1/metrics")
def metrics_endpoint(window_minutes: int = WindowParam) -> dict:
    """In-memory snapshot (`durable: false`, per process) plus the Postgres-backed
    aggregate under `durable_store` (window via ?window_minutes=, default 24h).

    `durable_store` is {"available": false, "reason": ...} when TELEMETRY_DURABLE
    is off or the database is unreachable.
    """
    snap = get_metrics().snapshot()
    snap["durable_store"] = try_durable_snapshot(window_minutes)
    return snap


@router.get("/api/v1/metrics/durable")
def metrics_durable_endpoint(window_minutes: int = WindowParam) -> dict:
    """Just the durable (Postgres) aggregate: counters, p50/p95/p99, tokens, cost."""
    return try_durable_snapshot(window_minutes)


@router.get("/api/v1/signals")
def signals_endpoint(
    source: str = Query(default="memory", pattern="^(memory|durable)$"),
    window_minutes: int = WindowParam,
) -> dict:
    """Operational alert signals vs configured thresholds.

    ?source=durable evaluates the Postgres window (falls back to in-memory when
    unavailable); the response reports `metrics_source`.
    """
    return evaluate_signals(source=source, window_minutes=window_minutes)


@router.get("/api/v1/ops/summary")
def ops_summary(
    settings: Settings = Depends(get_settings),
    window_minutes: int = WindowParam,
) -> dict:
    """Compact ops view: readiness + top counters + alert signals.

    `metrics.durable` stays the in-memory snapshot flag (false). The Postgres
    view is reported via `metrics.durable_available` + `metrics.durable_window`.
    """
    overall, deps = _dependency_status(settings)
    snap = get_metrics().snapshot()
    signals = evaluate_signals(snap)
    cfg = load_observability_config()
    durable = try_durable_snapshot(window_minutes)
    return {
        "ready": overall == "ok",
        "readiness_status": overall,
        "dependencies": deps.model_dump(),
        "metrics": {
            "uptime_seconds": snap["uptime_seconds"],
            "durable": False,
            "source": "in-memory",
            "durable_available": bool(durable.get("available")),
            "durable_window": durable_window_summary(durable),
            "derived": snap["derived"],
            "http_latency": (snap.get("latencies") or {}).get("http.request"),
            "counters_sample": {
                k: snap["counters"].get(k, 0)
                for k in (
                    "http.requests_total",
                    "http.requests_5xx",
                    "retrieval.attempts",
                    "retrieval.empty",
                    "generation.timeout",
                    "judge.malformed",
                    "diagnosis.total",
                    "llm.retries",
                    "llm.failures",
                )
            },
        },
        "signals": signals,
        "config_version": cfg.get("version"),
        "runbooks_dir": "docs/runbooks",
    }
