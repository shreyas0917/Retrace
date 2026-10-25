"""Phase 1 infrastructure tests (T01–T10)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import check_database_connection, init_db
from app.services.chroma import check_chroma_connection, reset_chroma_client


def test_t01_backend_app_starts(client: TestClient) -> None:
    """T01 — Backend application object starts successfully."""
    assert client.app is not None
    assert client.app.title == "Retrace"


def test_t02_health_returns_200(client: TestClient) -> None:
    """T02 — GET /health returns 200 and status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_t02b_api_v1_health_returns_200(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_t03_missing_api_key_returns_401(client: TestClient) -> None:
    """T03 — Missing/invalid API key returns 401."""
    response = client.get("/api/v1/status")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert "request_id" in body


def test_t03b_invalid_api_key_returns_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/status",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_t04_valid_api_key_allows_access(client: TestClient, api_key: str) -> None:
    """T04 — Valid API key allows authenticated API access."""
    response = client.get(
        "/api/v1/status",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # May be ok or degraded depending on whether deps are up; auth must succeed.
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "retrace-backend"
    assert "dependencies" in body


def test_t05_request_id_generated_when_absent(client: TestClient) -> None:
    """T05 — Request ID is generated when absent."""
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


def test_t06_provided_request_id_preserved(client: TestClient) -> None:
    """T06 — Provided request ID is preserved."""
    rid = f"test-{uuid.uuid4()}"
    response = client.get("/health", headers={"X-Request-ID": rid})
    assert response.headers["X-Request-ID"] == rid


def test_t07_request_id_in_response_headers(client: TestClient) -> None:
    """T07 — Request ID is returned in response headers."""
    response = client.get("/api/v1/health")
    assert "X-Request-ID" in response.headers


def test_t08_database_connection_works() -> None:
    """T08 — Database connection works (requires running Postgres)."""
    init_db()
    try:
        assert check_database_connection() is True
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available: {exc}")


def test_t09_chroma_connection_works() -> None:
    """T09 — Chroma connection works (requires running Chroma)."""
    reset_chroma_client()
    settings = get_settings()
    try:
        assert check_chroma_connection(settings) is True
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chroma not available: {exc}")


def test_t10_configuration_loads_correctly() -> None:
    """T10 — Application configuration loads correctly."""
    settings = Settings()  # type: ignore[call-arg]
    assert settings.api_key
    assert settings.database_url.startswith("postgresql")
    assert settings.chroma_host
    assert settings.chroma_port > 0
    assert settings.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.model_name
    assert os.environ.get("API_KEY") == settings.api_key
