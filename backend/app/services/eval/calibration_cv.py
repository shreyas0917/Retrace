"""Cross-validated calibration on a labelled suite (Step G).

The committed calibrator (`backend/configs/calibration.json`) is fitted on the
synthetic `calib_v1` suite. This module asks whether the confidence score is
calibrated on real runs, without fitting and scoring on the same cases:

* k-fold (default 5), stratified on correct/incorrect when both classes have at
  least k cases; the histogram calibrator is fitted on k-1 folds and applied to
  the held-out fold, so every case gets an out-of-fold calibrated probability;
* pooled ECE and Brier score for three predictors: the raw `diagnosis_score`,
  the committed calibrator's `calibrated_confidence`, and the cross-validated
  live calibrator;
* percentile bootstrap 95% CIs, plus paired bootstrap CIs of each predictor's
  difference from the raw score, so "clearly lower" has a definition;
* reliability tables with the case count per bin, and the number of distinct
  raw score values (a score with four values cannot be finely calibrated).

Nothing here writes the calibration config.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any

from app.services.diagnosis.calibration import (
    apply_calibration,
    brier_score,
    expected_calibration_error,
    fit_histogram_calibrator,
    reliability_bins,
)

CV_SEED = 20261109
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261109
PREDICTORS = ("raw", "calib_v1", "cv_live")


def stratified_folds(correct: Sequence[bool], k: int, *, seed: int = CV_SEED) -> tuple[list[int], bool]:
    """Fold index per case. Stratified on the outcome when each class has >= k cases."""
    n = len(correct)
    if n < k:
        raise ValueError(f"need at least {k} cases for {k}-fold cross-validation, got {n}")
    rng = random.Random(seed)
    folds = [0] * n
    pos = [i for i in range(n) if correct[i]]
    neg = [i for i in range(n) if not correct[i]]
    stratified = len(pos) >= k and len(neg) >= k
    groups = [pos, neg] if stratified else [list(range(n))]
    offset = 0
    for group in groups:
        rng.shuffle(group)
        for j, i in enumerate(group):
            folds[i] = (j + offset) % k
        offset += len(group)
    return folds, stratified


def out_of_fold_calibrated(
    scores: Sequence[float], correct: Sequence[bool], folds: Sequence[int], k: int, n_bins: int
) -> list[float]:
    out = [0.0] * len(scores)
    for f in range(k):
        train = [i for i in range(len(scores)) if folds[i] != f]
        table = fit_histogram_calibrator(
            [scores[i] for i in train], [correct[i] for i in train], n_bins=n_bins, fitted_on=f"fold-{f}"
        )
        for i in range(len(scores)):
            if folds[i] == f:
                out[i] = apply_calibration(table, scores[i])
    return out


def _ece(probs: Sequence[float], correct: Sequence[bool], n_bins: int) -> float | None:
    return expected_calibration_error(reliability_bins(probs, correct, n_bins))


def _bootstrap(
    n: int, stat: Callable[[list[int]], float | None], *, resamples: int, seed: int
) -> dict[str, float | None]:
    point = stat(list(range(n)))
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        v = stat([rng.randrange(n) for _ in range(n)])
        if v is not None:
            values.append(v)
    if point is None or not values:
        return {"point": point, "low": None, "high": None}
    values.sort()
    lo = values[int(0.025 * (len(values) - 1))]
    hi = values[int(0.975 * (len(values) - 1))]
    return {"point": round(point, 6), "low": round(lo, 6), "high": round(hi, 6)}


def cross_validated_calibration(
    rows: Sequence[dict[str, Any]],
    *,
    k: int = 5,
    n_bins: int = 10,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """rows: evaluation cases with diagnosis_score, calibrated_confidence and correct_failure_code."""
    usable = [r for r in rows if r.get("diagnosis_score") is not None]
    raw = [float(r["diagnosis_score"]) for r in usable]
    committed = [
        float(r["calibrated_confidence"]) if r.get("calibrated_confidence") is not None else float(r["diagnosis_score"])
        for r in usable
    ]
    correct = [bool(r.get("correct_failure_code")) for r in usable]
    folds, stratified = stratified_folds(correct, k)
    cv = out_of_fold_calibrated(raw, correct, folds, k, n_bins)
    probs = {"raw": raw, "calib_v1": committed, "cv_live": cv}
    n = len(usable)

    def metric(name: str, which: str) -> Callable[[list[int]], float | None]:
        p = probs[name]
        if which == "ece":
            return lambda idx: _ece([p[i] for i in idx], [correct[i] for i in idx], n_bins)
        return lambda idx: brier_score([p[i] for i in idx], [correct[i] for i in idx])

    def diff(name: str, which: str) -> Callable[[list[int]], float | None]:
        a, b = metric(name, which), metric("raw", which)

        def f(idx: list[int]) -> float | None:
            x, y = a(idx), b(idx)
            return None if x is None or y is None else x - y

        return f

    predictors: dict[str, Any] = {}
    for name in PREDICTORS:
        entry: dict[str, Any] = {
            "ece": _bootstrap(n, metric(name, "ece"), resamples=resamples, seed=seed),
            "brier": _bootstrap(n, metric(name, "brier"), resamples=resamples, seed=seed),
            "bins": [b.__dict__ for b in reliability_bins(probs[name], correct, n_bins)],
            "distinct_values": len({round(v, 6) for v in probs[name]}),
        }
        if name != "raw":
            entry["ece_minus_raw"] = _bootstrap(n, diff(name, "ece"), resamples=resamples, seed=seed)
            entry["brier_minus_raw"] = _bootstrap(n, diff(name, "brier"), resamples=resamples, seed=seed)
        predictors[name] = entry

    cv_entry = predictors["cv_live"]
    clearly_better = all(
        cv_entry[key]["high"] is not None and cv_entry[key]["high"] < 0 for key in ("ece_minus_raw", "brier_minus_raw")
    )
    return {
        "n": n,
        "k": k,
        "n_bins": n_bins,
        "stratified": stratified,
        "cv_seed": CV_SEED,
        "bootstrap": {"resamples": resamples, "seed": seed},
        "accuracy": round(sum(correct) / n, 6) if n else None,
        "distinct_raw_scores": sorted({round(v, 6) for v in raw}),
        "fold_sizes": [folds.count(f) for f in range(k)],
        "predictors": predictors,
        "decision": {
            "cv_clearly_lower_than_raw": clearly_better,
            "rule": "the cross-validated calibrator counts as clearly better only if the upper end of the 95% "
            "paired-bootstrap CI of both (ECE_cv - ECE_raw) and (Brier_cv - Brier_raw) is below 0",
        },
    }


def score_distribution(rows: Sequence[dict[str, Any]], n_bins: int = 10) -> dict[str, Any]:
    """How a suite's raw and calibrated scores spread over the reliability bins."""
    usable = [r for r in rows if r.get("diagnosis_score") is not None]
    correct = [bool(r.get("correct_failure_code")) for r in usable]
    raw = [float(r["diagnosis_score"]) for r in usable]
    cal = [float(r.get("calibrated_confidence") or r["diagnosis_score"]) for r in usable]
    raw_bins = reliability_bins(raw, correct, n_bins)
    cal_bins = reliability_bins(cal, correct, n_bins)
    return {
        "n": len(usable),
        "distinct_raw_scores": sorted({round(v, 6) for v in raw}),
        "raw_bins_used": sum(1 for b in raw_bins if b.count),
        "calibrated_bins": [b.__dict__ for b in cal_bins],
        "largest_calibrated_bin": max((b.count for b in cal_bins), default=0),
        "calibrated_ece": expected_calibration_error(cal_bins),
    }


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------
_NAMES = {
    "raw": "Raw `diagnosis_score`",
    "calib_v1": "Committed calibrator (fitted on `calib_v1`)",
    "cv_live": "Cross-validated live calibrator",
}


def _ci(ci: dict[str, float | None]) -> str:
    if ci.get("point") is None:
        return "n/a"
    if ci.get("low") is None:
        return f"{ci['point']:.3f}"
    return f"{ci['point']:.3f} ({ci['low']:.3f} to {ci['high']:.3f})"


def _signed(ci: dict[str, float | None]) -> str:
    if ci.get("point") is None or ci.get("low") is None:
        return "n/a"
    return f"{ci['point']:+.3f} ({ci['low']:+.3f} to {ci['high']:+.3f})"


def render_cv_markdown(report: dict[str, Any], *, command: str, suite: str, provenance: str, banner: str | None) -> str:
    r = report
    p = r["predictors"]
    lines = [f"# Calibration on {suite}, cross-validated", ""]
    if banner:
        lines += [f"> **{banner}.** Do not quote these numbers until the review is done.", ""]
    lines += [
        f"Produced by `{command}`. {provenance}",
        "",
        f"{r['n']} cases, {r['k']}-fold cross-validation "
        f"({'stratified on correct/incorrect' if r['stratified'] else 'not stratified: too few cases in one class'}; "
        f"fold sizes {', '.join(map(str, r['fold_sizes']))}; seed {r['cv_seed']}). Diagnosis accuracy (strict) on "
        f"these cases: {r['accuracy'] * 100:.1f}%. The histogram calibrator ({r['n_bins']} equal-width bins) is fitted "
        "on four folds and applied to the fifth, so no case is scored by a calibrator that saw it.",
        "",
        f"The raw score takes **{len(r['distinct_raw_scores'])} distinct values** "
        f"({', '.join(f'{v:g}' for v in r['distinct_raw_scores'])}), so any calibrator can only map those few values "
        "to probabilities.",
        "",
        "## Pooled results",
        "",
        "Lower is better. 95% CIs: percentile bootstrap over cases "
        f"({r['bootstrap']['resamples']} resamples, seed {r['bootstrap']['seed']}), with the fold assignment fixed.",
        "",
        "| Predictor | ECE | Brier | ECE minus raw | Brier minus raw | Distinct values |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for name in PREDICTORS:
        e = p[name]
        lines.append(
            f"| {_NAMES[name]} | {_ci(e['ece'])} | {_ci(e['brier'])} | "
            f"{_signed(e['ece_minus_raw']) if 'ece_minus_raw' in e else '—'} | "
            f"{_signed(e['brier_minus_raw']) if 'brier_minus_raw' in e else '—'} | {e['distinct_values']} |"
        )
    lines += ["", "## Reliability tables", "", "Bins with no cases are left out."]
    for name in PREDICTORS:
        lines += [
            "",
            f"**{_NAMES[name]}**",
            "",
            "| Bin | Cases | Mean predicted | Accuracy |",
            "| --- | ---: | ---: | ---: |",
        ]
        for b in p[name]["bins"]:
            if b["count"]:
                lines.append(
                    f"| {b['lo']:.1f}–{b['hi']:.1f} | {b['count']} | {b['mean_score']:.3f} | {b['accuracy']:.3f} |"
                )
    lines += [
        "",
        "## What the data supports",
        "",
        f"Decision rule, fixed before looking at the numbers: {r['decision']['rule']}.",
        "",
    ]
    if r["decision"]["cv_clearly_lower_than_raw"]:
        cv = p["cv_live"]
        lines.append(
            f"The cross-validated live calibrator is clearly better calibrated than the raw score: ECE "
            f"{_ci(cv['ece'])} against {_ci(p['raw']['ece'])}, Brier {_ci(cv['brier'])} against {_ci(p['raw']['brier'])}."
        )
    else:
        lines.append(
            "The cross-validated live calibrator is **not** clearly better than the raw score on these cases. "
            "The honest claim is: confidence is a rule-strength score, and its calibration on real runs is "
            f"limited by sample size ({r['n']} cases) and by the raw score taking only "
            f"{len(r['distinct_raw_scores'])} values."
        )
    lines += [
        "",
        "## Limits",
        "",
        f"- {r['n']} cases from one model and one corpus; a few cases move every number here.",
        "- ECE with 10 equal-width bins is itself noisy at this size; the bootstrap intervals include that noise "
        "but not the variation from a different fold split.",
        "- This report never writes `backend/configs/calibration.json`.",
        "",
    ]
    return "\n".join(lines)
