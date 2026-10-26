"""Failure taxonomy 1.0 — machine-readable codes from the locked PRD."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


TAXONOMY_VERSION = "1.0"


class Layer(str, Enum):
    RETRIEVAL = "retrieval"
    GROUNDING = "grounding"
    GENERATION = "generation"
    ABSTENTION = "abstention"
    INFRA = "infra"
    NONE = "none"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class FailureCode:
    code: str
    layer: Layer
    description: str
    mvp: bool = True
    reserved: bool = False


FAILURE_CODES: dict[str, FailureCode] = {
    "RETRIEVAL_EMPTY": FailureCode(
        "RETRIEVAL_EMPTY", Layer.RETRIEVAL, "No chunks returned"
    ),
    "RETRIEVAL_MISS": FailureCode(
        "RETRIEVAL_MISS",
        Layer.RETRIEVAL,
        "Gold-relevant chunk(s) exist but none retrieved in top-k",
    ),
    "RETRIEVAL_RANK_TOO_LOW": FailureCode(
        "RETRIEVAL_RANK_TOO_LOW",
        Layer.RETRIEVAL,
        "Gold chunk ranked too low",
        mvp=False,
        reserved=True,
    ),
    "RETRIEVAL_DISTRACTOR_DOMINANT": FailureCode(
        "RETRIEVAL_DISTRACTOR_DOMINANT",
        Layer.RETRIEVAL,
        "Retrieved set dominated by irrelevant distractors",
    ),
    "RETRIEVAL_INSUFFICIENT_CONTEXT": FailureCode(
        "RETRIEVAL_INSUFFICIENT_CONTEXT",
        Layer.RETRIEVAL,
        "Some signal but not enough context to answer",
    ),
    "GROUNDING_UNSUPPORTED": FailureCode(
        "GROUNDING_UNSUPPORTED",
        Layer.GROUNDING,
        "Answer asserts claims not supported by retrieved context",
    ),
    "GROUNDING_PARTIAL": FailureCode(
        "GROUNDING_PARTIAL",
        Layer.GROUNDING,
        "Some claims supported, others not",
    ),
    "GROUNDING_CONTRADICTORY_CONTEXT": FailureCode(
        "GROUNDING_CONTRADICTORY_CONTEXT",
        Layer.GROUNDING,
        "Retrieved chunks contradict each other",
        mvp=False,
        reserved=True,
    ),
    "GROUNDING_CITATION_MISMATCH": FailureCode(
        "GROUNDING_CITATION_MISMATCH",
        Layer.GROUNDING,
        "Answer attributes content to wrong chunk",
        mvp=False,
        reserved=True,
    ),
    "GENERATION_HALLUCINATION": FailureCode(
        "GENERATION_HALLUCINATION",
        Layer.GENERATION,
        "Context sufficient but answer invents unsupported content",
    ),
    "GENERATION_CONTRADICTION": FailureCode(
        "GENERATION_CONTRADICTION",
        Layer.GENERATION,
        "Answer conflicts with retrieved evidence",
    ),
    "GENERATION_BAD_SYNTHESIS": FailureCode(
        "GENERATION_BAD_SYNTHESIS",
        Layer.GENERATION,
        "Evidence sufficient but synthesis wrong",
        mvp=False,
        reserved=True,
    ),
    "GENERATION_INSTRUCTION_FAIL": FailureCode(
        "GENERATION_INSTRUCTION_FAIL",
        Layer.GENERATION,
        "Violates system generation rules",
        mvp=False,
        reserved=True,
    ),
    "ABSTENTION_FALSE_NEGATIVE": FailureCode(
        "ABSTENTION_FALSE_NEGATIVE",
        Layer.ABSTENTION,
        "Should abstain but produced a substantive answer",
    ),
    "ABSTENTION_FALSE_POSITIVE": FailureCode(
        "ABSTENTION_FALSE_POSITIVE",
        Layer.ABSTENTION,
        "Abstained despite sufficient evidence",
    ),
    "OK_GROUNDED": FailureCode(
        "OK_GROUNDED", Layer.NONE, "Answer grounded; no failure"
    ),
    "OK_CORRECT_ABSTENTION": FailureCode(
        "OK_CORRECT_ABSTENTION",
        Layer.ABSTENTION,
        "Correctly abstained under insufficient evidence",
    ),
    "EVAL_MODEL_TIMEOUT": FailureCode(
        "EVAL_MODEL_TIMEOUT", Layer.INFRA, "Generator or judge timed out"
    ),
    "EVAL_JUDGE_MALFORMED": FailureCode(
        "EVAL_JUDGE_MALFORMED",
        Layer.INFRA,
        "Judge output failed schema after retry",
    ),
    "EVAL_MISSING_CONTEXT": FailureCode(
        "EVAL_MISSING_CONTEXT",
        Layer.INFRA,
        "Required retrieve/answer fields missing",
    ),
    "EVAL_INTERNAL_ERROR": FailureCode(
        "EVAL_INTERNAL_ERROR", Layer.INFRA, "Unexpected pipeline exception"
    ),
    "DIAGNOSIS_UNCERTAIN": FailureCode(
        "DIAGNOSIS_UNCERTAIN",
        Layer.UNCERTAIN,
        "Judge signals are internally inconsistent or sit on a decision "
        "boundary; no confident localization. Route to manual review.",
    ),
}


RECOMMENDATIONS: dict[str, str] = {
    "RETRIEVAL_EMPTY": "CHECK_INDEX",
    "RETRIEVAL_MISS": "TUNE_RETRIEVAL",
    "RETRIEVAL_DISTRACTOR_DOMINANT": "ADD_RERANK_OR_FILTER",
    "RETRIEVAL_INSUFFICIENT_CONTEXT": "INCREASE_K_OR_CHUNK",
    "GENERATION_HALLUCINATION": "TIGHTEN_GENERATOR",
    "GENERATION_CONTRADICTION": "TIGHTEN_GENERATOR",
    "GROUNDING_PARTIAL": "REQUIRE_CITATIONS",
    "GROUNDING_UNSUPPORTED": "TIGHTEN_GENERATOR",
    "ABSTENTION_FALSE_NEGATIVE": "ENFORCE_ABSTAIN",
    "ABSTENTION_FALSE_POSITIVE": "RELAX_ABSTAIN_OR_RETRIEVAL",
    "OK_GROUNDED": "NONE",
    "OK_CORRECT_ABSTENTION": "NONE",
    "EVAL_MODEL_TIMEOUT": "FIX_PIPELINE",
    "EVAL_JUDGE_MALFORMED": "FIX_PIPELINE",
    "EVAL_MISSING_CONTEXT": "FIX_PIPELINE",
    "EVAL_INTERNAL_ERROR": "FIX_PIPELINE",
    "DIAGNOSIS_UNCERTAIN": "MANUAL_REVIEW",
}


def recommendation_for(code: str) -> str:
    return RECOMMENDATIONS.get(code, "FIX_PIPELINE")


def layer_for(code: str) -> str:
    entry = FAILURE_CODES.get(code)
    return entry.layer.value if entry else Layer.INFRA.value
