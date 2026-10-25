"""Baseline promotion and active-baseline lookup (immutable metrics)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.models import BaselineArtifact, Experiment, ExperimentMetric
from app.services.eval.suite_loader import load_suite
from app.services.eval.thresholds_config import load_thresholds


class BaselineError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="BASELINE_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


def get_active_baseline(
    db: Session,
    *,
    suite_id: str,
    suite_version: str,
) -> BaselineArtifact | None:
    return db.execute(
        select(BaselineArtifact).where(
            BaselineArtifact.suite_id == suite_id,
            BaselineArtifact.suite_version == suite_version,
            BaselineArtifact.is_active.is_(True),
        )
    ).scalars().first()


def promote_baseline(
    db: Session,
    *,
    experiment_id: str,
    thresholds: dict[str, Any] | None = None,
    name: str | None = None,
) -> BaselineArtifact:
    """Explicitly promote a COMPLETED experiment to an immutable baseline."""
    exp = db.get(Experiment, experiment_id)
    if not exp:
        raise NotFoundError(f"Experiment not found: {experiment_id}")
    if exp.status == "RUNNING":
        raise BaselineError("cannot promote incomplete experiment", {"status": exp.status})
    if exp.status == "FAILED":
        raise BaselineError("cannot promote failed experiment", {"status": exp.status})
    if exp.status == "REGRESSION":
        raise BaselineError(
            "cannot promote regression experiment; re-run a passing eval first",
            {"status": exp.status},
        )
    if exp.status != "COMPLETED":
        raise BaselineError(
            f"cannot promote experiment with status={exp.status}",
            {"status": exp.status},
        )
    if not exp.suite_id or not exp.suite_version or not exp.suite_hash:
        raise BaselineError("experiment missing suite identity")

    metrics_row = db.get(ExperimentMetric, experiment_id)
    if not metrics_row or not metrics_row.metrics:
        raise BaselineError("experiment has no persisted metrics")

    required = ("failure_code_accuracy", "total_cases", "correct", "incorrect")
    for key in required:
        if key not in metrics_row.metrics:
            raise BaselineError(f"experiment metrics missing key: {key}")

    # Suite integrity: recompute hash and compare
    _, current_hash, _ = load_suite(exp.suite_id, exp.suite_version)
    if current_hash != exp.suite_hash:
        raise BaselineError(
            "suite integrity error: hash changed since experiment",
            {"expected": exp.suite_hash, "actual": current_hash},
        )

    thr = thresholds or load_thresholds()
    # Snapshot thresholds without internal keys
    thr_snapshot = {k: v for k, v in thr.items() if not str(k).startswith("_")}

    # Deactivate previous active baseline for this suite (metadata only; metrics untouched)
    db.execute(
        update(BaselineArtifact)
        .where(
            BaselineArtifact.suite_id == exp.suite_id,
            BaselineArtifact.suite_version == exp.suite_version,
            BaselineArtifact.is_active.is_(True),
        )
        .values(is_active=False)
    )

    baseline_id = str(uuid.uuid4())
    label = name or f"{exp.suite_id}@{exp.suite_version}/{baseline_id[:8]}"
    row = BaselineArtifact(
        id=baseline_id,
        name=label,
        experiment_id=exp.id,
        suite_id=exp.suite_id,
        suite_version=exp.suite_version,
        suite_hash=exp.suite_hash,
        metrics=dict(metrics_row.metrics),
        thresholds=thr_snapshot,
        is_active=True,
    )
    db.add(row)
    exp.baseline_experiment_id = None  # reserved; active link is BaselineArtifact
    db.commit()
    db.refresh(row)
    return row


def baseline_to_dict(row: BaselineArtifact) -> dict[str, Any]:
    return {
        "baseline_id": row.id,
        "name": row.name,
        "experiment_id": row.experiment_id,
        "suite_id": row.suite_id,
        "suite_version": row.suite_version,
        "suite_hash": row.suite_hash,
        "metrics": row.metrics,
        "thresholds": row.thresholds,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
