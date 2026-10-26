"""Head-to-head comparison of diagnosis classifiers on identical signal bags.

Inputs are the per-case signal dicts persisted by a benchmark experiment, so
every classifier sees exactly what the rule engine saw (including judge
outputs). Reports strict/lenient accuracy, macro-F1, per-class F1, confusion
matrices, pairwise Cohen's kappa and, for the LLM classifier, malformed-output
rate and latency.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Diagnosis, ExperimentCaseResult
from app.services.diagnosis.classifiers import (
    Classifier,
    HeuristicClassifier,
    MajorityClassifier,
    RuleEngineClassifier,
    signal_bag_from_dict,
)
from app.services.eval.suite_loader import load_suite
from app.services.metrics.diagnosis import (
    aggregate_f1,
    confusion_matrix,
    macro_f1,
    per_class_metrics,
)


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Agreement between two label sequences corrected for chance."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    expected = 0.0
    for label in labels:
        pa = sum(1 for x in a if x == label) / n
        pb = sum(1 for y in b if y == label) / n
        expected += pa * pb
    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1.0 - expected), 6)


def load_cases_from_experiment(db: Session, experiment_id: str) -> list[dict[str, Any]]:
    """Join experiment case results with the persisted diagnosis signal bags."""
    rows = db.execute(
        select(ExperimentCaseResult).where(
            ExperimentCaseResult.experiment_id == experiment_id
        )
    ).scalars().all()
    if not rows:
        return []
    # acceptable codes come from the suite definition
    suite_id = None
    suite_version = None
    from app.db.models import Experiment

    exp = db.get(Experiment, experiment_id)
    if exp:
        suite_id, suite_version = exp.suite_id, exp.suite_version
    acceptable: dict[str, list[str]] = {}
    if suite_id and suite_version:
        cases, _, _ = load_suite(suite_id, suite_version)
        acceptable = {c.case_id: list(c.acceptable_primary_codes) for c in cases}

    out: list[dict[str, Any]] = []
    for r in rows:
        signals: dict[str, Any] = {}
        if r.diagnosis_id:
            diag = db.get(Diagnosis, r.diagnosis_id)
            if diag and isinstance(diag.signals, dict):
                signals = diag.signals
        out.append(
            {
                "case_id": r.case_id,
                "expected_failure_code": r.expected_failure_code,
                "acceptable_primary_codes": acceptable.get(
                    r.case_id, [r.expected_failure_code]
                ),
                "stored_prediction": r.predicted_failure_code,
                "stored_rule_id": r.predicted_rule_id,
                "signals": signals,
            }
        )
    return out


def default_classifiers(labels: Sequence[str]) -> list[Classifier]:
    return [
        RuleEngineClassifier(),
        MajorityClassifier(labels),
        HeuristicClassifier(),
    ]


def compare_classifiers(
    cases: list[dict[str, Any]],
    classifiers: Sequence[Classifier],
) -> dict[str, Any]:
    """Run each classifier over every case and summarise."""
    results: dict[str, list[dict[str, Any]]] = {c.name: [] for c in classifiers}
    timings: dict[str, float] = {c.name: 0.0 for c in classifiers}
    malformed: dict[str, int] = {c.name: 0 for c in classifiers}

    for case in cases:
        bag = signal_bag_from_dict(case.get("signals") or {})
        expected = str(case["expected_failure_code"])
        acceptable = set(case.get("acceptable_primary_codes") or [expected])
        for clf in classifiers:
            started = time.perf_counter()
            pred = clf.predict(bag)
            timings[clf.name] += time.perf_counter() - started
            if pred.malformed:
                malformed[clf.name] += 1
            results[clf.name].append(
                {
                    "case_id": case["case_id"],
                    "expected_failure_code": expected,
                    "predicted_failure_code": pred.code,
                    "predicted_rule_id": pred.rule_id,
                    "score": pred.score,
                    "rationale": pred.rationale,
                    "correct_failure_code": pred.code in acceptable,
                    "correct_strict": pred.code == expected,
                    "stored_prediction": case.get("stored_prediction"),
                }
            )

    summary: dict[str, Any] = {}
    for name, rows in results.items():
        n = len(rows)
        per_class = per_class_metrics(rows)
        agg = aggregate_f1(per_class)
        lenient = sum(1 for r in rows if r["correct_failure_code"]) / n if n else None
        strict = sum(1 for r in rows if r["correct_strict"]) / n if n else None
        mf = macro_f1(rows)
        summary[name] = {
            "n": n,
            "lenient_accuracy": None if lenient is None else round(lenient, 6),
            "strict_accuracy": None if strict is None else round(strict, 6),
            "macro_f1": None if mf is None else round(mf, 6),
            "micro_f1": agg["micro_f1"],
            "weighted_f1": agg["weighted_f1"],
            "per_class": per_class,
            "confusion_matrix": confusion_matrix(rows),
            "malformed_outputs": malformed[name],
            "mean_latency_ms": round(timings[name] / n * 1000, 3) if n else None,
            "uncertain_rate": (
                round(sum(1 for r in rows if r["predicted_failure_code"] == "DIAGNOSIS_UNCERTAIN") / n, 6)
                if n
                else None
            ),
        }

    names = list(results.keys())
    agreement: dict[str, Any] = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            pa = [r["predicted_failure_code"] for r in results[a]]
            pb = [r["predicted_failure_code"] for r in results[b]]
            agreement[f"{a}~{b}"] = {
                "raw_agreement": round(sum(1 for x, y in zip(pa, pb) if x == y) / len(pa), 6)
                if pa
                else None,
                "cohens_kappa": cohens_kappa(pa, pb),
            }

    # Consistency: re-running the rule engine on stored signals must reproduce
    # the stored prediction (guards against drift between engine and bench).
    consistency = None
    if "rule_engine" in results:
        rows = results["rule_engine"]
        comparable = [r for r in rows if r.get("stored_prediction")]
        if comparable:
            consistency = round(
                sum(1 for r in comparable if r["predicted_failure_code"] == r["stored_prediction"])
                / len(comparable),
                6,
            )

    return {
        "classifiers": summary,
        "agreement": agreement,
        "rule_engine_replay_consistency": consistency,
        "per_case": results,
    }
