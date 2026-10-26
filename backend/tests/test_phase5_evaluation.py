"""Phase 5 — gold suite, planted failures, benchmark metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.services.eval.planted import build_offline_execution
from app.services.eval.runner import run_suite_benchmark
from app.services.eval.schemas import GoldCase
from app.services.eval.suite_loader import (
    SuiteValidationError,
    compute_suite_hash,
    load_suite,
)
from app.services.metrics.diagnosis import (
    confusion_matrix,
    diagnosis_accuracy,
    rule_accuracy,
    summarize_results,
)


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


def test_gold_suite_loads_and_hashes() -> None:
    cases, suite_hash, meta = load_suite("gold_v1", "1.0.0")
    assert len(cases) >= 2
    assert suite_hash.startswith("sha256:")
    assert meta["suite_hash"] == suite_hash
    # Deterministic
    cases2, hash2, _ = load_suite("gold_v1", "1.0.0")
    assert hash2 == suite_hash
    assert [c.case_id for c in cases2] == [c.case_id for c in cases]


def test_planted_suite_loads() -> None:
    cases, suite_hash, _ = load_suite("planted_v1", "1.0.0")
    assert len(cases) == 12
    ids = {c.case_id for c in cases}
    assert {"P01", "P06", "P12"}.issubset(ids)
    assert suite_hash.startswith("sha256:")


def test_duplicate_case_ids_rejected(tmp_path: Path) -> None:
    root = tmp_path / "suites"
    d = root / "bad_v1" / "v1.0.0"
    d.mkdir(parents=True)
    case = {
        "case_id": "dup",
        "suite_id": "bad_v1",
        "suite_version": "1.0.0",
        "corpus_id": "demo",
        "corpus_version_pin": "x",
        "query": "q",
        "expected_abstention": False,
        "relevant_chunk_ids": ["a:c000"],
        "failure_label": "OK_GROUNDED",
        "acceptable_primary_codes": ["OK_GROUNDED"],
        "annotator": "t",
        "annotation_date": "2026-09-27",
        "taxonomy_version": "1.0",
    }
    (d / "cases.jsonl").write_text(
        json.dumps(case) + "\n" + json.dumps(case) + "\n", encoding="utf-8"
    )
    with pytest.raises(SuiteValidationError, match="duplicate"):
        load_suite("bad_v1", "1.0.0", root=root)


def test_invalid_failure_label_rejected(tmp_path: Path) -> None:
    root = tmp_path / "suites"
    d = root / "bad_v1" / "v1.0.0"
    d.mkdir(parents=True)
    case = {
        "case_id": "x",
        "suite_id": "bad_v1",
        "suite_version": "1.0.0",
        "corpus_id": "demo",
        "corpus_version_pin": "x",
        "query": "q",
        "expected_abstention": False,
        "relevant_chunk_ids": [],
        "failure_label": "NOT_A_REAL_CODE",
        "acceptable_primary_codes": ["NOT_A_REAL_CODE"],
        "annotator": "t",
        "annotation_date": "2026-09-27",
    }
    (d / "cases.jsonl").write_text(json.dumps(case) + "\n", encoding="utf-8")
    with pytest.raises(SuiteValidationError):
        load_suite("bad_v1", "1.0.0", root=root)


def test_suite_hash_canonical() -> None:
    lines = [
        '{"b": 1, "a": 2}',
        '{"a": 2, "b": 1}',
    ]
    # Different key order → same canonical hash when parsed
    h1 = compute_suite_hash([lines[0]])
    h2 = compute_suite_hash([lines[1]])
    assert h1 == h2


def test_planted_mutations_build_fixtures() -> None:
    cases, _, _ = load_suite("planted_v1", "1.0.0")
    by_id = {c.case_id: c for c in cases}
    fx = build_offline_execution(by_id["P01"])
    assert by_id["P01"].relevant_chunk_ids[0] not in [
        c["chunk_id"] for c in fx.retrieved_chunks
    ]
    fx6 = build_offline_execution(by_id["P06"])
    assert "10 days" in (fx6.answer or "")
    fx7 = build_offline_execution(by_id["P07"])
    assert fx7.abstained is False
    fx8 = build_offline_execution(by_id["P08"])
    assert fx8.abstained is True
    fx12 = build_offline_execution(by_id["P12"])
    assert fx12.status == "GENERATION_TIMEOUT"


def test_metrics_helpers() -> None:
    rows = [
        {
            "correct_failure_code": True,
            "correct_rule_id": True,
            "expected_rule_id": "R30",
            "expected_failure_code": "GENERATION_CONTRADICTION",
            "predicted_failure_code": "GENERATION_CONTRADICTION",
        },
        {
            "correct_failure_code": False,
            "correct_rule_id": False,
            "expected_rule_id": "R20",
            "expected_failure_code": "ABSTENTION_FALSE_NEGATIVE",
            "predicted_failure_code": "OK_GROUNDED",
        },
    ]
    assert diagnosis_accuracy(rows) == 0.5
    assert rule_accuracy(rows) == 0.5
    cm = confusion_matrix(rows)
    assert cm["matrix"]["GENERATION_CONTRADICTION"]["GENERATION_CONTRADICTION"] == 1
    assert cm["matrix"]["ABSTENTION_FALSE_NEGATIVE"]["OK_GROUNDED"] == 1
    summary = summarize_results(rows)
    assert summary["correct"] == 1
    assert summary["incorrect"] == 1


def test_benchmark_planted_p06_correct() -> None:
    db = _open_db()
    try:
        report = run_suite_benchmark(
            db,
            suite_id="planted_v1",
            suite_version="1.0.0",
            persist=True,
        )
    finally:
        db.close()

    by_id = {c["scenario_id"]: c for c in report["cases"]}
    p06 = by_id["P06"]
    assert p06["predicted"]["failure_code"] == "GENERATION_CONTRADICTION"
    assert p06["predicted"]["rule_id"] == "R30"
    assert p06["correct"] is True
    assert p06["evidence_refs_valid"] is True

    summary = report["summary"]
    assert summary["total_cases"] == 12
    assert 0.0 <= summary["failure_code_accuracy"] <= 1.0
    assert summary["confusion_matrix"]["matrix"]
    assert report["suite_hash"].startswith("sha256:")


def test_benchmark_api(client: TestClient, api_key: str) -> None:
    r = client.get("/api/v1/suites/planted_v1", headers=_auth(api_key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["case_count"] == 12

    r = client.post(
        "/api/v1/benchmark/run",
        headers=_auth(api_key),
        json={"suite_id": "planted_v1", "suite_version": "1.0.0"},
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["summary"]["total_cases"] == 12
    assert "failure_code_accuracy" in report["summary"]
    exp_id = report["experiment_id"]

    r = client.get(
        f"/api/v1/benchmark/experiments/{exp_id}",
        headers=_auth(api_key),
    )
    assert r.status_code == 200
    assert r.json()["metrics"] is not None


def test_benchmark_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/api/v1/benchmark/run",
        json={"suite_id": "planted_v1"},
    )
    assert r.status_code == 401


def test_gold_case_schema_roundtrip() -> None:
    cases, _, _ = load_suite("gold_v1", "1.0.0")
    for case in cases:
        assert isinstance(case, GoldCase)
        assert case.failure_label in case.acceptable_primary_codes
