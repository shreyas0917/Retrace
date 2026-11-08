"""live_v1: record real pipeline runs, replay them offline.

The live builder (scripts/build_live_suite.py) runs each query through real
retrieval, real generation and real judges, and appends one *run record* per
query to `runs.jsonl`. This module holds the pieces that do not need a live
model:

* `RecordingLLM` wraps the real provider during diagnosis and keeps every raw
  judge reply, per judge type and in call order, which is exactly what
  `ScriptedJudgeLLM` replays.
* `record_to_offline_execution` turns a run record into the `OfflineExecution`
  a suite case carries, so the suite re-diagnoses offline.
* `replay_record` re-diagnoses a record offline. The builder uses it to check
  that replay reproduces the live diagnosis before anything is labelled.

Run records hold Retrace's own live prediction and the injected condition.
Neither may reach the labelling sheet (scripts/live_labelling.py).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import GenerationTimeoutError
from app.db.models import ExecutionTrace
from app.services.diagnosis.engine import diagnose_execution
from app.services.eval.fakes import ScriptedJudgeLLM, detect_judge_type
from app.services.eval.schemas import OfflineExecution
from app.services.judges.replay import replaying_judges
from app.services.llm_client import LLMResult, set_llm_provider

RUN_RECORD_VERSION = "live_run.v1"


class RecordingLLM:
    """Delegate to a real provider and keep each raw judge reply."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.replies: dict[str, list[str]] = {}
        self.timeouts: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[dict[str, str]], *, model: str, timeout: float) -> LLMResult:
        judge = detect_judge_type(messages)
        try:
            result = self.inner.complete(messages, model=model, timeout=timeout)
        except GenerationTimeoutError:
            self.timeouts.append(judge)
            self.calls.append({"judge": judge, "timeout": True})
            raise
        self.replies.setdefault(judge, []).append(result.content)
        self.calls.append({"judge": judge, "latency_ms": result.latency_ms, "model": result.model})
        return result


def runs_hash(lines: list[str]) -> str:
    """Same canonical hashing as suite files: sorted keys, compact separators."""
    canonical = [
        json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for line in lines
        if line.strip()
    ]
    payload = "\n".join(canonical) + ("\n" if canonical else "")
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def judge_scripts_from_record(record: dict[str, Any]) -> dict[str, Any]:
    judges = record.get("judges") or {}
    scripts: dict[str, Any] = {}
    for judge in ("relevance", "contradiction"):
        if judges.get(judge):
            scripts[judge] = list(judges[judge])
    if judges.get("faithfulness_llm"):
        # Kept for comparison; the router replays faithfulness_nli when present.
        scripts["faithfulness"] = list(judges["faithfulness_llm"])
    if judges.get("faithfulness_nli") is not None:
        scripts["faithfulness_nli"] = judges["faithfulness_nli"]
    return scripts


def record_to_offline_execution(record: dict[str, Any]) -> OfflineExecution:
    execution = record["execution"]
    return OfflineExecution(
        retrieved_chunks=list(execution.get("retrieved_chunks") or []),
        answer=execution.get("answer"),
        abstained=bool(execution.get("abstained")),
        status=execution.get("status") or "COMPLETED",
        error_code=execution.get("error_code"),
        judge_scripts=judge_scripts_from_record(record),
        generation_model=(record.get("generation") or {}).get("model"),
        prompt_version=(record.get("generation") or {}).get("prompt_version"),
        judge_timeout_on=((record.get("judges") or {}).get("timeouts") or [None])[0],
    )


def insert_offline_execution(
    db: Session, *, corpus_version_id: str, query: str, fixture: OfflineExecution, request_tag: str
) -> str:
    eid = str(uuid.uuid4())
    db.add(
        ExecutionTrace(
            id=eid,
            request_id=f"replay-{request_tag}-{uuid.uuid4().hex[:8]}",
            corpus_version_id=corpus_version_id,
            query=query,
            retrieval_trace_id=None,
            top_k=max(5, len(fixture.retrieved_chunks)),
            retrieved_chunks=fixture.retrieved_chunks,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_revision="sentence-transformers/all-MiniLM-L6-v2@sentence-transformers-local",
            generation_model=fixture.generation_model or "unknown",
            generation_temperature=0.0,
            prompt_version=fixture.prompt_version or "generator.v1",
            answer_text=fixture.answer,
            abstained=fixture.abstained,
            status=fixture.status,
            error_code=fixture.error_code,
        )
    )
    db.commit()
    return eid


def replay_record(
    db: Session,
    record: dict[str, Any],
    *,
    corpus_version_id: str,
    gold_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-diagnose a run record offline from its recorded judge outputs."""
    fixture = record_to_offline_execution(record)
    scripts = fixture.judge_scripts or {}
    set_llm_provider(
        ScriptedJudgeLLM(
            {k: v for k, v in scripts.items() if isinstance(v, list)},
            timeout_on=fixture.judge_timeout_on,
        )
    )
    try:
        eid = insert_offline_execution(
            db,
            corpus_version_id=corpus_version_id,
            query=record["query"],
            fixture=fixture,
            request_tag=str(record.get("query_id")),
        )
        with replaying_judges(scripts):
            return diagnose_execution(db, execution_id=eid, gold_chunk_ids=gold_chunk_ids or None)
    finally:
        set_llm_provider(None)


def prediction_summary(diagnosis: dict[str, Any]) -> dict[str, Any]:
    return {
        "failure_code": diagnosis.get("failure_code"),
        "rule_id": diagnosis.get("rule_id"),
        "calibrated_confidence": diagnosis.get("calibrated_confidence"),
        "uncertain": bool(diagnosis.get("uncertain", False)),
    }
