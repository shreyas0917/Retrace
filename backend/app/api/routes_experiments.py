"""Experiment + baseline APIs (Phase 6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import require_api_key
from app.db.models import (
    Experiment,
    ExperimentCaseResult,
    ExperimentMetric,
)
from app.db.session import get_db
from app.services.eval.baseline import (
    baseline_to_dict,
    get_active_baseline,
    promote_baseline,
)
from app.services.eval.evaluate import run_evaluation
from app.services.eval.regression import compare_metrics
from app.services.eval.thresholds_config import load_thresholds

router = APIRouter(
    prefix="/api/v1",
    tags=["experiments"],
    dependencies=[Depends(require_api_key)],
)


class EvalRequest(BaseModel):
    suite_id: str = Field(..., min_length=1)
    suite_version: str = Field(default="1.0.0")
    expect_hash: str | None = None
    thresholds_path: str | None = None


class PromoteRequest(BaseModel):
    experiment_id: str = Field(..., min_length=1)
    name: str | None = None


@router.post("/experiments")
def post_experiment(body: EvalRequest, db: Session = Depends(get_db)) -> dict:
    """Run evaluation (suite → experiment → gate)."""
    result = run_evaluation(
        db,
        suite_id=body.suite_id,
        suite_version=body.suite_version,
        expect_hash=body.expect_hash,
        thresholds_path=body.thresholds_path,
        persist=True,
    )
    return {
        "experiment_id": result["experiment_id"],
        "suite_id": result["suite_id"],
        "suite_version": result["suite_version"],
        "suite_hash": result["suite_hash"],
        "status": result["gate_status"],
        "exit_code": result["exit_code"],
        "summary": result["summary"],
        "comparison": result["comparison"],
        "baseline": result.get("baseline"),
        "no_baseline": result.get("no_baseline"),
        "artifact_uri": result.get("artifact_uri"),
    }


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db), limit: int = 20) -> dict:
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
                "suite_hash": e.suite_hash,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            }
            for e in rows
        ]
    }


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, db: Session = Depends(get_db)) -> dict:
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
        "git_commit": exp.git_commit,
        "artifact_uri": exp.artifact_uri,
        "metrics": metrics.metrics if metrics else None,
        "confusion_matrix": metrics.confusion_matrix if metrics else None,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "completed_at": exp.completed_at.isoformat() if exp.completed_at else None,
    }


@router.get("/experiments/{experiment_id}/results")
def get_experiment_results(experiment_id: str, db: Session = Depends(get_db)) -> dict:
    exp = db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError(f"Experiment not found: {experiment_id}")
    rows = db.execute(
        select(ExperimentCaseResult).where(
            ExperimentCaseResult.experiment_id == experiment_id
        )
    ).scalars().all()
    return {
        "experiment_id": experiment_id,
        "results": [
            {
                "case_id": r.case_id,
                "query": r.query,
                "expected_failure_code": r.expected_failure_code,
                "expected_rule_id": r.expected_rule_id,
                "predicted_failure_code": r.predicted_failure_code,
                "predicted_rule_id": r.predicted_rule_id,
                "diagnosis_confidence": r.diagnosis_confidence,
                "expected_evidence_refs": r.expected_evidence_refs,
                "predicted_evidence_refs": r.predicted_evidence_refs,
                "evidence_valid": r.evidence_valid,
                "passed": r.passed,
                "execution_id": r.execution_id,
                "diagnosis_id": r.diagnosis_id,
                "latency_ms": r.latency_ms,
                "token_usage": r.token_usage,
                "cost": r.cost,
                "error": r.error,
            }
            for r in rows
        ],
    }


@router.get("/experiments/{experiment_id}/comparison")
def get_experiment_comparison(experiment_id: str, db: Session = Depends(get_db)) -> dict:
    exp = db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError(f"Experiment not found: {experiment_id}")
    metrics = db.get(ExperimentMetric, experiment_id)
    if not metrics:
        raise NotFoundError("Experiment has no metrics")
    baseline = None
    if exp.suite_id and exp.suite_version:
        baseline = get_active_baseline(
            db, suite_id=exp.suite_id, suite_version=exp.suite_version
        )
    thresholds = (
        baseline.thresholds if baseline and baseline.thresholds else load_thresholds()
    )
    comparison = compare_metrics(
        current=metrics.metrics,
        baseline=baseline.metrics if baseline else None,
        thresholds=thresholds,
    )
    return {
        "experiment_id": experiment_id,
        "baseline": baseline_to_dict(baseline) if baseline else None,
        "comparison": comparison,
    }


@router.post("/baselines/promote")
def post_baseline_promote(body: PromoteRequest, db: Session = Depends(get_db)) -> dict:
    row = promote_baseline(db, experiment_id=body.experiment_id, name=body.name)
    return baseline_to_dict(row)


@router.get("/baselines/active")
def get_baselines_active(
    suite_id: str,
    suite_version: str = "1.0.0",
    db: Session = Depends(get_db),
) -> dict:
    row = get_active_baseline(db, suite_id=suite_id, suite_version=suite_version)
    if not row:
        return {"baseline": None, "suite_id": suite_id, "suite_version": suite_version}
    return {"baseline": baseline_to_dict(row)}
