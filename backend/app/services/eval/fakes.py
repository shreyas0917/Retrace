"""Deterministic fake LLM providers for planted-failure / offline suite runs."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import GenerationTimeoutError
from app.services.llm_client import LLMResult


def detect_judge_type(messages: list[dict[str, str]]) -> str:
    system = (messages[0]["content"] if messages else "").lower()
    if "faithful" in system:
        return "faithfulness"
    if "contradict" in system:
        return "contradiction"
    return "relevance"


class ScriptedJudgeLLM:
    """Returns scripted JSON per judge type; supports multi-attempt lists."""

    def __init__(
        self,
        scripts: dict[str, list[str]],
        *,
        timeout_on: str | None = None,
    ) -> None:
        self.scripts = scripts
        self.timeout_on = timeout_on
        self.calls: dict[str, int] = {}
        self.captured: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, str]], *, model: str, timeout: float
    ) -> LLMResult:
        judge = detect_judge_type(messages)
        if self.timeout_on and judge == self.timeout_on:
            raise GenerationTimeoutError(
                "planted judge timeout",
                details={"judge": judge},
            )
        idx = self.calls.get(judge, 0)
        self.calls[judge] = idx + 1
        self.captured.append({"judge": judge, "attempt": idx + 1})
        series = self.scripts.get(judge) or ["{}"]
        content = series[min(idx, len(series) - 1)]
        return LLMResult(content=content, model=model, latency_ms=1.0)


def relevance_json(
    chunk_ids: list[str],
    *,
    sufficient: bool,
    relevant: bool = True,
    score: float = 0.9,
    scores: list[float] | None = None,
) -> str:
    items = []
    for i, cid in enumerate(chunk_ids):
        s = scores[i] if scores is not None else (score if relevant else 0.1)
        items.append(
            {
                "chunk_id": cid,
                "relevant": s >= 0.5,
                "score": s,
                "rationale": "fixture",
            }
        )
    return json.dumps({"items": items, "context_sufficient": sufficient})


def faithfulness_json(
    *,
    score: float,
    unsupported: int = 0,
    supported: int = 1,
    support_chunk_ids: list[str] | None = None,
) -> str:
    support_chunk_ids = support_chunk_ids or ["employee_handbook:c000"]
    claims = []
    for i in range(supported):
        claims.append(
            {
                "claim": f"supported claim {i}",
                "supported": True,
                "supporting_chunk_ids": support_chunk_ids,
            }
        )
    for i in range(unsupported):
        claims.append(
            {
                "claim": f"unsupported claim {i}",
                "supported": False,
                "supporting_chunk_ids": [],
            }
        )
    return json.dumps({"faithfulness_score": score, "claims": claims})


def contradiction_json(contradicts: bool, chunk_ids: list[str] | None = None) -> str:
    return json.dumps(
        {
            "contradicts": contradicts,
            "explanation": "fixture",
            "chunk_ids": chunk_ids or (["employee_handbook:c000"] if contradicts else []),
        }
    )
