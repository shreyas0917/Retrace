"""Offline planted/gold benchmark runner (Phase 5).

Does not implement the future `retrace eval` regression CLI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import (
    Case,
    Corpus,
    CorpusVersion,
    Experiment,
    ExperimentCaseResult,
    ExperimentMetric,
    ExecutionTrace,
    Run,
    Suite,
)
from app.services.diagnosis.engine import diagnose_execution
from app.services.diagnosis.taxonomy import TAXONOMY_VERSION
from app.services.eval.fakes import ScriptedJudgeLLM
from app.services.eval.planted import build_offline_execution
from app.services.eval.schemas import GoldCase
from app.services.eval.suite_loader import load_suite
from app.services.llm_client import set_llm_provider
from app.services.metrics.diagnosis import (
    evidence_refs_valid,
    expected_evidence_hit,
    summarize_results,
)

logger = get_logger(__name__)


def _ensure_eval_corpus(db: Session) -> str:
    """Create a stub READY corpus version for FK constraints (offline fixtures)."""
    corpus_id = "eval_stub"
    existing = db.get(Corpus, corpus_id)
    if not existing:
        db.add(Corpus(id=corpus_id, title="Eval Stub (offline fixtures)"))
        db.flush()

    ready = db.execute(
        select(CorpusVersion).where(
            CorpusVersion.corpus_id == corpus_id,
            CorpusVersion.status == "READY",
        )
    ).scalars().first()
    if ready:
        return ready.id

    vid = str(uuid.uuid4())
    db.add(
        CorpusVersion(
            id=vid,
            corpus_id=corpus_id,
            corpus_hash="sha256:eval_stub",
            chunking_config={
                "strategy": "recursive_character",
                "chunk_size": 512,
                "chunk_overlap": 64,
                "tokenizer": "char",
            },
            chunking_config_hash="sha256:eval_stub_cfg",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_revision="sentence-transformers/all-MiniLM-L6-v2@sentence-transformers-local",
            vector_collection=f"cv_{vid}",
            status="READY",
            document_count=0,
            chunk_count=0,
        )
    )
    db.commit()
    return vid


def _upsert_suite(
    db: Session,
    *,
    suite_id: str,
    suite_version: str,
    suite_hash: str,
    corpus_id: str,
    cases: list[GoldCase],
) -> None:
    if db.get(Corpus, corpus_id) is None:
        db.add(Corpus(id=corpus_id, title=f"Suite corpus {corpus_id}"))
        db.flush()

    suite = db.get(Suite, (suite_id, suite_version))
    if suite is None:
        db.add(
            Suite(
                id=suite_id,
                version=suite_version,
                suite_hash=suite_hash,
                corpus_id=corpus_id,
                taxonomy_version=TAXONOMY_VERSION,
            )
        )
        db.flush()
    else:
        suite.suite_hash = suite_hash
        db.flush()

    for case in cases:
        row = db.get(Case, (case.case_id, suite_id, suite_version))
        payload = case.model_dump(mode="json")
        if row is None:
            db.add(
                Case(
                    case_id=case.case_id,
                    suite_id=suite_id,
                    suite_version=suite_version,
                    payload=payload,
                )
            )
        else:
            row.payload = payload
    db.commit()


def _insert_execution(
    db: Session,
    *,
    corpus_version_id: str,
    case: GoldCase,
    fixture: Any,
) -> str:
    eid = str(uuid.uuid4())
    db.add(
        ExecutionTrace(
            id=eid,
            request_id=f"bench-{case.case_id}-{uuid.uuid4().hex[:8]}",
            corpus_version_id=corpus_version_id,
            query=case.query,
            retrieval_trace_id=None,
            top_k=5,
            retrieved_chunks=fixture.retrieved_chunks,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_revision="sentence-transformers/all-MiniLM-L6-v2@sentence-transformers-local",
            generation_model="gpt-4.1-mini",
            generation_temperature=0.0,
            prompt_version="generator.v1",
            answer_text=fixture.answer,
            abstained=fixture.abstained,
            status=fixture.status,
            error_code=fixture.error_code,
            retrieval_latency_ms=1.0,
            generation_latency_ms=1.0,
            total_latency_ms=2.0,
        )
    )
    db.commit()
    return eid


def _score_case(
    case: GoldCase,
    diagnosis: dict[str, Any],
    *,
    retrieved_ids: list[str],
) -> dict[str, Any]:
    predicted_code = diagnosis["failure_code"]
    predicted_rule = diagnosis["rule_id"]
    acceptable = set(case.acceptable_primary_codes)
    correct_code = predicted_code in acceptable
    correct_rule = (
        None
        if not case.expected_rule_id
        else predicted_rule == case.expected_rule_id
    )
    expected_chunks = case.expected_evidence_chunk_ids
    if expected_chunks is None and case.relevant_chunk_ids:
        # Only require evidence hit when diagnosis cites chunks and gold chunks exist
        expected_chunks = None

    refs = list(diagnosis.get("evidence_refs") or [])
    refs_ok = evidence_refs_valid(
        refs,
        retrieved_ids=retrieved_ids,
        execution_id=diagnosis.get("execution_id"),
        gold_ids=list(case.relevant_chunk_ids),
    )
    evid_hit = (
        None
        if expected_chunks is None
        else expected_evidence_hit(refs, expected_chunks)
    )

    return {
        "suite_version": case.suite_version,
        "suite_id": case.suite_id,
        "scenario_id": case.case_id,
        "case_id": case.case_id,
        "expected": {
            "failure_code": case.failure_label,
            "rule_id": case.expected_rule_id,
            "acceptable_primary_codes": case.acceptable_primary_codes,
        },
        "predicted": {
            "failure_code": predicted_code,
            "rule_id": predicted_rule,
            "confidence": diagnosis.get("confidence"),
            "score": diagnosis.get("diagnosis_score"),
            "calibrated_confidence": diagnosis.get("calibrated_confidence"),
            "uncertain": bool(diagnosis.get("uncertain", False)),
        },
        "expected_failure_code": case.failure_label,
        "predicted_failure_code": predicted_code,
        "expected_rule_id": case.expected_rule_id,
        "predicted_rule_id": predicted_rule,
        "correct": correct_code,
        "correct_failure_code": correct_code,
        "correct_strict": predicted_code == case.failure_label,
        "diagnosis_score": diagnosis.get("diagnosis_score"),
        "calibrated_confidence": diagnosis.get("calibrated_confidence"),
        "uncertain": bool(diagnosis.get("uncertain", False)),
        "explanation": diagnosis.get("explanation"),
        "tags": list(case.tags or []),
        "correct_rule_id": correct_rule,
        "correct_evidence": evid_hit,
        "expected_evidence_chunk_ids": expected_chunks,
        "evidence_refs": refs,
        "evidence_refs_valid": refs_ok,
        "execution_id": diagnosis.get("execution_id"),
        "diagnosis_id": diagnosis.get("diagnosis_id"),
        "planted_failure": (
            case.planted_failure.model_dump() if case.planted_failure else None
        ),
    }


def run_suite_benchmark(
    db: Session,
    *,
    suite_id: str,
    suite_version: str,
    settings: Settings | None = None,
    report_dir: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Execute an offline suite benchmark and return the full report."""
    settings = settings or get_settings()
    cases, suite_hash, meta = load_suite(suite_id, suite_version)

    corpus_version_id = _ensure_eval_corpus(db)
    # Suite table corpus_id should match case corpus_id (typically demo)
    suite_corpus_id = cases[0].corpus_id
    _upsert_suite(
        db,
        suite_id=suite_id,
        suite_version=suite_version,
        suite_hash=suite_hash,
        corpus_id=suite_corpus_id,
        cases=cases,
    )

    experiment_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    pipeline = {
        "mode": "suite_offline",
        "suite_hash": suite_hash,
        "embedding_model": settings.embedding_model,
        "generation_model": settings.model_name,
        "generation_temperature": 0.0,
        "judge_model": settings.model_name,
        "judge_temperature": 0.0,
        "taxonomy_version": TAXONOMY_VERSION,
        "corpus_version_id": corpus_version_id,
    }

    if persist:
        db.add(
            Experiment(
                id=experiment_id,
                name=f"{suite_id}@{suite_version}",
                corpus_version_id=corpus_version_id,
                suite_id=suite_id,
                suite_version=suite_version,
                suite_hash=suite_hash,
                pipeline=pipeline,
                status="RUNNING",
            )
        )
        db.commit()

    case_results: list[dict[str, Any]] = []

    try:
        for case in cases:
            fixture = build_offline_execution(case)
            scripts = fixture.judge_scripts or {}
            provider = ScriptedJudgeLLM(scripts)
            set_llm_provider(provider)
            try:
                execution_id = _insert_execution(
                    db,
                    corpus_version_id=corpus_version_id,
                    case=case,
                    fixture=fixture,
                )
                diagnosis = diagnose_execution(
                    db,
                    execution_id=execution_id,
                    gold_chunk_ids=list(case.relevant_chunk_ids),
                    settings=settings,
                )
                retrieved_ids = [
                    str(c.get("chunk_id"))
                    for c in (fixture.retrieved_chunks or [])
                    if c.get("chunk_id")
                ]
                scored = _score_case(case, diagnosis, retrieved_ids=retrieved_ids)
                scored["metrics"] = diagnosis.get("metrics") or {}
                case_results.append(scored)

                if persist:
                    run_id = str(uuid.uuid4())
                    db.add(
                        Run(
                            id=run_id,
                            experiment_id=experiment_id,
                            case_id=case.case_id,
                            execution_id=execution_id,
                            request_id=f"run-{case.case_id}-{uuid.uuid4().hex[:8]}",
                            query=case.query,
                            answer_text=fixture.answer,
                            abstained=fixture.abstained,
                            latency_ms=diagnosis.get("metrics") or {},
                            error=None
                            if scored["correct_failure_code"]
                            else {
                                "expected": case.failure_label,
                                "predicted": diagnosis["failure_code"],
                            },
                        )
                    )
                    expected_refs = (
                        [f"chunk:{cid}" for cid in (scored["expected_evidence_chunk_ids"] or [])]
                        if scored["expected_evidence_chunk_ids"] is not None
                        else None
                    )
                    db.add(
                        ExperimentCaseResult(
                            id=str(uuid.uuid4()),
                            experiment_id=experiment_id,
                            case_id=case.case_id,
                            query=case.query,
                            expected_failure_code=case.failure_label,
                            expected_rule_id=case.expected_rule_id,
                            predicted_failure_code=diagnosis["failure_code"],
                            predicted_rule_id=diagnosis["rule_id"],
                            diagnosis_confidence=diagnosis.get("confidence"),
                            expected_evidence_refs=expected_refs,
                            predicted_evidence_refs=list(scored.get("evidence_refs") or []),
                            evidence_valid=scored.get("evidence_refs_valid"),
                            passed=bool(scored["correct_failure_code"]),
                            execution_id=execution_id,
                            diagnosis_id=diagnosis.get("diagnosis_id"),
                            latency_ms=diagnosis.get("metrics") or {},
                            token_usage=None,
                            cost=None,
                            error=None
                            if scored["correct_failure_code"]
                            else {
                                "expected": case.failure_label,
                                "predicted": diagnosis["failure_code"],
                            },
                        )
                    )
                    db.commit()
            finally:
                set_llm_provider(None)

        summary = summarize_results(case_results)
        finished = datetime.now(timezone.utc)
        report: dict[str, Any] = {
            "experiment_id": experiment_id,
            "suite_id": suite_id,
            "suite_version": suite_version,
            "suite_hash": suite_hash,
            "taxonomy_version": TAXONOMY_VERSION,
            "started_at": started.isoformat(),
            "completed_at": finished.isoformat(),
            "pipeline": pipeline,
            "summary": summary,
            "cases": case_results,
            "meta": meta,
        }

        if persist:
            exp = db.get(Experiment, experiment_id)
            if exp:
                exp.status = "COMPLETED"
                exp.completed_at = finished
            db.merge(
                ExperimentMetric(
                    experiment_id=experiment_id,
                    metrics={
                        "failure_code_accuracy": summary["failure_code_accuracy"],
                        "strict_accuracy": summary["strict_accuracy"],
                        "rule_accuracy": summary["rule_accuracy"],
                        "evidence_accuracy": summary["evidence_accuracy"],
                        "macro_f1": summary["macro_f1"],
                        "micro_f1": summary["micro_f1"],
                        "weighted_f1": summary["weighted_f1"],
                        "total_cases": summary["total_cases"],
                        "correct": summary["correct"],
                        "incorrect": summary["incorrect"],
                        "per_class": summary["per_class"],
                        "selective": summary["selective"],
                    },
                    confusion_matrix=summary["confusion_matrix"],
                )
            )
            db.commit()

            out_dir = report_dir or Path("/data/reports")
            if not out_dir.exists():
                # Local / test fallback
                out_dir = Path(__file__).resolve().parents[4] / "data" / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{suite_id}_{suite_version}_{experiment_id[:8]}.json"
            out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            report["artifact_uri"] = str(out_path)
            if exp:
                exp.artifact_uri = str(out_path)
                db.commit()

        logger.info(
            "benchmark_completed",
            suite_id=suite_id,
            suite_version=suite_version,
            correct=summary["correct"],
            total=summary["total_cases"],
            failure_code_accuracy=summary["failure_code_accuracy"],
        )
        return report
    except Exception:
        if persist:
            exp = db.get(Experiment, experiment_id)
            if exp:
                exp.status = "FAILED"
                db.commit()
        raise
