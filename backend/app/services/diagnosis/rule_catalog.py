"""Human-readable rule documentation for the investigation UI.

This catalog documents the deterministic rule engine — it does not re-run
diagnosis. Conditions mirror `apply_rules` in rules.py.
"""

from __future__ import annotations

from typing import Any


RULE_CATALOG: dict[str, dict[str, Any]] = {
    "R00": {
        "rule_id": "R00",
        "result": "EVAL_MODEL_TIMEOUT",
        "layer": "infra",
        "conditions": ["stage_error == TIMEOUT"],
        "summary": "Generation or model stage timed out before a usable answer.",
    },
    "R01": {
        "rule_id": "R01",
        "result": "EVAL_JUDGE_MALFORMED",
        "layer": "infra",
        "conditions": ["judge_schema_ok == false"],
        "summary": "A required judge returned malformed output after retry.",
    },
    "R02": {
        "rule_id": "R02",
        "result": "EVAL_MISSING_CONTEXT",
        "layer": "infra",
        "conditions": ["missing_answer", "n_retrieved == 0"],
        "summary": "Execution is missing both answer and retrieved context.",
    },
    "R10": {
        "rule_id": "R10",
        "result": "RETRIEVAL_EMPTY",
        "layer": "retrieval",
        "conditions": ["n_retrieved == 0"],
        "summary": "Retrieval returned zero chunks.",
    },
    "R11": {
        "rule_id": "R11",
        "result": "RETRIEVAL_MISS",
        "layer": "retrieval",
        "conditions": ["gold_ids present", "gold_hit == false"],
        "summary": "Gold-relevant chunk(s) exist but none appear in top-k.",
    },
    "R12": {
        "rule_id": "R12",
        "result": "RETRIEVAL_DISTRACTOR_DOMINANT",
        "layer": "retrieval",
        "conditions": [
            "n_retrieved > 0",
            "irrelevant_frac >= TAU_DISTRACTOR_FRAC",
            "context_sufficient == false",
            "answer_is_abstention == true",
        ],
        "summary": "Retrieved set is dominated by distractors; system abstained.",
    },
    "R14": {
        "rule_id": "R14",
        "result": "OK_CORRECT_ABSTENTION",
        "layer": "abstention",
        "conditions": [
            "context_sufficient == false",
            "answer_is_abstention == true",
        ],
        "summary": "Context insufficient and the system correctly abstained.",
    },
    "R20": {
        "rule_id": "R20",
        "result": "ABSTENTION_FALSE_NEGATIVE",
        "layer": "abstention",
        "conditions": [
            "context_sufficient == false",
            "answer_is_abstention == false",
        ],
        "summary": "Context insufficient but the system answered anyway.",
    },
    "R21": {
        "rule_id": "R21",
        "result": "ABSTENTION_FALSE_POSITIVE",
        "layer": "abstention",
        "conditions": [
            "context_sufficient == true",
            "answer_is_abstention == true",
        ],
        "summary": "Context was sufficient but the system abstained.",
    },
    "R30": {
        "rule_id": "R30",
        "result": "GENERATION_CONTRADICTION",
        "layer": "generation",
        "conditions": [
            "context_sufficient == true",
            "answer_contradicts_context == true",
        ],
        "summary": "Answer conflicts with retrieved evidence (contradiction judge).",
    },
    "R31": {
        "rule_id": "R31",
        "result": "GENERATION_HALLUCINATION",
        "layer": "generation",
        "conditions": [
            "context_sufficient == true",
            "unsupported_claim_count > 0",
            "faithfulness_score < TAU_FAITHFUL",
        ],
        "summary": "Context sufficient but answer invents unsupported content.",
    },
    "R33": {
        "rule_id": "R33",
        "result": "GROUNDING_PARTIAL",
        "layer": "grounding",
        "conditions": [
            "context_sufficient == true",
            "unsupported_claim_count > 0",
            "supported_claim_count > 0",
            "answer_contradicts_context == false",
        ],
        "summary": "Some claims supported by context, others not.",
    },
    "R34": {
        "rule_id": "R34",
        "result": "GROUNDING_UNSUPPORTED",
        "layer": "grounding",
        "conditions": [
            "context_sufficient == true",
            "unsupported_claim_count > 0",
            "supported_claim_count == 0",
        ],
        "summary": "Answer asserts claims not supported by retrieved context.",
    },
    "R40": {
        "rule_id": "R40",
        "result": "OK_GROUNDED",
        "layer": "none",
        "conditions": [
            "context_sufficient == true",
            "faithfulness_score >= TAU_FAITHFUL",
            "answer_contradicts_context == false",
            "answer_is_abstention == false",
        ],
        "summary": "Answer is grounded in retrieved evidence.",
    },
    "R90": {
        "rule_id": "R90",
        "result": "DIAGNOSIS_UNCERTAIN",
        "layer": "uncertain",
        "conditions": [
            "judges ran",
            "signals inconsistent: faithfulness_score < TAU_FAITHFUL with "
            "unsupported_claim_count == 0, OR a required judge verdict is missing",
        ],
        "summary": (
            "Judge outputs are self-inconsistent or incomplete; the engine "
            "declines to localize and recommends manual review."
        ),
    },
    "R99": {
        "rule_id": "R99",
        "result": "EVAL_INTERNAL_ERROR",
        "layer": "infra",
        "conditions": ["no earlier rule matched"],
        "summary": "Fallback when no primary rule matched the signal bag.",
    },
}


RUNBOOK_BY_FAILURE: dict[str, str] = {
    "RETRIEVAL_MISS": "retrieval-miss-rate",
    "RETRIEVAL_EMPTY": "retrieval-miss-rate",
    "EVAL_MODEL_TIMEOUT": "generation-timeout",
    "EVAL_JUDGE_MALFORMED": "judge-malformed",
}

RUNBOOK_BY_SIGNAL: dict[str, str] = {
    "retrieval_miss_rate": "retrieval-miss-rate",
    "retrieval_empty_rate": "retrieval-miss-rate",
    "generation_timeout_rate": "generation-timeout",
    "judge_timeout_rate": "judge-malformed",
    "judge_malformed_rate": "judge-malformed",
    "request_error_rate": "request-errors-readiness",
    "p95_latency_ms": "request-errors-readiness",
}


def get_rule(rule_id: str) -> dict[str, Any] | None:
    return RULE_CATALOG.get(rule_id)


def list_rules() -> list[dict[str, Any]]:
    return [RULE_CATALOG[k] for k in sorted(RULE_CATALOG.keys())]
