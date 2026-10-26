"""Ranking metrics for retrieval evaluation (binary relevance).

All functions are pure and dependency-free so they can be unit-tested with
hand-computed values. Conventions:

* ``ranked_ids`` is the retriever output in rank order (rank 1 first).
* ``relevant_ids`` is the set of ids judged relevant for the query.
* Metrics that need at least one relevant id return ``None`` when the relevant
  set is empty (unanswerable query); callers exclude those from means and
  report them separately as abstention cases.
* nDCG uses binary gains and a ``1 / log2(rank + 1)`` discount; the ideal DCG
  assumes ``min(len(relevant), k)`` relevant items at the top.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

DEFAULT_KS: tuple[int, ...] = (1, 3, 5, 10)


def _top(ranked_ids: Sequence[str], k: int) -> list[str]:
    if k <= 0:
        raise ValueError("k must be >= 1")
    return list(ranked_ids[:k])


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float | None:
    """|relevant ∩ top-k| / |relevant|; None when nothing is relevant."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    hits = sum(1 for cid in _top(ranked_ids, k) if cid in relevant)
    return hits / len(relevant)


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float | None:
    """|relevant ∩ top-k| / k (k is the denominator even when fewer results exist)."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    hits = sum(1 for cid in _top(ranked_ids, k) if cid in relevant)
    return hits / k


def hit_rate_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float | None:
    """1.0 if any relevant id is in the top-k, else 0.0; None when nothing is relevant."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    return 1.0 if any(cid in relevant for cid in _top(ranked_ids, k)) else 0.0


def mrr(ranked_ids: Sequence[str], relevant_ids: Iterable[str]) -> float | None:
    """Reciprocal rank of the first relevant id (0.0 when none retrieved)."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def dcg_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    return sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(_top(ranked_ids, k), start=1)
        if cid in relevant
    )


def ndcg_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float | None:
    """Binary-gain nDCG@k with log2 discount; None when nothing is relevant."""
    relevant = set(relevant_ids)
    if not relevant:
        return None
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if idcg == 0.0:
        return 0.0
    return dcg_at_k(ranked_ids, relevant, k) / idcg


def evaluate_ranking(
    ranked_ids: Sequence[str],
    relevant_ids: Iterable[str],
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, float | None]:
    """All metrics for one query as a flat dict (``recall@5``, ``mrr`` …)."""
    relevant = set(relevant_ids)
    out: dict[str, float | None] = {}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(ranked_ids, relevant, k)
        out[f"precision@{k}"] = precision_at_k(ranked_ids, relevant, k)
        out[f"hit_rate@{k}"] = hit_rate_at_k(ranked_ids, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked_ids, relevant, k)
    out["mrr"] = mrr(ranked_ids, relevant)
    return out


def aggregate(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean of every numeric metric across queries, ignoring ``None`` values.

    Returns ``{"n": <rows>, "<metric>": mean, ...}``; a metric that is ``None``
    for every row is reported as ``None``.
    """
    rows = list(per_query)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    out: dict[str, Any] = {"n": len(rows)}
    for key in keys:
        values = [
            float(row[key])
            for row in rows
            if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)
        ]
        out[key] = (sum(values) / len(values)) if values else None
    return out
