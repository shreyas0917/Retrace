"""Pytest configuration and shared fixtures for infrastructure tests."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# Ensure required env exists before app import (tests / local)
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("API_KEY", "test-retrace-api-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://retrace:retrace@localhost:5432/retrace",
)
os.environ.setdefault("CHROMA_HOST", "localhost")
os.environ.setdefault("CHROMA_PORT", "8001")
os.environ.setdefault("MODEL_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("MODEL_API_KEY", "test-model-key")
os.environ.setdefault("MODEL_NAME", "gpt-4.1-mini")
os.environ.setdefault(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
os.environ.setdefault("LOG_LEVEL", "WARNING")
# The whole test process shares one API key and therefore one rate-limit
# budget; keep it out of the way unless a test configures the limiter itself.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MINUTE", "100000")


@pytest.fixture(scope="session")
def api_key() -> str:
    return os.environ["API_KEY"]


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    from app.main import create_app

    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
