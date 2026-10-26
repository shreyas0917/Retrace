"""v1.0 — LLM retries/timeouts, concurrency, and dependency failure injection."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.errors import DependencyUnavailableError, GenerationError, GenerationTimeoutError
from app.core.metrics import get_metrics
from app.db import session as db_session
from app.db.models import ExecutionTrace
from app.db.session import get_db
from app.services import chroma as chroma_service
from app.services.llm_client import LLMResult, OpenAICompatibleProvider, set_llm_provider


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


@pytest.fixture(autouse=True)
def _reset_llm():
    set_llm_provider(None)
    yield
    set_llm_provider(None)


def _settings(**overrides: Any):
    base = {
        "model_base_url": "http://llm.test/v1",
        "model_api_key": "test-key",
        "model_timeout_seconds": 5.0,
        "model_connect_timeout_seconds": 1.0,
        "model_max_retries": 2,
        "model_retry_backoff_seconds": 0.001,
    }
    base.update(overrides)
    return get_settings().model_copy(update=base)


def _ok(content: str = "ok", model: str = "fake-model") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "cmpl-1",
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def _provider(handler, **settings_overrides: Any) -> tuple[OpenAICompatibleProvider, list[float]]:
    sleeps: list[float] = []
    provider = OpenAICompatibleProvider(
        _settings(**settings_overrides),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    return provider, sleeps


MESSAGES = [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# Retry / timeout behaviour of the provider
# ---------------------------------------------------------------------------


def test_retries_on_503_then_succeeds() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) <= 2:
            return httpx.Response(503, text="upstream busy")
        return _ok("recovered")

    m = get_metrics()
    m.reset()
    provider, sleeps = _provider(handler, model_max_retries=3)
    result = provider.complete(MESSAGES, model="m", timeout=5.0)

    assert result.content == "recovered"
    assert result.prompt_tokens == 10
    assert len(calls) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0] * 1.5 or sleeps[1] >= sleeps[0]  # exponential-ish
    assert m.get_counter("llm.retries") == 2
    assert m.get_counter("llm.failures") == 0
    assert m.get_counter("llm.attempts") == 3
    body = json.loads(calls[0].content)
    assert body["temperature"] == 0.0
    assert calls[0].headers["Authorization"] == "Bearer test-key"


def test_gives_up_after_max_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="still busy")

    m = get_metrics()
    m.reset()
    provider, _ = _provider(handler, model_max_retries=2)
    with pytest.raises(GenerationError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=5.0)

    err = exc_info.value
    assert err.code == "GENERATION_FAILED"
    assert err.message == "LLM provider returned an error"
    assert err.details["status_code"] == 503
    assert err.details["attempts"] == 3
    assert len(calls) == 3  # 1 + 2 retries
    assert m.get_counter("llm.retries") == 2
    assert m.get_counter("llm.failures") == 1


def test_transport_error_is_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return _ok()

    provider, _ = _provider(handler)
    assert provider.complete(MESSAGES, model="m", timeout=5.0).content == "ok"
    assert len(calls) == 2


def test_transport_error_exhausted_keeps_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider, _ = _provider(handler, model_max_retries=1)
    with pytest.raises(GenerationError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=5.0)
    assert exc_info.value.message == "LLM request failed"
    assert exc_info.value.details["attempts"] == 2


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_no_retry_on_non_retryable_4xx(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"error": "bad request"})

    m = get_metrics()
    m.reset()
    provider, sleeps = _provider(handler, model_max_retries=3)
    with pytest.raises(GenerationError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=5.0)
    assert exc_info.value.details["status_code"] == status
    assert exc_info.value.message == "LLM provider returned an error"
    assert len(calls) == 1
    assert sleeps == []
    assert m.get_counter("llm.retries") == 0
    assert m.get_counter("llm.failures") == 1


def test_401_is_authentication_failure_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="unauthorized")

    provider, _ = _provider(handler)
    with pytest.raises(GenerationError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=5.0)
    assert exc_info.value.message == "LLM authentication failed"
    assert len(calls) == 1


def test_429_honours_retry_after() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="slow down")
        return _ok()

    m = get_metrics()
    m.reset()
    provider, sleeps = _provider(handler, model_max_retries=2, model_timeout_seconds=30.0)
    assert provider.complete(MESSAGES, model="m", timeout=30.0).content == "ok"
    assert len(calls) == 2
    assert sleeps == [pytest.approx(2.0, abs=0.01)] or sleeps[0] >= 2.0
    assert m.get_counter("llm.retries") == 1


def test_large_retry_after_is_ignored_in_favour_of_backoff() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return _ok()

    provider, sleeps = _provider(handler, model_retry_backoff_seconds=0.01)
    provider.complete(MESSAGES, model="m", timeout=5.0)
    assert len(calls) == 2
    assert sleeps[0] < 1.0


def test_timeout_raises_generation_timeout_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("read timed out", request=request)

    m = get_metrics()
    m.reset()
    provider, sleeps = _provider(handler, model_max_retries=3)
    with pytest.raises(GenerationTimeoutError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=2.5)
    assert exc_info.value.code == "GENERATION_TIMEOUT"
    assert exc_info.value.message == "LLM request timed out"
    assert exc_info.value.details["timeout_seconds"] == 2.5
    assert len(calls) == 1
    assert sleeps == []
    assert m.get_counter("llm.retries") == 0
    assert m.get_counter("llm.timeouts") == 1
    assert m.get_counter("llm.failures") == 1


def test_retry_is_skipped_when_backoff_exceeds_remaining_budget() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    # 1s backoff cannot fit inside a 0.2s total budget → fail fast, no sleep.
    provider, sleeps = _provider(handler, model_max_retries=5, model_retry_backoff_seconds=1.0)
    with pytest.raises(GenerationError):
        provider.complete(MESSAGES, model="m", timeout=0.2)
    assert len(calls) == 1
    assert sleeps == []


def test_per_attempt_timeout_uses_separate_connect_and_read() -> None:
    seen: list[httpx.Timeout] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return _ok()

    provider, _ = _provider(handler, model_connect_timeout_seconds=1.5)
    provider.complete(MESSAGES, model="m", timeout=20.0)
    t = seen[0]
    assert t["connect"] == pytest.approx(1.5)
    assert t["read"] == pytest.approx(20.0, abs=0.5)


def test_malformed_body_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"choices": []})

    provider, _ = _provider(handler)
    with pytest.raises(GenerationError) as exc_info:
        provider.complete(MESSAGES, model="m", timeout=5.0)
    assert exc_info.value.message == "LLM returned a malformed response"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# End-to-end through the API
# ---------------------------------------------------------------------------


def _ingest_corpus(client: TestClient, api_key: str) -> str:
    corpus_id = f"res_{uuid.uuid4().hex[:8]}"
    headers = _auth(api_key)
    client.post("/api/v1/corpora", headers=headers, json={"id": corpus_id, "title": "Resilience"})
    docs = [
        {
            "id": "pto_doc",
            "text": (
                "Full-time employees accrue 1.25 days of PTO per month. "
                "Unused PTO may be carried over up to 5 days."
            ),
            "source_name": "pto.md",
        },
        {
            "id": "refund_doc",
            "text": "Customers may request a refund within 30 days of purchase.",
            "source_name": "refund.md",
        },
    ]
    r = client.post(
        f"/api/v1/corpora/{corpus_id}/versions", headers=headers, json={"documents": docs}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_llm_timeout_via_api_persists_generation_timeout_trace(
    client: TestClient, api_key: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    provider, _ = _provider(handler)
    set_llm_provider(provider)
    version_id = _ingest_corpus(client, api_key)

    r = client.post(
        "/api/v1/generate",
        headers=_auth(api_key),
        json={"corpus_version_id": version_id, "query": "How much PTO accrues?", "top_k": 3},
    )
    assert r.status_code == 504, r.text
    err = r.json()["error"]
    assert err["code"] == "GENERATION_TIMEOUT"
    execution_id = err["details"]["execution_id"]

    db = _open_db()
    try:
        row = db.get(ExecutionTrace, execution_id)
        assert row is not None
        assert row.status == "GENERATION_TIMEOUT"
        assert row.error_code == "GENERATION_TIMEOUT"
        assert row.retrieval_trace_id  # retrieval succeeded before the LLM timed out
        assert row.answer_text is None
    finally:
        db.close()


def test_llm_5xx_via_api_after_retries_returns_502(client: TestClient, api_key: str) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502, text="bad gateway")

    provider, _ = _provider(handler, model_max_retries=1)
    set_llm_provider(provider)
    version_id = _ingest_corpus(client, api_key)
    r = client.post(
        "/api/v1/generate",
        headers=_auth(api_key),
        json={"corpus_version_id": version_id, "query": "How much PTO accrues?", "top_k": 3},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "GENERATION_FAILED"
    assert len(calls) == 2


class SlowFakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, model, timeout) -> LLMResult:
        import time

        self.calls += 1
        time.sleep(0.02)
        return LLMResult(
            content="Full-time employees accrue 1.25 days of PTO per month.",
            model=model,
            latency_ms=20.0,
            prompt_tokens=30,
            completion_tokens=12,
            total_tokens=42,
        )


def test_twenty_concurrent_generate_calls(client: TestClient, api_key: str) -> None:
    fake = SlowFakeLLM()
    set_llm_provider(fake)
    version_id = _ingest_corpus(client, api_key)
    headers = _auth(api_key)

    def one(i: int) -> tuple[int, dict]:
        r = client.post(
            "/api/v1/generate",
            headers={**headers, "X-Request-ID": f"conc-{uuid.uuid4()}"},
            json={
                "corpus_version_id": version_id,
                "query": f"How much PTO do employees accrue? (#{i})",
                "top_k": 3,
            },
        )
        return r.status_code, (r.json() if r.content else {})

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(one, range(20)))

    statuses = [s for s, _ in results]
    assert statuses == [200] * 20, statuses
    execution_ids = [b["execution_id"] for _, b in results]
    assert len(set(execution_ids)) == 20
    assert fake.calls == 20

    db = _open_db()
    try:
        rows = [db.get(ExecutionTrace, eid) for eid in execution_ids]
    finally:
        db.close()
    assert all(r is not None and r.status == "COMPLETED" for r in rows)
    assert len({r.request_id for r in rows}) == 20


def test_chroma_failure_returns_503_and_not_ready(
    client: TestClient, api_key: str, monkeypatch
) -> None:
    version_id = _ingest_corpus(client, api_key)

    def boom(*args: Any, **kwargs: Any) -> dict:
        raise DependencyUnavailableError("Chroma unavailable", details={"injected": True})

    monkeypatch.setattr(chroma_service, "query_collection", boom)
    r = client.post(
        "/api/v1/retrieve",
        headers=_auth(api_key),
        json={"corpus_version_id": version_id, "query": "PTO?", "top_k": 3},
    )
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert body["error"]["details"] == {"injected": True}
    assert body["request_id"]
    assert r.headers.get("X-Request-ID") == body["request_id"]

    from app.api import routes_health

    def chroma_down(*args: Any, **kwargs: Any) -> bool:
        raise DependencyUnavailableError("heartbeat failed")

    monkeypatch.setattr(routes_health, "check_chroma_connection", chroma_down)
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["ready"] is False
    assert body["dependencies"]["chroma"] == "error"
    assert body["dependencies"]["postgres"] == "ok"
    assert "chroma_error" in body["dependencies"]["details"]

    # Liveness is unaffected by dependency failures.
    assert client.get("/health/live").json()["status"] == "ok"


def test_database_failure_returns_database_error(client: TestClient, api_key: str) -> None:
    class BrokenSession:
        def get(self, *a: Any, **k: Any):
            raise OperationalError("SELECT", {}, Exception("connection refused"))

        def execute(self, *a: Any, **k: Any):
            raise OperationalError("SELECT", {}, Exception("connection refused"))

        def close(self) -> None:
            pass

    def broken_db():
        yield BrokenSession()

    app = client.app
    app.dependency_overrides[get_db] = broken_db
    # The unhandled-exception path re-raises inside TestClient by default.
    quiet = TestClient(app, raise_server_exceptions=False)
    try:
        r = quiet.get(f"/api/v1/executions/{uuid.uuid4()}", headers=_auth(api_key))
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "DATABASE_ERROR"
    assert body["error"]["message"] == "An internal error occurred"
    assert body["request_id"]
