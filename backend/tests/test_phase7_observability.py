"""Phase 7 — observability, metrics, signals, redaction, health."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.metrics import get_metrics
from app.core.redaction import redact_event_dict
from app.core.signals import evaluate_signals, load_observability_config
from app.core.ops import record_diagnosis, record_judge, record_retrieval


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_redaction_strips_secrets() -> None:
    event = {
        "event": "x",
        "authorization": "Bearer secret-token",
        "api_key": "abc",
        "nested": {"password": "p", "ok": 1},
        "request_id": "r1",
    }
    out = redact_event_dict(None, "info", event)
    assert out["authorization"] == "[REDACTED]"
    assert out["api_key"] == "[REDACTED]"
    assert out["nested"]["password"] == "[REDACTED]"
    assert out["nested"]["ok"] == 1
    assert out["request_id"] == "r1"


def test_metrics_registry_counters_and_percentiles() -> None:
    m = get_metrics()
    m.reset()
    m.inc("http.requests_total", 10)
    m.inc("http.requests_5xx", 1)
    for ms in (10, 20, 30, 40, 100):
        m.observe("http.request", ms)
    snap = m.snapshot()
    assert snap["durable"] is False
    assert snap["counters"]["http.requests_total"] == 10
    assert snap["derived"]["request_error_rate"] == 0.1
    lat = snap["latencies"]["http.request"]
    assert lat["count"] == 5
    assert lat["p50_ms"] is not None
    assert lat["p95_ms"] is not None


def test_ops_helpers_feed_diagnosis_rates() -> None:
    m = get_metrics()
    m.reset()
    record_retrieval(empty=True, latency_ms=5)
    record_retrieval(empty=False, latency_ms=8)
    record_judge(judge_type="relevance", ok=True, latency_ms=3)
    record_judge(judge_type="relevance", ok=False, malformed=True, latency_ms=4)
    record_diagnosis(
        failure_code="RETRIEVAL_MISS", rule_id="R11", layer="retrieval", latency_ms=2
    )
    record_diagnosis(
        failure_code="OK_GROUNDED", rule_id="R40", layer="none", latency_ms=2
    )
    snap = m.snapshot()
    assert snap["derived"]["retrieval_empty_rate"] == 0.5
    assert snap["derived"]["judge_malformed_rate"] == 0.5
    assert snap["derived"]["retrieval_miss_rate"] == 0.5


def test_signals_alert_when_over_threshold() -> None:
    m = get_metrics()
    m.reset()
    # Force miss rate 1.0 > 0.10
    record_diagnosis(
        failure_code="RETRIEVAL_MISS", rule_id="R11", layer="retrieval"
    )
    signals = evaluate_signals()
    miss = next(s for s in signals["signals"] if s["signal"] == "retrieval_miss_rate")
    assert miss["status"] == "ALERT"
    assert miss["actual"] == 1.0


def test_observability_config_loads() -> None:
    cfg = load_observability_config()
    assert "signals" in cfg
    assert cfg["signals"]["request_error_rate"]["threshold"] == 0.05


def test_health_live_and_ready(client: TestClient) -> None:
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert "ready" in body
    assert body["ready"] is True
    assert body["dependencies"]["postgres"] == "ok"


def test_metrics_endpoint(client: TestClient) -> None:
    get_metrics().reset()
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["counters"]["http.requests_total"] >= 1
    assert "latencies" in body
    assert body["durable"] is False


def test_signals_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/signals")
    assert r.status_code == 200
    body = r.json()
    assert "signals" in body
    assert isinstance(body["signals"], list)


def test_ops_summary(client: TestClient) -> None:
    r = client.get("/api/v1/ops/summary")
    assert r.status_code == 200
    body = r.json()
    assert "ready" in body
    assert "signals" in body
    assert body["metrics"]["durable"] is False


def test_request_id_still_echoed(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "ops-test-rid"})
    assert r.headers.get("X-Request-ID") == "ops-test-rid"
