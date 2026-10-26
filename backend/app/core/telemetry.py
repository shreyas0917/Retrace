"""Durable telemetry store (v1.0).

Design
------
`MetricsRegistry.inc()` / `.observe()` keep working as the fast in-process
view, but every event is *also* appended to a thread-safe `TelemetryBuffer`.
The buffer is flushed to Postgres (`metric_events` table, one row per event)
at the end of each HTTP request by `RequestIdMiddleware`, from the FastAPI
lifespan shutdown, and by CLI/eval paths through `flush_telemetry()`.

A flush is a single batched INSERT. DB errors are swallowed and logged: the
telemetry pipeline must never fail or slow down a request path materially.
Events that could not be written are re-queued (bounded) so a transient
outage does not lose them.

`durable_snapshot(db, window_minutes)` aggregates the events in SQL
(SUM for counters, percentile_cont for latencies) and returns the same
`counters` / `latencies` / `derived` shape as the in-memory snapshot so
signal evaluation can run on either source. Cost is stored as the integer
counter `generation.cost_usd_micros` (micro-dollars) so cost is additive
across windows and processes; the snapshot exposes it as `cost.usd`.

Set TELEMETRY_DURABLE=false to disable all DB writes (the buffer stays empty).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable

import structlog
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_BUFFERED_EVENTS = 20_000
MAX_WINDOW_MINUTES = 43_200  # 30 days
DEFAULT_WINDOW_MINUTES = 1_440  # 24 hours

KIND_COUNTER = "counter"
KIND_LATENCY = "latency"

TOKEN_COUNTERS = {
    "prompt": "generation.prompt_tokens",
    "completion": "generation.completion_tokens",
    "total": "generation.tokens_total",
}
COST_COUNTER = "generation.cost_usd_micros"

# Lazily resolved: None → ask Settings; True/False → explicit override (tests).
_enabled_override: bool | None = None
_enabled_cached: bool | None = None


def set_telemetry_enabled(value: bool | None) -> None:
    """Override (True/False) or clear (None) the TELEMETRY_DURABLE setting."""
    global _enabled_override, _enabled_cached
    _enabled_override = value
    _enabled_cached = None


def telemetry_enabled() -> bool:
    global _enabled_cached
    if _enabled_override is not None:
        return _enabled_override
    if _enabled_cached is None:
        try:
            from app.core.config import get_settings

            _enabled_cached = bool(get_settings().telemetry_durable)
        except Exception:  # noqa: BLE001 - settings missing in odd contexts
            _enabled_cached = False
    return _enabled_cached


def _current_request_id() -> str | None:
    try:
        ctx = structlog.contextvars.get_contextvars()
    except Exception:  # noqa: BLE001
        return None
    rid = ctx.get("request_id")
    return str(rid) if rid else None


class TelemetryBuffer:
    """Thread-safe bounded buffer of metric events awaiting a DB flush."""

    def __init__(self, max_events: int = MAX_BUFFERED_EVENTS) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque()
        self._max = max_events
        self.dropped = 0
        self.flushed = 0
        self.flush_errors = 0
        self.last_error: str | None = None

    def append(
        self,
        kind: str,
        name: str,
        value: float,
        *,
        labels: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        if not telemetry_enabled():
            return
        row = {
            "kind": kind,
            "name": name,
            "value": float(value),
            "labels": labels,
            "request_id": request_id if request_id is not None else _current_request_id(),
        }
        with self._lock:
            if len(self._events) >= self._max:
                self._events.popleft()
                self.dropped += 1
            self._events.append(row)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._events)
            self._events.clear()
        return rows

    def requeue(self, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            for row in reversed(rows):
                if len(self._events) >= self._max:
                    self.dropped += 1
                    break
                self._events.appendleft(row)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def flush(self, session_factory: Callable[[], Session] | None = None) -> int:
        """Bulk-insert buffered rows. Returns rows written; never raises."""
        rows = self.drain()
        if not rows:
            return 0
        if not telemetry_enabled():
            return 0
        try:
            factory = session_factory or _default_session_factory()
            from app.db.models import MetricEvent

            session = factory()
            try:
                session.execute(insert(MetricEvent), rows)
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - telemetry must never fail callers
            self.flush_errors += 1
            self.last_error = str(exc)[:300]
            self.requeue(rows)
            logger.warning(
                "telemetry_flush_failed",
                error=str(exc)[:300],
                pending=len(self),
                operation="telemetry",
            )
            return 0
        self.flushed += len(rows)
        return len(rows)


def _default_session_factory() -> Callable[[], Session]:
    from app.db import session as db_session

    if db_session.SessionLocal is None:
        db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal


_BUFFER = TelemetryBuffer()


def get_buffer() -> TelemetryBuffer:
    return _BUFFER


def record_event(
    kind: str,
    name: str,
    value: float,
    *,
    labels: dict[str, Any] | None = None,
) -> None:
    """Hook called by MetricsRegistry for every inc/observe."""
    _BUFFER.append(kind, name, value, labels=labels)


def flush_telemetry(session_factory: Callable[[], Session] | None = None) -> int:
    """Flush pending events to Postgres. Safe to call from CLI/eval paths."""
    return _BUFFER.flush(session_factory)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

_DERIVED_RATES: dict[str, tuple[str, str]] = {
    "request_error_rate": ("http.requests_5xx", "http.requests_total"),
    "retrieval_empty_rate": ("retrieval.empty", "retrieval.attempts"),
    "generation_timeout_rate": ("generation.timeout", "generation.attempts"),
    "judge_timeout_rate": ("judge.timeout", "judge.attempts"),
    "judge_malformed_rate": ("judge.malformed", "judge.attempts"),
    "retrieval_miss_rate": ("diagnosis.code.RETRIEVAL_MISS", "diagnosis.total"),
}


def derived_rates(counters: dict[str, float]) -> dict[str, float | None]:
    """Same derived-rate keys as MetricsRegistry.snapshot()['derived']."""
    out: dict[str, float | None] = {}
    for key, (num, den) in _DERIVED_RATES.items():
        d = counters.get(den, 0) or 0
        out[key] = None if d <= 0 else round((counters.get(num, 0) or 0) / d, 6)
    return out


def clamp_window(window_minutes: int | None) -> int:
    if window_minutes is None:
        return DEFAULT_WINDOW_MINUTES
    return max(1, min(int(window_minutes), MAX_WINDOW_MINUTES))


_COUNTER_SQL = text(
    """
    SELECT name, SUM(value) AS total
    FROM metric_events
    WHERE kind = 'counter' AND ts >= now() - make_interval(mins => :mins)
    GROUP BY name
    """
)

_LATENCY_SQL = text(
    """
    SELECT name,
           COUNT(*) AS n,
           AVG(value) AS avg_ms,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY value) AS p99,
           MAX(value) AS max_ms
    FROM metric_events
    WHERE kind = 'latency' AND ts >= now() - make_interval(mins => :mins)
    GROUP BY name
    """
)

_META_SQL = text(
    """
    SELECT COUNT(*) AS n, MIN(ts) AS oldest, MAX(ts) AS newest
    FROM metric_events
    WHERE ts >= now() - make_interval(mins => :mins)
    """
)


def _r(v: Any) -> float | None:
    return None if v is None else round(float(v), 2)


def durable_snapshot(db: Session, window_minutes: int | None = None) -> dict[str, Any]:
    """Aggregate metric_events over the trailing window. Raises on DB error."""
    mins = clamp_window(window_minutes)
    counters: dict[str, float] = {}
    for name, total in db.execute(_COUNTER_SQL, {"mins": mins}):
        total_f = float(total or 0)
        counters[name] = int(total_f) if total_f.is_integer() else total_f

    latencies: dict[str, Any] = {}
    for name, n, avg_ms, p50, p95, p99, max_ms in db.execute(
        _LATENCY_SQL, {"mins": mins}
    ):
        latencies[name] = {
            "count": int(n),
            "avg_ms": _r(avg_ms),
            "p50_ms": _r(p50),
            "p95_ms": _r(p95),
            "p99_ms": _r(p99),
            "max_ms": _r(max_ms),
        }

    meta = db.execute(_META_SQL, {"mins": mins}).one()
    oldest: datetime | None = meta[1]
    newest: datetime | None = meta[2]

    cost_micros = float(counters.get(COST_COUNTER, 0) or 0)
    return {
        "available": True,
        "durable": True,
        "source": "postgres",
        "window_minutes": mins,
        "generated_at": time.time(),
        "event_count": int(meta[0] or 0),
        "oldest_event_ts": oldest.isoformat() if oldest else None,
        "newest_event_ts": newest.isoformat() if newest else None,
        "counters": counters,
        "latencies": latencies,
        "derived": derived_rates(counters),
        "tokens": {
            key: int(counters.get(counter, 0) or 0)
            for key, counter in TOKEN_COUNTERS.items()
        },
        "cost": {
            "usd": round(cost_micros / 1_000_000, 6),
            "counter": COST_COUNTER,
            "unit": "USD (summed from integer micro-dollar counter)",
        },
    }


def try_durable_snapshot(
    window_minutes: int | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    """durable_snapshot() that never raises: returns {available: False, reason}."""
    mins = clamp_window(window_minutes)
    if not telemetry_enabled():
        return {
            "available": False,
            "durable": False,
            "source": "postgres",
            "window_minutes": mins,
            "reason": "telemetry_disabled (TELEMETRY_DURABLE=false)",
        }
    try:
        factory = session_factory or _default_session_factory()
        session = factory()
        try:
            return durable_snapshot(session, mins)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "durable_snapshot_failed", error=str(exc)[:300], operation="telemetry"
        )
        return {
            "available": False,
            "durable": False,
            "source": "postgres",
            "window_minutes": mins,
            "reason": f"db_error: {str(exc)[:200]}",
        }


def durable_window_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compact view for /api/v1/ops/summary."""
    if not snapshot.get("available"):
        return {
            "available": False,
            "reason": snapshot.get("reason"),
            "window_minutes": snapshot.get("window_minutes"),
        }
    http = (snapshot.get("latencies") or {}).get("http.request") or {}
    derived = snapshot.get("derived") or {}
    counters = snapshot.get("counters") or {}
    return {
        "available": True,
        "source": snapshot.get("source"),
        "window_minutes": snapshot.get("window_minutes"),
        "event_count": snapshot.get("event_count"),
        "http_latency": {
            "count": http.get("count", 0),
            "p50_ms": http.get("p50_ms"),
            "p95_ms": http.get("p95_ms"),
            "p99_ms": http.get("p99_ms"),
            "max_ms": http.get("max_ms"),
        },
        "requests_total": int(counters.get("http.requests_total", 0) or 0),
        "requests_5xx": int(counters.get("http.requests_5xx", 0) or 0),
        "request_error_rate": derived.get("request_error_rate"),
        "generation_attempts": int(counters.get("generation.attempts", 0) or 0),
        "generation_timeout_rate": derived.get("generation_timeout_rate"),
        "llm_retries": int(counters.get("llm.retries", 0) or 0),
        "llm_failures": int(counters.get("llm.failures", 0) or 0),
        "tokens": snapshot.get("tokens"),
        "cost_usd": (snapshot.get("cost") or {}).get("usd"),
    }
