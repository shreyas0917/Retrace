"""Diagnosis decision object and signal bag."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiagnosisDecision:
    primary_code: str
    rule_id: str
    layer: str
    diagnosis_confidence: str  # high | medium | low
    diagnosis_score: float
    secondary_codes: list[str] = field(default_factory=list)
    recommendation_code: str = "NONE"
    evidence_refs: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    judges_ran: bool = False


@dataclass
class SignalBag:
    """Inputs to the ordered rule engine."""

    n_retrieved: int = 0
    retrieved_ids: list[str] = field(default_factory=list)
    gold_ids: list[str] = field(default_factory=list)
    # None = no gold reference for this execution (not evaluated).
    # True/False only when gold_ids is non-empty.
    gold_hit: bool | None = None
    gold_recall_at_k: float | None = None
    irrelevant_frac: float | None = None
    context_sufficient: bool | None = None
    answer_is_abstention: bool = False
    answer_contradicts_context: bool | None = None
    faithfulness_score: float | None = None
    unsupported_claim_count: int | None = None
    supported_claim_count: int | None = None
    judge_schema_ok: bool = True
    stage_error: str | None = None  # TIMEOUT | None
    missing_answer: bool = False
    chunk_relevance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_retrieved": self.n_retrieved,
            "retrieved_ids": self.retrieved_ids,
            "gold_ids": self.gold_ids,
            "gold_hit": self.gold_hit,
            "gold_recall_at_k": self.gold_recall_at_k,
            "irrelevant_frac": self.irrelevant_frac,
            "context_sufficient": self.context_sufficient,
            "answer_is_abstention": self.answer_is_abstention,
            "answer_contradicts_context": self.answer_contradicts_context,
            "faithfulness_score": self.faithfulness_score,
            "unsupported_claim_count": self.unsupported_claim_count,
            "supported_claim_count": self.supported_claim_count,
            "judge_schema_ok": self.judge_schema_ok,
            "stage_error": self.stage_error,
            "missing_answer": self.missing_answer,
            "chunk_relevance": self.chunk_relevance,
        }
