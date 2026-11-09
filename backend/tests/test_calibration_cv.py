"""Cross-validated calibration (services/eval/calibration_cv.py)."""

from __future__ import annotations

from app.services.eval import calibration_cv as cv


def _rows(pattern: list[tuple[float, bool]], calibrated: float | None = None) -> list[dict]:
    return [{"diagnosis_score": s, "calibrated_confidence": calibrated, "correct_failure_code": c} for s, c in pattern]


def test_folds_are_stratified_and_balanced() -> None:
    correct = [True] * 20 + [False] * 30
    folds, stratified = cv.stratified_folds(correct, 5)
    assert stratified
    for f in range(5):
        members = [i for i in range(50) if folds[i] == f]
        assert len(members) == 10
        assert sum(correct[i] for i in members) == 4
    assert cv.stratified_folds(correct, 5) == (folds, stratified)  # seeded


def test_folds_fall_back_when_a_class_is_too_small() -> None:
    folds, stratified = cv.stratified_folds([True] * 10 + [False] * 2, 5)
    assert not stratified and sorted(set(folds)) == [0, 1, 2, 3, 4]


def test_out_of_fold_never_uses_its_own_fold() -> None:
    # One case alone in its bin: out of fold, that bin is empty, so the raw score is returned.
    scores = [0.95] + [0.55] * 9
    correct = [False] + [True] * 9
    folds = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    out = cv.out_of_fold_calibrated(scores, correct, folds, 5, 10)
    assert out[0] == 0.95  # an in-sample fit would have said 0.0
    assert all(v == 1.0 for v in out[1:])


def test_report_shape_and_decision_rule() -> None:
    # Raw score badly overconfident; accuracy depends on the score, so a fitted calibrator can fix it.
    pattern = [(0.95, i % 5 == 0) for i in range(40)] + [(0.45, i % 10 != 0) for i in range(40)]
    report = cv.cross_validated_calibration(_rows(pattern), k=5, resamples=300)
    assert report["n"] == 80 and report["distinct_raw_scores"] == [0.45, 0.95]
    p = report["predictors"]
    assert set(p) == {"raw", "calib_v1", "cv_live"}
    for name in p:
        assert p[name]["ece"]["low"] <= p[name]["ece"]["point"] <= p[name]["ece"]["high"]
        assert sum(b["count"] for b in p[name]["bins"]) == 80
    assert p["cv_live"]["ece"]["point"] < p["raw"]["ece"]["point"]
    assert report["decision"]["cv_clearly_lower_than_raw"] is True
    spread = report["split_spread"]
    assert spread["seeds"] == cv.SPLIT_SEEDS and spread["ece"]["min"] <= spread["ece"]["median"] <= spread["ece"]["max"]
    md = cv.render_cv_markdown(report, command="cmd", suite="live_v1", provenance="p", banner=None)
    assert "lookup table" in md and "Other fold splits" in md and "> **" not in md
    # The committed calibrator falls back to the raw score when calibrated_confidence is missing.
    assert p["calib_v1"]["ece"]["point"] == p["raw"]["ece"]["point"]


def test_no_claim_when_the_raw_score_is_already_calibrated() -> None:
    pattern = [(0.8, i % 5 != 0) for i in range(50)]
    report = cv.cross_validated_calibration(_rows(pattern, calibrated=0.8), k=5, resamples=300)
    assert report["decision"]["cv_clearly_lower_than_raw"] is False
    md = cv.render_cv_markdown(report, command="cmd", suite="live_v1", provenance="p", banner="Labels: x")
    assert "**not** clearly better" in md and "rule-strength score" in md and "> **Labels: x.**" in md
    assert "| Bin | Cases |" in md and "never writes `backend/configs/calibration.json`" in md


def test_heldout_report_warns_when_one_bin_holds_most_cases() -> None:
    from app.cli.benchmark_cmd import calibration_report, concentration_caveat

    cases = [{"diagnosis_score": 0.95, "calibrated_confidence": 1.0, "correct_failure_code": True}] * 153 + [
        {"diagnosis_score": 0.75, "calibrated_confidence": 0.667, "correct_failure_code": i < 4} for i in range(7)
    ]
    text = concentration_caveat(calibration_report(cases))
    assert text is not None and "153 of 160 cases in one bin" in text and "only 2 of the 10 bins" in text
    spread = [
        {"diagnosis_score": s, "calibrated_confidence": s, "correct_failure_code": True}
        for s in (0.15, 0.45, 0.75, 0.95)
    ]
    assert concentration_caveat(calibration_report(spread)) is None


def test_score_distribution_counts_bins() -> None:
    rows = _rows([(0.9, True)] * 9 + [(0.3, False)], calibrated=0.97)
    dist = cv.score_distribution(rows)
    assert dist["n"] == 10 and dist["raw_bins_used"] == 2 and dist["largest_calibrated_bin"] == 10
