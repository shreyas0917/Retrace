"""Diagnosis localization metrics (PRD §15)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def diagnosis_accuracy(results: Iterable[dict[str, Any]]) -> float:
    """Fraction where predicted primary ∈ acceptable_primary_codes."""
    rows = list(results)
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if r.get("correct_failure_code"))
    return hits / len(rows)


def rule_accuracy(results: Iterable[dict[str, Any]]) -> float | None:
    """Fraction where predicted rule_id == expected_rule_id (when expected set)."""
    scored = [r for r in results if r.get("expected_rule_id")]
    if not scored:
        return None
    hits = sum(1 for r in scored if r.get("correct_rule_id"))
    return hits / len(scored)


def evidence_accuracy(results: Iterable[dict[str, Any]]) -> float | None:
    """Fraction where expected evidence chunk refs appear in diagnosis evidence."""
    scored = [r for r in results if r.get("expected_evidence_chunk_ids") is not None]
    if not scored:
        return None
    hits = sum(1 for r in scored if r.get("correct_evidence"))
    return hits / len(scored)


def confusion_matrix(
    results: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build gold_label × predicted_primary counts."""
    rows = list(results)
    labels: set[str] = set()
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        actual = str(r.get("expected_failure_code") or r.get("failure_label") or "")
        predicted = str(r.get("predicted_failure_code") or "")
        labels.add(actual)
        labels.add(predicted)
        counts[actual][predicted] += 1

    ordered = sorted(labels)
    matrix = {a: {p: int(counts[a].get(p, 0)) for p in ordered} for a in ordered}
    return {"labels": ordered, "matrix": matrix}


def macro_f1(results: Iterable[dict[str, Any]]) -> float | None:
    """Macro-F1 over labels present as gold failure_label."""
    rows = list(results)
    if not rows:
        return None
    labels = sorted(
        {
            str(r.get("expected_failure_code") or r.get("failure_label"))
            for r in rows
            if r.get("expected_failure_code") or r.get("failure_label")
        }
    )
    if not labels:
        return None

    f1s: list[float] = []
    for label in labels:
        tp = fp = fn = 0
        for r in rows:
            actual = str(r.get("expected_failure_code") or r.get("failure_label"))
            predicted = str(r.get("predicted_failure_code") or "")
            if predicted == label and actual == label:
                tp += 1
            elif predicted == label and actual != label:
                fp += 1
            elif predicted != label and actual == label:
                fn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        if precision + recall == 0:
            f1s.append(0.0)
        else:
            f1s.append(2 * precision * recall / (precision + recall))
    return sum(f1s) / len(f1s)


def _expected(r: dict[str, Any]) -> str:
    return str(r.get("expected_failure_code") or r.get("failure_label") or "")


def _predicted(r: dict[str, Any]) -> str:
    return str(r.get("predicted_failure_code") or "")


def strict_accuracy(results: Iterable[dict[str, Any]]) -> float:
    """Fraction where predicted primary == failure_label exactly."""
    rows = list(results)
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if _predicted(r) == _expected(r))
    return hits / len(rows)


def per_class_metrics(results: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Precision / recall / F1 / support per expected label (strict match).

    Labels that were only ever predicted (never expected) are included with
    support 0 so false positives against them are visible.
    """
    rows = list(results)
    labels = sorted({_expected(r) for r in rows} | {_predicted(r) for r in rows})
    out: dict[str, dict[str, Any]] = {}
    for label in labels:
        if not label:
            continue
        tp = fp = fn = 0
        for r in rows:
            a, p = _expected(r), _predicted(r)
            if p == label and a == label:
                tp += 1
            elif p == label:
                fp += 1
            elif a == label:
                fn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            0.0
            if precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        out[label] = {
            "support": tp + fn,
            "predicted": tp + fp,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }
    return out


def aggregate_f1(per_class: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    """Micro and support-weighted F1 from a per-class table."""
    supported = {k: v for k, v in per_class.items() if v.get("support", 0) > 0}
    if not supported:
        return {"micro_f1": None, "weighted_f1": None}
    tp = sum(v["tp"] for v in supported.values())
    fp = sum(v["fp"] for v in supported.values())
    fn = sum(v["fn"] for v in supported.values())
    micro_p = tp / (tp + fp) if (tp + fp) else 0.0
    micro_r = tp / (tp + fn) if (tp + fn) else 0.0
    micro = 0.0 if micro_p + micro_r == 0 else 2 * micro_p * micro_r / (micro_p + micro_r)
    total_support = sum(v["support"] for v in supported.values())
    weighted = sum(v["f1"] * v["support"] for v in supported.values()) / total_support
    return {"micro_f1": round(micro, 6), "weighted_f1": round(weighted, 6)}


def selective_metrics(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy when the engine is allowed to defer `uncertain` cases.

    coverage = fraction of cases answered (not flagged uncertain);
    selective_accuracy = lenient accuracy on the answered subset;
    deferred_accuracy = lenient accuracy on the deferred subset (how many
    deferrals would have been right anyway).
    """
    rows = list(results)
    if not rows:
        return {
            "coverage": None,
            "selective_accuracy": None,
            "deferred": 0,
            "deferred_accuracy": None,
            "uncertain_rate": None,
        }
    answered = [r for r in rows if not r.get("uncertain")]
    deferred = [r for r in rows if r.get("uncertain")]

    def acc(subset: list[dict[str, Any]]) -> float | None:
        if not subset:
            return None
        return round(
            sum(1 for r in subset if r.get("correct_failure_code")) / len(subset), 6
        )

    return {
        "coverage": round(len(answered) / len(rows), 6),
        "selective_accuracy": acc(answered),
        "deferred": len(deferred),
        "deferred_accuracy": acc(deferred),
        "uncertain_rate": round(len(deferred) / len(rows), 6),
    }


def summarize_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    correct = sum(1 for r in case_results if r.get("correct_failure_code"))
    incorrect = total - correct
    code_acc = diagnosis_accuracy(case_results)
    rule_acc = rule_accuracy(case_results)
    evid_acc = evidence_accuracy(case_results)
    per_class = per_class_metrics(case_results)
    agg = aggregate_f1(per_class)
    return {
        "total_cases": total,
        "correct": correct,
        "incorrect": incorrect,
        "failure_code_accuracy": round(code_acc, 6),
        "strict_accuracy": round(strict_accuracy(case_results), 6),
        "rule_accuracy": None if rule_acc is None else round(rule_acc, 6),
        "evidence_accuracy": None if evid_acc is None else round(evid_acc, 6),
        "macro_f1": None
        if (mf := macro_f1(case_results)) is None
        else round(mf, 6),
        "micro_f1": agg["micro_f1"],
        "weighted_f1": agg["weighted_f1"],
        "per_class": per_class,
        "selective": selective_metrics(case_results),
        "confusion_matrix": confusion_matrix(case_results),
    }


def evidence_refs_valid(
    evidence_refs: list[str],
    *,
    retrieved_ids: list[str],
    execution_id: str | None,
    gold_ids: list[str] | None = None,
) -> bool:
    """Chunk refs must point at retrieved or gold chunk ids; other prefixes allowed."""
    allowed = set(retrieved_ids) | set(gold_ids or [])
    for ref in evidence_refs:
        if ref.startswith("chunk:"):
            cid = ref[len("chunk:") :]
            if not cid:
                return False
            if allowed and cid not in allowed:
                return False
        elif ref.startswith("execution:"):
            if execution_id and ref != f"execution:{execution_id}":
                return False
    return True


def expected_evidence_hit(
    evidence_refs: list[str],
    expected_chunk_ids: list[str],
) -> bool:
    if not expected_chunk_ids:
        return True
    refs = set(evidence_refs)
    return all(f"chunk:{cid}" in refs or cid in refs for cid in expected_chunk_ids)
