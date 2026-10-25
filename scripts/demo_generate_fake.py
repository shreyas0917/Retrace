"""One-off Phase 3 e2e generate using FakeLLM (no paid API)."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session as db_session
from app.db.models import CorpusVersion
from app.services.llm_client import LLMResult, set_llm_provider
from app.services.rag import run_rag


class Fake:
    def complete(self, messages, *, model, timeout):
        return LLMResult(
            content="Full-time employees accrue 1.25 days of PTO per month.",
            model=model,
            latency_ms=5.0,
            prompt_tokens=32,
            completion_tokens=14,
            total_tokens=46,
        )


def main() -> int:
    set_llm_provider(Fake())
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        version = db.execute(
            select(CorpusVersion)
            .where(CorpusVersion.status == "READY")
            .order_by(CorpusVersion.created_at.desc())
        ).scalars().first()
        if not version:
            print("No READY corpus version — run seed_demo_corpus.py first")
            return 1
        out = run_rag(
            db,
            corpus_version_id=version.id,
            query="How much PTO do full-time employees accrue per month?",
            top_k=3,
            request_id="demo-e2e-001",
        )
        print("execution_id:", out["execution_id"])
        print("status:", out["status"])
        print("answer:", out["answer"])
        print("retrieval_trace_id:", out["retrieval"]["retrieval_trace_id"])
        print("chunks:", [r["chunk_id"] for r in out["retrieval"]["results"]])
        print("gen_latency_ms:", out["generation"]["latency_ms"])
        print("tokens:", out["generation"]["total_tokens"])
        return 0
    finally:
        db.close()
        set_llm_provider(None)


if __name__ == "__main__":
    raise SystemExit(main())
