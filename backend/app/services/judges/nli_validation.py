"""Validate the NLI faithfulness backend against the labelled judge examples.

Three views, so the NLI backend can be compared with the LLM judge:

* claim level: each labelled claim is scored directly against its example's
  chunks, isolating the NLI model from the claim splitter;
* answer level: the answer is split into claims and scored end to end, giving
  the same metrics the LLM faithfulness judge reports (has-unsupported-claim
  accuracy and kappa, score error, share of scores inside the labelled band);
* contradiction: the `nli_contradiction` flag against the contradiction
  labels, and against the LLM contradiction judge when its predictions exist.

The decision rule is fixed (entailment is the top label). The threshold sweep
and the cross-validated thresholds are reported as a sensitivity table only;
they never change the rule.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Sequence

from app.services.judges.faithfulness_nli import (
    DECISION_RULE,
    NLI_FAITHFULNESS_VERSION,
    NLIScorer,
    score_claims,
    split_claims,
)
from app.services.judges.validation import (
    JudgeExample,
    binary_metrics,
    cohen_kappa,
    compute_examples_hash,
)

SWEEP_THRESHOLDS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _mean(values: Sequence[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _claim_level(examples: Sequence[JudgeExample], scorer: NLIScorer) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    for ex in examples:
        labelled = list(ex.claims or [])
        if not labelled:
            continue
        results, _ = score_claims([c.claim for c in labelled], ex.chunk_dicts(), scorer)
        for claim, res in zip(labelled, results):
            units.append(
                {
                    "example_id": ex.example_id,
                    "claim": claim.claim,
                    "label": bool(claim.supported),
                    "pred": bool(res.supported),
                    "entailment": res.entailment,
                }
            )
    metrics = binary_metrics([u["label"] for u in units], [u["pred"] for u in units])
    return metrics, units


def _answer_level(examples: Sequence[JudgeExample], scorer: NLIScorer) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    abs_err: list[float] = []
    in_band: list[float] = []
    records: list[dict[str, Any]] = []
    no_claims = 0
    for ex in examples:
        claims = split_claims(ex.answer or "")
        results, _ = score_claims(claims, ex.chunk_dicts(), scorer)
        if not results:
            no_claims += 1
            continue
        score = sum(1 for r in results if r.supported) / len(results)
        has_unsupported = any(not r.supported for r in results)
        y_true.append(ex.labeled_has_unsupported)
        y_pred.append(has_unsupported)
        abs_err.append(abs(score - ex.labeled_faithfulness_score))
        lo, hi = ex.faithfulness_band or (0.0, 1.0)
        in_band.append(1.0 if lo - 1e-9 <= score <= hi + 1e-9 else 0.0)
        records.append(
            {
                "example_id": ex.example_id,
                "split_claims": claims,
                "faithfulness_score": round(score, 6),
                "has_unsupported": has_unsupported,
            }
        )
    return (
        {
            "has_unsupported_claim": binary_metrics(y_true, y_pred),
            "score_mae": _mean(abs_err),
            "score_in_band_rate": _mean(in_band),
            "examples_without_claims": no_claims,
        },
        records,
    )


def _contradiction(
    examples: Sequence[JudgeExample],
    scorer: NLIScorer,
    llm_verdicts: dict[str, bool] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    records: list[dict[str, Any]] = []
    for ex in examples:
        results, _ = score_claims(split_claims(ex.answer or ""), ex.chunk_dicts(), scorer)
        flag = any(r.contradicted for r in results)
        y_true.append(bool(ex.contradicts))
        y_pred.append(flag)
        records.append({"example_id": ex.example_id, "nli_contradiction": flag})
    out: dict[str, Any] = {"vs_labels": binary_metrics(y_true, y_pred), "vs_llm_judge": None}
    if llm_verdicts:
        paired = [(r["nli_contradiction"], llm_verdicts[r["example_id"]]) for r in records if r["example_id"] in llm_verdicts]
        if paired:
            nli, llm = [p[0] for p in paired], [p[1] for p in paired]
            out["vs_llm_judge"] = {
                "n": len(paired),
                "raw_agreement": sum(1 for a, b in paired if a == b) / len(paired),
                "kappa": cohen_kappa(nli, llm),
            }
    return out, records


def _metrics_at(units: Sequence[dict[str, Any]], threshold: float) -> dict[str, Any]:
    labels = [u["label"] for u in units]
    preds = [u["entailment"] >= threshold for u in units]
    m = binary_metrics(labels, preds)
    return {"threshold": threshold, "n": m["n"], "accuracy": m["accuracy"], "kappa": m["kappa"]}


def threshold_sensitivity(units: Sequence[dict[str, Any]], *, k_folds: int = 5) -> dict[str, Any]:
    """Sweep entailment thresholds, plus grouped k-fold cross-validation.

    Folds are grouped by example so claims from one answer never sit on both
    sides. Each fold picks the threshold with the highest training kappa (ties
    go to the threshold nearest 0.5) and is scored on its held-out claims.
    """
    sweep = [_metrics_at(units, t) for t in SWEEP_THRESHOLDS]
    example_ids = sorted({u["example_id"] for u in units})
    k = max(2, min(k_folds, len(example_ids))) if len(example_ids) >= 2 else 0
    folds: list[dict[str, Any]] = []
    if k:
        fold_of = {eid: i % k for i, eid in enumerate(example_ids)}
        for fold in range(k):
            train = [u for u in units if fold_of[u["example_id"]] != fold]
            test = [u for u in units if fold_of[u["example_id"]] == fold]
            if not train or not test:
                continue
            scored = [_metrics_at(train, t) for t in SWEEP_THRESHOLDS]
            best = max(scored, key=lambda m: ((m["kappa"] if m["kappa"] is not None else -2.0), -abs(m["threshold"] - 0.5)))
            held = _metrics_at(test, best["threshold"])
            folds.append(
                {
                    "fold": fold,
                    "chosen_threshold": best["threshold"],
                    "train_kappa": best["kappa"],
                    "test_n": held["n"],
                    "test_accuracy": held["accuracy"],
                    "test_kappa": held["kappa"],
                }
            )
    return {
        "note": (
            "Sensitivity only. The decision rule stays 'entailment is the top label'; "
            "these thresholds were not used to choose it."
        ),
        "sweep": sweep,
        "cross_validation": {
            "k": k,
            "grouped_by": "example_id",
            "folds": folds,
            "mean_test_accuracy": _mean([f["test_accuracy"] for f in folds if f["test_accuracy"] is not None]),
            "mean_test_kappa": _mean([f["test_kappa"] for f in folds if f["test_kappa"] is not None]),
        },
    }


def llm_contradiction_verdicts(llm_report: dict[str, Any] | None, variant: str) -> dict[str, bool]:
    """Primary-variant contradiction verdicts from a `validate_judges` report."""
    out: dict[str, bool] = {}
    for rec in (llm_report or {}).get("predictions") or []:
        if rec.get("judge") == "contradiction" and rec.get("variant") == variant and rec.get("schema_ok"):
            out[rec["example_id"]] = bool(rec.get("contradicts"))
    return out


def validate_nli_faithfulness(
    examples: Sequence[JudgeExample],
    scorer: NLIScorer,
    *,
    llm_report: dict[str, Any] | None = None,
    llm_variant: str = "v1",
    k_folds: int = 5,
) -> dict[str, Any]:
    started = time.perf_counter()
    examples = list(examples)
    faith = [ex for ex in examples if ex.judge == "faithfulness"]
    contra = [ex for ex in examples if ex.judge == "contradiction"]

    claim_metrics, claim_units = _claim_level(faith, scorer)
    answer_metrics, answer_records = _answer_level(faith, scorer)
    contra_metrics, contra_records = _contradiction(
        contra, scorer, llm_contradiction_verdicts(llm_report, llm_variant)
    )
    return {
        "backend": "nli",
        "version": NLI_FAITHFULNESS_VERSION,
        "model_id": scorer.model_id,
        "revision": scorer.revision,
        "decision_rule": DECISION_RULE,
        "label_order": scorer.label_order,
        "example_set_hash": compute_examples_hash(examples),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "faithfulness_examples": len(faith),
            "labelled_claims": len(claim_units),
            "contradiction_examples": len(contra),
        },
        "claim_level": claim_metrics,
        "answer_level": answer_metrics,
        "contradiction": contra_metrics,
        "sensitivity": threshold_sensitivity(claim_units, k_folds=k_folds),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "records": {
            "claims": claim_units,
            "answers": answer_records,
            "contradiction": contra_records,
        },
    }


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------
def _f(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _metric_row(name: str, m: dict[str, Any]) -> str:
    return (
        f"| {name} | {m['n']} | {_f(m['accuracy'])} | {_f(m['precision'])} | "
        f"{_f(m['recall'])} | {_f(m['f1'])} | {_f(m['kappa'])} |"
    )


def format_nli_markdown(section: dict[str, Any], *, llm_faithfulness: dict[str, Any] | None = None) -> str:
    """Markdown block for docs/benchmarks/judge_validation.md."""
    a = section["answer_level"]
    lines = [
        "## Faithfulness: NLI backend",
        "",
        f"Model `{section['model_id']}` at revision `{section['revision']}`, decision rule "
        f"`{section['decision_rule']}` (label order read from the model config: "
        f"{', '.join(section['label_order'])}). Version `{section['version']}`. "
        f"Example-set hash `{section['example_set_hash']}`.",
        "",
        "| view | n | acc | prec | rec | F1 | kappa |",
        "|---|---|---|---|---|---|---|",
        _metric_row("labelled claims: supported", section["claim_level"]),
        _metric_row("answers: has unsupported claim", a["has_unsupported_claim"]),
        _metric_row("contradiction flag vs labels", section["contradiction"]["vs_labels"]),
        "",
        f"Answer-level score error (mean absolute): {_f(a['score_mae'])}; share of scores inside the "
        f"labelled band: {_f(a['score_in_band_rate'])}; answers with no checkable claim: "
        f"{a['examples_without_claims']}.",
    ]
    vs_llm = section["contradiction"].get("vs_llm_judge")
    if vs_llm:
        lines += [
            "",
            f"Agreement between the NLI contradiction flag and the LLM contradiction judge on "
            f"{vs_llm['n']} examples: raw {_f(vs_llm['raw_agreement'])}, kappa {_f(vs_llm['kappa'])}.",
        ]
    if llm_faithfulness:
        lm = llm_faithfulness.get("has_unsupported_claim") or {}
        if lm:
            lines += [
                "",
                "Side by side on the same examples (has unsupported claim):",
                "",
                "| backend | n | acc | prec | rec | F1 | kappa | score MAE | in band |",
                "|---|---|---|---|---|---|---|---|---|",
                f"| llm | {lm['n']} | {_f(lm['accuracy'])} | {_f(lm['precision'])} | {_f(lm['recall'])} | "
                f"{_f(lm['f1'])} | {_f(lm['kappa'])} | {_f(llm_faithfulness.get('score_mae'))} | "
                f"{_f(llm_faithfulness.get('score_in_band_rate'))} |",
                f"| nli | {a['has_unsupported_claim']['n']} | {_f(a['has_unsupported_claim']['accuracy'])} | "
                f"{_f(a['has_unsupported_claim']['precision'])} | {_f(a['has_unsupported_claim']['recall'])} | "
                f"{_f(a['has_unsupported_claim']['f1'])} | {_f(a['has_unsupported_claim']['kappa'])} | "
                f"{_f(a['score_mae'])} | {_f(a['score_in_band_rate'])} |",
            ]
    sens = section["sensitivity"]
    lines += [
        "",
        "### Entailment threshold sensitivity (not used to choose the rule)",
        "",
        sens["note"],
        "",
        "| entailment threshold | n | acc | kappa |",
        "|---|---|---|---|",
    ]
    lines += [f"| {_f(r['threshold'], 1)} | {r['n']} | {_f(r['accuracy'])} | {_f(r['kappa'])} |" for r in sens["sweep"]]
    cv = sens["cross_validation"]
    if cv["folds"]:
        lines += [
            "",
            f"Grouped {cv['k']}-fold cross-validation by example (threshold chosen on the training folds, "
            f"scored on the held-out fold): mean held-out accuracy {_f(cv['mean_test_accuracy'])}, "
            f"mean held-out kappa {_f(cv['mean_test_kappa'])}; chosen thresholds per fold: "
            + ", ".join(_f(f["chosen_threshold"], 1) for f in cv["folds"])
            + ".",
        ]
    return "\n".join(lines) + "\n"
