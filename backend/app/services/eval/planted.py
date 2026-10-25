"""Build offline execution fixtures from planted_failure mutations.

Canonical corpus is never mutated — scenarios only craft retrieve/answer snapshots.
"""

from __future__ import annotations

from typing import Any

from app.services.eval.fakes import (
    contradiction_json,
    faithfulness_json,
    relevance_json,
)
from app.services.eval.schemas import GoldCase, OfflineExecution
from app.services.prompts import ABSTENTION_ANSWER

PTO_TEXT = (
    "Full-time employees accrue 1.25 days of PTO per month, for a total of "
    "15 days per year."
)
PTO_CHUNK_ID = "employee_handbook:c000"
NOISE_TEXT = "All employees must enable multi-factor authentication on company accounts."
NOISE_CHUNK_ID = "security_policy:c000"
CAFETERIA_TEXT = "The cafeteria serves lunch at noon on weekdays."
CAFETERIA_CHUNK_ID = "facilities:c000"


def _chunk(
    chunk_id: str,
    text: str,
    *,
    rank: int = 1,
    score: float = 0.5,
    document_id: str | None = None,
) -> dict[str, Any]:
    doc = document_id or chunk_id.split(":")[0]
    return {
        "chunk_id": chunk_id,
        "document_id": doc,
        "text": text,
        "rank": rank,
        "retrieval_score": score,
        "source_name": f"{doc}.md",
    }


def build_offline_execution(case: GoldCase) -> OfflineExecution:
    """Resolve offline fixture from explicit offline_execution or planted mutation."""
    if case.offline_execution is not None:
        return case.offline_execution

    planted = case.planted_failure
    if planted is None:
        raise ValueError(f"case {case.case_id} has no planted_failure or offline_execution")

    ptype = planted.type
    params = planted.params or {}

    if ptype in {"REMOVE_GOLD_FROM_INDEX", "REDUCE_TOP_K"}:
        # Gold exists in labels but not in retrieved set
        return OfflineExecution(
            retrieved_chunks=[
                _chunk(NOISE_CHUNK_ID, NOISE_TEXT, rank=1, score=0.4),
            ],
            answer="Could not find PTO policy.",
            abstained=False,
            status="COMPLETED",
            judge_scripts={},  # R11 short-circuits judges
        )

    if ptype == "FORCE_DISTRACTORS":
        chunks = [
            _chunk(NOISE_CHUNK_ID, NOISE_TEXT, rank=1, score=0.2),
            _chunk(CAFETERIA_CHUNK_ID, CAFETERIA_TEXT, rank=2, score=0.15),
        ]
        ids = [c["chunk_id"] for c in chunks]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=ABSTENTION_ANSWER,
            abstained=True,
            status="ABSTAINED",
            judge_scripts={
                "relevance": [
                    relevance_json(ids, sufficient=False, scores=[0.1, 0.1])
                ],
            },
        )

    if ptype == "PARTIAL_GOLD":
        # Only noise-ish / weak signal; abstain correctly
        chunks = [
            _chunk(PTO_CHUNK_ID, "PTO requests require manager approval.", rank=1, score=0.4),
            _chunk(NOISE_CHUNK_ID, NOISE_TEXT, rank=2, score=0.2),
        ]
        ids = [c["chunk_id"] for c in chunks]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=ABSTENTION_ANSWER,
            abstained=True,
            status="ABSTAINED",
            judge_scripts={
                "relevance": [
                    relevance_json(ids, sufficient=False, scores=[0.55, 0.1])
                ],
            },
        )

    if ptype == "FORCE_HALLUCINATION":
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer="Full-time employees also receive free housing stipends.",
            abstained=False,
            status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json([PTO_CHUNK_ID], sufficient=True)],
                "faithfulness": [
                    faithfulness_json(
                        score=0.2, supported=0, unsupported=1, support_chunk_ids=[PTO_CHUNK_ID]
                    )
                ],
                "contradiction": [contradiction_json(False)],
            },
        )

    if ptype in {"FORCE_CONTRADICTION", "OFFLINE_CONTRADICTORY_ANSWER"}:
        answer = params.get(
            "answer",
            "Full-time employees accrue 10 days of PTO per month.",
        )
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=answer,
            abstained=False,
            status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json([PTO_CHUNK_ID], sufficient=True)],
                "faithfulness": [
                    faithfulness_json(
                        score=0.2, supported=0, unsupported=1, support_chunk_ids=[PTO_CHUNK_ID]
                    )
                ],
                "contradiction": [contradiction_json(True, [PTO_CHUNK_ID])],
            },
        )

    if ptype == "FORCE_ANSWER_INSUFFICIENT":
        chunks = [_chunk(CAFETERIA_CHUNK_ID, CAFETERIA_TEXT, rank=1, score=0.1)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=params.get("answer", "Employees get unlimited PTO."),
            abstained=False,
            status="COMPLETED",
            judge_scripts={
                "relevance": [
                    relevance_json(
                        [CAFETERIA_CHUNK_ID],
                        sufficient=False,
                        relevant=False,
                        score=0.1,
                    )
                ],
            },
        )

    if ptype == "FORCE_ABSTAIN_SUFFICIENT":
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=ABSTENTION_ANSWER,
            abstained=True,
            status="ABSTAINED",
            judge_scripts={
                "relevance": [relevance_json([PTO_CHUNK_ID], sufficient=True)],
            },
        )

    if ptype == "GROUNDED_OK":
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        answer = params.get(
            "answer",
            "Full-time employees accrue 1.25 days of PTO per month.",
        )
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=answer,
            abstained=False,
            status="COMPLETED",
            judge_scripts={
                "relevance": [relevance_json([PTO_CHUNK_ID], sufficient=True)],
                "faithfulness": [
                    faithfulness_json(
                        score=1.0, supported=1, unsupported=0, support_chunk_ids=[PTO_CHUNK_ID]
                    )
                ],
                "contradiction": [contradiction_json(False)],
            },
        )

    if ptype == "CORRECT_ABSTENTION":
        chunks = [
            _chunk(PTO_CHUNK_ID, "Office snacks are available on Fridays.", rank=1, score=0.3),
            _chunk(NOISE_CHUNK_ID, NOISE_TEXT, rank=2, score=0.2),
        ]
        ids = [c["chunk_id"] for c in chunks]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=ABSTENTION_ANSWER,
            abstained=True,
            status="ABSTAINED",
            judge_scripts={
                "relevance": [
                    relevance_json(ids, sufficient=False, scores=[0.55, 0.2])
                ],
            },
        )

    if ptype == "MALFORMED_JUDGE":
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer="Full-time employees accrue 1.25 days of PTO per month.",
            abstained=False,
            status="COMPLETED",
            judge_scripts={"relevance": ["NOT_JSON", "STILL_BAD"]},
        )

    if ptype == "TIMEOUT":
        chunks = [_chunk(PTO_CHUNK_ID, PTO_TEXT, rank=1, score=0.9)]
        return OfflineExecution(
            retrieved_chunks=chunks,
            answer=None,
            abstained=False,
            status="GENERATION_TIMEOUT",
            error_code="GENERATION_TIMEOUT",
            judge_scripts={},
        )

    raise ValueError(f"unsupported planted_failure.type: {ptype}")
