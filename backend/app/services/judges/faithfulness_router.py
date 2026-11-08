"""Choose the faithfulness judge: replayed output, NLI (default) or LLM."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.core.config import Settings, get_settings
from app.services.judges.faithfulness import FAITHFULNESS_PROMPT_VERSION, judge_faithfulness
from app.services.judges.faithfulness_nli import (
    NLI_FAITHFULNESS_VERSION,
    NLIFaithfulnessResult,
    judge_faithfulness_nli,
)
from app.services.judges.replay import current_replay
from app.services.judges.schemas import FaithfulnessJudgeResult

# Either backend's output: both have `faithfulness_score` and `claims` with `supported`.
FaithfulnessResult = NLIFaithfulnessResult | FaithfulnessJudgeResult


def judge_faithfulness_routed(
    query: str,
    answer: str,
    chunks: Sequence[dict[str, Any]],
    settings: Settings | None = None,
) -> tuple[FaithfulnessResult, dict[str, Any], str]:
    """Return (result, meta, version). The result always has
    `faithfulness_score` and `claims` (each with `supported`)."""
    settings = settings or get_settings()
    replay = current_replay()
    if replay is not None:
        # Recorded outputs win over the backend setting, so suites stay reproducible.
        if "faithfulness_nli" in replay:
            recorded = replay["faithfulness_nli"]
            if isinstance(recorded, str):
                recorded = json.loads(recorded)
            recorded_result = NLIFaithfulnessResult.model_validate(recorded)
            meta = {
                "model": f"{recorded_result.model_id}@{recorded_result.revision[:12]}",
                "schema_ok": True,
                "attempts": 1,
                "latency_ms": 0,
                "backend": "nli",
                "replayed": True,
            }
            return recorded_result, meta, recorded_result.version
        result, meta = judge_faithfulness(query, answer, chunks, settings=settings)
        return result, {**meta, "backend": "llm"}, FAITHFULNESS_PROMPT_VERSION

    if settings.faithfulness_backend == "nli":
        nli_result, nli_meta = judge_faithfulness_nli(query, answer, chunks, max_pairs=settings.nli_max_pairs)
        return nli_result, nli_meta, NLI_FAITHFULNESS_VERSION
    result, meta = judge_faithfulness(query, answer, chunks, settings=settings)
    return result, {**meta, "backend": "llm"}, FAITHFULNESS_PROMPT_VERSION
