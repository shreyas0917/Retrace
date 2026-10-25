"""Diagnosis engine — load execution → deterministic checks → judges → rules → persist."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.logging import bind_correlation, get_logger
from app.core.ops import record_diagnosis  # noqa: F401 — used via _emit_ops
from app.db.models import Diagnosis, DiagnosisEvidence, ExecutionTrace, JudgeResult
from app.services.diagnosis.models import DiagnosisDecision, SignalBag
from app.services.diagnosis.rules import apply_rules, needs_judges
from app.services.diagnosis.taxonomy import TAXONOMY_VERSION
from app.services.diagnosis.thresholds import (
    TAU_REL,
    THRESHOLDS_VERSION,
)
from app.services.judges.base import JudgeMalformedError
from app.services.judges.contradiction import (
    CONTRADICTION_PROMPT_VERSION,
    judge_contradiction,
)
from app.services.judges.faithfulness import (
    FAITHFULNESS_PROMPT_VERSION,
    judge_faithfulness,
)
from app.services.judges.relevance import RELEVANCE_PROMPT_VERSION, judge_relevance
from app.services.prompts import ABSTENTION_ANSWER

logger = get_logger(__name__)


def _emit_ops(decision: DiagnosisDecision, started: float) -> None:
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    record_diagnosis(
        failure_code=decision.primary_code,
        rule_id=decision.rule_id,
        layer=decision.layer,
        latency_ms=latency_ms,
    )


def _input_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _base_signals(
    execution: ExecutionTrace,
    gold_chunk_ids: list[str] | None,
) -> SignalBag:
    chunks = execution.retrieved_chunks or []
    retrieved_ids = [str(c.get("chunk_id")) for c in chunks if c.get("chunk_id")]
    gold_ids = list(gold_chunk_ids or [])
    gold_set = set(gold_ids)
    retrieved_set = set(retrieved_ids)
    if gold_ids:
        gold_hit: bool | None = bool(gold_set & retrieved_set)
        recall: float | None = len(gold_set & retrieved_set) / max(len(gold_set), 1)
    else:
        gold_hit = None
        recall = None

    abstained = bool(execution.abstained) or (
        (execution.answer_text or "").strip() == ABSTENTION_ANSWER
    )

    stage_error = None
    if execution.status == "GENERATION_TIMEOUT" or execution.error_code == "GENERATION_TIMEOUT":
        stage_error = "TIMEOUT"

    return SignalBag(
        n_retrieved=len(retrieved_ids),
        retrieved_ids=retrieved_ids,
        gold_ids=gold_ids,
        gold_hit=gold_hit,
        gold_recall_at_k=recall,
        answer_is_abstention=abstained,
        stage_error=stage_error,
        missing_answer=execution.answer_text is None
        and execution.status not in {"ABSTAINED", "GENERATION_TIMEOUT", "FAILED"},
    )


def _persist_judge(
    db: Session,
    *,
    execution_id: str,
    judge_type: str,
    prompt_version: str,
    meta: dict[str, Any],
    output: dict[str, Any],
    input_payload: dict[str, Any],
) -> None:
    row = JudgeResult(
        id=str(uuid.uuid4()),
        run_id=None,
        execution_id=execution_id,
        judge_type=judge_type,
        prompt_version=prompt_version,
        model=str(meta.get("model") or ""),
        input_hash=_input_hash(input_payload),
        output=output,
        schema_ok=bool(meta.get("schema_ok")),
        attempts=int(meta.get("attempts") or 1),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    db.add(row)


def _persist_diagnosis(
    db: Session,
    *,
    execution: ExecutionTrace,
    decision: DiagnosisDecision,
) -> Diagnosis:
    existing = db.execute(
        select(Diagnosis).where(Diagnosis.execution_id == execution.id)
    ).scalars().first()
    if existing:
        # Idempotent: return prior diagnosis; do not overwrite history.
        return existing

    diagnosis = Diagnosis(
        id=str(uuid.uuid4()),
        run_id=None,
        execution_id=execution.id,
        taxonomy_version=TAXONOMY_VERSION,
        primary_code=decision.primary_code,
        secondary_codes=decision.secondary_codes or None,
        rule_id=decision.rule_id,
        layer=decision.layer,
        diagnosis_confidence=decision.diagnosis_confidence,
        diagnosis_score=decision.diagnosis_score,
        recommendation_code=decision.recommendation_code,
        signals={
            **decision.signals,
            "metrics": decision.metrics,
            "thresholds_version": THRESHOLDS_VERSION,
            "judges_ran": decision.judges_ran,
        },
    )
    db.add(diagnosis)
    db.flush()

    for ref in decision.evidence_refs:
        evidence_type = "chunk" if ref.startswith("chunk:") else "signal"
        db.add(
            DiagnosisEvidence(
                diagnosis_id=diagnosis.id,
                evidence_type=evidence_type,
                ref=ref,
                payload={"ref": ref},
            )
        )
    if execution.retrieval_trace_id:
        db.add(
            DiagnosisEvidence(
                diagnosis_id=diagnosis.id,
                evidence_type="retrieval_trace",
                ref=f"retrieval_trace:{execution.retrieval_trace_id}",
                payload={"retrieval_trace_id": execution.retrieval_trace_id},
            )
        )
    db.add(
        DiagnosisEvidence(
            diagnosis_id=diagnosis.id,
            evidence_type="execution",
            ref=f"execution:{execution.id}",
            payload={"execution_id": execution.id, "request_id": execution.request_id},
        )
    )
    db.commit()
    db.refresh(diagnosis)
    return diagnosis


def diagnose_execution(
    db: Session,
    *,
    execution_id: str,
    gold_chunk_ids: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Diagnose a stored execution. Deterministic rules first; judges if needed."""
    settings = settings or get_settings()
    started = time.perf_counter()
    execution = db.get(ExecutionTrace, execution_id)
    if not execution:
        raise NotFoundError(f"Execution not found: {execution_id}")

    bind_correlation(
        request_id=execution.request_id,
        execution_id=execution.id,
        corpus_version_id=execution.corpus_version_id,
        retrieval_trace_id=execution.retrieval_trace_id,
        operation="diagnosis",
    )

    existing = db.execute(
        select(Diagnosis).where(Diagnosis.execution_id == execution_id)
    ).scalars().first()
    if existing:
        logger.info(
            "diagnosis_idempotent_hit",
            execution_id=execution_id,
            diagnosis_id=existing.id,
        )
        return _to_response(existing, execution)

    signals = _base_signals(execution, gold_chunk_ids)
    chunks = list(execution.retrieved_chunks or [])
    metrics: dict[str, Any] = {
        "retrieval_latency_ms": execution.retrieval_latency_ms,
        "generation_latency_ms": execution.generation_latency_ms,
        "total_latency_ms": execution.total_latency_ms,
        "top_k": execution.top_k,
        "retrieved_chunk_count": signals.n_retrieved,
    }
    judges_ran = False

    # Short-circuit infra / empty / gold miss without judges
    if not needs_judges(signals):
        decision = apply_rules(signals)
        metrics["diagnosis_latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        decision.metrics = metrics
        decision.judges_ran = False
        # Ensure evidence includes retrieval refs for empty case
        if "retrieval:empty" not in decision.evidence_refs and signals.n_retrieved == 0:
            decision.evidence_refs.append("retrieval:empty")
        row = _persist_diagnosis(db, execution=execution, decision=decision)
        _emit_ops(decision, started)
        return _to_response(row, execution)

    try:
        # Relevance always needed when judges run
        rel, rel_meta = judge_relevance(execution.query, chunks, settings=settings)
        judges_ran = True
        _persist_judge(
            db,
            execution_id=execution.id,
            judge_type="relevance",
            prompt_version=RELEVANCE_PROMPT_VERSION,
            meta=rel_meta,
            output=rel.model_dump(),
            input_payload={"query": execution.query, "chunk_ids": signals.retrieved_ids},
        )
        metrics["relevance_judge_latency_ms"] = rel_meta.get("latency_ms")

        scores = [item.score for item in rel.items]
        irrelevant = sum(1 for s in scores if s < TAU_REL)
        signals.irrelevant_frac = (
            irrelevant / max(len(scores), 1) if scores else 1.0
        )
        signals.context_sufficient = bool(rel.context_sufficient)
        signals.chunk_relevance = [i.model_dump() for i in rel.items]

        # Faithfulness + contradiction only when context is sufficient and answered
        answer = (execution.answer_text or "").strip()
        if (
            answer
            and not signals.answer_is_abstention
            and signals.context_sufficient is True
        ):
            faith, faith_meta = judge_faithfulness(
                execution.query, answer, chunks, settings=settings
            )
            _persist_judge(
                db,
                execution_id=execution.id,
                judge_type="faithfulness",
                prompt_version=FAITHFULNESS_PROMPT_VERSION,
                meta=faith_meta,
                output=faith.model_dump(),
                input_payload={
                    "query": execution.query,
                    "answer": answer,
                    "chunk_ids": signals.retrieved_ids,
                },
            )
            metrics["faithfulness_judge_latency_ms"] = faith_meta.get("latency_ms")
            signals.faithfulness_score = faith.faithfulness_score
            signals.unsupported_claim_count = sum(
                1 for c in faith.claims if not c.supported
            )
            signals.supported_claim_count = sum(1 for c in faith.claims if c.supported)

            contra, contra_meta = judge_contradiction(
                execution.query, answer, chunks, settings=settings
            )
            _persist_judge(
                db,
                execution_id=execution.id,
                judge_type="contradiction",
                prompt_version=CONTRADICTION_PROMPT_VERSION,
                meta=contra_meta,
                output=contra.model_dump(),
                input_payload={
                    "query": execution.query,
                    "answer": answer,
                    "chunk_ids": signals.retrieved_ids,
                },
            )
            metrics["contradiction_judge_latency_ms"] = contra_meta.get("latency_ms")
            signals.answer_contradicts_context = bool(contra.contradicts)
        else:
            # Insufficient context or abstained: grounding judges not required
            signals.faithfulness_score = (
                1.0 if signals.answer_is_abstention else None
            )
            signals.unsupported_claim_count = 0
            signals.supported_claim_count = 0
            signals.answer_contradicts_context = False

        signals.judge_schema_ok = True
        decision = apply_rules(signals)
        metrics["diagnosis_latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        decision.metrics = metrics
        decision.judges_ran = judges_ran
        row = _persist_diagnosis(db, execution=execution, decision=decision)
        logger.info(
            "diagnosis_completed",
            execution_id=execution.id,
            primary_code=decision.primary_code,
            rule_id=decision.rule_id,
            confidence=decision.diagnosis_confidence,
            failure_code=decision.primary_code,
            operation="diagnosis",
        )
        _emit_ops(decision, started)
        return _to_response(row, execution)

    except JudgeMalformedError as exc:
        signals.judge_schema_ok = False
        decision = apply_rules(signals)
        metrics["diagnosis_latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        decision.metrics = metrics
        decision.judges_ran = judges_ran
        decision.evidence_refs.append(f"judge:{exc.judge_type}:malformed")
        row = _persist_diagnosis(db, execution=execution, decision=decision)
        db.commit()
        _emit_ops(decision, started)
        return _to_response(row, execution)


def _to_response(diagnosis: Diagnosis, execution: ExecutionTrace) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if isinstance(diagnosis.signals, dict):
        metrics = diagnosis.signals.get("metrics") or {}
    return {
        "diagnosis_id": diagnosis.id,
        "execution_id": execution.id,
        "request_id": execution.request_id,
        "failure_code": diagnosis.primary_code,
        "secondary_codes": diagnosis.secondary_codes or [],
        "rule_id": diagnosis.rule_id,
        "layer": diagnosis.layer,
        "confidence": diagnosis.diagnosis_confidence,
        "diagnosis_score": diagnosis.diagnosis_score,
        "recommendation_code": diagnosis.recommendation_code,
        "taxonomy_version": diagnosis.taxonomy_version,
        "evidence_refs": _evidence_refs_from_db(diagnosis),
        "signals": diagnosis.signals,
        "metrics": metrics,
        "query": execution.query,
        "answer": execution.answer_text,
        "status": execution.status,
    }


def _evidence_refs_from_db(diagnosis: Diagnosis) -> list[str]:
    # Prefer explicit evidence table when available via identity map
    refs: list[str] = []
    try:
        from sqlalchemy.orm import object_session

        session = object_session(diagnosis)
        if session is not None:
            rows = session.execute(
                select(DiagnosisEvidence).where(
                    DiagnosisEvidence.diagnosis_id == diagnosis.id
                )
            ).scalars().all()
            refs = [r.ref for r in rows if r.ref]
    except Exception:  # noqa: BLE001
        refs = []
    return refs
