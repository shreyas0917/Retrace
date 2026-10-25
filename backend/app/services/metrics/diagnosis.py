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


def summarize_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    correct = sum(1 for r in case_results if r.get("correct_failure_code"))
    incorrect = total - correct
    code_acc = diagnosis_accuracy(case_results)
    rule_acc = rule_accuracy(case_results)
    evid_acc = evidence_accuracy(case_results)
    return {
        "total_cases": total,
        "correct": correct,
        "incorrect": incorrect,
        "failure_code_accuracy": round(code_acc, 6),
        "rule_accuracy": None if rule_acc is None else round(rule_acc, 6),
        "evidence_accuracy": None if evid_acc is None else round(evid_acc, 6),
        "macro_f1": None
        if (mf := macro_f1(case_results)) is None
        else round(mf, 6),
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
