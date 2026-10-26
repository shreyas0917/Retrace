"""v1.0 — uncertain outcome, explanations, calibration, classifiers, held-out suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import session as db_session
from app.services.diagnosis.calibration import (
    CalibrationTable,
    apply_calibration,
    brier_score,
    expected_calibration_error,
    fit_histogram_calibrator,
    load_calibration,
    reliability_bins,
    save_calibration,
)
from app.services.diagnosis.classifiers import (
    HeuristicClassifier,
    LLMClassifier,
    MajorityClassifier,
    RuleEngineClassifier,
    signal_bag_from_dict,
)
from app.services.diagnosis.explain import build_explanation
from app.services.diagnosis.models import SignalBag
from app.services.diagnosis.rule_catalog import get_rule
from app.services.diagnosis.rules import apply_rules
from app.services.diagnosis.taxonomy import FAILURE_CODES, layer_for, recommendation_for
from app.services.eval.classifier_bench import cohens_kappa, compare_classifiers
from app.services.eval.suite_loader import load_suite
from app.services.eval.thresholds_config import default_thresholds_path, load_thresholds
from app.services.llm_client import LLMResult, set_llm_provider
from app.services.metrics.diagnosis import (
    aggregate_f1,
    per_class_metrics,
    selective_metrics,
    strict_accuracy,
    summarize_results,
)


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


# --- taxonomy / rules -------------------------------------------------------


def test_taxonomy_has_uncertain_code() -> None:
    assert "DIAGNOSIS_UNCERTAIN" in FAILURE_CODES
    assert layer_for("DIAGNOSIS_UNCERTAIN") == "uncertain"
    assert recommendation_for("DIAGNOSIS_UNCERTAIN") == "MANUAL_REVIEW"
    assert get_rule("R90")["result"] == "DIAGNOSIS_UNCERTAIN"


def test_r90_fires_on_inconsistent_faithfulness() -> None:
    # Low faithfulness but zero unsupported claims: the judge contradicts itself.
    bag = SignalBag(
        n_retrieved=1,
        retrieved_ids=["doc:c000"],
        context_sufficient=True,
        answer_is_abstention=False,
        answer_contradicts_context=False,
        faithfulness_score=0.4,
        unsupported_claim_count=0,
        supported_claim_count=2,
    )
    decision = apply_rules(bag)
    assert decision.primary_code == "DIAGNOSIS_UNCERTAIN"
    assert decision.rule_id == "R90"
    assert decision.diagnosis_confidence == "low"
    assert "judge:faithfulness:inconsistent" in decision.evidence_refs


def test_r90_fires_when_relevance_verdict_missing() -> None:
    bag = SignalBag(n_retrieved=2, retrieved_ids=["a:c000", "b:c000"], context_sufficient=None)
    decision = apply_rules(bag)
    assert decision.primary_code == "DIAGNOSIS_UNCERTAIN"
    assert "judge:relevance:missing" in decision.evidence_refs


def test_consistent_signals_still_reach_ok_grounded() -> None:
    bag = SignalBag(
        n_retrieved=1,
        retrieved_ids=["doc:c000"],
        context_sufficient=True,
        answer_is_abstention=False,
        answer_contradicts_context=False,
        faithfulness_score=1.0,
        unsupported_claim_count=0,
        supported_claim_count=2,
    )
    assert apply_rules(bag).primary_code == "OK_GROUNDED"


# --- explanations -----------------------------------------------------------


def test_explanation_mentions_rule_and_evidence() -> None:
    bag = SignalBag(
        n_retrieved=2,
        retrieved_ids=["doc:c000", "x:c001"],
        gold_ids=["doc:c000"],
        gold_hit=True,
        gold_recall_at_k=1.0,
        irrelevant_frac=0.5,
        context_sufficient=True,
        answer_is_abstention=False,
        answer_contradicts_context=False,
        faithfulness_score=0.2,
        unsupported_claim_count=2,
        supported_claim_count=0,
        chunk_relevance=[
            {"chunk_id": "doc:c000", "relevant": True, "score": 0.9},
            {"chunk_id": "x:c001", "relevant": False, "score": 0.1},
        ],
    )
    decision = apply_rules(bag)
    text = build_explanation(decision, bag)
    assert decision.primary_code == "GENERATION_HALLUCINATION"
    assert "R31" in text
    assert "GENERATION_HALLUCINATION" in text
    assert "Retrieved 2 chunk(s)" in text
    assert "1/2 chunk(s) relevant" in text
    assert "faithfulness 0.20" in text
    assert "no conflict" in text


def test_explanation_for_uncertain_recommends_review() -> None:
    bag = SignalBag(
        n_retrieved=1,
        retrieved_ids=["doc:c000"],
        context_sufficient=True,
        faithfulness_score=0.5,
        unsupported_claim_count=0,
        supported_claim_count=1,
    )
    decision = apply_rules(bag)
    assert "manual review" in build_explanation(decision, bag)


# --- calibration -----------------------------------------------------------


def test_reliability_bins_and_ece() -> None:
    scores = [0.95, 0.95, 0.95, 0.95, 0.15, 0.15]
    correct = [True, True, True, False, False, False]
    bins = reliability_bins(scores, correct, n_bins=10)
    top = bins[9]
    assert top.count == 4 and top.accuracy == 0.75 and top.mean_score == 0.95
    low = bins[1]
    assert low.count == 2 and low.accuracy == 0.0
    ece = expected_calibration_error(bins)
    # (4/6)*|0.75-0.95| + (2/6)*|0-0.15|
    assert ece == pytest.approx((4 / 6) * 0.2 + (2 / 6) * 0.15, abs=1e-6)


def test_perfectly_calibrated_scores_have_zero_ece_and_brier_math() -> None:
    scores = [1.0, 1.0, 0.0]
    correct = [True, True, False]
    bins = reliability_bins(scores, correct, n_bins=4)
    assert expected_calibration_error(bins) == 0.0
    assert brier_score(scores, correct) == 0.0
    assert brier_score([0.5], [True]) == 0.25


def test_histogram_calibrator_round_trip(tmp_path: Path) -> None:
    table = fit_histogram_calibrator(
        [0.95] * 8 + [0.3] * 2,
        [True] * 6 + [False] * 2 + [False, True],
        n_bins=10,
        fitted_on="unit",
    )
    assert apply_calibration(table, 0.97) == 0.75
    # empty bin falls back to the raw score
    assert apply_calibration(table, 0.55) == 0.55
    path = save_calibration(table, tmp_path / "cal.json")
    loaded = load_calibration(path)
    assert isinstance(loaded, CalibrationTable)
    assert loaded.sample_size == 10
    assert apply_calibration(loaded, 0.3) == 0.5
    assert apply_calibration(None, 0.42) == 0.42


# --- metrics ---------------------------------------------------------------


def _row(expected: str, predicted: str, *, acceptable=None, uncertain=False) -> dict:
    acceptable = acceptable or [expected]
    return {
        "expected_failure_code": expected,
        "predicted_failure_code": predicted,
        "correct_failure_code": predicted in acceptable,
        "uncertain": uncertain,
    }


def test_per_class_and_aggregate_f1() -> None:
    rows = [
        _row("A", "A"),
        _row("A", "B"),
        _row("B", "B"),
        _row("B", "B"),
        _row("C", "A"),
    ]
    pc = per_class_metrics(rows)
    assert pc["A"] == {
        "support": 2, "predicted": 2, "tp": 1, "fp": 1, "fn": 1,
        "precision": 0.5, "recall": 0.5, "f1": 0.5,
    }
    assert pc["B"]["precision"] == pytest.approx(2 / 3)
    assert pc["B"]["recall"] == 1.0
    assert pc["C"]["support"] == 1 and pc["C"]["f1"] == 0.0
    agg = aggregate_f1(pc)
    assert agg["micro_f1"] == pytest.approx(0.6)
    assert strict_accuracy(rows) == pytest.approx(0.6)


def test_selective_metrics_defer_uncertain() -> None:
    rows = [
        _row("A", "A"),
        _row("A", "A"),
        _row("A", "B", uncertain=True),
        _row("B", "B", uncertain=True),
    ]
    sel = selective_metrics(rows)
    assert sel["coverage"] == 0.5
    assert sel["selective_accuracy"] == 1.0
    assert sel["deferred"] == 2
    assert sel["deferred_accuracy"] == 0.5
    summary = summarize_results(rows)
    assert summary["selective"]["uncertain_rate"] == 0.5
    assert "per_class" in summary and "weighted_f1" in summary


# --- classifiers -----------------------------------------------------------


def test_baseline_classifiers_and_kappa() -> None:
    maj = MajorityClassifier(["OK_GROUNDED", "OK_GROUNDED", "RETRIEVAL_MISS"])
    assert maj.predict(SignalBag()).code == "OK_GROUNDED"
    heur = HeuristicClassifier()
    assert heur.predict(SignalBag(n_retrieved=0)).code == "RETRIEVAL_EMPTY"
    assert heur.predict(SignalBag(n_retrieved=1, gold_ids=["g"], gold_hit=False)).code == "RETRIEVAL_MISS"
    assert heur.predict(SignalBag(n_retrieved=1, answer_is_abstention=True)).code == "OK_CORRECT_ABSTENTION"
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    assert cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert cohens_kappa([], []) is None


def test_signal_bag_round_trip_ignores_unknown_keys() -> None:
    data = SignalBag(n_retrieved=3, retrieved_ids=["a", "b", "c"]).to_dict()
    data["metrics"] = {"x": 1}
    data["explanation"] = "ignored"
    bag = signal_bag_from_dict(data)
    assert bag.n_retrieved == 3 and bag.retrieved_ids == ["a", "b", "c"]


class _ScriptedClassifierLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(self, messages, *, model, timeout):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResult(content=reply, model=model, latency_ms=1.0)


def test_llm_classifier_parses_and_falls_back() -> None:
    bag = SignalBag(n_retrieved=1, retrieved_ids=["d:c000"], context_sufficient=True,
                    faithfulness_score=0.1, unsupported_claim_count=1)
    good = _ScriptedClassifierLLM(
        ['```json\n{"failure_code": "generation_hallucination", "confidence": 0.8, "rationale": "r"}\n```']
    )
    set_llm_provider(good)
    try:
        pred = LLMClassifier().predict(bag)
    finally:
        set_llm_provider(None)
    assert pred.code == "GENERATION_HALLUCINATION" and pred.score == 0.8 and not pred.malformed

    bad = _ScriptedClassifierLLM(["nonsense", '{"failure_code": "NOT_A_CODE"}'])
    set_llm_provider(bad)
    try:
        pred = LLMClassifier().predict(bag)
    finally:
        set_llm_provider(None)
    assert pred.code == "DIAGNOSIS_UNCERTAIN" and pred.malformed and bad.calls == 2


def test_compare_classifiers_reports_agreement_and_consistency() -> None:
    cases = [
        {
            "case_id": "c1",
            "expected_failure_code": "RETRIEVAL_EMPTY",
            "acceptable_primary_codes": ["RETRIEVAL_EMPTY"],
            "stored_prediction": "RETRIEVAL_EMPTY",
            "signals": SignalBag(n_retrieved=0).to_dict(),
        },
        {
            "case_id": "c2",
            "expected_failure_code": "RETRIEVAL_MISS",
            "acceptable_primary_codes": ["RETRIEVAL_MISS"],
            "stored_prediction": "RETRIEVAL_MISS",
            "signals": SignalBag(n_retrieved=1, retrieved_ids=["x"], gold_ids=["g"], gold_hit=False).to_dict(),
        },
    ]
    report = compare_classifiers(
        cases, [RuleEngineClassifier(), MajorityClassifier(["RETRIEVAL_MISS"]), HeuristicClassifier()]
    )
    assert report["classifiers"]["rule_engine"]["lenient_accuracy"] == 1.0
    assert report["classifiers"]["heuristic"]["lenient_accuracy"] == 1.0
    assert report["classifiers"]["majority"]["lenient_accuracy"] == 0.5
    assert report["rule_engine_replay_consistency"] == 1.0
    assert "rule_engine~heuristic" in report["agreement"]


# --- per-suite thresholds ----------------------------------------------------


def test_per_suite_thresholds_resolve() -> None:
    assert default_thresholds_path("heldout_v1").name == "thresholds.heldout_v1.yaml"
    assert default_thresholds_path("planted_v1").name == "thresholds.default.yaml"
    thr = load_thresholds(suite_id="heldout_v1")
    assert thr["fail_on_eval_error_rate_gt"] == 0.20
    assert thr["min_failure_code_accuracy"] == 0.80


# --- held-out suite ------------------------------------------------------------


def test_heldout_suites_load_and_match_manifest() -> None:
    for suite_id, minimum in (("heldout_v1", 150), ("calib_v1", 60)):
        cases, suite_hash, meta = load_suite(suite_id, "1.0.0")
        assert len(cases) >= minimum
        assert meta["manifest"]["suite_hash"] == suite_hash
        labels = {c.failure_label for c in cases}
        assert {
            "RETRIEVAL_MISS", "GENERATION_HALLUCINATION", "GROUNDING_PARTIAL",
            "OK_GROUNDED", "ABSTENTION_FALSE_NEGATIVE", "EVAL_MODEL_TIMEOUT",
        } <= labels
        assert all(c.offline_execution is not None for c in cases)
        assert all(c.annotator == "synthetic_generator_v1" for c in cases)
    heldout = {c.case_id for c in load_suite("heldout_v1", "1.0.0")[0]}
    calib = {c.case_id for c in load_suite("calib_v1", "1.0.0")[0]}
    assert not heldout & calib


def test_heldout_benchmark_end_to_end_meets_floor() -> None:
    """Run the full held-out suite through the engine; enforce the documented floor."""
    from app.services.eval.evaluate import run_evaluation

    db = _open_db()
    try:
        result = run_evaluation(db, suite_id="heldout_v1", suite_version="1.0.0", persist=True)
    finally:
        db.close()
    summary = result["summary"]
    assert summary["total_cases"] >= 150
    assert summary["failure_code_accuracy"] >= 0.80, summary
    assert summary["strict_accuracy"] >= 0.70, summary
    assert summary["per_class"]["RETRIEVAL_MISS"]["recall"] == 1.0
    assert summary["per_class"]["EVAL_MODEL_TIMEOUT"]["f1"] == 1.0
    # Boundary cases are the ones expected to be wrong or deferred.
    wrong = [c for c in result["cases"] if not c["correct_failure_code"]]
    assert all("boundary" in c["tags"] for c in wrong), [
        (c["case_id"], c["expected_failure_code"], c["predicted_failure_code"]) for c in wrong
    ]
    assert all(c.get("explanation") for c in result["cases"])
    assert result["exit_code"] in (0, 1)
