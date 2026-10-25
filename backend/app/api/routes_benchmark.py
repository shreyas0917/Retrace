"""Benchmark API — run gold/planted suites (offline Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import require_api_key
from app.db.models import Experiment, ExperimentMetric
from app.db.session import get_db
from app.services.eval.runner import run_suite_benchmark
from app.services.eval.suite_loader import load_suite

router = APIRouter(
    prefix="/api/v1",
    tags=["benchmark"],
    dependencies=[Depends(require_api_key)],
)


class BenchmarkRequest(BaseModel):
    suite_id: str = Field(..., min_length=1)
    suite_version: str = Field(default="1.0.0", min_length=1)


@router.get("/suites/{suite_id}")
def get_suite(suite_id: str, suite_version: str = "1.0.0") -> dict:
    cases, suite_hash, meta = load_suite(suite_id, suite_version)
    return {
        "suite_id": suite_id,
        "suite_version": suite_version,
        "suite_hash": suite_hash,
        "case_count": len(cases),
        "cases": [
            {
                "case_id": c.case_id,
                "failure_label": c.failure_label,
                "expected_rule_id": c.expected_rule_id,
                "planted": c.planted_failure is not None,
                "tags": c.tags,
            }
            for c in cases
        ],
        "meta": meta,
    }


@router.post("/benchmark/run")
def post_benchmark_run(body: BenchmarkRequest, db: Session = Depends(get_db)) -> dict:
    report = run_suite_benchmark(
        db,
        suite_id=body.suite_id,
        suite_version=body.suite_version,
        persist=True,
    )
    summary = report["summary"]
    return {
        "experiment_id": report["experiment_id"],
        "suite_id": report["suite_id"],
        "suite_version": report["suite_version"],
        "suite_hash": report["suite_hash"],
        "summary": summary,
        "cases": [
            {
                "scenario_id": c["scenario_id"],
                "correct": c["correct"],
                "expected": c["expected"],
                "predicted": c["predicted"],
                "evidence_refs_valid": c["evidence_refs_valid"],
            }
            for c in report["cases"]
        ],
        "artifact_uri": report.get("artifact_uri"),
    }


@router.get("/benchmark/experiments/{experiment_id}")
def get_benchmark_experiment(experiment_id: str, db: Session = Depends(get_db)) -> dict:
    exp = db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError(f"Experiment not found: {experiment_id}")
    metrics = db.get(ExperimentMetric, experiment_id)
    return {
        "experiment_id": exp.id,
        "name": exp.name,
        "suite_id": exp.suite_id,
        "suite_version": exp.suite_version,
        "suite_hash": exp.suite_hash,
        "status": exp.status,
        "pipeline": exp.pipeline,
        "artifact_uri": exp.artifact_uri,
        "metrics": metrics.metrics if metrics else None,
        "confusion_matrix": metrics.confusion_matrix if metrics else None,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "completed_at": exp.completed_at.isoformat() if exp.completed_at else None,
    }


@router.get("/benchmark/experiments")
def list_benchmark_experiments(db: Session = Depends(get_db), limit: int = 20) -> dict:
    rows = db.execute(
        select(Experiment)
        .where(Experiment.suite_id.is_not(None))
        .order_by(Experiment.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return {
        "experiments": [
            {
                "experiment_id": e.id,
                "name": e.name,
                "suite_id": e.suite_id,
                "suite_version": e.suite_version,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
    }
