"""Choose the faithfulness judge: replayed output, NLI (default) or LLM."""

from __future__ import annotations

import json
from typing import Any, Sequence

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.services.judges.faithfulness import FAITHFULNESS_PROMPT_VERSION, judge_faithfulness
from app.services.judges.faithfulness_nli import (
    NLI_FAITHFULNESS_VERSION,
    NLIFaithfulnessResult,
    judge_faithfulness_nli,
)
from app.services.judges.replay import current_replay


def judge_faithfulness_routed(
    query: str,
    answer: str,
    chunks: Sequence[dict[str, Any]],
    settings: Settings | None = None,
) -> tuple[BaseModel, dict[str, Any], str]:
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
            result = NLIFaithfulnessResult.model_validate(recorded)
            meta = {
                "model": f"{result.model_id}@{result.revision[:12]}",
                "schema_ok": True,
                "attempts": 1,
                "latency_ms": 0,
                "backend": "nli",
                "replayed": True,
            }
            return result, meta, result.version
        result, meta = judge_faithfulness(query, answer, chunks, settings=settings)
        return result, {**meta, "backend": "llm"}, FAITHFULNESS_PROMPT_VERSION

    if settings.faithfulness_backend == "nli":
        result, meta = judge_faithfulness_nli(query, answer, chunks, max_pairs=settings.nli_max_pairs)
        return result, meta, NLI_FAITHFULNESS_VERSION
    result, meta = judge_faithfulness(query, answer, chunks, settings=settings)
    return result, {**meta, "backend": "llm"}, FAITHFULNESS_PROMPT_VERSION
