"""Phase 8 — investigation API, rules, runbooks."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import CorpusVersion, ExecutionTrace
from app.services.ingestion import create_corpus
from app.services.llm_client import set_llm_provider
from app.services.prompts import ABSTENTION_ANSWER


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


def _insert_empty_execution() -> str:
    db = _open_db()
    try:
        cid = f"c8_{uuid.uuid4().hex[:8]}"
        create_corpus(db, corpus_id=cid, title="phase8")
        vid = uuid.uuid4().hex
        db.add(
            CorpusVersion(
                id=vid,
                corpus_id=cid,
                corpus_hash=f"sha256:{vid}",
                chunking_config={
                    "strategy": "recursive_character",
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                    "tokenizer": "char",
                },
                chunking_config_hash="sha256:cfg",
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                embedding_revision="x",
                vector_collection=f"cv_{vid}",
                status="READY",
            )
        )
        db.commit()
        eid = str(uuid.uuid4())
        db.add(
            ExecutionTrace(
                id=eid,
                request_id=f"req-{uuid.uuid4()}",
                corpus_version_id=vid,
                query="Anything?",
                retrieval_trace_id=None,
                top_k=5,
                retrieved_chunks=[],
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                generation_model="gpt-4.1-mini",
                generation_temperature=0.0,
                prompt_version="generator.v1",
                answer_text=ABSTENTION_ANSWER,
                abstained=True,
                status="ABSTAINED",
                retrieval_latency_ms=10.0,
                generation_latency_ms=5.0,
                total_latency_ms=15.0,
            )
        )
        db.commit()
        return eid
    finally:
        db.close()


def test_rules_catalog(client: TestClient, api_key: str) -> None:
    r = client.get("/api/v1/rules", headers=_auth(api_key))
    assert r.status_code == 200
    rules = r.json()["rules"]
    assert any(x["rule_id"] == "R11" for x in rules)
    r2 = client.get("/api/v1/rules/R30", headers=_auth(api_key))
    assert r2.status_code == 200
    body = r2.json()
    assert body["result"] == "GENERATION_CONTRADICTION"
    assert "conditions" in body


def test_runbooks_index_and_body(client: TestClient) -> None:
    r = client.get("/api/v1/runbooks")
    assert r.status_code == 200
    body = r.json()
    assert "by_failure_code" in body
    assert body["by_failure_code"]["RETRIEVAL_MISS"] == "retrieval-miss-rate"
    assert isinstance(body["runbooks"], list)
    # Content available when docs/runbooks is mounted or present on disk
    if body["runbooks"]:
        slug = body["runbooks"][0]["slug"]
        md = client.get(f"/api/v1/runbooks/{slug}")
        assert md.status_code == 200
        assert len(md.text) > 20


def test_investigation_after_diagnose(client: TestClient, api_key: str) -> None:
    set_llm_provider(None)
    eid = _insert_empty_execution()
    d = client.post(
        "/api/v1/diagnose",
        headers=_auth(api_key),
        json={"execution_id": eid},
    )
    assert d.status_code == 200, d.text
    assert d.json()["failure_code"] == "RETRIEVAL_EMPTY"
    assert d.json()["rule_id"] == "R10"

    inv = client.get(
        f"/api/v1/investigations/{eid}",
        headers=_auth(api_key),
    )
    assert inv.status_code == 200, inv.text
    body = inv.json()
    assert body["execution"]["execution_id"] == eid
    assert body["diagnosis"]["failure_code"] == "RETRIEVAL_EMPTY"
    assert body["diagnosis"]["rule_id"] == "R10"
    assert body["rule"]["rule_id"] == "R10"
    assert body["why"]["engine"] == "deterministic_rule_engine"
    assert any(e.get("ref") for e in body["evidence"])
    assert any(t["operation"] == "diagnosis" for t in body["timeline"])
    assert body["failure"]["runbook"] == "retrieval-miss-rate"


def test_investigation_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v1/investigations/does-not-exist")
    assert r.status_code == 401


def test_investigation_missing_execution(client: TestClient, api_key: str) -> None:
    r = client.get(
        "/api/v1/investigations/missing-id",
        headers=_auth(api_key),
    )
    assert r.status_code == 404
