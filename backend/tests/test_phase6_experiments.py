"""Phase 6 — experiments, baselines, retrace eval CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import Experiment, ExperimentCaseResult
from app.services.eval.baseline import BaselineError, get_active_baseline, promote_baseline
from app.services.eval.evaluate import (
    EXIT_ERROR,
    EXIT_PASS,
    EXIT_REGRESSION,
    EvalIntegrityError,
    run_evaluation,
    verify_suite_integrity,
)
from app.services.eval.regression import compare_metrics
from app.services.eval.thresholds_config import load_thresholds
from app.cli.retrace import main as cli_main
from sqlalchemy import select


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


def test_thresholds_default_loads() -> None:
    thr = load_thresholds()
    assert thr["require_failure_code_accuracy_drop_lt"] == 0.05
    assert thr["min_failure_code_accuracy"] == 0.0


def test_compare_no_baseline_passes_with_defaults() -> None:
    current = {
        "failure_code_accuracy": 1.0,
        "rule_accuracy": 1.0,
        "evidence_accuracy": 1.0,
        "total_cases": 2,
        "incorrect": 0,
    }
    thr = load_thresholds()
    result = compare_metrics(current=current, baseline=None, thresholds=thr)
    assert result["passed"] is True
    assert result["has_baseline"] is False


def test_compare_drop_is_regression() -> None:
    thr = load_thresholds()
    current = {
        "failure_code_accuracy": 0.90,
        "rule_accuracy": 1.0,
        "evidence_accuracy": 1.0,
        "total_cases": 10,
        "incorrect": 1,
    }
    baseline = {
        "failure_code_accuracy": 1.0,
        "rule_accuracy": 1.0,
        "evidence_accuracy": 1.0,
    }
    result = compare_metrics(current=current, baseline=baseline, thresholds=thr)
    assert result["passed"] is False
    assert any("failure_code_accuracy" in v for v in result["violations"])


def test_compare_within_drop_tolerance_passes() -> None:
    thr = load_thresholds()
    current = {
        "failure_code_accuracy": 0.96,
        "rule_accuracy": 1.0,
        "evidence_accuracy": 1.0,
        "total_cases": 100,
        "incorrect": 0,
    }
    baseline = {
        "failure_code_accuracy": 1.0,
        "rule_accuracy": 1.0,
        "evidence_accuracy": 1.0,
    }
    # drop 0.04 < 0.05
    result = compare_metrics(current=current, baseline=baseline, thresholds=thr)
    assert result["passed"] is True


def test_compare_zero_cases_safe() -> None:
    thr = load_thresholds()
    result = compare_metrics(
        current={
            "failure_code_accuracy": 0.0,
            "rule_accuracy": None,
            "evidence_accuracy": None,
            "total_cases": 0,
            "incorrect": 0,
        },
        baseline=None,
        thresholds=thr,
    )
    assert result["error_rate"] == 0.0
    assert result["passed"] is True


def test_suite_integrity_mismatch() -> None:
    with pytest.raises(EvalIntegrityError) as exc:
        verify_suite_integrity(
            "gold_v1",
            "1.0.0",
            expect_hash="sha256:deadbeef",
        )
    assert exc.value.details["expected"] == "sha256:deadbeef"
    assert exc.value.details["actual"].startswith("sha256:")


def test_eval_gold_persists_case_results() -> None:
    db = _open_db()
    try:
        result = run_evaluation(
            db, suite_id="gold_v1", suite_version="1.0.0", persist=True
        )
        assert result["exit_code"] == EXIT_PASS
        exp_id = result["experiment_id"]
        rows = db.execute(
            select(ExperimentCaseResult).where(
                ExperimentCaseResult.experiment_id == exp_id
            )
        ).scalars().all()
        assert len(rows) == 2
        exp = db.get(Experiment, exp_id)
        assert exp is not None
        assert exp.status == "COMPLETED"
        assert exp.suite_hash == result["suite_hash"]
        assert exp.pipeline.get("app_version") == "1.0.0"
        assert "cost_per_query" in exp.pipeline
        assert exp.pipeline["cost_per_query"] is None
    finally:
        db.close()


def test_baseline_promote_and_immutable_metrics() -> None:
    db = _open_db()
    try:
        result = run_evaluation(
            db, suite_id="gold_v1", suite_version="1.0.0", persist=True
        )
        exp_id = result["experiment_id"]
        row = promote_baseline(db, experiment_id=exp_id)
        assert row.is_active is True
        assert row.experiment_id == exp_id
        assert row.suite_hash == result["suite_hash"]
        original_metrics = dict(row.metrics)

        # Second promote deactivates first; metrics of first remain unchanged
        result2 = run_evaluation(
            db, suite_id="gold_v1", suite_version="1.0.0", persist=True
        )
        row2 = promote_baseline(db, experiment_id=result2["experiment_id"])
        db.refresh(row)
        assert row.is_active is False
        assert row.metrics == original_metrics
        assert row2.is_active is True
        active = get_active_baseline(
            db, suite_id="gold_v1", suite_version="1.0.0"
        )
        assert active is not None
        assert active.id == row2.id
    finally:
        db.close()


def test_cannot_promote_failed_or_running() -> None:
    db = _open_db()
    try:
        # Create a FAILED experiment stub via eval then force status
        result = run_evaluation(
            db, suite_id="gold_v1", suite_version="1.0.0", persist=True
        )
        exp = db.get(Experiment, result["experiment_id"])
        assert exp is not None
        exp.status = "FAILED"
        db.commit()
        with pytest.raises(BaselineError, match="failed"):
            promote_baseline(db, experiment_id=exp.id)

        exp.status = "RUNNING"
        db.commit()
        with pytest.raises(BaselineError, match="incomplete"):
            promote_baseline(db, experiment_id=exp.id)
    finally:
        db.close()


def test_cli_exit_0_pass() -> None:
    code = cli_main(["eval", "--suite", "gold_v1", "--suite-version", "1.0.0"])
    assert code == EXIT_PASS


def test_cli_exit_1_regression() -> None:
    impossible = Path("/app/configs/thresholds.impossible.yaml")
    if not impossible.is_file():
        impossible = (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "thresholds.impossible.yaml"
        )
    code = cli_main(
        [
            "eval",
            "--suite",
            "gold_v1",
            "--suite-version",
            "1.0.0",
            "--thresholds",
            str(impossible),
        ]
    )
    assert code == EXIT_REGRESSION


def test_cli_exit_2_integrity() -> None:
    code = cli_main(
        [
            "eval",
            "--suite",
            "gold_v1",
            "--expect-hash",
            "sha256:not-the-real-hash",
        ]
    )
    assert code == EXIT_ERROR


def test_cli_baseline_promote() -> None:
    # Run eval to get experiment
    db = _open_db()
    try:
        result = run_evaluation(
            db, suite_id="gold_v1", suite_version="1.0.0", persist=True
        )
        exp_id = result["experiment_id"]
    finally:
        db.close()
    code = cli_main(["baseline", "promote", exp_id])
    assert code == EXIT_PASS


def test_experiments_api(client: TestClient, api_key: str) -> None:
    r = client.post(
        "/api/v1/experiments",
        headers=_auth(api_key),
        json={"suite_id": "gold_v1", "suite_version": "1.0.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    exp_id = body["experiment_id"]
    assert body["exit_code"] == 0

    r = client.get(f"/api/v1/experiments/{exp_id}", headers=_auth(api_key))
    assert r.status_code == 200
    assert r.json()["metrics"] is not None

    r = client.get(
        f"/api/v1/experiments/{exp_id}/results", headers=_auth(api_key)
    )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2

    r = client.post(
        "/api/v1/baselines/promote",
        headers=_auth(api_key),
        json={"experiment_id": exp_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    r = client.get(
        "/api/v1/baselines/active",
        headers=_auth(api_key),
        params={"suite_id": "gold_v1", "suite_version": "1.0.0"},
    )
    assert r.status_code == 200
    assert r.json()["baseline"]["experiment_id"] == exp_id

    r = client.get(
        f"/api/v1/experiments/{exp_id}/comparison",
        headers=_auth(api_key),
    )
    assert r.status_code == 200
    assert r.json()["comparison"]["passed"] is True
