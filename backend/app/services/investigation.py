"""Assemble an investigation payload for the Phase 8 evidence UI."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models import Diagnosis, DiagnosisEvidence, ExecutionTrace, JudgeResult
from app.services.diagnosis.engine import _to_response
from app.services.diagnosis.rule_catalog import (
    RUNBOOK_BY_FAILURE,
    get_rule,
)
from app.services.diagnosis.taxonomy import FAILURE_CODES


def _chunk_status(
    chunk_id: str,
    *,
    gold_ids: set[str],
    relevance_by_id: dict[str, dict[str, Any]],
) -> str:
    rel = relevance_by_id.get(chunk_id)
    if gold_ids and chunk_id in gold_ids:
        return "expected"
    if rel is not None:
        label = str(rel.get("label") or "").lower()
        score = rel.get("score")
        if label in {"relevant", "yes", "true"} or (
            isinstance(score, (int, float)) and score >= 0.5
        ):
            return "relevant"
        return "distractor"
    return "retrieved"


def _enrich_chunks(
    chunks: list[dict[str, Any]],
    signals: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    signals = signals or {}
    gold_ids = {str(x) for x in (signals.get("gold_ids") or [])}
    relevance_items = signals.get("chunk_relevance") or []
    relevance_by_id: dict[str, dict[str, Any]] = {}
    for item in relevance_items:
        if isinstance(item, dict) and item.get("chunk_id"):
            relevance_by_id[str(item["chunk_id"])] = item

    enriched: list[dict[str, Any]] = []
    for c in chunks:
        cid = str(c.get("chunk_id") or "")
        rel = relevance_by_id.get(cid)
        status = _chunk_status(cid, gold_ids=gold_ids, relevance_by_id=relevance_by_id)
        # Snapshot stores retrieval_score; older payloads may use score.
        score = c.get("score")
        if score is None:
            score = c.get("retrieval_score")
        enriched.append(
            {
                "chunk_id": cid or None,
                "document_id": c.get("document_id"),
                "source_name": c.get("source_name"),
                "rank": c.get("rank"),
                "score": score,
                "text": c.get("text"),
                "chunk_index": c.get("chunk_index"),
                "relevance": rel,
                "evidence_status": status,
                "is_gold_expected": bool(cid and cid in gold_ids),
            }
        )

    # Surface gold chunks that were never retrieved
    retrieved_ids = {str(c.get("chunk_id")) for c in chunks if c.get("chunk_id")}
    for gid in sorted(gold_ids - retrieved_ids):
        enriched.append(
            {
                "chunk_id": gid,
                "document_id": None,
                "source_name": None,
                "rank": None,
                "score": None,
                "text": None,
                "chunk_index": None,
                "relevance": None,
                "evidence_status": "missing",
                "is_gold_expected": True,
            }
        )
    return enriched


_JUDGE_TIMELINE_ORDER = {
    "relevance": 0,
    "faithfulness": 1,
    "contradiction": 2,
}


def _timeline(
    execution: ExecutionTrace,
    diagnosis: Diagnosis | None,
    judges: list[JudgeResult],
) -> list[dict[str, Any]]:
    """Build an engineering trace.

    Durations:
    - retrieval / generation: from the generate (RAG) request
    - judge:*: individual LLM call durations inside diagnose (sequential)
    - diagnosis: diagnose request wall-clock (includes judges when they ran)

    Generate total and diagnosis wall-clock are separate requests; they must
    not be summed into a single implied end-to-end total in the UI.
    """
    rows: list[dict[str, Any]] = [
        {
            "operation": "request",
            "status": "ok",
            "duration_ms": None,
            "id": execution.request_id,
            "phase": "generate",
        },
        {
            "operation": "retrieval",
            "status": "ok" if execution.retrieval_trace_id else "skipped",
            "duration_ms": execution.retrieval_latency_ms,
            "id": execution.retrieval_trace_id,
            "phase": "generate",
        },
        {
            "operation": "generation",
            "status": execution.status,
            "duration_ms": execution.generation_latency_ms,
            "id": execution.id,
            "phase": "generate",
        },
    ]
    ordered = sorted(
        judges,
        key=lambda j: (_JUDGE_TIMELINE_ORDER.get(j.judge_type, 99), j.judge_type),
    )
    for j in ordered:
        rows.append(
            {
                "operation": f"judge:{j.judge_type}",
                "status": "ok" if j.schema_ok else "malformed",
                "duration_ms": j.latency_ms,
                "id": j.id,
                "phase": "diagnose",
            }
        )
    if diagnosis:
        metrics = (diagnosis.signals or {}).get("metrics") or {}
        rows.append(
            {
                "operation": "diagnosis",
                "status": diagnosis.primary_code,
                "duration_ms": metrics.get("diagnosis_latency_ms"),
                "id": diagnosis.id,
                "phase": "diagnose",
            }
        )
    return rows


def _judges_payload(judges: list[JudgeResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for j in judges:
        output = j.output if isinstance(j.output, dict) else {"raw": j.output}
        result_summary: dict[str, Any] = {}
        if j.judge_type == "relevance":
            result_summary = {
                "context_sufficient": output.get("context_sufficient"),
                "item_count": len(output.get("items") or []),
            }
        elif j.judge_type == "faithfulness":
            result_summary = {
                "faithfulness_score": output.get("faithfulness_score"),
                "claim_count": len(output.get("claims") or []),
            }
        elif j.judge_type == "contradiction":
            result_summary = {
                "contradicts": output.get("contradicts"),
            }
        out.append(
            {
                "judge_type": j.judge_type,
                "status": "ok" if j.schema_ok else "malformed",
                "schema_ok": j.schema_ok,
                "model": j.model,
                "prompt_version": j.prompt_version,
                "latency_ms": j.latency_ms,
                "attempts": j.attempts,
                "result": result_summary,
                "output": output,
            }
        )
    return out


def build_investigation(db: Session, execution_id: str) -> dict[str, Any]:
    execution = db.get(ExecutionTrace, execution_id)
    if not execution:
        raise NotFoundError(f"Execution not found: {execution_id}")

    diagnosis = db.execute(
        select(Diagnosis).where(Diagnosis.execution_id == execution_id)
    ).scalars().first()

    judges = (
        db.execute(
            select(JudgeResult)
            .where(JudgeResult.execution_id == execution_id)
            .order_by(JudgeResult.judge_type.asc())
        )
        .scalars()
        .all()
    )

    evidence_rows: list[dict[str, Any]] = []
    diagnosis_payload = None
    rule = None
    signals: dict[str, Any] = {}
    if diagnosis:
        diagnosis_payload = _to_response(diagnosis, execution)
        signals = diagnosis.signals if isinstance(diagnosis.signals, dict) else {}
        rule = get_rule(diagnosis.rule_id)
        rows = (
            db.execute(
                select(DiagnosisEvidence).where(
                    DiagnosisEvidence.diagnosis_id == diagnosis.id
                )
            )
            .scalars()
            .all()
        )
        evidence_rows = [
            {
                "evidence_type": r.evidence_type,
                "ref": r.ref,
                "payload": r.payload,
            }
            for r in rows
        ]

    chunks = list(execution.retrieved_chunks or [])
    failure_code = diagnosis.primary_code if diagnosis else None
    failure_meta = FAILURE_CODES.get(failure_code) if failure_code else None

    abstention_kind = None
    if execution.abstained or failure_code in {
        "OK_CORRECT_ABSTENTION",
        "ABSTENTION_FALSE_NEGATIVE",
        "ABSTENTION_FALSE_POSITIVE",
    }:
        if failure_code == "OK_CORRECT_ABSTENTION":
            abstention_kind = "CORRECT_ABSTENTION"
        elif failure_code == "ABSTENTION_FALSE_NEGATIVE":
            abstention_kind = "FALSE_NEGATIVE_ABSTENTION"
        elif failure_code == "ABSTENTION_FALSE_POSITIVE":
            abstention_kind = "FALSE_POSITIVE_ABSTENTION"
        elif execution.abstained:
            abstention_kind = "ABSTAINED"

    return {
        "execution": {
            "execution_id": execution.id,
            "request_id": execution.request_id,
            "corpus_version_id": execution.corpus_version_id,
            "retrieval_trace_id": execution.retrieval_trace_id,
            "query": execution.query,
            "status": execution.status,
            "error_code": execution.error_code,
            "error_message": execution.error_message,
            "abstained": execution.abstained,
            "abstention_kind": abstention_kind,
            "answer": execution.answer_text,
            "top_k": execution.top_k,
            "generation": {
                "model": execution.generation_model,
                "temperature": execution.generation_temperature,
                "prompt_version": execution.prompt_version,
                "latency_ms": execution.generation_latency_ms,
                "prompt_tokens": execution.prompt_tokens,
                "completion_tokens": execution.completion_tokens,
                "total_tokens": execution.total_tokens,
            },
            "embedding": {
                "model": execution.embedding_model,
                "revision": execution.embedding_revision,
            },
            "latency_ms": {
                # Generate (RAG) request wall-clock — excludes diagnose/judges.
                "retrieval": execution.retrieval_latency_ms,
                "generation": execution.generation_latency_ms,
                "total": execution.total_latency_ms,
                "generate_total": execution.total_latency_ms,
                # Diagnose request wall-clock (sequential judges live inside this).
                "diagnosis": (
                    (signals.get("metrics") or {}).get("diagnosis_latency_ms")
                    if isinstance(signals.get("metrics"), dict)
                    else None
                ),
            },
        },
        "diagnosis": diagnosis_payload,
        "rule": rule,
        "failure": (
            {
                "code": failure_code,
                "description": failure_meta.description if failure_meta else None,
                "layer": diagnosis.layer if diagnosis else None,
                "runbook": RUNBOOK_BY_FAILURE.get(failure_code or ""),
            }
            if diagnosis
            else None
        ),
        "retrieval": {
            "chunks": _enrich_chunks(chunks, signals),
            "gold_ids": signals.get("gold_ids") or [],
            # No gold reference ⇒ not evaluated (null). Preserve true/false only when gold_ids present.
            "gold_hit": (
                signals.get("gold_hit")
                if (signals.get("gold_ids") or [])
                else None
            ),
            "gold_recall_at_k": (
                signals.get("gold_recall_at_k")
                if (signals.get("gold_ids") or [])
                else None
            ),
            "n_retrieved": signals.get("n_retrieved", len(chunks)),
            "context_sufficient": signals.get("context_sufficient"),
            "irrelevant_frac": signals.get("irrelevant_frac"),
        },
        "judges": _judges_payload(list(judges)),
        "evidence": evidence_rows,
        "timeline": _timeline(execution, diagnosis, list(judges)),
        "why": {
            "engine": "deterministic_rule_engine",
            "note": (
                "Diagnosis is produced by ordered rules (first match wins), "
                "not by a free-form LLM explanation."
            ),
            "signals_used": {
                k: signals.get(k)
                for k in (
                    "n_retrieved",
                    "gold_hit",
                    "context_sufficient",
                    "answer_is_abstention",
                    "answer_contradicts_context",
                    "faithfulness_score",
                    "unsupported_claim_count",
                    "supported_claim_count",
                    "irrelevant_frac",
                    "stage_error",
                    "judge_schema_ok",
                )
                if k in signals
            },
            "rule": rule,
        },
    }
