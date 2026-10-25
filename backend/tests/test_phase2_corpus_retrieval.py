"""Phase 2 unit + API tests for corpus, chunking, embedding, retrieval."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.services.chunking import chunk_text, make_chunk_id, normalize_chunking_config
from app.services.hashing import compute_corpus_hash
from app.services import chroma as chroma_service


DEMO_DOCS = [
    {
        "id": "employee_handbook",
        "text": (
            "Full-time employees accrue 1.25 days of PTO per month. "
            "Unused PTO may be carried over up to 5 days."
        ),
        "source_name": "employee_handbook.md",
    },
    {
        "id": "refund_policy",
        "text": (
            "Customers may request a full refund within 30 days of purchase "
            "if the product is unused."
        ),
        "source_name": "refund_policy.md",
    },
]


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_same_corpus_same_hash() -> None:
    docs = [("a", "hello"), ("b", "world")]
    h1 = compute_corpus_hash(docs)
    h2 = compute_corpus_hash(list(reversed(docs)))
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_changed_content_different_hash() -> None:
    h1 = compute_corpus_hash([("a", "hello")])
    h2 = compute_corpus_hash([("a", "hello!")])
    assert h1 != h2


def test_deterministic_chunks_and_stable_ids() -> None:
    text = "x" * 1200
    c1 = chunk_text(text, chunk_size=512, chunk_overlap=64)
    c2 = chunk_text(text, chunk_size=512, chunk_overlap=64)
    assert len(c1) == len(c2)
    assert [c.text for c in c1] == [c.text for c in c2]
    assert make_chunk_id("doc", 0) == "doc:c000"
    assert make_chunk_id("doc", 12) == "doc:c012"


def test_chunking_config_normalization() -> None:
    cfg = normalize_chunking_config({"chunk_size": 256, "chunk_overlap": 32})
    assert cfg["strategy"] == "recursive_character"
    assert cfg["chunk_size"] == 256
    with pytest.raises(ValueError):
        normalize_chunking_config({"chunk_size": 100, "chunk_overlap": 100})


def test_create_ingest_retrieve_flow(client: TestClient, api_key: str) -> None:
    corpus_id = f"test_{uuid.uuid4().hex[:8]}"
    headers = _auth(api_key)

    r = client.post(
        "/api/v1/corpora",
        headers=headers,
        json={"id": corpus_id, "title": "Test Corpus"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == corpus_id

    r = client.post(
        f"/api/v1/corpora/{corpus_id}/versions",
        headers=headers,
        json={"documents": DEMO_DOCS},
    )
    assert r.status_code == 200, r.text
    version = r.json()
    assert version["status"] == "READY"
    assert version["document_count"] == 2
    assert version["chunk_count"] >= 2
    assert version["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    version_id = version["id"]

    # Idempotent re-ingest
    r2 = client.post(
        f"/api/v1/corpora/{corpus_id}/versions",
        headers=headers,
        json={"documents": DEMO_DOCS},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == version_id
    count = chroma_service.collection_count(version_id)
    assert count == version["chunk_count"]

    # Retrieve
    rid = f"req-{uuid.uuid4()}"
    r = client.post(
        "/api/v1/retrieve",
        headers={**headers, "X-Request-ID": rid},
        json={
            "corpus_version_id": version_id,
            "query": "How much PTO do full-time employees accrue?",
            "top_k": 2,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request_id"] == rid
    assert r.headers["X-Request-ID"] == rid
    assert len(body["results"]) <= 2
    assert len(body["results"]) >= 1
    assert body["results"][0]["rank"] == 1
    assert "chunk_id" in body["results"][0]
    assert body["results"][0]["text"]


def test_corpus_isolation(client: TestClient, api_key: str) -> None:
    headers = _auth(api_key)
    a = f"iso_a_{uuid.uuid4().hex[:6]}"
    b = f"iso_b_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/corpora", headers=headers, json={"id": a, "title": "A"})
    client.post("/api/v1/corpora", headers=headers, json={"id": b, "title": "B"})

    va = client.post(
        f"/api/v1/corpora/{a}/versions",
        headers=headers,
        json={
            "documents": [
                {"id": "only_a", "text": "Alpha unique zebra token for corpus A."}
            ]
        },
    ).json()
    vb = client.post(
        f"/api/v1/corpora/{b}/versions",
        headers=headers,
        json={
            "documents": [
                {"id": "only_b", "text": "Beta unique penguin token for corpus B."}
            ]
        },
    ).json()

    ra = client.post(
        "/api/v1/retrieve",
        headers=headers,
        json={
            "corpus_version_id": va["id"],
            "query": "zebra token",
            "top_k": 3,
        },
    ).json()
    assert all(
        (item.get("document_id") == "only_a") or ("Alpha" in (item.get("text") or ""))
        for item in ra["results"]
    )
    # Ensure B's collection is separate
    assert chroma_service.collection_name_for_corpus_version(va["id"]) != (
        chroma_service.collection_name_for_corpus_version(vb["id"])
    )


def test_non_ready_cannot_retrieve(client: TestClient, api_key: str, monkeypatch) -> None:
    """Simulate FAILED status by inserting a version row without vectors."""
    headers = _auth(api_key)
    from app.db.session import SessionLocal, init_db
    from app.db.models import CorpusVersion
    from app.services.ingestion import create_corpus

    init_db()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        cid = f"fail_{uuid.uuid4().hex[:6]}"
        create_corpus(db, corpus_id=cid, title="Fail")
        vid = f"cv_fail_{uuid.uuid4().hex[:8]}"
        db.add(
            CorpusVersion(
                id=vid,
                corpus_id=cid,
                corpus_hash="sha256:dead",
                chunking_config={"strategy": "recursive_character", "chunk_size": 512, "chunk_overlap": 64, "tokenizer": "char"},
                chunking_config_hash="sha256:dead",
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                embedding_revision="x",
                vector_collection=f"cv_{vid}",
                status="FAILED",
                status_message="simulated",
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/v1/retrieve",
        headers=headers,
        json={"corpus_version_id": vid, "query": "anything", "top_k": 3},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATE"


def test_retrieve_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/api/v1/retrieve",
        json={"corpus_version_id": "x", "query": "q", "top_k": 3},
    )
    assert r.status_code == 401


def test_empty_documents_rejected(client: TestClient, api_key: str) -> None:
    headers = _auth(api_key)
    cid = f"empty_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/corpora", headers=headers, json={"id": cid, "title": "E"})
    r = client.post(
        f"/api/v1/corpora/{cid}/versions",
        headers=headers,
        json={"documents": [{"id": "d", "text": "   "}]},
    )
    assert r.status_code in (400, 409)


def test_missing_corpus_404(client: TestClient, api_key: str) -> None:
    r = client.post(
        "/api/v1/corpora/does_not_exist/versions",
        headers=_auth(api_key),
        json={"documents": DEMO_DOCS},
    )
    assert r.status_code == 404
