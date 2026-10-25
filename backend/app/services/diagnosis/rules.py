"""Ordered diagnosis rules R00–R40 (PRD §3.3). First match wins."""

from __future__ import annotations

from app.services.diagnosis.models import DiagnosisDecision, SignalBag
from app.services.diagnosis.taxonomy import (
    layer_for,
    recommendation_for,
)
from app.services.diagnosis.thresholds import (
    TAU_DISTRACTOR_FRAC,
    TAU_FAITHFUL,
)


def _confidence_for_rule(rule_id: str, signals: SignalBag) -> tuple[str, float]:
    """Rule-strength heuristic — not calibrated probability (PRD §4)."""
    deterministic = {
        "R00",
        "R02",
        "R03",
        "R10",
        "R11",
    }
    if rule_id in deterministic:
        return "high", 1.0
    if not signals.judge_schema_ok:
        return "low", 0.3
    if rule_id in {"R12", "R14", "R20", "R21", "R30", "R31", "R33", "R34", "R40"}:
        score = 0.5
        if signals.faithfulness_score is not None:
            score = max(score, min(1.0, abs(signals.faithfulness_score)))
        if signals.context_sufficient is not None:
            score = max(score, 0.7)
        if score >= 0.75:
            return "high", score
        if score >= 0.5:
            return "medium", score
        return "low", score
    if rule_id == "R01":
        return "high", 1.0
    return "medium", 0.5


def _decision(
    code: str,
    rule_id: str,
    signals: SignalBag,
    *,
    secondary: list[str] | None = None,
    evidence: list[str] | None = None,
) -> DiagnosisDecision:
    conf, score = _confidence_for_rule(rule_id, signals)
    secs = (secondary or [])[:3]
    return DiagnosisDecision(
        primary_code=code,
        rule_id=rule_id,
        layer=layer_for(code),
        diagnosis_confidence=conf,
        diagnosis_score=score,
        secondary_codes=secs,
        recommendation_code=recommendation_for(code),
        evidence_refs=evidence or [],
        signals=signals.to_dict(),
    )


def apply_rules(signals: SignalBag) -> DiagnosisDecision:
    """Evaluate PRD rules in order. First match is primary."""

    # --- Infrastructure ---
    if signals.stage_error == "TIMEOUT":
        return _decision("EVAL_MODEL_TIMEOUT", "R00", signals)

    if not signals.judge_schema_ok:
        return _decision("EVAL_JUDGE_MALFORMED", "R01", signals)

    if signals.missing_answer and signals.n_retrieved == 0:
        # Offline-style missing fields
        return _decision("EVAL_MISSING_CONTEXT", "R02", signals)

    # --- Retrieval ---
    if signals.n_retrieved == 0:
        refs = ["retrieval:empty"]
        return _decision("RETRIEVAL_EMPTY", "R10", signals, evidence=refs)

    if signals.gold_ids and not signals.gold_hit:
        refs = [f"chunk:{cid}" for cid in signals.gold_ids[:5]]
        refs.append("retrieval:gold_miss")
        return _decision("RETRIEVAL_MISS", "R11", signals, evidence=refs)

    if (
        signals.n_retrieved > 0
        and signals.irrelevant_frac is not None
        and signals.irrelevant_frac >= TAU_DISTRACTOR_FRAC
        and signals.context_sufficient is False
        and signals.answer_is_abstention
    ):
        # Distractors dominate and the system correctly/incorrectly abstained —
        # retrieval is the primary localization. Answered+insufficient is R20.
        refs = [f"chunk:{cid}" for cid in signals.retrieved_ids[:5]]
        return _decision(
            "RETRIEVAL_DISTRACTOR_DOMINANT", "R12", signals, evidence=refs
        )

    # R13 is advisory secondary only — primary decided below

    if signals.context_sufficient is False and signals.answer_is_abstention:
        secondary = (
            ["RETRIEVAL_INSUFFICIENT_CONTEXT"]
            if signals.n_retrieved > 0
            else []
        )
        return _decision(
            "OK_CORRECT_ABSTENTION",
            "R14",
            signals,
            secondary=secondary,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    # --- Abstention ---
    if signals.context_sufficient is False and not signals.answer_is_abstention:
        secondary = ["RETRIEVAL_INSUFFICIENT_CONTEXT"]
        if (
            signals.irrelevant_frac is not None
            and signals.irrelevant_frac >= TAU_DISTRACTOR_FRAC
        ):
            secondary = ["RETRIEVAL_DISTRACTOR_DOMINANT"]
        return _decision(
            "ABSTENTION_FALSE_NEGATIVE",
            "R20",
            signals,
            secondary=secondary,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    if signals.context_sufficient is True and signals.answer_is_abstention:
        return _decision(
            "ABSTENTION_FALSE_POSITIVE",
            "R21",
            signals,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    # --- Grounding / generation (context sufficient, answered) ---
    if signals.context_sufficient is True and signals.answer_contradicts_context:
        refs = [f"chunk:{cid}" for cid in signals.retrieved_ids[:5]]
        return _decision("GENERATION_CONTRADICTION", "R30", signals, evidence=refs)

    unsupported = (signals.unsupported_claim_count or 0) > 0
    supported = (signals.supported_claim_count or 0) > 0
    faith = signals.faithfulness_score

    if (
        signals.context_sufficient is True
        and unsupported
        and supported
        and not signals.answer_contradicts_context
    ):
        return _decision(
            "GROUNDING_PARTIAL",
            "R33",
            signals,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    if (
        signals.context_sufficient is True
        and unsupported
        and faith is not None
        and faith < TAU_FAITHFUL
    ):
        return _decision(
            "GENERATION_HALLUCINATION",
            "R31",
            signals,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    if signals.context_sufficient is True and unsupported and not supported:
        return _decision(
            "GROUNDING_UNSUPPORTED",
            "R34",
            signals,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    if (
        signals.context_sufficient is True
        and faith is not None
        and faith >= TAU_FAITHFUL
        and not signals.answer_contradicts_context
        and not signals.answer_is_abstention
    ):
        return _decision(
            "OK_GROUNDED",
            "R40",
            signals,
            evidence=[f"chunk:{cid}" for cid in signals.retrieved_ids[:5]],
        )

    return _decision("EVAL_INTERNAL_ERROR", "R99", signals)


def needs_judges(signals: SignalBag) -> bool:
    """Whether semantic judges are required before final classification."""
    if signals.stage_error == "TIMEOUT":
        return False
    if signals.n_retrieved == 0:
        return False
    if signals.gold_ids and not signals.gold_hit:
        return False
    return True
