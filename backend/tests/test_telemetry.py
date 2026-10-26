"""v1.0 — durable telemetry (Postgres metric_events), cost accounting, endpoints."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core import telemetry
from app.core.metrics import MetricsRegistry, get_metrics
from app.core.signals import evaluate_signals
from app.core.telemetry import (
    durable_snapshot,
    flush_telemetry,
    get_buffer,
    set_telemetry_enabled,
    try_durable_snapshot,
)
from app.db import session as db_session
from app.db.models import ExecutionTrace, MetricEvent
from app.services import pricing
from app.services.llm_client import LLMResult, set_llm_provider


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture(autouse=True)
def _telemetry_on():
    set_telemetry_enabled(True)
    yield
    set_telemetry_enabled(None)
    set_llm_provider(None)
    pricing.reset_pricing_cache()


class FakeLLM:
    def __init__(self, answer: str = "Full-time employees accrue 1.25 days of PTO per month.") -> None:
        self.answer = answer
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], *, model: str, timeout: float) -> LLMResult:
        self.calls += 1
        return LLMResult(
            content=self.answer,
            model=model,
            latency_ms=12.5,
            prompt_tokens=40,
            completion_tokens=18,
            total_tokens=58,
        )


def _ingest_corpus(client: TestClient, api_key: str) -> str:
    corpus_id = f"tel_{uuid.uuid4().hex[:8]}"
    headers = _auth(api_key)
    client.post("/api/v1/corpora", headers=headers, json={"id": corpus_id, "title": "Telemetry"})
    docs = [
        {
            "id": "pto_doc",
            "text": (
                "Full-time employees accrue 1.25 days of PTO per month. "
                "Unused PTO may be carried over up to 5 days."
            ),
            "source_name": "pto.md",
        }
    ]
    r = client.post(
        f"/api/v1/corpora/{corpus_id}/versions", headers=headers, json={"documents": docs}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Buffer + flush
# ---------------------------------------------------------------------------


def test_registry_events_are_flushed_to_postgres() -> None:
    uid = uuid.uuid4().hex[:8]
    counter = f"test.counter.{uid}"
    latency = f"test.latency.{uid}"
    m = get_metrics()
    m.inc(counter, 3)
    m.inc(counter)
    m.observe(latency, 12.5)

    written = flush_telemetry()
    assert written >= 3
    assert len(get_buffer()) == 0

    db = _open_db()
    try:
        rows = db.execute(
            select(MetricEvent).where(MetricEvent.name.in_([counter, latency]))
        ).scalars().all()
    finally:
        db.close()
    kinds = {(r.name, r.kind, r.value) for r in rows}
    assert (counter, "counter", 3.0) in kinds
    assert (counter, "counter", 1.0) in kinds
    assert (latency, "latency", 12.5) in kinds
    assert all(r.ts is not None for r in rows)


def test_durable_snapshot_survives_registry_restart() -> None:
    """Simulate a process restart: a fresh registry has nothing, Postgres has it all."""
    uid = uuid.uuid4().hex[:8]
    counter = f"restart.counter.{uid}"
    latency = f"restart.latency.{uid}"

    before_restart = MetricsRegistry()
    before_restart.inc(counter, 5)
    for ms in (10, 20, 30):
        before_restart.observe(latency, ms)
    assert flush_telemetry() >= 4

    after_restart = MetricsRegistry()  # brand-new process view
    assert after_restart.get_counter(counter) == 0
    assert counter not in after_restart.snapshot()["counters"]

    db = _open_db()
    try:
        snap = durable_snapshot(db, window_minutes=60)
    finally:
        db.close()
    assert snap["durable"] is True
    assert snap["source"] == "postgres"
    assert snap["window_minutes"] == 60
    assert snap["counters"][counter] == 5
    lat = snap["latencies"][latency]
    assert lat["count"] == 3
    assert lat["avg_ms"] == 20.0
    assert lat["p50_ms"] == 20.0
    assert lat["max_ms"] == 30.0
    # Same derived keys as the in-memory snapshot
    assert set(snap["derived"]) == set(after_restart.snapshot()["derived"])


def test_durable_percentiles_match_percentile_cont() -> None:
    uid = uuid.uuid4().hex[:8]
    name = f"pct.latency.{uid}"
    m = get_metrics()
    for v in range(1, 101):
        m.observe(name, v)
    assert flush_telemetry() >= 100

    db = _open_db()
    try:
        snap = durable_snapshot(db, window_minutes=60)
    finally:
        db.close()
    lat = snap["latencies"][name]
    assert lat["count"] == 100
    assert lat["p50_ms"] == 50.5
    assert lat["p95_ms"] == 95.05
    assert lat["p99_ms"] == 99.01
    assert lat["max_ms"] == 100.0
    assert lat["avg_ms"] == 50.5


def test_window_is_clamped() -> None:
    assert telemetry.clamp_window(None) == telemetry.DEFAULT_WINDOW_MINUTES
    assert telemetry.clamp_window(0) == 1
    assert telemetry.clamp_window(10**9) == telemetry.MAX_WINDOW_MINUTES


def test_flush_swallows_db_errors_and_requeues() -> None:
    class BrokenSession:
        def execute(self, *a: Any, **k: Any) -> None:
            raise OperationalError("INSERT", {}, Exception("db down"))

        def commit(self) -> None:  # pragma: no cover - never reached
            pass

        def close(self) -> None:
            pass

    buf = telemetry.TelemetryBuffer(max_events=10)
    buf.append("counter", "broken.counter", 1)
    assert len(buf) == 1
    errors_before = buf.flush_errors
    assert buf.flush(lambda: BrokenSession()) == 0
    assert buf.flush_errors == errors_before + 1
    assert "db down" in (buf.last_error or "")
    assert len(buf) == 1  # requeued, not lost


def test_buffer_is_bounded() -> None:
    buf = telemetry.TelemetryBuffer(max_events=5)
    for i in range(8):
        buf.append("counter", "bounded", i)
    assert len(buf) == 5
    assert buf.dropped == 3


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------


def test_cost_estimate_math_from_pricing_yaml() -> None:
    path = pricing.default_pricing_path()
    assert path.is_file()
    table = pricing.load_pricing(path)
    assert table["version"] == "pricing.v1-2026-10"
    assert table["default"] == {"prompt": 0.0, "completion": 0.0}

    # 1M prompt + 1M completion on gpt-4.1-mini = 0.40 + 1.60
    assert pricing.estimate_cost_usd("gpt-4.1-mini", 1_000_000, 1_000_000, path=path) == 2.0
    assert pricing.estimate_cost_usd("gpt-4.1-mini", 1000, 500, path=path) == pytest.approx(0.0012)
    # Longest-prefix matching: dated snapshot resolves to gpt-4.1-mini, not gpt-4.1
    assert pricing.resolve_model_pricing("gpt-4.1-mini-2025-04-14", table)[0] == "gpt-4.1-mini"
    assert pricing.resolve_model_pricing("gpt-4.1-2025-04-14", table)[0] == "gpt-4.1"
    # Local models are free, unknown models fall back to default (0)
    assert pricing.estimate_cost_usd("llama3.2:latest", 500, 500, path=path) == 0.0
    assert pricing.resolve_model_pricing("totally-unknown", table)[0] == "default"
    assert pricing.estimate_cost_usd("totally-unknown", 10, 10, path=path) == 0.0
    # Unknown token counts → None (not zero)
    assert pricing.estimate_cost_usd("gpt-4.1-mini", None, None, path=path) is None
    # Partial usage still estimates
    assert pricing.estimate_cost_usd("gpt-4.1", 1_000_000, None, path=path) == 2.0


def test_missing_pricing_file_falls_back_to_zero(tmp_path) -> None:
    missing = tmp_path / "nope.yaml"
    table = pricing.load_pricing(missing)
    assert table["version"] == "pricing.builtin-zero"
    assert pricing.estimate_cost_usd("gpt-4.1", 10, 10, path=missing) == 0.0


def test_generate_persists_cost_and_records_token_counters(
    client: TestClient, api_key: str, monkeypatch
) -> None:
    from app.core.config import get_settings

    model_name = get_settings().model_name
    priced_table = {
        "version": "test-pricing",
        "currency": "USD",
        "unit": "per_1m_tokens",
        "default": {"prompt": 0.0, "completion": 0.0},
        "models": {model_name: {"prompt": 1.0, "completion": 2.0}},
        "_source_path": "<monkeypatched>",
    }
    monkeypatch.setattr(pricing, "load_pricing", lambda path=None: priced_table)

    fake = FakeLLM()
    set_llm_provider(fake)
    version_id = _ingest_corpus(client, api_key)

    m = get_metrics()
    m.reset()
    r = client.post(
        "/api/v1/generate",
        headers=_auth(api_key),
        json={"corpus_version_id": version_id, "query": "How much PTO accrues?", "top_k": 3},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert fake.calls == 1

    # (40 * 1.0 + 18 * 2.0) / 1e6
    expected_cost = 76 / 1_000_000
    db = _open_db()
    try:
        row = db.get(ExecutionTrace, body["execution_id"])
        assert row is not None
        assert row.prompt_tokens == 40 and row.completion_tokens == 18
        assert row.cost_usd == pytest.approx(expected_cost)
        assert row.pricing_version == "test-pricing"
    finally:
        db.close()

    counters = m.snapshot()["counters"]
    assert counters["generation.prompt_tokens"] == 40
    assert counters["generation.completion_tokens"] == 18
    assert counters["generation.tokens_total"] == 58
    assert counters["generation.cost_usd_micros"] == 76

    # The middleware flushed the request's events; the durable window sees them.
    durable = try_durable_snapshot(60)
    assert durable["available"] is True
    assert durable["tokens"]["prompt"] >= 40
    assert durable["tokens"]["completion"] >= 18
    assert durable["counters"]["generation.cost_usd_micros"] >= 76
    assert durable["cost"]["usd"] >= expected_cost


def test_generation_without_usage_leaves_cost_null(client: TestClient, api_key: str) -> None:
    class NoUsageLLM:
        def complete(self, messages, *, model, timeout):
            return LLMResult(content="PTO accrues at 1.25 days per month.", model=model, latency_ms=3.0)

    set_llm_provider(NoUsageLLM())
    version_id = _ingest_corpus(client, api_key)
    r = client.post(
        "/api/v1/generate",
        headers=_auth(api_key),
        json={"corpus_version_id": version_id, "query": "PTO?", "top_k": 2},
    )
    assert r.status_code == 200, r.text
    db = _open_db()
    try:
        row = db.get(ExecutionTrace, r.json()["execution_id"])
        assert row is not None
        assert row.cost_usd is None
        assert row.pricing_version is not None  # we know which table *would* apply
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def test_metrics_endpoints_expose_durable_store(client: TestClient) -> None:
    client.get("/health")  # guarantees at least one http.request event + flush
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["durable"] is False  # in-memory part is still per-process
    store = body["durable_store"]
    assert store["available"] is True
    assert store["source"] == "postgres"
    assert store["durable"] is True
    assert store["window_minutes"] == telemetry.DEFAULT_WINDOW_MINUTES
    http = store["latencies"]["http.request"]
    assert http["count"] >= 1
    for key in ("p50_ms", "p95_ms", "p99_ms", "avg_ms", "max_ms"):
        assert key in http
    assert store["counters"]["http.requests_total"] >= 1
    assert set(store["derived"]) == set(body["derived"])
    assert "tokens" in store and "cost" in store

    r = client.get("/api/v1/metrics/durable?window_minutes=60")
    assert r.status_code == 200
    assert r.json()["window_minutes"] == 60
    assert r.json()["available"] is True

    r = client.get("/api/v1/metrics/durable?window_minutes=99999999")
    assert r.status_code == 400  # validation envelope, max 43200


def test_ops_summary_and_signals_report_durable_source(client: TestClient) -> None:
    client.get("/health")
    r = client.get("/api/v1/ops/summary?window_minutes=120")
    assert r.status_code == 200
    metrics = r.json()["metrics"]
    assert metrics["durable"] is False  # backward-compatible key
    assert metrics["durable_available"] is True
    window = metrics["durable_window"]
    assert window["available"] is True
    assert window["window_minutes"] == 120
    assert set(window["http_latency"]) >= {"p50_ms", "p95_ms", "p99_ms", "count"}
    assert window["requests_total"] >= 1
    assert "request_error_rate" in window
    assert "tokens" in window and "cost_usd" in window

    r = client.get("/api/v1/signals?source=durable")
    assert r.status_code == 200
    body = r.json()
    assert body["metrics_source"] == "postgres"
    assert any(s["signal"] == "p95_latency_ms" for s in body["signals"])

    r = client.get("/api/v1/signals")
    assert r.json()["metrics_source"] == "in-memory"

    r = client.get("/api/v1/signals?source=bogus")
    assert r.status_code == 400


def test_evaluate_signals_on_durable_snapshot_directly() -> None:
    get_metrics().inc("http.requests_total")
    flush_telemetry()
    out = evaluate_signals(source="durable", window_minutes=60)
    assert out["metrics_source"] == "postgres"
    assert out["window_minutes"] == 60
    row = next(s for s in out["signals"] if s["signal"] == "request_error_rate")
    assert row["status"] in {"OK", "ALERT"}


def test_telemetry_disabled_path(client: TestClient) -> None:
    set_telemetry_enabled(False)
    buf = get_buffer()
    buf.clear()
    try:
        get_metrics().inc(f"disabled.counter.{uuid.uuid4().hex[:6]}")
        assert len(buf) == 0  # nothing buffered
        assert flush_telemetry() == 0

        snap = try_durable_snapshot(60)
        assert snap["available"] is False
        assert "telemetry_disabled" in snap["reason"]

        r = client.get("/api/v1/metrics/durable")
        assert r.status_code == 200
        assert r.json()["available"] is False

        r = client.get("/metrics")
        assert r.json()["durable_store"]["available"] is False

        r = client.get("/api/v1/ops/summary")
        metrics = r.json()["metrics"]
        assert metrics["durable_available"] is False
        assert metrics["durable_window"]["available"] is False

        r = client.get("/api/v1/signals?source=durable")
        assert r.json()["metrics_source"] == "in-memory"
    finally:
        set_telemetry_enabled(None)


def test_try_durable_snapshot_reports_db_error() -> None:
    class BrokenSession:
        def execute(self, *a: Any, **k: Any) -> None:
            raise OperationalError("SELECT", {}, Exception("connection refused"))

        def close(self) -> None:
            pass

    snap = try_durable_snapshot(60, session_factory=lambda: BrokenSession())
    assert snap["available"] is False
    assert snap["reason"].startswith("db_error")
