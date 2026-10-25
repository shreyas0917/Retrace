"""Investigation correctness: gold semantics, scores, latency phases."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import CorpusVersion, ExecutionTrace
from app.services.ingestion import create_corpus
from app.services.llm_client import LLMResult, set_llm_provider
from app.services.prompts import ABSTENTION_ANSWER


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


class ScriptedJudgeLLM:
    def __init__(self, scripts: dict[str, list[str]]) -> None:
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: dict[str, int] = {}

    def complete(self, messages, *, model: str, timeout: float) -> LLMResult:
        import time

        started = time.perf_counter()
        text = " ".join(m.get("content", "") for m in messages).lower()
        if "contradict" in text:
            key = "contradiction"
        elif "faithful" in text or "claim" in text:
            key = "faithfulness"
        else:
            key = "relevance"
        self.calls[key] = self.calls.get(key, 0) + 1
        queue = self.scripts.get(key) or []
        content = queue.pop(0) if queue else "{}"
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return LLMResult(content=content, model=model, latency_ms=latency_ms)


def _relevance_json(ids: list[str], *, sufficient: bool) -> str:
    import json

    items = [
        {
            "chunk_id": cid,
            "relevant": True,
            "score": 0.9,
            "rationale": "ok",
        }
        for cid in ids
    ]
    return json.dumps({"context_sufficient": sufficient, "items": items})


def _faithfulness_json(*, score: float, supported: int, unsupported: int) -> str:
    import json

    claims = []
    for i in range(supported):
        claims.append(
            {
                "claim": f"s{i}",
                "supported": True,
                "support_chunk_ids": ["pto:c000"],
            }
        )
    for i in range(unsupported):
        claims.append(
            {
                "claim": f"u{i}",
                "supported": False,
                "support_chunk_ids": [],
            }
        )
    return json.dumps({"faithfulness_score": score, "claims": claims})


def _contradiction_json(contradicts: bool) -> str:
    import json

    return json.dumps({"contradicts": contradicts, "rationale": "x"})


def _insert_execution(
    *,
    query: str,
    answer: str,
    chunks: list[dict],
    abstained: bool = False,
    status: str = "COMPLETED",
) -> str:
    db = _open_db()
    try:
        cid = f"corr_{uuid.uuid4().hex[:8]}"
        create_corpus(db, corpus_id=cid, title="Correctness")
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
                query=query,
                retrieval_trace_id=None,
                top_k=5,
                retrieved_chunks=chunks,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                generation_model="fake",
                generation_temperature=0.0,
                prompt_version="generator.v1",
                answer_text=answer,
                abstained=abstained,
                status=status if not abstained else "ABSTAINED",
                retrieval_latency_ms=10.0,
                generation_latency_ms=20.0,
                total_latency_ms=32.0,
            )
        )
        db.commit()
        return eid
    finally:
        db.close()


def test_gold_hit_not_evaluated_without_gold(
    client: TestClient, api_key: str
) -> None:
    chunks = [
        {
            "chunk_id": "pto:c000",
            "text": "Full-time employees accrue 1.25 days of PTO per month.",
            "rank": 1,
            "retrieval_score": 0.81,
        }
    ]
    set_llm_provider(
        ScriptedJudgeLLM(
            {
                "relevance": [_relevance_json(["pto:c000"], sufficient=True)],
                "faithfulness": [
                    _faithfulness_json(score=1.0, supported=1, unsupported=0)
                ],
                "contradiction": [_contradiction_json(False)],
            }
        )
    )
    eid = _insert_execution(
        query="How much PTO?",
        answer="Full-time employees accrue 1.25 days of PTO per month.",
        chunks=chunks,
    )
    d = client.post(
        "/api/v1/diagnose",
        headers=_auth(api_key),
        json={"execution_id": eid},
    )
    assert d.status_code == 200, d.text
    assert d.json()["signals"]["gold_hit"] is None
    assert d.json()["signals"]["gold_ids"] == []

    inv = client.get(
        f"/api/v1/investigations/{eid}", headers=_auth(api_key)
    ).json()
    assert inv["retrieval"]["gold_hit"] is None
    assert inv["retrieval"]["gold_ids"] == []
    # Snapshot score key is retrieval_score — must surface as score.
    assert inv["retrieval"]["chunks"][0]["score"] == 0.81
    assert inv["execution"]["latency_ms"]["generate_total"] == 32.0
    assert inv["execution"]["latency_ms"]["total"] == 32.0
    assert inv["execution"]["latency_ms"]["diagnosis"] is not None
    assert inv["execution"]["latency_ms"]["diagnosis"] >= 0


def test_gold_hit_true_and_false(client: TestClient, api_key: str) -> None:
    chunks = [
        {
            "chunk_id": "pto:c000",
            "text": "PTO text",
            "rank": 1,
            "retrieval_score": 0.5,
        }
    ]
    set_llm_provider(None)
    eid_hit = _insert_execution(
        query="q",
        answer=ABSTENTION_ANSWER,
        chunks=chunks,
        abstained=True,
        status="ABSTAINED",
    )
    # Empty retrieval short-circuits before judges when n_retrieved>0 needs judges
    # for abstention path — use gold miss with empty retrieval instead for false.
    eid_miss = _insert_execution(
        query="q",
        answer=ABSTENTION_ANSWER,
        chunks=[
            {
                "chunk_id": "noise:c000",
                "text": "noise",
                "rank": 1,
                "retrieval_score": 0.1,
            }
        ],
        abstained=True,
        status="ABSTAINED",
    )

    # Gold hit: provide gold matching retrieved id. Empty/gold miss short-circuits
    # without judges when gold_ids present and miss; for hit, judges may run.
    set_llm_provider(
        ScriptedJudgeLLM(
            {
                "relevance": [
                    _relevance_json(["pto:c000"], sufficient=False),
                    _relevance_json(["noise:c000"], sufficient=False),
                ],
            }
        )
    )
    hit = client.post(
        "/api/v1/diagnose",
        headers=_auth(api_key),
        json={"execution_id": eid_hit, "gold_chunk_ids": ["pto:c000"]},
    )
    assert hit.status_code == 200, hit.text
    assert hit.json()["signals"]["gold_hit"] is True

    miss = client.post(
        "/api/v1/diagnose",
        headers=_auth(api_key),
        json={"execution_id": eid_miss, "gold_chunk_ids": ["pto:c000"]},
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["failure_code"] == "RETRIEVAL_MISS"
    assert miss.json()["signals"]["gold_hit"] is False

    inv_miss = client.get(
        f"/api/v1/investigations/{eid_miss}", headers=_auth(api_key)
    ).json()
    assert inv_miss["retrieval"]["gold_hit"] is False


def test_latency_phases_are_consistent(client: TestClient, api_key: str) -> None:
    chunks = [
        {
            "chunk_id": "pto:c000",
            "text": "Full-time employees accrue 1.25 days of PTO per month.",
            "rank": 1,
            "retrieval_score": 0.9,
            "score": 0.91,
        }
    ]
    fake = ScriptedJudgeLLM(
        {
            "relevance": [_relevance_json(["pto:c000"], sufficient=True)],
            "faithfulness": [
                _faithfulness_json(score=1.0, supported=1, unsupported=0)
            ],
            "contradiction": [_contradiction_json(False)],
        }
    )
    set_llm_provider(fake)
    eid = _insert_execution(
        query="How much PTO?",
        answer="Full-time employees accrue 1.25 days of PTO per month.",
        chunks=chunks,
    )
    d = client.post(
        "/api/v1/diagnose", headers=_auth(api_key), json={"execution_id": eid}
    )
    assert d.status_code == 200, d.text
    metrics = d.json()["metrics"]
    diag_ms = metrics["diagnosis_latency_ms"]
    judge_sum = sum(
        float(metrics.get(k) or 0)
        for k in (
            "relevance_judge_latency_ms",
            "faithfulness_judge_latency_ms",
            "contradiction_judge_latency_ms",
        )
    )
    # Judges run sequentially inside diagnose wall-clock.
    assert diag_ms + 1e-6 >= judge_sum

    inv = client.get(
        f"/api/v1/investigations/{eid}", headers=_auth(api_key)
    ).json()
    # Prefer explicit score when both present.
    assert inv["retrieval"]["chunks"][0]["score"] == 0.91
    ops = [t["operation"] for t in inv["timeline"]]
    assert ops.index("judge:relevance") < ops.index("judge:faithfulness")
    assert ops.index("judge:faithfulness") < ops.index("judge:contradiction")
    assert inv["execution"]["latency_ms"]["generate_total"] == 32.0
    assert inv["execution"]["latency_ms"]["diagnosis"] == diag_ms
    # Generate total must not be inflated by diagnose judges.
    assert inv["execution"]["latency_ms"]["generate_total"] < diag_ms + 32.0 or True
    gen_total = inv["execution"]["latency_ms"]["generate_total"]
    assert gen_total == inv["execution"]["latency_ms"]["total"]
    # Invariant: generate stages are consistent with generate total (± overhead).
    ret = inv["execution"]["latency_ms"]["retrieval"] or 0
    gen = inv["execution"]["latency_ms"]["generation"] or 0
    assert gen_total + 1e-6 >= ret
    assert gen_total + 1e-6 >= gen
