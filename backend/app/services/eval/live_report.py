"""live_v1 benchmark report: real runs, the author's blind labels.

`run_live_report` evaluates the labelled live suite offline (the recorded
judge outputs replay; no model is called), then adds what a small real
benchmark needs on top of the usual metrics:

* bootstrap 95% confidence intervals, because about 50 cases leave wide ones;
* a breakdown per injected condition (a tag, not the label);
* an error analysis line for every miss. The cause is an automatic first
  pass that compares Retrace's judge signals with what the label implies
  (judge error, rule gap, deferral, or a label that allowed alternatives).
  It is a starting point and is marked as such in the report.

Rendered by `retrace benchmark report --suite live_v1`.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Diagnosis
from app.services.abstention import exact_sentinel_matching
from app.services.diagnosis.calibration import load_calibration
from app.services.diagnosis.taxonomy import short_code
from app.services.eval.evaluate import APP_VERSION, run_evaluation
from app.services.eval.suite_loader import load_suite, suite_dir
from app.services.metrics.diagnosis import macro_f1

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261108
GROUNDING_FAILURES = {"GROUNDING_PARTIAL", "GROUNDING_UNSUPPORTED", "GENERATION_HALLUCINATION"}


def _condition(tags: list[str] | None) -> str:
    for tag in tags or []:
        if tag.startswith("condition:"):
            return tag.split(":", 1)[1]
    return "unknown"


def _lenient(rows: list[dict[str, Any]]) -> float | None:
    return sum(1 for r in rows if r.get("correct_failure_code")) / len(rows) if rows else None


def _strict(rows: list[dict[str, Any]]) -> float | None:
    return sum(1 for r in rows if r.get("correct_strict")) / len(rows) if rows else None


def bootstrap_ci(
    rows: list[dict[str, Any]],
    metric: Callable[[list[dict[str, Any]]], float | None],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float | None]:
    """Percentile bootstrap 95% CI, resampling cases with replacement."""
    point = metric(rows) if rows else None
    if point is None:
        return {"point": None, "low": None, "high": None}
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        value = metric(sample)
        if value is not None:
            values.append(value)
    values.sort()
    low = values[int(0.025 * (len(values) - 1))]
    high = values[int(0.975 * (len(values) - 1))]
    return {"point": round(point, 6), "low": round(low, 6), "high": round(high, 6)}


def attribute_miss(result: dict[str, Any], label: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    """Automatic first-pass cause for one miss: compare judge signals with the label."""
    expected = result["expected_failure_code"]
    predicted = result["predicted_failure_code"]
    causes: list[tuple[str, str]] = []

    if predicted == "DIAGNOSIS_UNCERTAIN":
        causes.append(("deferred", "the engine deferred (R90): " + str(result.get("explanation") or "")[:160]))
    if expected.startswith("EVAL_") or predicted.startswith("EVAL_"):
        causes.append(("infrastructure", f"label {expected}, prediction {predicted}"))

    label_sufficient = not label.get("expected_abstention", False)
    judged_sufficient = signals.get("context_sufficient")
    if judged_sufficient is not None and judged_sufficient != label_sufficient and expected != "RETRIEVAL_MISS":
        causes.append(
            (
                "judge error: relevance",
                f"relevance judge said the context was {'sufficient' if judged_sufficient else 'insufficient'}; "
                f"the label says the system {'should' if not label_sufficient else 'should not'} abstain",
            )
        )

    contradicts = signals.get("answer_contradicts_context")
    if expected == "GENERATION_CONTRADICTION" and contradicts is False:
        causes.append(("judge error: contradiction", "contradiction judge did not flag the conflict"))
    if predicted == "GENERATION_CONTRADICTION" and expected != "GENERATION_CONTRADICTION" and contradicts:
        causes.append(("judge error: contradiction", "contradiction judge flagged a conflict the label does not see"))

    unsupported = signals.get("unsupported_claim_count") or 0
    if expected in GROUNDING_FAILURES and unsupported == 0 and signals.get("faithfulness_score") is not None:
        causes.append(("judge error: faithfulness", "NLI found every claim supported"))
    if expected == "OK_GROUNDED" and unsupported > 0:
        causes.append(("judge error: faithfulness", f"NLI marked {unsupported} claim(s) unsupported"))

    if expected == "RETRIEVAL_MISS" and signals.get("gold_hit"):
        causes.append(("label check", "labelled a retrieval miss, but a labelled gold chunk was retrieved"))
    if predicted == "RETRIEVAL_MISS" and expected != "RETRIEVAL_MISS":
        causes.append(
            ("rule gap", "R11 fires whenever no labelled gold chunk is retrieved; the label chose " + expected)
        )

    if not causes:
        causes.append(("rule gap", f"judge signals agree with the label, but the rules map them to {predicted}"))
    alternatives = [c for c in label.get("acceptable_primary_codes", []) if c != expected]
    return {
        "case_id": result["case_id"],
        "condition": _condition(result.get("tags")),
        "expected": expected,
        "alternatives": alternatives,
        "predicted": predicted,
        "rule_id": result.get("predicted_rule_id"),
        "cause": causes[0][0],
        "why": causes[0][1],
        "other_causes": [c[0] for c in causes[1:]],
        "label_notes": label.get("notes"),
    }


def _signals(db: Session, diagnosis_id: str | None) -> dict[str, Any]:
    if not diagnosis_id:
        return {}
    row = db.get(Diagnosis, diagnosis_id)
    return dict(row.signals or {}) if row is not None else {}


def run_live_report(db: Session, *, suite_id: str = "live_v1", suite_version: str = "1.0.0") -> dict[str, Any]:
    gold_cases, suite_hash, _ = load_suite(suite_id, suite_version)
    labels = {c.case_id: c.model_dump() for c in gold_cases}
    directory = suite_dir(suite_id, suite_version)
    runs_manifest_path = directory / "runs_manifest.json"
    runs_manifest = json.loads(runs_manifest_path.read_text(encoding="utf-8")) if runs_manifest_path.is_file() else {}
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))

    # Headline = the diagnosis Retrace made with the code that recorded these runs. The abstention
    # sentinel is matched exactly here (ADR-047), so a model answer like "INSUFFICIENT CONTEXT" with a
    # space is read exactly as it was at recording time, before the parsing fix.
    with exact_sentinel_matching():
        result = run_evaluation(db, suite_id=suite_id, suite_version=suite_version, persist=True)
    rows = result["cases"]
    summary = result["summary"]

    # Secondary = the same recordings re-diagnosed with the parsing fix in place (tolerant matching).
    # It is optimistic (the fix was written after seeing these very misses) and not an independent
    # measurement; no runs are re-recorded.
    fixed = run_evaluation(db, suite_id=suite_id, suite_version=suite_version, persist=False)
    fixed_rows = fixed["cases"]
    recorded_code = {r["case_id"]: r.get("predicted_failure_code") for r in rows}
    flipped = sorted(
        r["case_id"] for r in fixed_rows if r.get("predicted_failure_code") != recorded_code.get(r["case_id"])
    )
    fixed_by_id = {r["case_id"]: r for r in fixed_rows}
    after_fix = {
        "lenient_accuracy": bootstrap_ci(fixed_rows, _lenient),
        "strict_accuracy": bootstrap_ci(fixed_rows, _strict),
        "macro_f1": bootstrap_ci(fixed_rows, macro_f1),
        "changed_case_ids": flipped,
        "newly_correct": sorted(
            r["case_id"]
            for r in fixed_rows
            if r.get("correct_failure_code") and not _recorded_correct(rows, r["case_id"])
        ),
        "changed_to": dict(sorted(_count(fixed_by_id[cid].get("predicted_failure_code") for cid in flipped).items())),
    }

    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_condition[_condition(r.get("tags"))].append(r)
    conditions = {
        name: {
            "n": len(group),
            "lenient": _lenient(group),
            "strict": _strict(group),
            "uncertain": sum(1 for r in group if r.get("uncertain")),
            "labels": dict(sorted(_count(r["expected_failure_code"] for r in group).items())),
        }
        for name, group in sorted(by_condition.items())
    }

    misses = [
        attribute_miss(r, labels[r["case_id"]], _signals(db, r.get("diagnosis_id")))
        for r in rows
        if not r.get("correct_failure_code")
    ]
    applied = load_calibration()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "suite_id": suite_id,
        "suite_version": suite_version,
        "suite_hash": suite_hash,
        "experiment_id": result["experiment_id"],
        "git_commit": result.get("git_commit"),
        "annotator": manifest.get("annotator"),
        "annotation_date": manifest.get("annotation_date"),
        "human_reviewed": bool(manifest.get("human_reviewed")),
        "review": manifest.get("review"),
        "runs": {
            k: runs_manifest.get(k)
            for k in ("runs_hash", "generation_models", "judge_models", "git_commits", "recorded_from", "recorded_to")
        },
        "applied_calibrator": (
            {"fitted_on": applied.fitted_on, "sample_size": applied.sample_size} if applied else None
        ),
        "summary": summary,
        "confidence_intervals": {
            "lenient_accuracy": bootstrap_ci(rows, _lenient),
            "strict_accuracy": bootstrap_ci(rows, _strict),
            "macro_f1": bootstrap_ci(rows, macro_f1),
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "conditions": conditions,
        "after_fix": after_fix,
        "misses": misses,
        "miss_causes": dict(sorted(_count(m["cause"] for m in misses).items())),
        "timeouts": sum(
            1
            for c in gold_cases
            if c.offline_execution is not None
            and (c.offline_execution.status == "GENERATION_TIMEOUT" or c.offline_execution.judge_timeout_on)
        ),
        "model_timeout_seconds": sorted(
            {(r.get("settings") or {}).get("model_timeout_seconds") for r in _records(directory)} - {None}
        ),
    }


def _recorded_correct(rows: list[dict[str, Any]], case_id: str) -> bool:
    for r in rows:
        if r["case_id"] == case_id:
            return bool(r.get("correct_failure_code"))
    return False


def _records(directory: Path) -> list[dict[str, Any]]:
    path = directory / "runs.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _ci(ci: dict[str, float | None], pct: bool = True) -> str:
    if ci["point"] is None:
        return "n/a"
    fmt = (lambda x: f"{x * 100:.1f}%") if pct else (lambda x: f"{x:.3f}")
    return f"{fmt(ci['point'])} (95% CI {fmt(ci['low'])} to {fmt(ci['high'])})"


AI_BLIND_WORDING = (
    "labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); "
    "not yet reviewed by a human"
)


def label_provenance(report: dict[str, Any]) -> str:
    """One sentence on who produced the labels, worded from the suite manifest."""
    annotator = report.get("annotator")
    n = report.get("summary", {}).get("total_cases")
    if annotator == "ai_draft_blind":
        return (
            f"Labels: {AI_BLIND_WORDING}. The annotator saw only the blind sheet, the labelling guide and the "
            "corpus chunks, never the runs or the injected conditions."
        )
    if annotator == "ai_draft_author_reviewed":
        review = report.get("review") or {}
        return (
            f"Labels: AI-drafted, reviewed and corrected by the author "
            f"({review.get('changed_cases', '?')} of {review.get('reviewed_cases', n)} changed). "
            "Both the drafting agent and the author saw only the blind sheet."
        )
    return f"Labels: {annotator}, from a sheet that showed only the question, the ranked chunks and the answer."


def _labeller_limit(report: dict[str, Any]) -> str:
    annotator = report.get("annotator")
    if annotator == "ai_draft_blind":
        return (
            "- One labeller, an independent AI annotator; no human has reviewed its labels yet, and label noise "
            "is not measured. Human review is planned."
        )
    if annotator == "ai_draft_author_reviewed":
        return (
            "- One AI draft and one human reviewer (the author), with no independent second annotator, so "
            "label noise is not measured. A reviewer who starts from a draft may anchor on it."
        )
    return f"- One labeller ({annotator}), with no second annotator, so label noise is not measured."


def _after_fix_lines(report: dict[str, Any], ci: dict[str, Any]) -> list[str]:
    af = report.get("after_fix")
    if not af:
        return []
    changed = af.get("changed_case_ids") or []
    newly = af.get("newly_correct") or []
    changed_to = ", ".join(f"`{code}` {n}" for code, n in (af.get("changed_to") or {}).items())
    return [
        "### After fixing a parsing bug found during this evaluation",
        "",
        "The abstention-parsing bug fixed in ADR-047 was found here. Re-diagnosing the **same recordings** with "
        "the fix (no new runs) gives the numbers below. This would be **optimistic and not an independent "
        "measurement**: the fix was written after seeing these exact misses. The headline above stays the "
        "as-recorded number.",
        "",
        "| Metric (same 50 recordings, fix applied) | Value |",
        "| --- | --- |",
        f"| Lenient accuracy | {_ci(af['lenient_accuracy'])} |",
        f"| Strict accuracy | {_ci(af['strict_accuracy'])} |",
        f"| Macro-F1 | {_ci(af['macro_f1'], pct=False)} |",
        "",
        f"The fix changes {len(changed)} diagnosis(es) ({changed_to or 'none'}) and makes **{len(newly)}** more "
        "correct, so the headline is unchanged. The fix makes the pipeline recognise these `unanswerable` runs as "
        "abstentions, but the rule engine then calls them `RETRIEVAL_DISTRACTOR_DOMINANT` (the retrieved chunks are "
        "off-topic and the system abstained) rather than the labelled `OK_CORRECT_ABSTENTION`. That is a second, "
        "separate disagreement between a rule and the label, not an error the parsing fix can settle; a human "
        "reviewer should decide which code fits an unanswerable question whose retrieval returned only distractors. "
        "The fix is in `app/services/abstention.py`.",
        "",
    ]


def render_live_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    ci = report["confidence_intervals"]
    runs = report["runs"]
    n = s["total_cases"]
    ai_only = report.get("annotator") == "ai_draft_blind"
    lines = [
        "# live_v1: real pipeline runs, labelled blind",
        "",
    ]
    if ai_only:
        lines += [f"> **Labels:** {AI_BLIND_WORDING}.", ""]
    lines += [
        f"Produced by `retrace benchmark report --suite live_v1` on {report['generated_at'][:10]}. "
        f"Suite hash `{report['suite_hash']}`, experiment `{report['experiment_id']}`, "
        f"report commit {report.get('git_commit') or 'unknown'}.",
        "",
        f"{n} questions on the 13-document demo corpus ran through real retrieval, generation and judges "
        f"({', '.join(runs.get('generation_models') or [])}, temperature 0; NLI faithfulness), recorded "
        f"{(runs.get('recorded_from') or '')[:10]} to {(runs.get('recorded_to') or '')[:10]} on commit "
        f"{', '.join(runs.get('git_commits') or [])}. Labelled on {report.get('annotation_date')}. "
        + label_provenance(report)
        + " This report replays the recorded judge outputs, so it is reproducible offline.",
        "",
        "## Results",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Lenient accuracy (prediction in the label's acceptable codes) | {_ci(ci['lenient_accuracy'])} |",
        f"| Strict accuracy (prediction equals the label) | {_ci(ci['strict_accuracy'])} |",
        f"| Macro-F1 over labelled classes | {_ci(ci['macro_f1'], pct=False)} |",
        f"| Deferred as uncertain | {s['selective']['deferred']} of {n} ({_pct(s['selective']['uncertain_rate'])}) |",
        f"| Accuracy on the cases not deferred | {_pct(s['selective']['selective_accuracy'])} |",
        "",
        f"Confidence intervals: percentile bootstrap over cases, {ci['resamples']} resamples, seed {ci['seed']}.",
        "",
        "The headline is the diagnosis Retrace made with the code that recorded these runs. The abstention "
        "sentinel was matched exactly then, so the 8 `unanswerable` runs where the model replied "
        "`INSUFFICIENT CONTEXT` (with a space) were read as answers, not abstentions.",
        "",
        *_after_fix_lines(report, ci),
        "## Per class (strict)",
        "",
        "| Label | Support | Predicted | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, m in s["per_class"].items():
        lines.append(
            f"| `{label}` | {m['support']} | {m['predicted']} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} |"
        )
    lines += [
        "",
        "## By injected condition",
        "",
        "The condition is how a run was produced, not its label: a wrong-facts prompt can still give a correct answer.",
        "",
        "| Condition | Cases | Lenient | Strict | Deferred | Labels given |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, c in report["conditions"].items():
        given = ", ".join(f"{k} {v}" for k, v in c["labels"].items())
        lines.append(f"| {name} | {c['n']} | {_pct(c['lenient'])} | {_pct(c['strict'])} | {c['uncertain']} | {given} |")

    cm = s["confusion_matrix"]
    labels = cm["labels"]
    short = {lab: f"`{short_code(lab)}`" for lab in labels}
    legend = ", ".join(f"`{short_code(lab)}` {lab}" for lab in labels if short_code(lab) != lab)
    lines += [
        "",
        "## Confusion matrix",
        "",
        "Rows are labels, columns are predictions." + (f" Columns: {legend}." if legend else ""),
        "",
        "| Label \\ Predicted | " + " | ".join(short[p] for p in labels) + " |",
        "| --- | " + " | ".join("---:" for _ in labels) + " |",
    ]
    for a in labels:
        if any(cm["matrix"][a].values()):
            lines.append(f"| `{a}` | " + " | ".join(str(cm["matrix"][a][p] or "") for p in labels) + " |")

    lines += [
        "",
        "## Error analysis",
        "",
        "One line per miss. Every cause is **suggested**: an automatic first pass that compares the recorded "
        "judge signals with what the label implies. None has been confirmed by hand; treat them as hypotheses.",
        "",
    ]
    if report["miss_causes"]:
        lines.append("Suggested causes: " + ", ".join(f"{k} {v}" for k, v in report["miss_causes"].items()) + ".")
        lines += [
            "",
            "| Case | Condition | Label | Predicted (rule) | Suggested cause | Why |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for m in report["misses"]:
            alt = f" (or {', '.join(m['alternatives'])})" if m["alternatives"] else ""
            why = m["why"].replace("|", "/")
            if m["other_causes"]:
                why += f"; also: {', '.join(m['other_causes'])}"
            lines.append(
                f"| {m['case_id']} | {m['condition']} | `{m['expected']}`{alt} | `{m['predicted']}` ({m['rule_id']}) | {m['cause']} | {why} |"
            )
    else:
        lines.append("No misses.")

    cal = report.get("applied_calibrator")
    lines += [
        "",
        "## Limits",
        "",
        f"- {n} cases. The confidence intervals above are wide; differences of a few cases are not meaningful.",
        "- One generation and judge model on one small, synthetic policy corpus. Other models and real "
        "document collections will behave differently.",
        _labeller_limit(report),
        "- The runs were recorded on a shared, heavily loaded developer machine with the model timeout set to "
        f"{', '.join(f'{t:g} s' for t in report.get('model_timeout_seconds') or []) or 'its default'} so that "
        f"contention would not create timeouts; {report.get('timeouts', 0)} run(s) timed out. Latency in these "
        "runs means nothing.",
        "- Conditions were injected on purpose (removed documents, near-topic distractors, faulty prompts), so "
        "the mix of failures is not the mix a production system would see.",
        "- Confidence is calibrated on the synthetic `calib_v1` suite"
        + (f" ({cal['fitted_on']})" if cal else "")
        + "; this report does not recalibrate on live data.",
        "",
        "## What this does and doesn't show",
        "",
        f"- **Shows:** how often Retrace's first-match diagnosis agrees with a blind label on {n} real runs of "
        "one pipeline, with intervals that say how much that agreement could move with a different sample.",
        "- **Shows:** which kinds of failure it gets right and which it confuses (per-class table, confusion "
        "matrix), and where the misses come from (suggested causes above).",
        "- **Does not show:** accuracy on other models, other corpora, or failures that occur naturally in "
        "production. One model, a 13-document synthetic policy corpus, and faults injected on purpose.",
        "- **Does not show:** agreement between labellers. "
        + (
            "There is one label per case, from an AI annotator that no human has reviewed yet."
            if ai_only
            else "There is one label per case."
        ),
        "- **Does not show:** that the confidence score is calibrated on real runs (see the calibration report).",
        "",
    ]
    return "\n".join(lines)
