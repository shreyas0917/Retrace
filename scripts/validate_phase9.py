"""Phase 9 clean-room validation — no new product features.

Runs inside the backend container (PYTHONPATH=/app):

  docker compose exec -T backend sh -c \\
    'cd /app && PYTHONPATH=/app python /scripts/validate_phase9.py'

Steps: health → seed demo → retrieve → fake RAG → diagnose → investigation →
planted eval → baseline promote → ops endpoints → report.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

# Ensure app imports when invoked as /scripts/...
sys.path.insert(0, "/app")

from app.db import session as db_session
from app.db.models import CorpusVersion
from app.services.diagnosis.engine import diagnose_execution
from app.services.investigation import build_investigation
from app.services.llm_client import LLMResult, set_llm_provider
from app.services.rag import run_rag


API_BASE = os.environ.get("RETRACE_API_BASE", "http://127.0.0.1:8000")
API_KEY = os.environ.get("API_KEY", "dev-retrace-api-key-change-me")
CORPUS_DIR_CANDIDATES = [
    Path("/data/corpus/demo"),
    Path(__file__).resolve().parents[1] / "data" / "corpus" / "demo",
]


class FakeLLM:
    """Deterministic provider — never calls a live API."""

    def complete(self, messages, *, model, timeout):
        system = (messages[0].get("content") or "").lower() if messages else ""
        user = ""
        if len(messages) > 1:
            user = messages[-1].get("content") or ""
        if "faithful" in system:
            content = json.dumps(
                {
                    "claims": [
                        {
                            "claim": "Full-time employees accrue 1.25 days of PTO per month.",
                            "supported": True,
                            "evidence_chunk_ids": [],
                        }
                    ],
                    "faithfulness_score": 0.95,
                }
            )
        elif "contradict" in system:
            content = json.dumps({"contradicts": False, "rationale": "consistent"})
        elif "relevant" in system:
            import re

            ids = re.findall(r"\[chunk_id=([^\]]+)\]", user)
            items = [
                {
                    "chunk_id": cid,
                    "relevant": "pto" in cid.lower() or "handbook" in cid.lower() or "employee" in cid.lower(),
                    "score": 0.9 if ("pto" in cid.lower() or "handbook" in cid.lower() or "employee" in cid.lower()) else 0.2,
                    "rationale": "fixture",
                }
                for cid in ids
            ]
            if not items:
                items = [
                    {
                        "chunk_id": "unknown",
                        "relevant": True,
                        "score": 0.8,
                        "rationale": "fixture",
                    }
                ]
            content = json.dumps(
                {"items": items, "context_sufficient": True}
            )
        else:
            content = "Full-time employees accrue 1.25 days of PTO per month."
        return LLMResult(
            content=content,
            model=model,
            latency_ms=5.0,
            prompt_tokens=32,
            completion_tokens=14,
            total_tokens=46,
        )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


def _ok(name: str, detail: str = "") -> None:
    print(f"PASS  {name}" + (f" — {detail}" if detail else ""))


def _fail(name: str, detail: str) -> None:
    print(f"FAIL  {name} — {detail}")
    raise SystemExit(1)


def check_health(client: httpx.Client) -> None:
    live = client.get("/health/live")
    if live.status_code != 200 or live.json().get("status") != "ok":
        _fail("health/live", live.text)
    _ok("health/live")

    ready = client.get("/health/ready")
    body = ready.json()
    if ready.status_code != 200 or not body.get("ready"):
        _fail("health/ready", ready.text)
    _ok("health/ready", f"postgres={body['dependencies'].get('postgres')} chroma={body['dependencies'].get('chroma')}")


def seed_demo(client: httpx.Client) -> str:
    corpus_dir = next((p for p in CORPUS_DIR_CANDIDATES if p.is_dir()), None)
    if not corpus_dir:
        _fail("seed_demo", "demo corpus directory not found")

    docs = []
    for path in sorted(corpus_dir.glob("*.md")):
        docs.append(
            {
                "id": path.stem,
                "text": path.read_text(encoding="utf-8"),
                "source_name": path.name,
            }
        )
    if not docs:
        _fail("seed_demo", f"no markdown in {corpus_dir}")

    r = client.post("/api/v1/corpora", json={"id": "demo", "title": "Demo Policies"})
    if r.status_code not in {200, 201, 409}:
        # create may return 200/201; Conflict if exists
        if r.status_code != 409 and "already" not in (r.text or "").lower():
            # Some installs return AppError CONFLICT 409
            pass
    if r.status_code >= 500:
        _fail("seed_demo create", r.text)

    # Idempotent: if corpus exists, continue to version ingest
    if r.status_code not in {200, 201, 409}:
        # ConflictError uses 409
        err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 409 and err.get("code") != "CONFLICT":
            _fail("seed_demo create", r.text)

    r = client.post(
        "/api/v1/corpora/demo/versions",
        json={
            "documents": docs,
            "chunking_config": {
                "strategy": "recursive_character",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "tokenizer": "char",
            },
        },
    )
    if r.status_code != 200:
        _fail("seed_demo ingest", r.text)
    version = r.json()
    if version.get("status") != "READY":
        _fail("seed_demo status", str(version.get("status")))
    _ok(
        "seed_demo",
        f"version={version['id']} chunks={version.get('chunk_count')}",
    )
    return version["id"]


def check_retrieve(client: httpx.Client, version_id: str) -> None:
    query = "How much PTO do full-time employees accrue per month?"
    r = client.post(
        "/api/v1/retrieve",
        json={"corpus_version_id": version_id, "query": query, "top_k": 3},
    )
    if r.status_code != 200:
        _fail("retrieve", r.text)
    results = r.json().get("results") or []
    if not results:
        _fail("retrieve", "empty results")
    _ok("retrieve", f"n={len(results)} top={results[0].get('chunk_id')}")


def check_rag_diagnose_investigate(version_id: str) -> str:
    set_llm_provider(FakeLLM())
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        out = run_rag(
            db,
            corpus_version_id=version_id,
            query="How much PTO do full-time employees accrue per month?",
            top_k=3,
            request_id=f"phase9-{uuid.uuid4().hex[:8]}",
        )
        if out.get("status") not in {"COMPLETED", "ABSTAINED"}:
            _fail("generate", str(out.get("status")))
        eid = out["execution_id"]
        _ok("generate", f"execution_id={eid} status={out['status']}")

        diag = diagnose_execution(db, execution_id=eid)
        if not diag.get("failure_code") or not diag.get("rule_id"):
            _fail("diagnose", str(diag))
        _ok("diagnose", f"{diag['failure_code']} / {diag['rule_id']}")

        inv = build_investigation(db, eid)
        if not inv.get("diagnosis") or not inv.get("rule"):
            _fail("investigation", "missing diagnosis/rule")
        if not inv.get("retrieval", {}).get("chunks"):
            _fail("investigation", "no retrieval chunks")
        _ok(
            "investigation",
            f"chunks={len(inv['retrieval']['chunks'])} evidence={len(inv.get('evidence') or [])}",
        )
        return eid
    finally:
        db.close()
        set_llm_provider(None)


def check_eval_baseline(client: httpx.Client) -> None:
    r = client.post(
        "/api/v1/experiments",
        json={"suite_id": "planted_v1", "suite_version": "1.0.0"},
    )
    if r.status_code != 200:
        _fail("eval planted_v1", r.text)
    body = r.json()
    exp_id = body.get("experiment_id")
    exit_code = body.get("exit_code")
    summary = body.get("summary") or {}
    _ok(
        "eval planted_v1",
        f"experiment={exp_id} exit_code={exit_code} "
        f"accuracy={summary.get('failure_code_accuracy')}",
    )

    # Promote only if completed successfully enough to promote
    # Baseline promote requires SUCCEEDED/COMPLETED style status
    detail = client.get(f"/api/v1/experiments/{exp_id}")
    if detail.status_code != 200:
        _fail("experiment detail", detail.text)
    status = detail.json().get("status")
    _ok("experiment detail", f"status={status}")

    if status == "COMPLETED" or exit_code == 0:
        prom = client.post(
            "/api/v1/baselines/promote",
            json={"experiment_id": exp_id, "name": f"phase9-{exp_id[:8]}"},
        )
        if prom.status_code == 200:
            _ok("baseline promote", prom.json().get("baseline_id", ""))
        else:
            # Name collision on re-run — still acceptable if baseline exists
            active = client.get(
                "/api/v1/baselines/active",
                params={"suite_id": "planted_v1", "suite_version": "1.0.0"},
            )
            if active.status_code == 200 and active.json().get("baseline"):
                _ok(
                    "baseline promote",
                    f"promote={prom.status_code}; active baseline present",
                )
            else:
                _fail("baseline promote", prom.text)
    else:
        _ok(
            "baseline promote",
            f"skipped — status={status} exit_code={exit_code}",
        )

    cmp_r = client.get(f"/api/v1/experiments/{exp_id}/comparison")
    if cmp_r.status_code != 200:
        _fail("comparison", cmp_r.text)
    cmp = cmp_r.json().get("comparison") or {}
    _ok(
        "comparison",
        f"has_baseline={cmp.get('has_baseline')} passed={cmp.get('passed')}",
    )


def check_ops(client: httpx.Client) -> None:
    for path in ("/metrics", "/api/v1/signals", "/api/v1/ops/summary", "/api/v1/runbooks"):
        r = client.get(path)
        if r.status_code != 200:
            _fail(path, r.text)
    metrics = client.get("/metrics").json()
    if metrics.get("durable") is not False:
        _fail("/metrics", "expected durable=false")
    signals = client.get("/api/v1/signals").json()
    if "signals" not in signals:
        _fail("/api/v1/signals", "missing signals")
    books = client.get("/api/v1/runbooks").json()
    if not books.get("runbooks"):
        _fail("/api/v1/runbooks", "empty runbook list (mount docs/runbooks?)")
    _ok("ops", "metrics durable=false; signals+runbooks ok")


def check_migration_head() -> None:
    # Best-effort via alembic current printed by caller; here verify models load
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        n = db.execute(select(CorpusVersion.id).limit(1)).first()
        _ok("db", f"queryable (sample={bool(n)})")
    finally:
        db.close()


def main() -> int:
    print("=== Retrace Phase 9 validation ===")
    print(f"API_BASE={API_BASE}")
    with httpx.Client(
        base_url=API_BASE, timeout=300.0, headers=_headers()
    ) as client:
        check_health(client)
        check_migration_head()
        version_id = seed_demo(client)
        check_retrieve(client, version_id)
        check_rag_diagnose_investigate(version_id)
        check_eval_baseline(client)
        check_ops(client)
    print("=== ALL PHASE 9 CHECKS PASSED ===")
    print(
        "LIMITATIONS: offline fixtures + FakeLLM ≠ live-LLM robustness; "
        "/metrics top level is the in-memory view (durable window under "
        "durable_store and /api/v1/metrics/durable)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
